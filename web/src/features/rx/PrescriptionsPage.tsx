// Prescriptions list (status / search) → detail.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { Button, DataTable, Input, PageHeader, Select, StatusPill, useDebounced } from '@/design';
import { date } from '@/lib/format';
import { toneOf, usePaging } from '../shared/hooks';

const STATUSES = ['draft', 'active', 'partly_dispensed', 'fully_dispensed', 'expired', 'cancelled'];

export default function PrescriptionsPage() {
  const { t, i18n } = useTranslation(['rx', 'common', 'nav', 'sales']);
  const user = useUser();
  const nav = useNavigate();
  const paging = usePaging();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const dq = useDebounced(q.trim());
  const list = useQuery({
    queryKey: ['prescription', 'rx', dq, status, paging.page, paging.size],
    queryFn: () => call(api.prescription.GET('/api/prescription/v1/prescriptions', { params: { query: { q: dq || undefined, status: (status || undefined) as never, page: paging.page, size: paging.size } } })),
  });
  const km = i18n.language === 'km';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.prescriptions')} title={t('rx.title')} actions={user.has('prescriptions.manage') && <Button variant="primary" onClick={() => nav('/rx/prescriptions/new')}>+ {t('rx.new')}</Button>} />
      <DataTable
        toolbar={<>
          <Input aria-label={t('common:action.search')} placeholder={`⌕ ${t('common:action.search')}`} className="w-72" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />
          <Select aria-label={t('common:label.status')} className="w-48" value={status} onChange={(e) => { setStatus(e.target.value); paging.reset(); }}>
            <option value="">{t('common:label.all')}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`sales:rxStatus.${s}`)}</option>)}
          </Select>
        </>}
        rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(r) => r.id} onRowClick={(r) => nav(`/rx/prescriptions/${r.id}`)}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('rx.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
          { key: 'p', header: t('rx.patient'), cell: (r) => (km ? r.patient.name_km || r.patient.name_en : r.patient.name_en || r.patient.name_km) },
          { key: 'd', header: t('rx.doctor'), cell: (r) => r.doctor.name ?? '—' },
          { key: 'i', header: t('rx.issued'), cell: (r) => date(r.issued_on) },
          { key: 'v', header: t('rx.validUntil'), cell: (r) => date(r.valid_until) },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`sales:rxStatus.${r.status}`)}</StatusPill> },
        ]} />
    </div>
  );
}
