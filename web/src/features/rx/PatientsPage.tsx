// 6a Patients (own branches, search by name or phone), 6c find a patient of another branch by the exact phone
// (logged), new patient with allergies.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PrescriptionS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, Button, DataTable, Dialog, Field, Input, PageHeader, Select, TextArea, useDebounced, useToast } from '@/design';
import { date } from '@/lib/format';
import { usePaging } from '../shared/hooks';

type AllergyIn = PrescriptionS['AllergyIn'];

export function PatientForm({ onDone }: { onDone: (id: string) => void }) {
  const { t } = useTranslation(['rx', 'common']);
  const { oneBranch } = useBranch();
  const toast = useToast();
  const [v, setV] = useState({ name_en: '', name_km: '', sex: 'female' as 'female' | 'male' | 'other', dob: '', phone: '', chronic_conditions: '', notes: '' });
  const [allergies, setAllergies] = useState<AllergyIn[]>([]);
  const m = useMutation({
    mutationFn: () => call(api.prescription.POST('/api/prescription/v1/patients', { body: { branch_id: oneBranch!.id, ...v, dob: v.dob || null, phone: v.phone || null, allergies } })),
    onSuccess: (p) => { toast.success(t('patients.saved')); onDone(p.id); },
  });
  return (
    <form id="patient-form" className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      <div className="grid gap-3 tablet:grid-cols-2">
        <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={v.name_km} onChange={(e) => setV({ ...v, name_km: e.target.value })} autoFocus />}</Field>
        <Field label={t('common:label.nameEn')}>{(id) => <Input id={id} value={v.name_en} onChange={(e) => setV({ ...v, name_en: e.target.value })} />}</Field>
        <Field label={t('common:label.phone')}>{(id) => <Input id={id} type="tel" prefix="+855" value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />}</Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('patients.sex')} required>{(id) => <Select id={id} value={v.sex} onChange={(e) => setV({ ...v, sex: e.target.value as typeof v.sex })}>{(['female', 'male', 'other'] as const).map((s) => <option key={s} value={s}>{t(`patients.${s}`)}</option>)}</Select>}</Field>
          <Field label={t('patients.dob')}>{(id) => <Input id={id} type="date" value={v.dob} onChange={(e) => setV({ ...v, dob: e.target.value })} />}</Field>
        </div>
      </div>
      <Field label={t('patients.chronic')}>{(id) => <TextArea id={id} rows={2} value={v.chronic_conditions} onChange={(e) => setV({ ...v, chronic_conditions: e.target.value })} />}</Field>
      <div className="flex flex-col gap-2">
        <span className="text-[13px] font-medium">{t('allergy.title')}</span>
        {allergies.map((a, i) => (
          <div key={i} className="grid grid-cols-[140px_1fr_1fr_auto] gap-2">
            <Select aria-label={t('allergy.kind')} value={a.kind} onChange={(e) => setAllergies(allergies.map((x, j) => (j === i ? { ...x, kind: e.target.value as AllergyIn['kind'] } : x)))}>
              <option value="ingredient">{t('allergy.ingredient')}</option><option value="class">{t('allergy.class')}</option>
            </Select>
            <Input aria-label={t('allergy.value')} placeholder={t('allergy.value')} value={a.value} onChange={(e) => setAllergies(allergies.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
            <Input aria-label={t('allergy.note')} placeholder={t('allergy.note')} value={a.note ?? ''} onChange={(e) => setAllergies(allergies.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))} />
            <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setAllergies(allergies.filter((_, j) => j !== i))}>✕</Button>
          </div>
        ))}
        <Button variant="link" className="self-start" onClick={() => setAllergies([...allergies, { kind: 'class', value: '', note: '' }])}>+ {t('allergy.add')}</Button>
      </div>
      <ApiErrorAlert error={m.error} />
      <button type="submit" hidden />
      <div className="flex justify-end"><Button type="submit" variant="primary" loading={m.isPending} disabled={!v.name_en && !v.name_km}>{t('common:action.save')}</Button></div>
    </form>
  );
}

function FindOther({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation(['rx', 'common']);
  const { oneBranch } = useBranch();
  const nav = useNavigate();
  const [phone, setPhone] = useState('');
  const m = useMutation({ mutationFn: () => call(api.prescription.POST('/api/prescription/v1/patients/link', { body: { branch_id: oneBranch!.id, phone } })) });
  return (
    <Dialog open={open} onClose={onClose} title={t('patients.findOther')} width={480}
      footer={<><Button onClick={onClose}>{t('common:action.close')}</Button><Button variant="primary" disabled={!phone} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.search')}</Button></>}>
      <div className="flex flex-col gap-3">
        <Alert tone="info">{t('patients.findOtherBody')}</Alert>
        <Field label={t('patients.exactPhone')}>{(id) => <Input id={id} type="tel" prefix="+855" value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus />}</Field>
        <ApiErrorAlert error={m.error} />
        {m.data && m.data.length === 0 && <Alert tone="warning">{t('patients.noneFound')}</Alert>}
        {m.data?.map((p) => (
          <button key={p.id} type="button" onClick={() => nav(`/rx/patients/${p.id}`)} className="flex items-center justify-between rounded-lg border border-success bg-success-bg p-3 text-left text-[13px]">
            <span>{t('patients.linked', { name: i18n.language === 'km' && p.name_km ? p.name_km : p.name_en })}</span><span>→</span>
          </button>
        ))}
      </div>
    </Dialog>
  );
}

export default function PatientsPage() {
  const { t, i18n } = useTranslation(['rx', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { byId } = useBranch();
  const paging = usePaging();
  const [q, setQ] = useState('');
  const dq = useDebounced(q.trim());
  const [dlg, setDlg] = useState<'' | 'new' | 'find'>('');
  const list = useQuery({
    queryKey: ['prescription', 'patients', dq, paging.page, paging.size],
    queryFn: () => call(api.prescription.GET('/api/prescription/v1/patients', { params: { query: { q: dq || undefined, page: paging.page, size: paging.size } } })),
  });
  const km = i18n.language === 'km';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.prescriptions')} title={t('patients.title')}
        actions={<>
          <Button onClick={() => setDlg('find')}>{t('patients.findOther')}</Button>
          {user.has('patients.manage') && <Button variant="primary" onClick={() => setDlg('new')}>+ {t('patients.new')}</Button>}
        </>} />
      <DataTable
        toolbar={<Input aria-label={t('patients.search')} placeholder={`⌕ ${t('patients.search')}`} className="w-72" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />}
        rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(p) => p.id} onRowClick={(p) => nav(`/rx/patients/${p.id}`)}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('common:label.name'), cell: (p) => <span className="flex flex-col"><b className="font-medium">{km ? p.name_km || p.name_en : p.name_en || p.name_km}</b><span className="text-[12px] text-neutral-500">{km ? p.name_en : p.name_km}</span></span> },
          { key: 's', header: t('patients.sex'), cell: (p) => t(`patients.${p.sex}`, { defaultValue: p.sex }) },
          { key: 'd', header: t('patients.dob'), cell: (p) => date(p.dob) },
          { key: 'p', header: t('common:label.phone'), cell: (p) => p.phone },
          { key: 'h', header: t('patients.home'), cell: (p) => byId(p.home_branch_id)?.code ?? '—' },
        ]} />
      <Dialog open={dlg === 'new'} onClose={() => setDlg('')} title={t('patients.new')} width={720}>
        {dlg === 'new' && <PatientForm onDone={(id) => { setDlg(''); void qc.invalidateQueries({ queryKey: ['prescription', 'patients'] }); nav(`/rx/patients/${id}`); }} />}
      </Dialog>
      <FindOther open={dlg === 'find'} onClose={() => setDlg('')} />
    </div>
  );
}
