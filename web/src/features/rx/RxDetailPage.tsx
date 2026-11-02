// 6f Rx detail: items with allowed / dispensed / held / remaining, attachments (streamed, each view logged),
// activate (draft), cancel with a reason (6g), dispense in the POS.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { QueryState } from '@/app/RouteError';
import { ApiErrorAlert, BlobViewer, Button, Card, DataTable, DefinitionList, PageHeader, ReasonDialog, SkeletonRows, StatusPill, UploadBox, useToast } from '@/design';
import { date, dateTime } from '@/lib/format';
import { toneOf, useMedicineNames } from '../shared/hooks';
import { downloadAttachment, uploadAttachment } from './attachments';
import { dispenseLoad } from './dispense';

export default function RxDetailPage() {
  const { id = '' } = useParams();
  const { t, i18n } = useTranslation(['rx', 'common', 'nav', 'sales']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [cancel, setCancel] = useState(false);
  const [view, setView] = useState<{ id: string; name: string } | null>(null);
  const q = useQuery({ queryKey: ['prescription', 'rx', id], queryFn: () => call(api.prescription.GET('/api/prescription/v1/prescriptions/{rx_id}', { params: { path: { rx_id: id } } })) });
  const rx = q.data;
  const names = useMedicineNames(rx?.items.map((i) => i.medicine_id) ?? []);
  const refresh = () => qc.invalidateQueries({ queryKey: ['prescription'] });
  const activate = useMutation({ mutationFn: () => call(api.prescription.POST('/api/prescription/v1/prescriptions/{rx_id}/activate', { params: { path: { rx_id: id } } })), onSuccess: () => { toast.success(t('rx.activated')); void refresh(); } });
  const upload = useMutation({ mutationFn: (f: File) => uploadAttachment(id, f), onSuccess: () => void refresh() });
  const dispense = useMutation({ mutationFn: () => dispenseLoad(id), onSuccess: (load) => nav('/pos', { state: { load } }) });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!rx) return <SkeletonRows />;
  const km = i18n.language === 'km';
  const open = rx.status === 'active' || rx.status === 'partly_dispensed';
  const manage = user.has('prescriptions.manage');
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.prescriptions')} / ${t('rx.title')}`} title={rx.number}
        actions={<>
          {rx.status === 'draft' && manage && <Button variant="primary" loading={activate.isPending} onClick={() => activate.mutate()}>{t('rx.activate')}</Button>}
          {open && user.is_pharmacist && user.has('pos.dispense_rx') && <Button variant="primary" loading={dispense.isPending} onClick={() => dispense.mutate()}>{t('rx.dispense')}</Button>}
          {(rx.status === 'draft' || open) && manage && <Button variant="danger-outline" onClick={() => setCancel(true)}>{t('rx.cancel')}</Button>}
        </>}>
        <StatusPill tone={toneOf(rx.status)}>{t(`sales:rxStatus.${rx.status}`)}</StatusPill>
      </PageHeader>
      <ApiErrorAlert error={activate.error ?? dispense.error} />
      <div className="grid gap-4 desktop:grid-cols-[2fr_1fr]">
        <Card title={t('rx.items')} padded={false}>
          <DataTable className="rounded-none border-0" rows={rx.items} rowKey={(i) => i.id} minWidth={720} columns={[
            { key: 'm', header: t('common:label.medicine'), cell: (i) => <span className="flex flex-col"><span className="font-medium">{names(i.medicine_id)}</span><span className="text-[12px] text-neutral-500">{[i.dosage, i.frequency, i.duration_days ? `${i.duration_days}d` : ''].filter(Boolean).join(' · ')}</span></span> },
            { key: 'f', header: t('rx.qtyBase'), align: 'right', cell: (i) => i.qty_base },
            { key: 'r', header: t('rx.repeats'), align: 'right', cell: (i) => `${i.repeats_used} / ${i.repeats_allowed}` },
            { key: 'a', header: t('rx.allowed'), align: 'right', cell: (i) => i.allowed_base },
            { key: 'd', header: t('rx.dispensed'), align: 'right', cell: (i) => i.dispensed_base },
            { key: 'h', header: t('rx.held'), align: 'right', cell: (i) => i.held_base || '—' },
            { key: 'x', header: t('rx.remaining'), align: 'right', cell: (i) => <b>{i.remaining_base}</b> },
          ]} />
        </Card>
        <div className="flex flex-col gap-4">
          <Card title={t('common:label.summary')}>
            <DefinitionList cols={1} items={[
              { label: t('rx.patient'), value: <button type="button" className="text-primary-600" onClick={() => nav(`/rx/patients/${rx.patient.id}`)}>{km ? rx.patient.name_km || rx.patient.name_en : rx.patient.name_en || rx.patient.name_km}</button> },
              { label: t('rx.doctor'), value: rx.doctor.name ?? '—' },
              { label: t('rx.rxNo'), value: rx.rx_no || '—' },
              { label: t('rx.issued'), value: date(rx.issued_on) },
              { label: t('rx.validUntil'), value: date(rx.valid_until) },
              ...(rx.cancel_reason ? [{ label: t('common:label.reason'), value: `${rx.cancel_reason} · ${dateTime(rx.cancelled_at)}` }] : []),
            ]} />
          </Card>
          <Card title={t('rx.attachments')}>
            <div className="flex flex-col gap-2 text-[13px]">
              {rx.attachments.map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-2"><span>{a.original_filename} · {Math.round(a.size_bytes / 1024)} KB</span>
                  <Button size="sm" onClick={() => setView({ id: a.id, name: a.original_filename })}>{t('rx.open')}</Button></div>
              ))}
              {manage && rx.status !== 'cancelled' && <UploadBox capture busy={upload.isPending} onFile={(f) => upload.mutate(f)} label={t('rx.upload')} />}
              <ApiErrorAlert error={upload.error} />
              <span className="text-[12px] text-neutral-500">{t('rx.fileLogged')}</span>
            </div>
          </Card>
        </div>
      </div>
      <ReasonDialog open={cancel} onClose={() => setCancel(false)} title={t('rx.cancel')} body={t('rx.cancelBody')} confirmLabel={t('rx.cancel')}
        onConfirm={async (reason) => { await call(api.prescription.POST('/api/prescription/v1/prescriptions/{rx_id}/cancel', { params: { path: { rx_id: id } }, body: { reason } })); await refresh(); }} />
      <BlobViewer load={view ? () => downloadAttachment(id, view.id) : null} title={view?.name} filename={view?.name ?? 'file'} onClose={() => setView(null)} />
    </div>
  );
}
