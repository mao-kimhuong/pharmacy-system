// 6b Patient detail: details (edit), allergies (add, remove with a reason), prescriptions, Rx summary PDF,
// deactivate / activate. Every view is logged by the API. Dispensing history per line has no API: shown only
// through the prescriptions' dispensed quantities.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { branchName, useBranch } from '@/app/branch';
import { QueryState } from '@/app/RouteError';
import { Alert, ApiErrorAlert, BranchTag, Button, Card, DataTable, DefinitionList, Dialog, Field, Input, PageHeader, ReasonDialog, SafetyBadge, Select, SkeletonRows, StatusPill, TextArea, usePdf, useToast } from '@/design';
import { date } from '@/lib/format';
import { toneOf } from '../shared/hooks';

export default function PatientDetailPage() {
  const { id = '' } = useParams();
  const { t, i18n } = useTranslation(['rx', 'common', 'nav', 'sales']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const pdf = usePdf();
  const { byId } = useBranch();
  const [dlg, setDlg] = useState<'' | 'edit' | 'allergy' | 'deactivate'>('');
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [allergy, setAllergy] = useState({ kind: 'class' as 'class' | 'ingredient', value: '', note: '' });
  const q = useQuery({ queryKey: ['prescription', 'patient', id], queryFn: () => call(api.prescription.GET('/api/prescription/v1/patients/{patient_id}', { params: { path: { patient_id: id } } })) });
  const rxs = useQuery({ queryKey: ['prescription', 'rx-of', id], queryFn: () => call(api.prescription.GET('/api/prescription/v1/prescriptions', { params: { query: { patient_id: id, size: 100 } } })) });
  const p = q.data;
  const [edit, setEdit] = useState<{ name_en: string; name_km: string; phone: string; dob: string; chronic_conditions: string; notes: string } | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ['prescription', 'patient', id] });
  const save = useMutation({
    mutationFn: () => call(api.prescription.PATCH('/api/prescription/v1/patients/{patient_id}', { params: { path: { patient_id: id } }, body: { ...edit!, dob: edit!.dob || null, phone: edit!.phone || null } })),
    onSuccess: () => { setDlg(''); void refresh(); toast.success(t('patients.saved')); },
  });
  const addAllergy = useMutation({
    mutationFn: () => call(api.prescription.POST('/api/prescription/v1/patients/{patient_id}/allergies', { params: { path: { patient_id: id } }, body: allergy })),
    onSuccess: () => { setDlg(''); setAllergy({ kind: 'class', value: '', note: '' }); void refresh(); },
  });
  const activate = useMutation({ mutationFn: () => call(api.prescription.POST('/api/prescription/v1/patients/{patient_id}/activate', { params: { path: { patient_id: id } }, body: null })), onSuccess: () => void refresh() });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!p) return <SkeletonRows />;
  const km = i18n.language === 'km';
  const manage = user.has('patients.manage');
  const name = km ? p.name_km || p.name_en : p.name_en || p.name_km;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.prescriptions')} / ${t('patients.title')}`} title={name}
        actions={<>
          {user.has('prescriptions.view') && <Button onClick={() => pdf.open({ type: 'rx_summary', patient_id: p.id }, t('patients.summary'), `rx-summary-${p.id.slice(0, 8)}.pdf`)}>{t('patients.summary')}</Button>}
          {user.has('prescriptions.manage') && p.is_active && <Button variant="primary" onClick={() => nav(`/rx/prescriptions/new?patient=${p.id}`)}>+ {t('rx.new')}</Button>}
          {manage && p.is_active && <Button onClick={() => { setEdit({ name_en: p.name_en, name_km: p.name_km, phone: p.phone, dob: p.dob ?? '', chronic_conditions: p.chronic_conditions, notes: p.notes }); setDlg('edit'); }}>{t('common:action.edit')}</Button>}
          {manage && (p.is_active ? <Button onClick={() => setDlg('deactivate')}>{t('common:action.deactivate')}</Button> : <Button onClick={() => activate.mutate()}>{t('common:action.activate')}</Button>)}
        </>}>
        {!p.is_active && <StatusPill tone="neutral">{t('common:label.inactive')}</StatusPill>}
      </PageHeader>
      <span className="text-[12px] text-neutral-500">{t('patients.viewLogged')}</span>
      <div className="grid gap-4 desktop:grid-cols-[1fr_1fr]">
        <Card title={t('common:label.details')}>
          <DefinitionList items={[
            { label: t('common:label.nameKm'), value: <span className="km">{p.name_km || '—'}</span> },
            { label: t('common:label.nameEn'), value: p.name_en || '—' },
            { label: t('patients.sex'), value: t(`patients.${p.sex}`, { defaultValue: p.sex }) },
            { label: t('patients.dob'), value: date(p.dob) },
            { label: t('common:label.phone'), value: p.phone || '—' },
            { label: t('patients.home'), value: <span className="flex items-center gap-1"><BranchTag code={byId(p.home_branch_id)?.code ?? '?'} />{branchName(byId(p.home_branch_id), i18n.language)}</span> },
            { label: t('patients.linkedBranches'), value: p.branch_ids.filter((b) => b !== p.home_branch_id).map((b) => byId(b)?.code ?? '?').join(', ') || '—' },
            { label: t('patients.chronic'), value: p.chronic_conditions || '—' },
          ]} />
        </Card>
        <Card title={t('allergy.title')} actions={manage && p.is_active && <Button size="sm" onClick={() => setDlg('allergy')}>+ {t('allergy.add')}</Button>}>
          {p.allergies.filter((a) => a.is_active).length === 0 ? <span className="text-neutral-500">{t('allergy.none')}</span> : (
            <div className="flex flex-col gap-2">
              {p.allergies.filter((a) => a.is_active).map((a) => (
                <div key={a.id} className="flex items-center gap-2 text-[13px]">
                  <SafetyBadge kind="allergy">{a.value}</SafetyBadge>
                  <span className="text-neutral-500">{t(`allergy.${a.kind}`, { defaultValue: a.kind })}{a.note ? ` · ${a.note}` : ''} · {date(a.created_at)}</span>
                  {manage && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setRemoveId(a.id)}>{t('allergy.remove')}</Button>}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      <Card title={t('rx.title')} padded={false}>
        <DataTable className="rounded-none border-0" rows={rxs.data?.items} loading={rxs.isLoading} error={rxs.error} rowKey={(r) => r.id} onRowClick={(r) => nav(`/rx/prescriptions/${r.id}`)}
          columns={[
            { key: 'n', header: t('rx.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
            { key: 'd', header: t('rx.doctor'), cell: (r) => r.doctor.name ?? '—' },
            { key: 'i', header: t('rx.issued'), cell: (r) => date(r.issued_on) },
            { key: 'v', header: t('rx.validUntil'), cell: (r) => date(r.valid_until) },
            { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`sales:rxStatus.${r.status}`)}</StatusPill> },
          ]} />
      </Card>
      <Dialog open={dlg === 'edit'} onClose={() => setDlg('')} title={t('common:action.edit')} width={640}
        footer={<><Button onClick={() => setDlg('')}>{t('common:action.cancel')}</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{t('common:action.save')}</Button></>}>
        {edit && (
          <div className="grid gap-3 tablet:grid-cols-2">
            <Field label={t('common:label.nameKm')}>{(fid) => <Input id={fid} className="km" value={edit.name_km} onChange={(e) => setEdit({ ...edit, name_km: e.target.value })} />}</Field>
            <Field label={t('common:label.nameEn')}>{(fid) => <Input id={fid} value={edit.name_en} onChange={(e) => setEdit({ ...edit, name_en: e.target.value })} />}</Field>
            <Field label={t('common:label.phone')}>{(fid) => <Input id={fid} value={edit.phone} onChange={(e) => setEdit({ ...edit, phone: e.target.value })} />}</Field>
            <Field label={t('patients.dob')}>{(fid) => <Input id={fid} type="date" value={edit.dob} onChange={(e) => setEdit({ ...edit, dob: e.target.value })} />}</Field>
            <Field label={t('patients.chronic')} className="tablet:col-span-2">{(fid) => <TextArea id={fid} rows={2} value={edit.chronic_conditions} onChange={(e) => setEdit({ ...edit, chronic_conditions: e.target.value })} />}</Field>
            <ApiErrorAlert error={save.error} className="tablet:col-span-2" />
          </div>
        )}
      </Dialog>
      <Dialog open={dlg === 'allergy'} onClose={() => setDlg('')} title={t('allergy.add')} width={480}
        footer={<><Button onClick={() => setDlg('')}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!allergy.value.trim()} loading={addAllergy.isPending} onClick={() => addAllergy.mutate()}>{t('common:action.save')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('allergy.kind')}>{(fid) => <Select id={fid} value={allergy.kind} onChange={(e) => setAllergy({ ...allergy, kind: e.target.value as 'class' | 'ingredient' })}><option value="class">{t('allergy.class')}</option><option value="ingredient">{t('allergy.ingredient')}</option></Select>}</Field>
          <Field label={t('allergy.value')} required>{(fid) => <Input id={fid} autoFocus value={allergy.value} onChange={(e) => setAllergy({ ...allergy, value: e.target.value })} />}</Field>
          <Field label={t('allergy.note')}>{(fid) => <Input id={fid} value={allergy.note} onChange={(e) => setAllergy({ ...allergy, note: e.target.value })} />}</Field>
          <ApiErrorAlert error={addAllergy.error} />
        </div>
      </Dialog>
      <ReasonDialog open={!!removeId} onClose={() => setRemoveId(null)} title={t('allergy.remove')} confirmLabel={t('allergy.remove')}
        onConfirm={async (reason) => { await call(api.prescription.POST('/api/prescription/v1/patients/{patient_id}/allergies/{allergy_id}/remove', { params: { path: { patient_id: id, allergy_id: removeId! } }, body: { reason } })); await refresh(); }} />
      <ReasonDialog open={dlg === 'deactivate'} onClose={() => setDlg('')} title={t('common:confirm.deactivateTitle', { name })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => { await call(api.prescription.POST('/api/prescription/v1/patients/{patient_id}/deactivate', { params: { path: { patient_id: id } }, body: { reason } })); await refresh(); }} />
      {pdf.element}
      {!p.is_active && <Alert tone="warning">{t('common:label.inactive')}</Alert>}
    </div>
  );
}
