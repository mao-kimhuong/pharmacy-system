// Hands lines to the POS (resume, template, order): the POS loads the medicines and re-prices through the preview.
import { api, call } from '@/api/client';
import type { PosLoad } from '../pos/usePos';

export async function customerRef(id: string | null | undefined): Promise<PosLoad['customer']> {
  if (!id) return null;
  try {
    const c = await call(api.customers.GET('/api/customers/v1/customers/{customer_id}', { params: { path: { customer_id: id } } }));
    return { id: c.id, name: c.name, phone: c.phone };
  } catch {
    return null;
  }
}

export function linesOf(raw: unknown[]): PosLoad['lines'] {
  return raw.flatMap((x) => {
    const l = x as { medicine_id?: string; pack_unit_id?: string; qty?: number };
    return l.medicine_id && l.pack_unit_id && l.qty ? [{ medicine_id: l.medicine_id, pack_unit_id: l.pack_unit_id, qty: l.qty }] : [];
  });
}
