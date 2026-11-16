// Receive a dispatched transfer (destination): per picked batch received / damaged (+ shelf); short, damaged and
// extra become differences. Controlled lines: PIN + witness.
import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { InventoryS } from '@/api/types';
import { Alert, ApiErrorAlert, Button, Field, Input, WitnessDialog, useToast } from '@/design';
import { date } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';
import { useMedicineNames } from '../shared/hooks';

export function ReceiveForm({ tr, onDone }: { tr: InventoryS['TransferOut']; onDone: () => void }) {
  const { t } = useTranslation(['transfer', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const names = useMedicineNames(tr.lines.map((l) => l.medicine_id));
  const med = (lineNo: number) => tr.lines.find((l) => l.line_no === lineNo)?.medicine_id ?? '';
  const controlled = tr.lines.some((l) => l.is_controlled);
  const [v, setV] = useState<Record<string, { got: string; bad: string; loc: string }>>(() => Object.fromEntries(tr.picks.map((p) => [p.id, { got: String(p.qty_base), bad: '0', loc: '' }])));
  const [witness, setWitness] = useState(false);
  const lines = useMemo(() => tr.picks.map((p) => ({ pick_id: p.id, qty_received: Number(v[p.id]?.got) || 0, qty_damaged: Number(v[p.id]?.bad) || 0, location: v[p.id]?.loc || null })), [tr.picks, v]);
  const key = useRequestKey(JSON.stringify(lines) + tr.id);
  const m = useMutation({
    mutationFn: (tk?: { pin?: string; witness: string }) => call(api.inventory.POST('/api/inventory/v1/transfers/{transfer_id}/receive', { params: { path: { transfer_id: tr.id } }, body: { lines, pin_token: tk?.pin ?? null, witness_token: tk?.witness ?? null }, ...withKey(key) })),
    onSuccess: () => { toast.success(t('tr.received')); void qc.invalidateQueries({ queryKey: ['inventory'] }); onDone(); },
  });
  return (
    <div className="flex flex-col gap-3">
      {tr.picks.map((p) => (
        <div key={p.id} className="flex flex-col gap-2 rounded-xl border border-neutral-200 bg-surface p-3">
          <div className="flex justify-between gap-2"><b>{names(med(p.line_no))}</b><span className="text-[12px] text-neutral-500"><span className="font-mono">{p.lot_no}</span> · {date(p.expiry_date)} · {p.qty_base}</span></div>
          <div className="grid grid-cols-3 gap-2">
            <Field label={t('tr.received')}>{(id) => <Input id={id} fieldSize="lg" inputMode="numeric" value={v[p.id]?.got ?? ''} onChange={(e) => setV({ ...v, [p.id]: { ...v[p.id], got: e.target.value.replace(/\D/g, '') } })} />}</Field>
            <Field label={t('tr.damaged')}>{(id) => <Input id={id} fieldSize="lg" inputMode="numeric" value={v[p.id]?.bad ?? ''} onChange={(e) => setV({ ...v, [p.id]: { ...v[p.id], bad: e.target.value.replace(/\D/g, '') } })} />}</Field>
            <Field label={t('tr.location')}>{(id) => <Input id={id} fieldSize="lg" value={v[p.id]?.loc ?? ''} onChange={(e) => setV({ ...v, [p.id]: { ...v[p.id], loc: e.target.value.toUpperCase() } })} />}</Field>
          </div>
        </div>
      ))}
      {controlled && <Alert tone="info">{t('tr.controlled')}</Alert>}
      <ApiErrorAlert error={m.error} />
      <Button variant="primary" size="lg" loading={m.isPending} onClick={() => (controlled ? setWitness(true) : m.mutate(undefined))}>{t('tr.receive')}</Button>
      <WitnessDialog open={witness} action="transfers.receive" branchId={tr.to_branch_id} onClose={() => setWitness(false)}
        onTokens={({ pin, witness: w }) => { setWitness(false); m.mutate({ pin: pin?.pin_token, witness: w.pin_token }); }} />
    </div>
  );
}
