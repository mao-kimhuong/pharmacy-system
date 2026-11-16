// The POS controller shared by the desktop POS and POS lite: cart, tender, preview, tokens, checkout.
import { useCallback, useEffect, useMemo, useReducer, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router';
import { api, call, withKey } from '@/api/client';
import { isApiError } from '@/api/errors';
import type { SalesS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import type { PinToken } from '@/design';
import { cartReducer, defaultPack, emptyCart, emptyTender, remainingAfterOthers, toLinesIn, toPayments, type CartLine, type CartState, type RxLink, type ChangeIn, type PaymentIn, type Tender } from './cart';
import { useMedicines, usePreview, useRate, useRequestKey, toCartMedicine, type Finding } from './hooks';

export interface PosLoad {
  /** No pack unit: the base unit. rx: the line dispenses this prescription item. */
  lines: { medicine_id: string; pack_unit_id?: string; qty: number; rx?: RxLink }[];
  customer?: { id: string; name: string; phone: string } | null;
  resumed?: { number: string; changes: unknown[] } | null;
}

/** A random id per browser (one per till), kept in localStorage when it can be. */
export function deviceId(): string {
  try {
    const known = localStorage.getItem('pos-device-id');
    if (known) return known;
    const made = `till-${crypto.randomUUID().slice(0, 12)}`;
    localStorage.setItem('pos-device-id', made);
    return made;
  } catch {
    return 'till-nostorage';
  }
}

/** T2: the POS tells the server it is alive every minute (offline alert after 10 minutes in opening hours). */
function useHeartbeat(branchId: string | undefined) {
  useEffect(() => {
    if (!branchId) return;
    const id = deviceId();
    const beat = () => { void api.notifications.POST('/api/notifications/v1/heartbeat', { body: { branch_id: branchId, device_id: id } }).catch(() => undefined); };
    beat();
    const timer = window.setInterval(beat, 60_000);
    return () => window.clearInterval(timer);
  }, [branchId]);
}

/** A PIN / approval token is good for 2 minutes and for one sale. */
function fresh(t: PinToken | null): PinToken | null {
  return t && Date.parse(t.expires_at) > Date.now() + 5_000 ? t : null;
}

export function usePos() {
  const user = useUser();
  const { oneBranch } = useBranch();
  const branchId = oneBranch?.id;
  const qc = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const [cart, dispatch] = useReducer(cartReducer, emptyCart);
  const [mode, setMode] = useState<'cart' | 'pay'>('cart');
  const [tender, setTender] = useState<Tender>(emptyTender);
  const [changeIn, setChangeIn] = useState<ChangeIn>('USD_KHR');
  const [pin, setPin] = useState<PinToken | null>(null);
  const [approval, setApproval] = useState<PinToken | null>(null);
  const [done, setDone] = useState<SalesS['InvoiceOut'] | null>(null);
  const [pending, setPending] = useState<PosLoad | null>(null);
  const rate = useRate(branchId);
  useHeartbeat(branchId);

  // lines handed over by the back office (resume, template, order): load their medicines first
  useEffect(() => {
    const st = location.state as { load?: PosLoad } | null;
    if (st?.load) {
      setPending(st.load);
      navigate(location.pathname, { replace: true, state: null });
    }
  }, [location.state, location.pathname, navigate]);
  const meds = useMedicines(pending?.lines.map((l) => l.medicine_id) ?? []);
  useEffect(() => {
    if (!pending || meds.some((m) => m.isLoading)) return;
    const lines: CartLine[] = pending.lines.flatMap((l, i) => {
      const m = meds[i]?.data;
      if (!m) return [];
      const medicine = toCartMedicine(m);
      return [{ key: `${l.medicine_id}-${i}-${Date.now()}`, medicine, pack_unit_id: l.pack_unit_id ?? defaultPack(medicine), qty: l.qty, rx: l.rx ?? null }];
    });
    dispatch({ type: 'load', lines, customer: pending.customer ?? null, resumedFrom: pending.resumed ?? null });
    setPending(null);
  }, [pending, meds]);

  const payments: PaymentIn[] = useMemo(() => (mode === 'pay' ? toPayments(tender) : []), [mode, tender]);
  const pinToken = fresh(pin)?.pin_token ?? null;
  const approvalToken = fresh(approval)?.pin_token ?? null;
  const preview = usePreview({ branchId, lines: cart.lines, customerId: cart.customer?.id, payments, changeIn, pinToken, approvalToken });
  const p = preview.data && preview.body ? preview.data : undefined;

  const all: Finding[] = p ? [...p.hard_stops, ...p.requirements, ...p.warnings, ...p.lines.flatMap((l) => [...l.hard_stops, ...l.requirements, ...l.warnings])] : [];
  const unresolved = all.filter((f) => !f.resolved && f.severity !== 'info');
  const requirementsOpen = unresolved.some((f) => f.severity === 'requirement');
  const canPay = !!p && preview.fresh && p.can_post && !requirementsOpen && cart.lines.length > 0;

  const invoiceBody = useMemo(() => branchId ? {
    branch_id: branchId,
    customer_id: cart.customer?.id ?? null,
    lines: toLinesIn(cart.lines),
    payments: toPayments(tender),
    change_in: changeIn,
    pin_token: pinToken,
    discount_approval_token: approvalToken,
  } : null, [branchId, cart.customer, cart.lines, tender, changeIn, pinToken, approvalToken]);
  const key = useRequestKey(JSON.stringify(invoiceBody));

  const complete = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/invoices', { body: invoiceBody!, ...withKey(key) })),
    onSuccess: (inv) => {
      setDone(inv);
      setPin(null);
      setApproval(null);
      void qc.invalidateQueries({ queryKey: ['sales', 'invoices'] });
    },
    onError: (e) => {
      // a used token cannot be used again: ask for it again
      if (isApiError(e) && (e.code === 'PIN_INVALID' || e.code === 'PIN_REQUIRED')) setPin(null);
      if (isApiError(e) && e.code === 'DISCOUNT_APPROVAL_REQUIRED') setApproval(null);
    },
  });

  const reset = useCallback(() => {
    dispatch({ type: 'clear' });
    setTender(emptyTender);
    setMode('cart');
    setPin(null);
    setApproval(null);
    setDone(null);
    complete.reset();
  }, [complete]);

  const addOther = (method: PaymentIn['method'], extra: Partial<PaymentIn> = {}) => {
    const due = remainingAfterOthers(Number(p?.total ?? 0), tender, rate.data?.khr_per_usd ?? null);
    if (due <= 0 && !extra.amount) return;
    setTender((t) => ({ ...t, others: [...t.others, { method, currency: 'USD', amount: due.toFixed(2), ...extra }] }));
    setMode('pay');
  };

  return {
    user, branch: oneBranch, branchId, rate: rate.data?.khr_per_usd ?? null, rateQuery: rate,
    cart, dispatch, mode, setMode, tender, setTender, changeIn, setChangeIn,
    pin, setPin, approval, setApproval, preview, p, all, unresolved, canPay,
    complete, done, reset, addOther, loading: !!pending,
  };
}

export type Pos = ReturnType<typeof usePos>;
export type { CartState };
