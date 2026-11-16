import { describe, expect, it } from 'vitest';
import { stateOf } from './Khqr';
import { tileStates } from './Panel';
import { mmss } from './PaymentModal';
import { tileForKey } from './PaymentTiles';
import type { Tender } from './cart';

const key = (k: string, code: string, alt = false) => ({ key: k, code, altKey: alt, ctrlKey: false, metaKey: false });
const t = (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k);
const empty: Tender = { cashUsd: '', cashKhr: '', others: [] };

describe('tileForKey', () => {
  it('1–5 pick the tiles outside text fields; Alt+1–5 also inside them', () => {
    expect(tileForKey(key('1', 'Digit1'), false)).toBe('cash');
    expect(tileForKey(key('5', 'Digit5'), false)).toBe('credit');
    expect(tileForKey(key('2', 'Digit2'), true)).toBeNull(); // typing a 2 into the cash field stays typing
    expect(tileForKey(key('™', 'Digit2', true), true)).toBe('KHQR'); // macOS Alt+2 types "™": the code decides
    expect(tileForKey(key('6', 'Digit6'), false)).toBeNull();
    expect(tileForKey({ ...key('1', 'Digit1'), ctrlKey: true }, false)).toBeNull();
  });
});

describe('tileStates', () => {
  it('pay later needs a customer with enough credit; nothing due disables the others', () => {
    const none = tileStates({ tender: empty, due: 5, hasCustomer: false, availableCredit: null, t });
    expect(none.credit.disabled).toBe('tiles.why.customer');
    expect(none.cash).toEqual({ selected: true, disabled: null });
    const low = tileStates({ tender: empty, due: 5, hasCustomer: true, availableCredit: 3, t });
    expect(low.credit.disabled).toContain('tiles.why.limit');
    const ok = tileStates({ tender: empty, due: 5, hasCustomer: true, availableCredit: 50, t });
    expect(ok.credit.disabled).toBeNull();
    const paid = tileStates({ tender: { ...empty, others: [{ method: 'KHQR', currency: 'USD', amount: '5.00' }] }, due: 0, hasCustomer: true, availableCredit: 50, t });
    expect(paid.KHQR).toEqual({ selected: true, disabled: 'tiles.why.nothingDue' });
    expect(paid.cash.selected).toBe(false); // KHQR covered it; cash is not the one in use
  });
});

describe('payment modal helpers', () => {
  it('shows the countdown as m:ss and maps a payment to its state', () => {
    expect(mmss(0)).toBe('0:00');
    expect(mmss(872)).toBe('14:32');
    expect(stateOf(undefined)).toBe('start');
    const base = { status: 'pending', provider_status: null } as never;
    expect(stateOf(base)).toBe('pending');
    expect(stateOf({ ...(base as object), provider_status: 'declined' } as never)).toBe('declined');
    expect(stateOf({ ...(base as object), status: 'review' } as never)).toBe('review');
    expect(stateOf({ ...(base as object), status: 'used' } as never)).toBe('cancelled');
  });
});
