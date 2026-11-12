import { describe, expect, it } from 'vitest';
import { promotionBody, type Create } from './promotionForm';

const base: Create = { code: 'A', name: 'A', type: 'percent_off', value: '10', buy_qty: 2, get_qty: 1, medicine_ids: ['m'], category_ids: ['c'], brand_ids: ['b'],
  tiers: [{ min_qty: 2, percent: '5' }], bundle_items: [{ medicine_id: 'm', qty_base: 2 }] };

describe('promotionBody', () => {
  it('keeps only the fields of the type', () => {
    expect(promotionBody(base)).toMatchObject({ value: '10', buy_qty: null, get_qty: null, tiers: [], bundle_items: [], medicine_ids: ['m'] });
    expect(promotionBody({ ...base, type: 'buy_x_get_y' })).toMatchObject({ value: null, buy_qty: 2, get_qty: 1, tiers: [] });
    expect(promotionBody({ ...base, type: 'qty_tiers' })).toMatchObject({ value: null, tiers: [{ min_qty: 2, percent: '5' }] });
  });
  it('a bundle sends its items and price, no targets', () => {
    expect(promotionBody({ ...base, type: 'bundle_price' })).toMatchObject({ value: '10', bundle_items: [{ medicine_id: 'm', qty_base: 2 }], medicine_ids: [], category_ids: [], brand_ids: [] });
  });
  it('an empty value is null', () => {
    expect(promotionBody({ ...base, value: '' }).value).toBeNull();
  });
});
