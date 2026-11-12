// The promotion form's rules that are plain data: which fields each type sends.
import type { CatalogS } from '@/api/types';

export type Create = CatalogS['PromotionCreate'];
export const TYPES: Create['type'][] = ['percent_off', 'amount_off', 'buy_x_get_y', 'bundle_price', 'qty_tiers', 'group_price'];

const HAS_VALUE: Create['type'][] = ['percent_off', 'amount_off', 'bundle_price', 'group_price'];
export const hasValue = (t: Create['type']) => HAS_VALUE.includes(t);

/** Only the fields of the chosen type, so switching type never sends leftovers. */
export function promotionBody(v: Create): Create {
  const t = v.type;
  const bundle = t === 'bundle_price';
  return {
    ...v,
    value: hasValue(t) && v.value !== '' ? v.value : null,
    buy_qty: t === 'buy_x_get_y' ? v.buy_qty : null,
    get_qty: t === 'buy_x_get_y' ? v.get_qty : null,
    tiers: t === 'qty_tiers' ? v.tiers : [],
    bundle_items: bundle ? v.bundle_items : [],
    medicine_ids: bundle ? [] : v.medicine_ids,
    category_ids: bundle ? [] : v.category_ids,
    brand_ids: bundle ? [] : v.brand_ids,
  };
}
