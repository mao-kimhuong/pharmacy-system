// Batches of one medicine at a branch (lot · expiry · on hand), optionally only one supplier's.
import { useQuery } from '@tanstack/react-query';
import { api, call } from '@/api/client';
import { Select } from '@/design';
import { date } from '@/lib/format';

export function BatchSelect({ branchId, medicineId, value, onChange, id, supplierId }: { branchId: string; medicineId: string | undefined; value: string; onChange: (id: string, onHand: number) => void; id?: string; supplierId?: string }) {
  const q = useQuery({
    queryKey: ['inventory', 'batches', branchId, medicineId, 'pick'],
    enabled: !!medicineId,
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/batches', { params: { query: { branch_id: branchId, medicine_id: medicineId, size: 100 } } })),
  });
  const rows = (q.data?.items ?? []).filter((b) => b.qty_on_hand > 0 && (!supplierId || b.supplier_id === supplierId));
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value, rows.find((b) => b.batch_id === e.target.value)?.qty_on_hand ?? 0)}>
      <option value="">—</option>
      {rows.map((b) => <option key={b.batch_id} value={b.batch_id}>{b.lot_no} · {date(b.expiry_date)} · {b.qty_on_hand}</option>)}
    </Select>
  );
}
