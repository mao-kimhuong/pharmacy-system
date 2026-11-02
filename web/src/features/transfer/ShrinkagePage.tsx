// 11e Shrinkage: record (batch, qty, reason, note; controlled: PIN + witness and a destruction method), above the
// branch limit it waits for another person with inventory.shrinkage_approve; photo (private, streamed).
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { isApiError } from '@/api/errors';
import type { InventoryS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, BlobViewer, Button, DataTable, Dialog, EmptyState, Field, Input, PageHeader, ReasonDialog, Select, StatusPill, TextArea, UploadBox, Usd, WitnessDialog, hasField, useToast } from '@/design';
import { dateTime } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';
import { BatchSelect } from '../shared/BatchSelect';
import { MedicinePicker, type Medicine } from '../shared/MedicinePicker';
import { useMedicineNames, usePaging, useStaffNames } from '../shared/hooks';
import { fileBody } from '../warehouse/upload';

type Shr = InventoryS['ShrinkageOut'];
const REASONS = ['expired', 'damaged', 'broken', 'lost_theft', 'recalled'] as const;

function NewShrinkage({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(['transfer', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const { oneBranch } = useBranch();
  const [med, setMed] = useState<Medicine | null>(null);
  const [batch, setBatch] = useState('');
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState<(typeof REASONS)[number]>('damaged');
  const [note, setNote] = useState('');
  const [method, setMethod] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [witness, setWitness] = useState(false);
  const controlled = !!med?.controlled_schedule;
  const body = useMemo(() => ({ branch_id: oneBranch?.id ?? '', batch_id: batch, qty_base: Number(qty), reason, note, destruction_method: method }), [oneBranch, batch, qty, reason, note, method]);
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: async (tk?: { pin?: string; witness: string }) => {
      const s = await call(api.inventory.POST('/api/inventory/v1/shrinkages', { body: { ...body, pin_token: tk?.pin ?? null, witness_token: tk?.witness ?? null }, ...withKey(key) }));
      if (photo) await call(api.inventory.POST('/api/inventory/v1/shrinkages/{shrinkage_id}/photo', { params: { path: { shrinkage_id: s.id } }, ...fileBody(photo) }));
      return s;
    },
    onSuccess: (s) => { toast.success(s.number); void qc.invalidateQueries({ queryKey: ['inventory'] }); onClose(); },
    onError: (e) => { if (isApiError(e) && (e.code === 'PIN_REQUIRED' || e.code === 'WITNESS_REQUIRED')) setWitness(true); },
  });
  const ok = batch && Number(qty) > 0 && (!controlled || reason === 'lost_theft' || method.trim());
  return (
    <>
      <Dialog open={!witness} onClose={onClose} title={t('shr.new')} width={560}
        footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!ok} loading={m.isPending} onClick={() => (controlled ? setWitness(true) : m.mutate(undefined))}>{t('common:action.save')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('common:label.medicine')} required>{(id) => <MedicinePicker id={id} value={med} onChange={(x) => { setMed(x); setBatch(''); }} autoFocus />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('common:label.batch')} required>{(id) => <BatchSelect id={id} branchId={oneBranch?.id ?? ''} medicineId={med?.id} value={batch} onChange={(b) => setBatch(b)} />}</Field>
            <Field label={`${t('common:label.qty')} (${med?.base_unit ?? ''})`} required>{(id) => <Input id={id} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ''))} />}</Field>
          </div>
          <Field label={t('common:label.reason')}>{(id) => <Select id={id} value={reason} onChange={(e) => setReason(e.target.value as typeof reason)}>{REASONS.map((r) => <option key={r} value={r}>{t(`shr.reason.${r}`)}</option>)}</Select>}</Field>
          {controlled && <Field label={t('shr.method')} required={reason !== 'lost_theft'}>{(id) => <Input id={id} value={method} onChange={(e) => setMethod(e.target.value)} />}</Field>}
          <Field label={t('common:label.notes')}>{(id) => <TextArea id={id} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
          <UploadBox capture accept="image/jpeg,image/png,application/pdf" label={photo ? photo.name : t('shr.addPhoto')} onFile={setPhoto} />
          {controlled && <Alert tone="info">{t('shr.controlled')}</Alert>}
          <Alert tone="info">{t('shr.pendingHint')}</Alert>
          <ApiErrorAlert error={m.error} />
        </div>
      </Dialog>
      <WitnessDialog open={witness} action="inventory.shrinkage" branchId={oneBranch?.id ?? ''} managerOnly={reason !== 'lost_theft'}
        onClose={() => setWitness(false)} onTokens={({ pin, witness: w }) => { setWitness(false); m.mutate({ pin: pin?.pin_token, witness: w.pin_token }); }} />
    </>
  );
}

export default function ShrinkagePage() {
  const { t } = useTranslation(['transfer', 'common', 'nav']);
  const user = useUser();
  const qc = useQueryClient();
  const staff = useStaffNames();
  const { branchParam } = useBranch();
  const paging = usePaging();
  const [status, setStatus] = useState('');
  const [neu, setNeu] = useState(false);
  const [reject, setReject] = useState<Shr | null>(null);
  const [photo, setPhoto] = useState<Shr | null>(null);
  const q = useQuery({ queryKey: ['inventory', 'shrinkages', branchParam, status, paging.page], queryFn: () => call(api.inventory.GET('/api/inventory/v1/shrinkages', { params: { query: { branch_id: branchParam, status: status || undefined, page: paging.page, size: paging.size } } })) });
  const names = useMedicineNames(q.data?.items.map((s) => s.medicine_id) ?? []);
  const approve = useMutation({
    mutationFn: (id: string) => call(api.inventory.POST('/api/inventory/v1/shrinkages/{shrinkage_id}/approve', { params: { path: { shrinkage_id: id } }, ...withKey(`approve-${id}`) })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['inventory'] }),
  });
  const showCost = !!q.data?.items.some((s) => hasField(s, 'value'));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.transfer')} title={t('shr.title')} actions={user.has('inventory.shrinkage') && <Button variant="primary" onClick={() => setNeu(true)}>+ {t('shr.new')}</Button>} />
      <ApiErrorAlert error={approve.error} />
      <DataTable toolbar={<Select aria-label={t('common:label.status')} className="w-48" value={status} onChange={(e) => { setStatus(e.target.value); paging.reset(); }}><option value="">{t('common:label.all')}</option>{['pending_approval', 'posted', 'rejected'].map((s) => <option key={s} value={s}>{t(`shr.status.${s}`)}</option>)}</Select>}
        rows={q.data?.items} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(s) => s.id} empty={<EmptyState title={t('shr.empty')} />}
        paging={{ page: paging.page, size: paging.size, total: q.data?.total ?? 0, onPage: paging.setPage }}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (s) => <span className="font-mono text-[12px]">{s.number}</span> },
          { key: 'm', header: t('common:label.medicine'), cell: (s) => `${names(s.medicine_id)}${s.lot_no ? ` · ${s.lot_no}` : ''}` },
          { key: 'q', header: t('common:label.qty'), align: 'right', cell: (s) => s.qty_base },
          { key: 'r', header: t('common:label.reason'), cell: (s) => t(`shr.reason.${s.reason}`, { defaultValue: s.reason }) },
          ...(showCost ? [{ key: 'v', header: t('common:label.value'), align: 'right' as const, cell: (s: Shr) => <Usd value={s.value} /> }] : []),
          { key: 'b', header: t('common:label.createdBy'), cell: (s) => `${staff(s.created_by)} · ${dateTime(s.created_at)}` },
          { key: 's', header: t('common:label.status'), cell: (s) => <StatusPill tone={s.status === 'posted' ? 'success' : s.status === 'pending_approval' ? 'warning' : 'danger'}>{t(`shr.status.${s.status}`, { defaultValue: s.status })}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (s) => (
            <span className="flex justify-end gap-1">
              {s.has_photo && <Button size="sm" onClick={() => setPhoto(s)}>{t('shr.photo')}</Button>}
              {s.status === 'pending_approval' && user.has('inventory.shrinkage_approve') && s.created_by !== user.id && <>
                <Button size="sm" variant="primary" loading={approve.isPending && approve.variables === s.id} onClick={() => approve.mutate(s.id)}>{t('shr.approve')}</Button>
                <Button size="sm" onClick={() => setReject(s)}>{t('shr.reject')}</Button></>}
            </span>
          ) },
        ]} />
      {neu && <NewShrinkage onClose={() => setNeu(false)} />}
      <ReasonDialog open={!!reject} onClose={() => setReject(null)} title={t('shr.reject')} confirmLabel={t('shr.reject')}
        onConfirm={async (reason) => { await call(api.inventory.POST('/api/inventory/v1/shrinkages/{shrinkage_id}/reject', { params: { path: { shrinkage_id: reject!.id } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['inventory'] }); }} />
      <BlobViewer load={photo ? () => call(api.inventory.GET('/api/inventory/v1/shrinkages/{shrinkage_id}/photo', { params: { path: { shrinkage_id: photo.id } }, parseAs: 'blob' })) as unknown as Promise<Blob> : null}
        title={photo?.number} filename={`${photo?.number ?? 'photo'}`} onClose={() => setPhoto(null)} />
    </div>
  );
}
