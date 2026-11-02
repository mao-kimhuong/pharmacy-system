// F6 / line options: manual discount (capped per role; above the cap needs approval), patient ID for controlled
// medicines, allergy override reason (pharmacist with prescriptions.override_warning), duplicate-therapy
// acknowledgement, and the pharmacist's batch override (with a reason).
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { Button, Checkbox, Dialog, Field, Input, Select, TextArea } from '@/design';
import { date } from '@/lib/format';
import type { CartLine } from './cart';

export function LineOptionsDialog({ line, branchId, onClose, onSave }: { line: CartLine | null; branchId: string; onClose: () => void; onSave: (patch: Partial<CartLine>) => void }) {
  const { t } = useTranslation(['pos', 'common']);
  const user = useUser();
  const [v, setV] = useState<Partial<CartLine>>({});
  useEffect(() => {
    if (line) setV({
      discount_pct: line.discount_pct ?? '', discount_amount: line.discount_amount ?? '', patient_id_document: line.patient_id_document ?? '',
      allergy_override_reason: line.allergy_override_reason ?? '', acknowledge_warnings: !!line.acknowledge_warnings, batch_id: line.batch_id ?? '', override_reason: line.override_reason ?? '',
    });
  }, [line]);
  const canBatch = user.is_pharmacist;
  const batches = useQuery({
    queryKey: ['inventory', 'batches', branchId, line?.medicine.id],
    enabled: !!line && canBatch,
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/batches', { params: { query: { branch_id: branchId, medicine_id: line!.medicine.id, size: 50 } } })),
  });
  if (!line) return null;
  const canOverride = user.is_pharmacist && user.has('prescriptions.override_warning');
  return (
    <Dialog open onClose={onClose} title={t('actions.options')} subtitle={line.medicine.name} width={520}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" onClick={() => { onSave({ ...v, batch_id: v.batch_id || null }); onClose(); }}>{t('common:action.apply')}</Button></>}>
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('line.discountPct')}>{(id) => <Input id={id} inputMode="decimal" suffix="%" value={v.discount_pct ?? ''} onChange={(e) => setV({ ...v, discount_pct: e.target.value, discount_amount: '' })} autoFocus />}</Field>
          <Field label={t('line.discountAmount')}>{(id) => <Input id={id} inputMode="decimal" prefix="$" value={v.discount_amount ?? ''} onChange={(e) => setV({ ...v, discount_amount: e.target.value, discount_pct: '' })} />}</Field>
        </div>
        {line.medicine.controlled && (
          <Field label={t('line.patientId')} required>{(id) => <Input id={id} value={v.patient_id_document ?? ''} onChange={(e) => setV({ ...v, patient_id_document: e.target.value })} />}</Field>
        )}
        {line.rx && canOverride && (
          <Field label={t('line.allergyReason')}>{(id) => <TextArea id={id} rows={2} value={v.allergy_override_reason ?? ''} onChange={(e) => setV({ ...v, allergy_override_reason: e.target.value })} />}</Field>
        )}
        {line.rx && <Checkbox label={t('line.acknowledge')} checked={!!v.acknowledge_warnings} onChange={(e) => setV({ ...v, acknowledge_warnings: e.target.checked })} />}
        {canBatch && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('line.batch')}>
              {(id) => (
                <Select id={id} value={v.batch_id ?? ''} onChange={(e) => setV({ ...v, batch_id: e.target.value })}>
                  <option value="">{t('line.batchFefo')}</option>
                  {batches.data?.items.filter((b) => b.qty_available > 0 || b.batch_id === v.batch_id).map((b) => (
                    <option key={b.batch_id} value={b.batch_id}>{b.lot_no} · {date(b.expiry_date)} · {b.qty_available}</option>
                  ))}
                </Select>
              )}
            </Field>
            {v.batch_id && <Field label={t('line.batchReason')} required>{(id) => <Input id={id} value={v.override_reason ?? ''} onChange={(e) => setV({ ...v, override_reason: e.target.value })} />}</Field>}
          </div>
        )}
      </div>
    </Dialog>
  );
}
