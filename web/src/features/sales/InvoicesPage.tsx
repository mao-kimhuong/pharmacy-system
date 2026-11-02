// 12d List Sale: invoices of the chosen branch with date / status / number filters; open one for its detail.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useBranch } from '@/app/branch';
import { DataTable, Field, Input, PageHeader, Select, StatusPill, Usd } from '@/design';
import { addDays, dateTime, todayIso } from '@/lib/format';
import { toneOf, useCustomerNames, usePaging, useStaffNames } from '../shared/hooks';

const STATUSES = ['completed', 'cancelled', 'failed', 'pending', 'needs_attention'];

export default function InvoicesPage() {
  const { t } = useTranslation(['sales', 'common', 'nav']);
  const { branchParam } = useBranch();
  const nav = useNavigate();
  const paging = usePaging();
  const [from, setFrom] = useState(addDays(todayIso(), -6));
  const [to, setTo] = useState(todayIso());
  const [status, setStatus] = useState('');
  const [number, setNumber] = useState('');
  const staff = useStaffNames();
  const q = useQuery({
    queryKey: ['sales', 'invoices', branchParam, from, to, status, number, paging.page, paging.size],
    queryFn: () => call(api.sales.GET('/api/sales/v1/invoices', { params: { query: {
      branch_id: branchParam, from: number ? undefined : from, to: number ? undefined : to, status: status || undefined, number: number || undefined, page: paging.page, size: paging.size,
    } } })),
  });
  const customer = useCustomerNames(q.data?.items.map((i) => i.customer_id) ?? []);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('invoices.title')} />
      <DataTable
        caption={t('invoices.title')}
        toolbar={<>
          <Field label={t('invoices.search')}>{(id) => <Input id={id} value={number} onChange={(e) => { setNumber(e.target.value.trim()); paging.reset(); }} placeholder="PP1-INV-…" className="w-56" />}</Field>
          <Field label={t('common:label.from')}>{(id) => <Input id={id} type="date" value={from} onChange={(e) => { setFrom(e.target.value); paging.reset(); }} />}</Field>
          <Field label={t('common:label.to')}>{(id) => <Input id={id} type="date" value={to} onChange={(e) => { setTo(e.target.value); paging.reset(); }} />}</Field>
          <Field label={t('common:label.status')}>{(id) => (
            <Select id={id} value={status} onChange={(e) => { setStatus(e.target.value); paging.reset(); }}>
              <option value="">{t('common:label.all')}</option>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
            </Select>
          )}</Field>
        </>}
        rows={q.data?.items}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        rowKey={(r) => r.id}
        onRowClick={(r) => nav(`/sales/invoices/${r.id}`)}
        paging={{ page: paging.page, size: paging.size, total: q.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('invoices.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number ?? '—'}</span> },
          { key: 'd', header: t('invoices.date'), cell: (r) => dateTime(r.completed_at ?? r.created_at) },
          { key: 'c', header: t('invoices.customer'), cell: (r) => (r.customer_id ? customer(r.customer_id)?.name ?? '…' : <span className="text-neutral-500">{t('invoices.walkIn')}</span>) },
          { key: 's', header: t('invoices.staff'), cell: (r) => staff(r.created_by) },
          { key: 't', header: t('invoices.total'), align: 'right', cell: (r) => <Usd value={r.total} strong /> },
          { key: 'st', header: t('invoices.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
        ]}
      />
    </div>
  );
}
