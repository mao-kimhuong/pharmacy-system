// 12i Dispense from Rx: active prescriptions; their open items go to the POS linked to the Rx.
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { ApiErrorAlert, Button, DataTable, PageHeader, StatusPill } from '@/design';
import { date } from '@/lib/format';
import { toneOf } from '../shared/hooks';
import { dispenseLoad } from './dispense';

export default function DispensePage() {
  const { t, i18n } = useTranslation(['rx', 'common', 'nav', 'sales']);
  const nav = useNavigate();
  const active = useQuery({ queryKey: ['prescription', 'rx', 'open'], queryFn: async () => {
    const [a, p] = await Promise.all(['active', 'partly_dispensed'].map((status) => call(api.prescription.GET('/api/prescription/v1/prescriptions', { params: { query: { status: status as never, size: 100 } } }))));
    return [...a.items, ...p.items].sort((x, y) => x.valid_until.localeCompare(y.valid_until));
  } });
  const go = useMutation({ mutationFn: dispenseLoad, onSuccess: (load) => nav('/pos', { state: { load } }) });
  const km = i18n.language === 'km';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.prescriptions')} title={t('dispense.title')}><span className="text-[13px] text-neutral-700">{t('dispense.hint')}</span></PageHeader>
      <ApiErrorAlert error={go.error} />
      <DataTable rows={active.data} loading={active.isLoading} error={active.error} onRetry={() => void active.refetch()} rowKey={(r) => r.id}
        columns={[
          { key: 'n', header: t('rx.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
          { key: 'p', header: t('rx.patient'), cell: (r) => (km ? r.patient.name_km || r.patient.name_en : r.patient.name_en || r.patient.name_km) },
          { key: 'd', header: t('rx.doctor'), cell: (r) => r.doctor.name ?? '—' },
          { key: 'v', header: t('rx.validUntil'), cell: (r) => date(r.valid_until) },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`sales:rxStatus.${r.status}`)}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (r) => <Button size="sm" variant="primary" loading={go.isPending && go.variables === r.id} onClick={() => go.mutate(r.id)}>{t('rx.dispense')}</Button> },
        ]} />
    </div>
  );
}
