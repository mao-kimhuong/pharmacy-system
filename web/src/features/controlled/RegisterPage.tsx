// 7a Controlled register: append-only, hash-chained per branch + medicine; filter by medicine and dates;
// adjust / destroy with PIN + witness (7c); register PDF (7f).
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { Alert, Button, DataTable, EmptyState, Field, Input, PageHeader, Select, usePdf } from '@/design';
import { addDays, date, dateTime, todayIso } from '@/lib/format';
import { AdjustDialog } from './AdjustDialog';

export default function RegisterPage() {
  const { t } = useTranslation(['controlled', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const { oneBranch } = useBranch();
  const pdf = usePdf();
  const [medicineId, setMedicineId] = useState('');
  const [from, setFrom] = useState(addDays(todayIso(), -30));
  const [to, setTo] = useState(todayIso());
  const [adjust, setAdjust] = useState(false);
  const q = useQuery({
    queryKey: ['controlled', 'register', oneBranch?.id, medicineId, from, to],
    enabled: !!oneBranch,
    queryFn: () => call(api.controlled.GET('/api/controlled/v1/register', { params: { query: { branch_id: oneBranch!.id, medicine_id: medicineId || undefined, from, to } } })),
  });
  const meds = new Map((q.data?.medicines ?? []).map((m) => [m.id, m]));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.controlled')} title={t('register.title')}
        actions={<>
          {oneBranch && <Button onClick={() => pdf.open({ type: 'controlled_register', branch_id: oneBranch.id, medicine_id: medicineId || null, date_from: from, date_to: to }, t('register.export'), `register-${oneBranch.code}.pdf`)}>{t('register.export')}</Button>}
          {user.has('controlled.adjust') && <Button variant="primary" onClick={() => setAdjust(true)}>{t('register.adjust')}</Button>}
        </>}>
        <span className="text-[12px] text-neutral-500">{t('register.appendOnly')}</span>
      </PageHeader>
      {q.data && (q.data.chain_valid ? <Alert tone="success">{t('register.chainOk')}</Alert> : <Alert tone="danger">{t('register.chainBad')}</Alert>)}
      <DataTable
        toolbar={<>
          <Field label={t('register.medicine')}>{(id) => <Select id={id} className="w-72" value={medicineId} onChange={(e) => setMedicineId(e.target.value)}><option value="">{t('register.allMeds')}</option>{q.data?.medicines.map((m) => <option key={m.id} value={m.id}>{m.name} {m.strength}</option>)}</Select>}</Field>
          <Field label={t('common:label.from')}>{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
          <Field label={t('common:label.to')}>{(id) => <Input id={id} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
        </>}
        rows={q.data?.entries} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(e) => e.id} onRowClick={(e) => nav(`/controlled/entries/${e.id}`)}
        empty={<EmptyState title={t('register.empty')} />} minWidth={1000} dense
        columns={[
          { key: 's', header: t('register.seq'), cell: (e) => e.seq },
          { key: 'w', header: t('register.when'), cell: (e) => dateTime(e.occurred_at) },
          { key: 'm', header: t('register.medicine'), cell: (e) => meds.get(e.medicine_id)?.name ?? '—' },
          { key: 't', header: t('register.type'), cell: (e) => <span>{t(`type.${e.entry_type}`, { defaultValue: e.entry_type })}{e.corrects_entry_id ? ' ↺' : ''}</span> },
          { key: 'l', header: t('register.lot'), cell: (e) => <span className="font-mono text-[11px]">{e.lot_no} {e.expiry_date ? `· ${date(e.expiry_date)}` : ''}</span> },
          { key: 'q', header: t('register.qty'), align: 'right', cell: (e) => <span className={e.qty_base < 0 ? 'text-pill-danger-fg' : 'text-pill-success-fg'}>{e.qty_base > 0 ? `+${e.qty_base}` : e.qty_base}</span> },
          { key: 'b', header: t('register.balance'), align: 'right', cell: (e) => <b>{e.balance_after}</b> },
          { key: 'r', header: t('register.rx'), cell: (e) => [e.prescription_number, e.patient_name].filter(Boolean).join(' · ') || '—' },
          { key: 'a', header: t('register.who'), cell: (e) => [e.actor_name, e.witness_name].filter(Boolean).join(' / ') || '—' },
        ]} />
      {oneBranch && adjust && <AdjustDialog open branchId={oneBranch.id} medicines={q.data?.medicines ?? []} onClose={() => setAdjust(false)} />}
      {pdf.element}
    </div>
  );
}
