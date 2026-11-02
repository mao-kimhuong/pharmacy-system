import { me } from '@/test/fixtures';
import { toCurrentUser } from './auth';
import { allowed } from './gate';

describe('permission gating', () => {
  const cashier = toCurrentUser(me());
  const owner = toCurrentUser(me({ role: 'owner', permissions: ['*'], menu: [] }));
  const none = new Set<string>();

  it('needs the menu key from /me', () => {
    expect(allowed({ menu: 'pos' }, cashier, none)).toBe(true);
    expect(allowed({ menu: 'sale_margin_by_item' }, cashier, none)).toBe(false);
  });
  it('hides menu keys of switched-off features', () => {
    expect(allowed({ menu: 'pos' }, cashier, new Set(['pos']))).toBe(false);
  });
  it('checks any-of permissions; the owner has *', () => {
    expect(allowed({ perms: ['finance.cost_profit'] }, cashier, none)).toBe(false);
    expect(allowed({ perms: ['finance.cost_profit', 'pos.sell'] }, cashier, none)).toBe(true);
    expect(allowed({ perms: ['finance.cost_profit'] }, owner, none)).toBe(true);
    expect(owner.has('anything')).toBe(true);
  });
  it('can require the pharmacist flag or the owner', () => {
    expect(allowed({ pharmacist: true }, cashier, none)).toBe(false);
    expect(allowed({ pharmacist: true }, toCurrentUser(me({ is_pharmacist: true })), none)).toBe(true);
    expect(allowed({ owner: true }, cashier, none)).toBe(false);
    expect(allowed({ owner: true }, owner, none)).toBe(true);
  });
});
