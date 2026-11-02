// 7d Discrepancies (register vs stock per batch, nightly): resolve with a reason, optional correction entry,
// PIN + witness (controlled.resolve).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { ControlledS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, Checkbox, DataTable, Dialog, EmptyState, Field, PageHeader, Select, StatusPill, TextArea, WitnessDialog } from '@/design';
import { dateTime } from '@/lib/format';
import { useMedicineNames } from '../shared/hooks';

type Disc = ControlledS['DiscrepancyOut'];

export default function DiscrepanciesPage() {
  const { t } = useTranslation(['controlled', 'common', 'nav']);
  const user = useUser();
  const qc = useQueryClient();
  const { branchParam } = useBranch();
  const [status, setStatus] = useState('open');
  const [sel, setSel] = useState<Disc | null>(null);
  const [witness, setWitness] = useState(false);
  const [v, setV] = useState({ reason: '', note: '', correct_register: true });
  const q = useQuery({
    queryKey: ['controlled', 'discrepancies', branchParam, status],
    queryFn: () => call(api.controlled.GET('/api/controlled/v1/discrepancies', { params: { query: { branch_id: branchParam, status: status || undefined } } })),
  });
  const names = useMedicineNames(q.data?.map((d) => d.medicine_id) ?? []);
  const m = useMutation({
    mutationFn: (tk: { pin?: string; witness: string }) => call(api.controlled.POST('/api/controlled/v1/discrepancies/{discrepancy_id}/resolve', { params: { path: { discrepancy_id: sel!.id } }, body: { ...v, pin_token: tk.pin, witness_token: tk.witness } })),
    onSuccess: () => { setSel(null); void qc.invalidateQueries({ queryKey: ['controlled'] }); },
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.controlled')} title={t('disc.title')}><span className="text-[12px] text-neutral-500">{t('disc.hint')}</span></PageHeader>
      <ApiErrorAlert error={m.error} />
      <DataTable
        toolbar={<Select aria-label={t('common:label.status')} className="w-48" value={status} onChange={(e) => setStatus(e.target.value)}><option value="open">{t('disc.open')}</option><option value="resolved">{t('disc.resolved')}</option><option value="">{t('common:label.all')}</option></Select>}
        rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(d) => d.id} empty={<EmptyState title={t('disc.empty')} />}
        columns={[
          { key: 'm', header: t('register.medicine'), cell: (d) => names(d.medicine_id) },
          { key: 'l', header: t('register.lot'), cell: (d) => <span className="font-mono text-[12px]">{d.lot_no}</span> },
          { key: 'r', header: t('disc.registerQty'), align: 'right', cell: (d) => d.register_qty },
          { key: 's', header: t('disc.stockQty'), align: 'right', cell: (d) => d.stock_qty },
          { key: 'd', header: t('disc.difference'), align: 'right', cell: (d) => <b className="text-pill-danger-fg">{d.difference}</b> },
          { key: 'f', header: t('disc.found'), cell: (d) => dateTime(d.found_at) },
          { key: 'st', header: t('common:label.status'), cell: (d) => <StatusPill tone={d.status === 'open' ? 'danger' : 'success'}>{d.status === 'open' ? t('disc.open') : t('disc.resolved')}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (d) => d.status === 'open' && user.has('controlled.resolve') && <Button size="sm" variant="primary" onClick={() => { setSel(d); setV({ reason: '', note: '', correct_register: true }); }}>{t('disc.resolve')}</Button> },
        ]} />
      <Dialog open={!!sel && !witness} onClose={() => setSel(null)} title={t('disc.resolveTitle')} width={520}
        footer={<><Button onClick={() => setSel(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!v.reason.trim()} loading={m.isPending} onClick={() => setWitness(true)}>{t('adjust.next')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('common:label.reason')} required>{(id) => <TextArea id={id} rows={2} value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />}</Field>
          <Field label={t('disc.note')}>{(id) => <TextArea id={id} rows={2} value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />}</Field>
          <Checkbox label={t('disc.correctRegister')} checked={v.correct_register} onChange={(e) => setV({ ...v, correct_register: e.target.checked })} />
        </div>
      </Dialog>
      {sel && <WitnessDialog open={witness} action="controlled.resolve" branchId={sel.branch_id} context={`${names(sel.medicine_id)} · ${sel.lot_no} · ${sel.difference}`}
        onClose={() => setWitness(false)} onTokens={({ pin, witness: w }) => { setWitness(false); m.mutate({ pin: pin?.pin_token, witness: w.pin_token }); }} />}
    </div>
  );
}
