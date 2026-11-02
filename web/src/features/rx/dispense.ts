// Open Rx items → POS lines linked to the Rx (base unit, what can be dispensed now).
import { api, call } from '@/api/client';
import type { PosLoad } from '../pos/usePos';

export async function dispenseLoad(rxId: string): Promise<PosLoad> {
  const r = await call(api.prescription.GET('/api/prescription/v1/prescriptions/{rx_id}/remaining', { params: { path: { rx_id: rxId } } }));
  return {
    lines: r.items.filter((i) => i.can_dispense_now > 0).map((i) => ({
      medicine_id: i.medicine_id, qty: i.can_dispense_now, rx: { rx_item_id: i.rx_item_id, number: r.number, patient: r.patient.name_en || r.patient.name_km },
    })),
  };
}
