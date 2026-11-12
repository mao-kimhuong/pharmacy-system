import { useMemo, useState } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import type { PillTone } from '@/design';

export function usePaging(size = 20) {
  const [page, setPage] = useState(1);
  const [s, setS] = useState(size);
  return { page, size: s, setPage, setSize: (n: number) => { setS(n); setPage(1); }, reset: () => setPage(1) };
}

/** Staff names by id. The full list needs settings.users; others see their own name only (never an id guess). */
export function useStaffNames() {
  const user = useUser();
  const q = useQuery({
    queryKey: ['auth', 'users', 'names'],
    enabled: user.has('settings.users'),
    staleTime: 5 * 60_000,
    queryFn: () => call(api.auth.GET('/api/auth/v1/users', { params: { query: { size: 100 } } })),
  });
  return useMemo(() => {
    const m = new Map<string, string>((q.data?.items ?? []).map((u) => [u.id, u.name]));
    m.set(user.id, user.name);
    return (id: string | null | undefined) => (id ? m.get(id) ?? '—' : '—');
  }, [q.data, user.id, user.name]);
}

/** Customer names for a page of records (unique ids only; needs contacts.customers). */
export function useCustomerNames(ids: (string | null | undefined)[]) {
  const user = useUser();
  const unique = [...new Set(ids.filter((x): x is string => !!x))];
  const qs = useQueries({
    queries: unique.map((id) => ({
      queryKey: ['customers', 'customer', id],
      enabled: user.has('contacts.customers'),
      staleTime: 5 * 60_000,
      queryFn: () => call(api.customers.GET('/api/customers/v1/customers/{customer_id}', { params: { path: { customer_id: id } } })),
    })),
  });
  const m = new Map(qs.flatMap((q) => (q.data ? [[q.data.id, q.data] as const] : [])));
  return (id: string | null | undefined) => (id ? m.get(id) : undefined);
}

const TONES: Record<string, PillTone> = {
  completed: 'success', fulfilled: 'success', paid: 'success', received: 'success', closed: 'neutral', approved: 'success', credited: 'success', refunded: 'success', posted: 'success',
  pending: 'warning', pending_approval: 'warning', submitted: 'warning', partly_fulfilled: 'warning', partly_received: 'warning', partly_dispensed: 'warning', partly_returned: 'warning', needs_attention: 'danger', in_transit: 'info', dispatched: 'info', picked: 'info',
  quote: 'neutral', draft: 'neutral', ordered: 'primary', sent: 'primary', active: 'primary', open: 'primary', suspended: 'info', counting: 'info', review: 'warning',
  cancelled: 'cancelled', failed: 'danger', expired: 'danger', rejected: 'danger', recalled: 'danger', quarantined: 'warning', fully_dispensed: 'neutral',
  returned: 'purple', resumed: 'neutral', cancelling: 'warning', lifted: 'neutral',
};
export const toneOf = (status: string): PillTone => TONES[status] ?? 'neutral';

/** Medicine display names by id (catalog GET per unique id, cached). */
export function useMedicineNames(ids: string[]) {
  const unique = [...new Set(ids)];
  const qs = useQueries({
    queries: unique.map((id) => ({
      queryKey: ['catalog', 'medicine', id],
      staleTime: 5 * 60_000,
      queryFn: () => call(api.catalog.GET('/api/catalog/v1/medicines/{medicine_id}', { params: { path: { medicine_id: id } } })),
    })),
  });
  const m = new Map(qs.flatMap((q) => (q.data ? [[q.data.id, q.data] as const] : [])));
  return (id: string) => {
    const x = m.get(id);
    return x ? [x.brand_name, x.strength].filter(Boolean).join(' ') : '…';
  };
}
