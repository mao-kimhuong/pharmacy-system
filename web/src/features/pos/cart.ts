// POS cart state. Prices, totals, promotions and every check come from POST /carts/preview; the cart only holds
// what the cashier chose (medicine, pack unit, qty and the per-line answers to the preview's findings).
import type { SalesS } from '@/api/types';

export type LineIn = SalesS['LineIn'];
export type PaymentIn = SalesS['PaymentIn'];
export type ChangeIn = 'USD' | 'KHR' | 'USD_KHR';

export interface PackUnitLite {
  id: string;
  name: string;
  qty_in_base: number;
  is_base: boolean;
  is_active: boolean;
}

export interface CartMedicine {
  id: string;
  sku: string;
  name: string;
  name_km: string;
  is_rx_only: boolean;
  controlled: boolean;
  is_hamper: boolean;
  pack_units: PackUnitLite[];
}

export interface RxLink {
  rx_item_id: string;
  number: string;
  patient: string;
}

export interface CartLine {
  key: string;
  medicine: CartMedicine;
  pack_unit_id: string;
  qty: number;
  batch_id?: string | null;
  override_reason?: string;
  rx?: RxLink | null;
  allergy_override_reason?: string;
  acknowledge_warnings?: boolean;
  patient_id_document?: string;
  discount_pct?: string;
  discount_amount?: string;
}

export interface CartCustomer {
  id: string;
  name: string;
  phone: string;
}

export interface CartState {
  lines: CartLine[];
  customer: CartCustomer | null;
  selected: number;
  /** Set when the cart came from a suspended cart (3n). */
  resumedFrom?: { number: string; changes: unknown[] } | null;
}

export const emptyCart: CartState = { lines: [], customer: null, selected: -1, resumedFrom: null };

export type CartAction =
  | { type: 'add'; medicine: CartMedicine; pack_unit_id?: string; qty?: number }
  | { type: 'qty'; key: string; qty: number }
  | { type: 'unit'; key: string; pack_unit_id: string }
  | { type: 'update'; key: string; patch: Partial<CartLine> }
  | { type: 'remove'; key: string }
  | { type: 'select'; index: number }
  | { type: 'customer'; customer: CartCustomer | null }
  | { type: 'load'; lines: CartLine[]; customer?: CartCustomer | null; resumedFrom?: CartState['resumedFrom'] }
  | { type: 'clear' };

let seq = 0;
export const newKey = () => `l${Date.now().toString(36)}${(++seq).toString(36)}`;

export function defaultPack(m: CartMedicine): string {
  const active = m.pack_units.filter((p) => p.is_active);
  return (active.find((p) => p.is_base) ?? active[0] ?? m.pack_units[0]).id;
}

export function cartReducer(s: CartState, a: CartAction): CartState {
  switch (a.type) {
    case 'add': {
      const pack = a.pack_unit_id ?? defaultPack(a.medicine);
      const qty = a.qty ?? 1;
      // the same pack again adds to the line (unless that line is tied to an Rx or a chosen batch)
      const i = s.lines.findIndex((l) => l.medicine.id === a.medicine.id && l.pack_unit_id === pack && !l.rx && !l.batch_id);
      if (i >= 0) {
        const lines = s.lines.map((l, j) => (j === i ? { ...l, qty: l.qty + qty } : l));
        return { ...s, lines, selected: i };
      }
      const lines = [...s.lines, { key: newKey(), medicine: a.medicine, pack_unit_id: pack, qty }];
      return { ...s, lines, selected: lines.length - 1 };
    }
    case 'qty':
      if (a.qty <= 0) return cartReducer(s, { type: 'remove', key: a.key });
      return { ...s, lines: s.lines.map((l) => (l.key === a.key ? { ...l, qty: Math.min(a.qty, 99_999) } : l)) };
    case 'unit':
      return { ...s, lines: s.lines.map((l) => (l.key === a.key ? { ...l, pack_unit_id: a.pack_unit_id, batch_id: null } : l)) };
    case 'update':
      return { ...s, lines: s.lines.map((l) => (l.key === a.key ? { ...l, ...a.patch } : l)) };
    case 'remove': {
      const lines = s.lines.filter((l) => l.key !== a.key);
      return { ...s, lines, selected: Math.min(s.selected, lines.length - 1) };
    }
    case 'select':
      return { ...s, selected: Math.max(-1, Math.min(a.index, s.lines.length - 1)) };
    case 'customer':
      return { ...s, customer: a.customer };
    case 'load':
      return { lines: a.lines, customer: a.customer ?? null, selected: a.lines.length - 1, resumedFrom: a.resumedFrom ?? null };
    case 'clear':
      return emptyCart;
  }
}

const num = (v: string | undefined) => (v && v.trim() !== '' && Number(v) > 0 ? v.trim() : null);

/** The cart as the API's lines (line_no = position + 1). */
export function toLinesIn(lines: CartLine[]): LineIn[] {
  return lines.map((l) => ({
    medicine_id: l.medicine.id,
    pack_unit_id: l.pack_unit_id,
    qty: l.qty,
    batch_id: l.batch_id || null,
    override_reason: l.batch_id ? l.override_reason || null : null,
    rx_item_id: l.rx?.rx_item_id ?? null,
    allergy_override_reason: l.allergy_override_reason?.trim() || null,
    acknowledge_warnings: !!l.acknowledge_warnings,
    patient_id_document: l.patient_id_document?.trim() || null,
    discount_pct: num(l.discount_pct),
    discount_amount: num(l.discount_amount),
  }));
}

/** Cash in USD and KHR plus the other methods. KHR must be whole hundreds. */
export interface Tender {
  cashUsd: string;
  cashKhr: string;
  others: PaymentIn[];
}

export const emptyTender: Tender = { cashUsd: '', cashKhr: '', others: [] };

/** USD left for the next method once the payments already added (not the cash fields) are counted: what a new KHQR,
 *  card, transfer or credit row takes. From the tender itself, not the preview (which has no payment figures while
 *  the payments are still short). Riel rows count at the rate. */
export function remainingAfterOthers(total: number, t: Tender, rate: number | null): number {
  const others = t.others.reduce((sum, p) => sum + (p.currency === 'KHR' ? (rate ? Number(p.amount) / rate : 0) : Number(p.amount)), 0);
  return Math.max(0, Math.round((total - others) * 100) / 100);
}

export function toPayments(t: Tender): PaymentIn[] {
  const out: PaymentIn[] = [...t.others];
  const usd = Number(t.cashUsd);
  const khr = Number(t.cashKhr);
  if (t.cashUsd && usd > 0) out.push({ method: 'cash', currency: 'USD', amount: usd.toFixed(2) });
  if (t.cashKhr && khr > 0) out.push({ method: 'cash', currency: 'KHR', amount: String(Math.round(khr)) });
  return out;
}

export function rielIsValid(v: string): boolean {
  if (!v) return true;
  const n = Number(v);
  return Number.isInteger(n) && n >= 0 && n % 100 === 0;
}

/** Quick cash buttons: exact total, then the next round notes above it. */
export function quickUsd(total: number): number[] {
  if (!(total > 0)) return [];
  const out = new Set<number>([Math.round(total * 100) / 100]);
  for (const step of [1, 5, 10, 20, 50, 100]) {
    const v = Math.ceil(total / step) * step;
    if (v > total) out.add(v);
    if (out.size >= 4) break;
  }
  return [...out];
}

export function quickKhr(total: number, rate: number): number[] {
  if (!(total > 0) || !rate) return [];
  const exact = Math.ceil((total * rate) / 100) * 100;
  const out = new Set<number>([exact]);
  for (const step of [5_000, 10_000, 20_000, 50_000, 100_000]) {
    const v = Math.ceil(exact / step) * step;
    if (v > exact) out.add(v);
    if (out.size >= 4) break;
  }
  return [...out];
}

/** A stable JSON of what is sent: a new Idempotency-Key whenever it changes (a retry of the same request reuses it). */
export function requestFingerprint(x: unknown): string {
  return JSON.stringify(x);
}
