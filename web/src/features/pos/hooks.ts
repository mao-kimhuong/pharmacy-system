import { useEffect, useMemo, useRef, useState } from 'react';
import { keepPreviousData, useQueries, useQuery } from '@tanstack/react-query';
import { api, call } from '@/api/client';
import type { CatalogS, SalesS } from '@/api/types';
import { useDebounced } from '@/design';
import type { CartLine, CartMedicine, PaymentIn, ChangeIn } from './cart';
import { toLinesIn } from './cart';

export type Preview = SalesS['CartPreviewOut'];
export type Finding = SalesS['FindingOut'];

export function toCartMedicine(m: CatalogS['SearchHit'] | CatalogS['MedicineOut']): CartMedicine {
  return {
    id: m.id,
    sku: m.sku,
    name: [m.brand_name, m.strength].filter(Boolean).join(' '),
    name_km: m.name_km,
    is_rx_only: m.is_rx_only,
    controlled: !!m.controlled_schedule,
    is_hamper: m.kind === 'hamper',
    pack_units: m.pack_units.map((p) => ({ id: p.id, name: p.name, qty_in_base: p.qty_in_base, is_base: p.is_base, is_active: p.is_active })),
  };
}

/** The branch's current KHR rate (latest of the history). */
export function useRate(branchId: string | undefined) {
  return useQuery({
    queryKey: ['sales', 'rate', branchId],
    enabled: !!branchId,
    staleTime: 60_000,
    queryFn: async () => {
      const rows = await call(api.sales.GET('/api/sales/v1/exchange-rates/{branch_id}', { params: { path: { branch_id: branchId! }, query: { size: 1 } } }));
      return rows[0] ?? null;
    },
  });
}

export interface PreviewInput {
  branchId: string | undefined;
  lines: CartLine[];
  customerId?: string | null;
  payments?: PaymentIn[];
  changeIn?: ChangeIn;
  pinToken?: string | null;
  approvalToken?: string | null;
}

/** POST /carts/preview after every change (debounced). Nothing is written and no token is consumed. */
export function usePreview(input: PreviewInput) {
  const body = useMemo(() => input.branchId && input.lines.length > 0 ? {
    branch_id: input.branchId,
    customer_id: input.customerId ?? null,
    lines: toLinesIn(input.lines),
    payments: input.payments && input.payments.length > 0 ? input.payments : null,
    change_in: input.changeIn ?? 'USD_KHR',
    pin_token: input.pinToken ?? null,
    discount_approval_token: input.approvalToken ?? null,
  } : null, [input.branchId, input.lines, input.customerId, input.payments, input.changeIn, input.pinToken, input.approvalToken]);
  const debounced = useDebounced(body, 250);
  const q = useQuery({
    queryKey: ['sales', 'preview', debounced],
    enabled: !!debounced,
    placeholderData: keepPreviousData,
    staleTime: 0,
    queryFn: () => call(api.sales.POST('/api/sales/v1/carts/preview', { body: debounced! })),
  });
  // the shown preview belongs to the current cart only when the debounced body caught up
  const fresh = !!body && debounced === body && !q.isFetching;
  return { ...q, body, fresh };
}

export async function searchMedicines(q: string) {
  const r = await call(api.catalog.GET('/api/catalog/v1/medicines/search', { params: { query: { q, size: 8 } } }));
  return r.items.filter((m) => m.is_active);
}

/** Medicines by id (lines loaded from a template, a suspended cart or an order). */
export function useMedicines(ids: string[]) {
  const qs = useQueries({
    queries: ids.map((id) => ({
      queryKey: ['catalog', 'medicine', id],
      staleTime: 5 * 60_000,
      queryFn: () => call(api.catalog.GET('/api/catalog/v1/medicines/{medicine_id}', { params: { path: { medicine_id: id } } })),
    })),
  });
  return qs;
}

/** Keeps an Idempotency-Key per distinct request: same body → same key (a retry replays), new body → new key. */
export function useRequestKey(fingerprint: string) {
  const ref = useRef<{ fp: string; key: string }>({ fp: '', key: '' });
  if (ref.current.fp !== fingerprint) ref.current = { fp: fingerprint, key: crypto.randomUUID() };
  return ref.current.key;
}

export function useHotkeys(map: Record<string, (e: KeyboardEvent) => void>, enabled = true) {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const fn = ref.current[e.key];
      if (fn) fn(e);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [enabled]);
}

export function useNowTick(ms: number) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((x) => x + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return n;
}
