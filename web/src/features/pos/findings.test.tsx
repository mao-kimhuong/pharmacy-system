import { renderHook, waitFor } from '@testing-library/react';
import { toCurrentUser } from '@/app/auth';
import { setLang } from '@/i18n';
import { me } from '@/test/fixtures';
import type { CartLine } from './cart';
import type { Finding } from './hooks';
import { useFindingActions } from './useFindingActions';
import type { Pos } from './usePos';

const line: CartLine = { key: 'k', medicine: { id: 'm', sku: 'S', name: 'N', name_km: '', is_rx_only: true, controlled: false, is_hamper: false, pack_units: [] }, pack_unit_id: 'p', qty: 1 };
const f = (code: string, details: Record<string, unknown> = {}): Finding => ({ code, severity: 'warning', line_no: 1, message_en: '', message_km: '', details, resolved: false });

async function actions(user: ReturnType<typeof me>, finding: Finding) {
  setLang('en');
  const pos = { user: toCurrentUser(user), dispatch: vi.fn() } as unknown as Pos;
  const ui = { linkRx: vi.fn(), options: vi.fn(), pin: vi.fn(), approval: vi.fn(), customer: vi.fn(), handoff: vi.fn() };
  const { result } = renderHook(() => useFindingActions(pos, ui));
  await waitFor(() => expect(result.current.line(line, f('RX_REQUIRED'))[0].label).not.toMatch(/^(find|handoff)/));
  return result.current.line(line, finding).map((a) => a.label);
}

const pharmacist = me({ is_pharmacist: true, permissions: ['pos.sell', 'pos.dispense_rx', 'prescriptions.override_warning'] });

describe('finding actions', async () => {
  it('cashier: an Rx line can only be handed over or removed', async () => {
    expect(await actions(me(), f('RX_REQUIRED'))).toEqual(['Hand to pharmacist (suspend)', 'Remove item']);
  });
  it('pharmacist: links the Rx', async () => {
    expect(await actions(pharmacist, f('RX_REQUIRED'))).toEqual(['Link Rx']);
  });
  it('reads the warning kinds: allergy override needs the permission, duplicate therapy is acknowledged', async () => {
    const w = f('ALLERGY_WARNING', { warnings: [{ kind: 'allergy' }, { kind: 'duplicate_therapy' }] });
    expect(await actions(pharmacist, w)).toEqual(['Override', 'Acknowledge', 'Remove item']);
    expect(await actions(me(), w)).toEqual(['Acknowledge', 'Remove item']);
    expect(await actions(pharmacist, f('ALLERGY_WARNING', { warnings: [{ kind: 'duplicate_therapy' }] }))).toEqual(['Acknowledge', 'Remove item']);
  });
});
