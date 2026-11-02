// 7b Entry detail: every field, hash check, neighbours, corrections; 18h correction entry with PIN + witness.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { useUser } from '@/app/auth';
import { QueryState } from '@/app/RouteError';
import { Alert, ApiErrorAlert, Button, Card, DefinitionList, Dialog, Field, Input, PageHeader, SkeletonRows, StatusPill, TextArea, WitnessDialog, useToast } from '@/design';
import { date, dateTime } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';

export default function EntryDetailPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['controlled', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState(false);
  const [witness, setWitness] = useState(false);
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const q = useQuery({ queryKey: ['controlled', 'entry', id], queryFn: () => call(api.controlled.GET('/api/controlled/v1/entries/{entry_id}', { params: { path: { entry_id: id } } })) });
  const body = { corrects_entry_id: id, qty_base: Number(qty), reason: reason.trim() };
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: (tk: { pin?: string; witness: string }) => call(api.controlled.POST('/api/controlled/v1/entries/correction', { body: { ...body, pin_token: tk.pin, witness_token: tk.witness }, ...withKey(key) })),
    onSuccess: (e) => { toast.success(t('adjust.done')); void qc.invalidateQueries({ queryKey: ['controlled'] }); nav(`/controlled/entries/${e.id}`); },
  });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data) return <SkeletonRows />;
  const { entry: e, prev_entry_id, next_entry_id, hash_valid, corrected_by } = q.data;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.controlled')} / ${t('register.title')}`} title={t('entry.title', { seq: e.seq })}
        actions={<>
          <Button disabled={!prev_entry_id} onClick={() => nav(`/controlled/entries/${prev_entry_id}`)}>‹ {t('entry.prev')}</Button>
          <Button disabled={!next_entry_id} onClick={() => nav(`/controlled/entries/${next_entry_id}`)}>{t('entry.next')} ›</Button>
          {user.has('controlled.adjust') && <Button variant="primary" onClick={() => setForm(true)}>{t('entry.correct')}</Button>}
        </>}>
        {hash_valid ? <StatusPill tone="success">{t('entry.hashOk')}</StatusPill> : <StatusPill tone="danger">{t('entry.hashBad')}</StatusPill>}
      </PageHeader>
      <Card>
        <DefinitionList cols={3} items={[
          { label: t('register.type'), value: t(`type.${e.entry_type}`, { defaultValue: e.entry_type }) },
          { label: t('register.when'), value: dateTime(e.occurred_at) },
          { label: t('register.lot'), value: `${e.lot_no}${e.expiry_date ? ` · ${date(e.expiry_date)}` : ''}` },
          { label: t('register.qty'), value: e.qty_base },
          { label: t('register.balance'), value: e.balance_after },
          { label: t('register.rx'), value: [e.prescription_number, e.patient_name].filter(Boolean).join(' · ') || '—' },
          { label: t('entry.patientDoc'), value: e.patient_id_document || '—' },
          { label: t('register.who'), value: [e.actor_name, e.witness_name].filter(Boolean).join(' / ') || '—' },
          { label: t('entry.reason'), value: e.reason || '—' },
          { label: t('entry.corrects'), value: e.corrects_entry_id ? <button type="button" className="text-primary-600" onClick={() => nav(`/controlled/entries/${e.corrects_entry_id}`)}>→</button> : '—' },
          { label: t('entry.correctedBy'), value: corrected_by.length ? corrected_by.map((c) => <button key={c} type="button" className="mr-2 text-primary-600" onClick={() => nav(`/controlled/entries/${c}`)}>→</button>) : '—' },
          { label: t('entry.hash'), value: <code className="font-mono text-[11px] break-all">{e.entry_hash}</code> },
        ]} />
      </Card>
      <Dialog open={form && !witness} onClose={() => setForm(false)} title={t('correction.title')} width={480}
        footer={<><Button onClick={() => setForm(false)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!Number(qty) || !reason.trim()} loading={m.isPending} onClick={() => setWitness(true)}>{t('adjust.next')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Alert tone="info">{t('correction.body', { seq: e.seq })}</Alert>
          <Field label={t('correction.qty')} required>{(fid) => <Input id={fid} inputMode="numeric" value={qty} onChange={(ev) => setQty(ev.target.value.replace(/[^\d-]/g, ''))} />}</Field>
          <Field label={t('common:label.reason')} required>{(fid) => <TextArea id={fid} rows={2} value={reason} onChange={(ev) => setReason(ev.target.value)} />}</Field>
          <ApiErrorAlert error={m.error} />
        </div>
      </Dialog>
      <WitnessDialog open={form && witness} action="controlled.adjust" branchId={e.branch_id} context={`${t('correction.title')} #${e.seq} · ${qty}`}
        onClose={() => setWitness(false)} onTokens={({ pin, witness: w }) => { setWitness(false); setForm(false); m.mutate({ pin: pin?.pin_token, witness: w.pin_token }); }} />
    </div>
  );
}
