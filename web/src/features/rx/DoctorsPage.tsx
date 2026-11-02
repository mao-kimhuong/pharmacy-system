// 6d Doctors: search, add, edit, deactivate (reason) / activate. Licence numbers are unique.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PrescriptionS } from '@/api/types';
import { useUser } from '@/app/auth';
import { ApiErrorAlert, Button, Checkbox, DataTable, Dialog, Field, Input, PageHeader, ReasonDialog, StatusPill, useDebounced } from '@/design';
import { usePaging } from '../shared/hooks';

type Doctor = PrescriptionS['DoctorOut'];

export default function DoctorsPage() {
  const { t } = useTranslation(['rx', 'common', 'nav', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const paging = usePaging();
  const [q, setQ] = useState('');
  const [inactive, setInactive] = useState(false);
  const dq = useDebounced(q.trim());
  const [edit, setEdit] = useState<Partial<Doctor> | null>(null);
  const [deact, setDeact] = useState<Doctor | null>(null);
  const list = useQuery({
    queryKey: ['prescription', 'doctors', dq, inactive, paging.page, paging.size],
    queryFn: () => call(api.prescription.GET('/api/prescription/v1/doctors', { params: { query: { q: dq || undefined, include_inactive: inactive, page: paging.page, size: paging.size } } })),
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { name: edit!.name ?? '', licence_no: edit!.licence_no ?? '', specialty: edit!.specialty ?? '', clinic: edit!.clinic ?? '', phone: edit!.phone || null };
      return edit!.id
        ? call(api.prescription.PATCH('/api/prescription/v1/doctors/{doctor_id}', { params: { path: { doctor_id: edit!.id } }, body }))
        : call(api.prescription.POST('/api/prescription/v1/doctors', { body }));
    },
    onSuccess: () => { setEdit(null); void qc.invalidateQueries({ queryKey: ['prescription', 'doctors'] }); },
  });
  const activate = useMutation({
    mutationFn: (id: string) => call(api.prescription.POST('/api/prescription/v1/doctors/{doctor_id}/activate', { params: { path: { doctor_id: id } }, body: null })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['prescription', 'doctors'] }),
  });
  const manage = user.has('prescriptions.manage');
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.prescriptions')} title={t('doctors.title')} actions={manage && <Button variant="primary" onClick={() => setEdit({})}>+ {t('doctors.new')}</Button>} />
      <DataTable
        toolbar={<><Input aria-label={t('common:action.search')} placeholder={`⌕ ${t('common:action.search')}`} className="w-72" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />
          <Checkbox label={t('common:label.inactive')} checked={inactive} onChange={(e) => setInactive(e.target.checked)} /></>}
        rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(d) => d.id}
        empty={<div className="p-8 text-center text-neutral-500">{t('doctors.empty')}</div>}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('common:label.name'), cell: (d) => d.name },
          { key: 'l', header: t('doctors.licence'), cell: (d) => <span className="font-mono text-[12px]">{d.licence_no}</span> },
          { key: 's', header: t('doctors.specialty'), cell: (d) => d.specialty || '—' },
          { key: 'c', header: t('doctors.clinic'), cell: (d) => d.clinic || '—' },
          { key: 'p', header: t('common:label.phone'), cell: (d) => d.phone || '—' },
          { key: 'st', header: t('common:label.status'), cell: (d) => <StatusPill tone={d.is_active ? 'success' : 'neutral'}>{d.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (d) => manage && (
            <span className="flex justify-end gap-1">
              <Button size="sm" onClick={() => setEdit(d)}>{t('common:action.edit')}</Button>
              {d.is_active ? <Button size="sm" onClick={() => setDeact(d)}>{t('common:action.deactivate')}</Button> : <Button size="sm" onClick={() => activate.mutate(d.id)}>{t('common:action.activate')}</Button>}
            </span>
          ) },
        ]} />
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? t('doctors.edit') : t('doctors.new')} width={560}
        footer={<><Button onClick={() => setEdit(null)}>{t('common:action.cancel')}</Button><Button variant="primary" loading={save.isPending} disabled={!edit?.name || !edit?.licence_no} onClick={() => save.mutate()}>{t('common:action.save')}</Button></>}>
        {edit && (
          <div className="grid gap-3 tablet:grid-cols-2">
            <Field label={t('common:label.name')} required>{(id) => <Input id={id} autoFocus value={edit.name ?? ''} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />}</Field>
            <Field label={t('doctors.licence')} required>{(id) => <Input id={id} value={edit.licence_no ?? ''} onChange={(e) => setEdit({ ...edit, licence_no: e.target.value })} />}</Field>
            <Field label={t('doctors.specialty')}>{(id) => <Input id={id} value={edit.specialty ?? ''} onChange={(e) => setEdit({ ...edit, specialty: e.target.value })} />}</Field>
            <Field label={t('doctors.clinic')}>{(id) => <Input id={id} value={edit.clinic ?? ''} onChange={(e) => setEdit({ ...edit, clinic: e.target.value })} />}</Field>
            <Field label={t('common:label.phone')}>{(id) => <Input id={id} value={edit.phone ?? ''} onChange={(e) => setEdit({ ...edit, phone: e.target.value })} />}</Field>
            <ApiErrorAlert error={save.error} className="tablet:col-span-2" />
          </div>
        )}
      </Dialog>
      <ReasonDialog open={!!deact} onClose={() => setDeact(null)} title={t('common:confirm.deactivateTitle', { name: deact?.name })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => { await call(api.prescription.POST('/api/prescription/v1/doctors/{doctor_id}/deactivate', { params: { path: { doctor_id: deact!.id } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['prescription', 'doctors'] }); }} />
    </div>
  );
}
