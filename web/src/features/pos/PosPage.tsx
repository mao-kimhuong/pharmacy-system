// POS (3a–3o) on desktop and tablet; phones get POS lite (4a–4d). All 9 flows run on POST /carts/preview: Pay stays
// disabled until the preview says can_post and every requirement (PIN, patient ID, approval) is met.
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiErrorAlert, BranchTag, ConfirmDialog, PinDialog, WitnessDialog, cx, useToast } from '@/design';
import { api, call } from '@/api/client';
import { LangToggle, ThemeToggle } from '@/app/shell/Header';
import { initials } from '@/lib/format';
import { useMediaQuery, useOnline } from '@/lib/hooks';
import { branchName } from '@/app/branch';
import { CartTable } from './CartTable';
import { CustomerBox, type CustomerBoxHandle } from './CustomerBox';
import { useHotkeys } from './hooks';
import { KhqrDialog } from './Khqr';
import { PaywayDialog, ReferenceDialog } from './Payway';
import type { TileKey } from './PaymentTiles';
import { LineOptionsDialog } from './LineOptions';
import { LinkRxDrawer } from './LinkRx';
import { CartFindings, KeyHints, PaymentView, SummaryActions, Totals } from './Panel';
import { PosLite } from './PosLite';
import { SaleComplete } from './SaleComplete';
import { ScanBox, type ScanBoxHandle } from './ScanBox';
import { SuspendDialog } from './Suspend';
import { AskTelegram } from './TelegramApproval';
import { useFindingActions } from './useFindingActions';
import { usePos } from './usePos';
import { remainingAfterOthers } from './cart';

export function PosDialogs({ pos, dlg, setDlg }: { pos: ReturnType<typeof usePos>; dlg: Dlg; setDlg: (d: Dlg) => void }) {
  const { t } = useTranslation('pos');
  const toast = useToast();
  const line = dlg.kind === 'options' || dlg.kind === 'rx' ? pos.cart.lines.find((l) => l.key === dlg.key) ?? null : null;
  const approvalFinding = pos.all.find((f) => f.code === 'DISCOUNT_APPROVAL_REQUIRED');
  const roles = (approvalFinding?.details?.approver_roles as string[] | undefined) ?? ['owner', 'branch_manager'];
  const total = remainingAfterOthers(Number(pos.p?.total ?? 0), pos.tender, pos.rate); // what the new payment takes
  if (!pos.branchId) return null;
  return (
    <>
      {dlg.kind === 'options' && <LineOptionsDialog line={line} branchId={pos.branchId} onClose={() => setDlg({ kind: '' })} onSave={(patch) => line && pos.dispatch({ type: 'update', key: line.key, patch })} />}
      {dlg.kind === 'rx' && <LinkRxDrawer line={line} onClose={() => setDlg({ kind: '' })} onLink={(rx) => line && pos.dispatch({ type: 'update', key: line.key, patch: { rx } })} onRemove={() => line && pos.dispatch({ type: 'remove', key: line.key })} />}
      <PinDialog open={dlg.kind === 'pin'} action="controlled.dispense" title={t('find.pin')} onClose={() => setDlg({ kind: '' })} onToken={(tk) => { pos.setPin(tk); setDlg({ kind: '' }); }} />
      <WitnessDialog open={dlg.kind === 'approval'} action="sales.discount" branchId={pos.branchId} ownPin={false} managerOnly={!roles.includes('pharmacist')}
        title={t('find.approval')} onClose={() => setDlg({ kind: '' })} onTokens={({ witness }) => { pos.setApproval(witness); setDlg({ kind: '' }); toast.success(t('find.approved', { name: witness.name })); }}
        context={dlg.kind === 'approval' ? <AskTelegram body={pos.preview.body} onApproved={(tk) => { pos.setApproval(tk); setDlg({ kind: '' }); toast.success(t('tg.approved')); }} /> : null} />
      <SuspendDialog open={dlg.kind === 'suspend'} cart={pos.cart} branchId={pos.branchId} onClose={() => setDlg({ kind: '' })}
        onDone={(n) => { setDlg({ kind: '' }); pos.reset(); toast.success(t('suspend.done', { number: n })); }} />
      <KhqrDialog open={dlg.kind === 'khqr'} branchId={pos.branchId} amountUsd={Math.max(total, 0)} rate={pos.rate} onClose={() => setDlg({ kind: '' })}
        onPaid={(k) => { setDlg({ kind: '' }); pos.addOther('KHQR', { khqr_id: k.id, amount: k.amount, currency: k.currency as 'USD' | 'KHR' }); }} />
      <PaywayDialog open={dlg.kind === 'payway'} branchId={pos.branchId} amountUsd={Math.max(total, 0)} rate={pos.rate} onClose={() => setDlg({ kind: '' })}
        onPaid={(k) => { setDlg({ kind: '' }); pos.addOther('PAYWAY', { khqr_id: k.id, amount: k.amount, currency: k.currency as 'USD' | 'KHR' }); }} />
      <ReferenceDialog open={dlg.kind === 'ref'} method={dlg.key === 'card' ? 'card' : 'ABA'} amountUsd={Math.max(total, 0)} onClose={() => setDlg({ kind: '' })}
        onAdd={(amount, reference) => { setDlg({ kind: '' }); pos.addOther(dlg.key === 'card' ? 'card' : 'ABA', { amount, ...(reference ? { reference } : {}) }); }} />
      <ConfirmDialog open={dlg.kind === 'cancel'} onClose={() => setDlg({ kind: '' })} title={t('cancelSale.title')} body={t('cancelSale.body')} confirmLabel={t('cancelSale.confirm')} variant="danger" onConfirm={() => pos.reset()} />
    </>
  );
}

export type Dlg = { kind: '' | 'options' | 'rx' | 'pin' | 'approval' | 'suspend' | 'khqr' | 'payway' | 'ref' | 'cancel'; key?: string };

/** The payment tiles' actions and what Pay later needs (the customer's credit), shared by POS and POS lite. */
export function usePaymentPicker(pos: ReturnType<typeof usePos>, setDlg: (d: Dlg) => void) {
  const options = useQuery({ queryKey: ['sales', 'payment-options'], staleTime: 5 * 60_000,
    queryFn: () => call(api.sales.GET('/api/sales/v1/payments/options')) });
  const customer = pos.cart.customer;
  const detail = useQuery({ queryKey: ['customers', 'customer', customer?.id], enabled: !!customer,
    queryFn: () => call(api.customers.GET('/api/customers/v1/customers/{customer_id}', { params: { path: { customer_id: customer!.id } } })) });
  const credit = detail.data?.available_credit;
  const pick = (k: TileKey) => {
    if (k === 'KHQR') setDlg({ kind: 'khqr' });
    else if (k === 'card') setDlg(options.data?.payway_checkout ? { kind: 'payway' } : { kind: 'ref', key: 'card' });
    else if (k === 'ABA') setDlg({ kind: 'ref', key: 'ABA' });
    else if (k === 'credit') pos.addOther('credit');
  };
  return { pick, hasCustomer: !!customer, availableCredit: credit === undefined || credit === null ? null : Number(credit) };
}

export default function PosPage() {
  const phone = useMediaQuery('(max-width: 1023px)');
  return phone ? <PosLite /> : <PosDesktop />;
}

function PosDesktop() {
  const { t, i18n } = useTranslation(['pos', 'shell', 'common']);
  const pos = usePos();
  const online = useOnline();
  const scan = useRef<ScanBoxHandle>(null);
  const customerBox = useRef<CustomerBoxHandle>(null);
  const [dlg, setDlg] = useState<Dlg>({ kind: '' });
  const picker = usePaymentPicker(pos, setDlg);
  const cashField = useRef<HTMLInputElement>(null);
  const [notFound, setNotFound] = useState<string | null>(null);
  const sel = pos.cart.lines[pos.cart.selected];
  // After a dialog closes or payment is left, the cashier is back at the scan box.
  useEffect(() => {
    if (dlg.kind === '' && pos.mode === 'cart' && !pos.done) scan.current?.focus();
  }, [dlg.kind, pos.mode, pos.done]);
  const ui = {
    linkRx: (key: string) => setDlg({ kind: 'rx', key }),
    options: (key: string) => setDlg({ kind: 'options', key }),
    pin: () => setDlg({ kind: 'pin' }),
    approval: () => setDlg({ kind: 'approval' }),
    customer: () => customerBox.current?.focus(),
    handoff: () => setDlg({ kind: 'suspend' }),
  };
  const fa = useFindingActions(pos, ui);
  const busy = dlg.kind !== '' || !!pos.done;
  useHotkeys({
    F2: (e) => { e.preventDefault(); scan.current?.focus(); },
    F4: (e) => { e.preventDefault(); customerBox.current?.focus(); },
    F6: (e) => { e.preventDefault(); if (sel) ui.options(sel.key); },
    F7: (e) => { e.preventDefault(); if (sel && (sel.medicine.is_rx_only || sel.medicine.controlled)) ui.linkRx(sel.key); },
    F8: (e) => { e.preventDefault(); if (pos.cart.lines.length) setDlg({ kind: 'suspend' }); },
    F9: (e) => { e.preventDefault(); if (pos.canPay) pos.setMode('pay'); },
    // Esc: leave payment, else back to the scan box, else (already there) cancel the sale.
    Escape: () => {
      if (pos.mode === 'pay') pos.setMode('cart');
      else if (!scan.current?.isFocused()) scan.current?.focus();
      else if (pos.cart.lines.length) setDlg({ kind: 'cancel' });
    },
    ArrowDown: (e) => { if ((e.target as HTMLElement).tagName !== 'SELECT') pos.dispatch({ type: 'select', index: pos.cart.selected + 1 }); },
    ArrowUp: (e) => { if ((e.target as HTMLElement).tagName !== 'SELECT') pos.dispatch({ type: 'select', index: pos.cart.selected - 1 }); },
    Delete: () => { if (sel) pos.dispatch({ type: 'remove', key: sel.key }); },
    Enter: (e) => {
      const tag = (e.target as HTMLElement).tagName;
      if (pos.mode === 'pay' && tag !== 'BUTTON' && pos.canPay && pos.p?.payment && !pos.complete.isPending) { e.preventDefault(); pos.complete.mutate(); }
    },
    '+': (e) => { if (sel && (e.target as HTMLElement).tagName !== 'INPUT') { e.preventDefault(); pos.dispatch({ type: 'qty', key: sel.key, qty: sel.qty + 1 }); } },
    '-': (e) => { if (sel && (e.target as HTMLElement).tagName !== 'INPUT') { e.preventDefault(); pos.dispatch({ type: 'qty', key: sel.key, qty: sel.qty - 1 }); } },
  }, !busy);
  const cartFindings = pos.p ? [...pos.p.hard_stops, ...pos.p.requirements, ...pos.p.warnings].filter((f) => f.line_no == null) : [];
  const tokens = [pos.pin && t('find.pinOk', { name: pos.pin.name }), pos.approval && t('find.approved', { name: pos.approval.name })].filter(Boolean);
  return (
    <div className="relative flex h-dvh flex-col bg-neutral-50">
      <header className="flex h-12 flex-none items-center gap-3.5 border-b border-neutral-200 bg-surface px-4 text-[13px]">
        <Link to="/" aria-label={t('common:action.goHome')} className="flex size-7 items-center justify-center rounded-[7px] bg-primary-600 font-bold text-white no-underline">+</Link>
        <span className="font-semibold">{t('title')}</span>
        {pos.branch && <span className="flex items-center gap-1.5"><BranchTag code={pos.branch.code} />{branchName(pos.branch, i18n.language)}</span>}
        <span className={cx('flex items-center gap-1.5', online ? 'text-pill-success-fg' : 'text-pill-warning-fg')}><span className={cx('size-2 rounded-full', online ? 'bg-pill-success-dot' : 'bg-warning')} />{online ? t('online') : t('offline')}</span>
        <span className="ml-auto text-neutral-700">{pos.rate ? t('rate', { rate: pos.rate.toLocaleString('en-US') }) : <span className="text-danger">{t('noRate')}</span>}</span>
        <LangToggle size="sm" />
        <ThemeToggle />
        <span className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-full bg-primary-600 text-[11px] font-semibold text-white">{initials(pos.user.name)}</span>
          <span className="flex flex-col leading-[15px]"><b>{pos.user.name}</b><span className="text-[11px] text-neutral-500">{t(`shell:role.${pos.user.role}`, { defaultValue: pos.user.role })}</span></span>
        </span>
      </header>
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col gap-3 px-4 pt-3.5">
          <ScanBox ref={scan} onAdd={(m, pack) => { setNotFound(null); pos.dispatch({ type: 'add', medicine: m, pack_unit_id: pack }); }} onError={setNotFound} />
          {notFound && <div role="alert" className="text-[13px] text-danger">{t('noMatch', { q: notFound })}</div>}
          {pos.cart.resumedFrom && (
            <div className="rounded-lg border border-info-bd bg-info-bg px-3.5 py-2.5 text-[13px] text-info-fg">
              <b>{t('resumed.title', { number: pos.cart.resumedFrom.number })}</b>{' '}
              {pos.cart.resumedFrom.changes.length === 0 ? t('resumed.none') : (
                <span>{t('resumed.changes')} {pos.cart.resumedFrom.changes.map((c, i) => <span key={i} className="mr-2">· {typeof c === 'object' && c ? Object.values(c as Record<string, unknown>).join(' ') : String(c)}</span>)}</span>
              )}
            </div>
          )}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-neutral-200 bg-surface">
            <CartTable lines={pos.cart.lines} preview={pos.p} selected={pos.cart.selected}
              h={{ qty: (key, qty) => pos.dispatch({ type: 'qty', key, qty }), unit: (key, id) => pos.dispatch({ type: 'unit', key, pack_unit_id: id }), select: (i) => pos.dispatch({ type: 'select', index: i }), actionsFor: fa.line }} />
            <div className="flex gap-4 border-t border-neutral-100 px-3 py-2 text-[12px] text-neutral-500">
              <span>{t('items', { count: pos.cart.lines.length })}</span><span>{t('hint')}</span>
            </div>
          </div>
          <KeyHints />
        </div>
        <aside className="flex w-[400px] flex-none flex-col border-l border-neutral-200 bg-surface">
          <CustomerBox ref={customerBox} customer={pos.cart.customer} onChange={(c) => pos.dispatch({ type: 'customer', customer: c })} />
          <Totals preview={pos.p} />
          <div className="flex flex-col gap-1 px-4 pt-2">
            <CartFindings findings={cartFindings} actionsFor={fa.cart} />
            {tokens.map((x) => <div key={x as string} className="rounded-md bg-success-bg px-2.5 py-1.5 text-[12px] font-medium text-pill-success-fg">✓ {x}</div>)}
          </div>
          {pos.mode === 'cart' ? (
            <SummaryActions
              canPay={pos.canPay}
              canSuspend={pos.cart.lines.length > 0}
              blockMsg={pos.p && !pos.canPay && pos.unresolved.length > 0 ? t('find.blocked') : undefined}
              onDiscount={() => sel && ui.options(sel.key)}
              onSuspend={() => setDlg({ kind: 'suspend' })}
              onCredit={() => pos.addOther('credit')}
              onKhqr={() => setDlg({ kind: 'khqr' })}
              onPay={() => pos.setMode('pay')}
              onCancel={() => pos.cart.lines.length && setDlg({ kind: 'cancel' })}
            />
          ) : (
            <PaymentView preview={pos.p} tender={pos.tender} setTender={pos.setTender} changeIn={pos.changeIn} setChangeIn={pos.setChangeIn} rate={pos.rate}
              onMethod={picker.pick} hasCustomer={picker.hasCustomer} availableCredit={picker.availableCredit} cashField={cashField}
              onBack={() => pos.setMode('cart')} completing={pos.complete.isPending} canComplete={pos.canPay && !!pos.p?.payment && pos.preview.fresh}
              onComplete={() => pos.complete.mutate()} error={<ApiErrorAlert error={pos.complete.error} />} />
          )}
        </aside>
      </div>
      <PosDialogs pos={pos} dlg={dlg} setDlg={setDlg} />
      {pos.done && <SaleComplete invoice={pos.done} onNew={() => { pos.reset(); setTimeout(() => scan.current?.focus(), 0); }} />}
    </div>
  );
}
