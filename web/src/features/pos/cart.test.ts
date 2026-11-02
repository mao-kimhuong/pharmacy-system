import { cartReducer, emptyCart, quickKhr, quickUsd, rielIsValid, toLinesIn, toPayments, type CartMedicine } from './cart';

const med = (over: Partial<CartMedicine> = {}): CartMedicine => ({
  id: 'm1', sku: 'PARA500', name: 'Paracetamol 500 mg', name_km: '', is_rx_only: false, controlled: false, is_hamper: false,
  pack_units: [
    { id: 'box', name: 'box', qty_in_base: 100, is_base: false, is_active: true },
    { id: 'tab', name: 'tab', qty_in_base: 1, is_base: true, is_active: true },
  ],
  ...over,
});

describe('cart', () => {
  it('adds the base pack unit and merges the same pack', () => {
    let s = cartReducer(emptyCart, { type: 'add', medicine: med() });
    s = cartReducer(s, { type: 'add', medicine: med() });
    expect(s.lines).toHaveLength(1);
    expect(s.lines[0]).toMatchObject({ pack_unit_id: 'tab', qty: 2 });
    s = cartReducer(s, { type: 'add', medicine: med(), pack_unit_id: 'box' });
    expect(s.lines).toHaveLength(2);
    expect(s.selected).toBe(1);
  });

  it('does not merge into a line linked to a prescription', () => {
    let s = cartReducer(emptyCart, { type: 'add', medicine: med() });
    s = cartReducer(s, { type: 'update', key: s.lines[0].key, patch: { rx: { rx_item_id: 'r', number: 'RX', patient: 'P' } } });
    s = cartReducer(s, { type: 'add', medicine: med() });
    expect(s.lines).toHaveLength(2);
  });

  it('removes a line when the quantity goes to 0', () => {
    let s = cartReducer(emptyCart, { type: 'add', medicine: med() });
    s = cartReducer(s, { type: 'qty', key: s.lines[0].key, qty: 0 });
    expect(s.lines).toHaveLength(0);
  });

  it('sends lines in order with the answers to the findings', () => {
    let s = cartReducer(emptyCart, { type: 'add', medicine: med() });
    s = cartReducer(s, { type: 'update', key: s.lines[0].key, patch: { discount_pct: '10', patient_id_document: ' 0102 ', batch_id: 'b1', override_reason: 'damaged box' } });
    expect(toLinesIn(s.lines)).toEqual([{
      medicine_id: 'm1', pack_unit_id: 'tab', qty: 1, batch_id: 'b1', override_reason: 'damaged box', rx_item_id: null,
      allergy_override_reason: null, acknowledge_warnings: false, patient_id_document: '0102', discount_pct: '10', discount_amount: null,
    }]);
  });

  it('builds cash payments in USD and whole-hundred riel', () => {
    expect(toPayments({ cashUsd: '10', cashKhr: '20000', others: [{ method: 'card', amount: '1.00' }] })).toEqual([
      { method: 'card', amount: '1.00' },
      { method: 'cash', currency: 'USD', amount: '10.00' },
      { method: 'cash', currency: 'KHR', amount: '20000' },
    ]);
    expect(rielIsValid('20000')).toBe(true);
    expect(rielIsValid('20050')).toBe(false);
  });

  it('offers quick cash amounts above the total', () => {
    expect(quickUsd(12.5)).toEqual([12.5, 13, 15, 20]);
    expect(quickKhr(12.5, 4100)).toEqual([51300, 55000, 60000, 100000]);
  });
});
