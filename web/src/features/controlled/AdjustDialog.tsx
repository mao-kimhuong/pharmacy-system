// 7c Adjust or destroy controlled stock: batch, kind, qty, reason (+ method) → own PIN + witness (destroy: branch
// manager or owner) → POST controlled entries (Idempotency-Key).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { ControlledS } from '@/api/types';
import { ApiErrorAlert, Alert, Button, Dialog, Field, Input, Select, TextArea, WitnessDialog, useToast } from '@/design';
import { date } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';

export function AdjustDialog({ open, onClose, branchId, medicines }: { open: boolean; onClose: () => void; branchId: string; medicines: ControlledS['MedicineRef'][] }) {
  const { t } = useTranslation(['controlled', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const [medicineId, setMedicineId] = useState('');
  const [v, setV] = useState({ batch_id: '', kind: 'destroy' as 'adjust_in' | 'adjust_out' | 'destroy', qty_base: '', reason: '', destruction_method: '' });
  const [witness, setWitness] = useState(false);
  const batches = useQuery({
    queryKey: ['inventory', 'batches', branchId, medicineId, 'all'],
    enabled: open && !!medicineId,
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/batches', { params: { query: { branch_id: branchId, medicine_id: medicineId, size: 100 } } })),
  });
  const body = { branch_id: branchId, batch_id: v.batch_id, kind: v.kind, qty_base: Number(v.qty_base), reason: v.reason.trim(), destruction_method: v.destruction_method };
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: (tokens: { pin?: string; witness: string }) => call(api.controlled.POST('/api/controlled/v1/entries', { body: { ...body, pin_token: tokens.pin, witness_token: tokens.witness }, ...withKey(key) })),
    onSuccess: () => { toast.success(t('adjust.done')); void qc.invalidateQueries({ queryKey: ['controlled'] }); onClose(); },
  });
  const ok = v.batch_id && Number(v.qty_base) > 0 && v.reason.trim() && (v.kind !== 'destroy' || v.destruction_method.trim());
  return (
    <>
      <Dialog open={open && !witness} onClose={onClose} title={t('adjust.title')} width={560}
        footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!ok} loading={m.isPending} onClick={() => setWitness(true)}>{t('adjust.next')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('register.medicine')} required>{(id) => (
            <Select id={id} value={medicineId} onChange={(e) => { setMedicineId(e.target.value); setV({ ...v, batch_id: '' }); }}>
              <option value="">—</option>{medicines.map((x) => <option key={x.id} value={x.id}>{x.name} {x.strength}</option>)}
            </Select>
          )}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('adjust.batch')} required>{(id) => (
              <Select id={id} value={v.batch_id} onChange={(e) => setV({ ...v, batch_id: e.target.value })}>
                <option value="">—</option>{batches.data?.items.map((b) => <option key={b.batch_id} value={b.batch_id}>{b.lot_no} · {date(b.expiry_date)} · {b.qty_on_hand}</option>)}
              </Select>
            )}</Field>
            <Field label={t('adjust.kind')}>{(id) => (
              <Select id={id} value={v.kind} onChange={(e) => setV({ ...v, kind: e.target.value as typeof v.kind })}>
                {(['destroy', 'adjust_out', 'adjust_in'] as const).map((k) => <option key={k} value={k}>{t(`adjust.${k}`)}</option>)}
              </Select>
            )}</Field>
          </div>
          <Field label={t('adjust.qty')} required>{(id) => <Input id={id} inputMode="numeric" value={v.qty_base} onChange={(e) => setV({ ...v, qty_base: e.target.value.replace(/\D/g, '') })} />}</Field>
          {v.kind === 'destroy' && <Field label={t('adjust.method')} required>{(id) => <Input id={id} value={v.destruction_method} onChange={(e) => setV({ ...v, destruction_method: e.target.value })} />}</Field>}
          <Field label={t('common:label.reason')} required>{(id) => <TextArea id={id} rows={2} value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />}</Field>
          <Alert tone="info">{t('adjust.witnessNote')}</Alert>
          <ApiErrorAlert error={m.error} />
        </div>
      </Dialog>
      <WitnessDialog open={open && witness} action={v.kind === 'destroy' ? 'controlled.destroy' : 'controlled.adjust'} branchId={branchId} managerOnly={v.kind === 'destroy'}
        context={`${t(`adjust.${v.kind}`)} · ${v.qty_base} · ${batches.data?.items.find((b) => b.batch_id === v.batch_id)?.lot_no ?? ''}`}
        onClose={() => setWitness(false)} onTokens={({ pin, witness: w }) => { setWitness(false); m.mutate({ pin: pin?.pin_token, witness: w.pin_token }); }} />
    </>
  );
}
