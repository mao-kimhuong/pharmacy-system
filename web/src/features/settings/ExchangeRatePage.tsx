// 14f Exchange rate for the branch chosen in the header: the rate in use, set a new one (whole riel per USD), and
// the history (who, when, previous → new) with a date filter.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { branchName, useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, Card, DataTable, EmptyState, Field, Input, KpiTile, PageHeader, Toolbar, useToast } from '@/design';
import { dateTime, khr } from '@/lib/format';
import { useStaffNames, usePaging } from '../shared/hooks';

export default function ExchangeRatePage() {
  const { t, i18n } = useTranslation(['settings', 'common', 'nav']);
  const { oneBranch } = useBranch();
  const qc = useQueryClient();
  const toast = useToast();
  const staff = useStaffNames();
  const paging = usePaging();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [rate, setRate] = useState('');
  const bid = oneBranch?.id ?? '';
  const current = useQuery({
    queryKey: ['sales', 'rate', bid, 'current'], enabled: !!bid,
    queryFn: () => call(api.sales.GET('/api/sales/v1/exchange-rates/{branch_id}', { params: { path: { branch_id: bid }, query: { page: 1, size: 1 } } })),
  });
  const query = { from: from || undefined, to: to || undefined, page: paging.page, size: paging.size };
  const hist = useQuery({
    queryKey: ['sales', 'rate', bid, query], enabled: !!bid,
    queryFn: () => call(api.sales.GET('/api/sales/v1/exchange-rates/{branch_id}', { params: { path: { branch_id: bid }, query } })),
  });
  const set = useMutation({
    mutationFn: () => call(api.sales.PUT('/api/sales/v1/exchange-rates/{branch_id}', { params: { path: { branch_id: bid } }, body: { khr_per_usd: Number.parseInt(rate, 10) } })),
    onSuccess: () => { setRate(''); toast.success(t('rate.saved')); void qc.invalidateQueries({ queryKey: ['sales', 'rate'] }); },
  });
  const now = current.data?.[0];
  const rows = hist.data ?? [];
  // The API returns a plain list: a full page means there may be another one.
  const total = (paging.page - 1) * paging.size + rows.length + (rows.length === paging.size ? 1 : 0);
  if (!oneBranch) return <EmptyState title={t('common:label.branch')} className="m-5" />;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={`${t('rate.title')} · ${branchName(oneBranch, i18n.language)}`} />
      <div className="grid grid-cols-1 gap-4 tablet:grid-cols-2">
        <KpiTile label={t('rate.current')} value={now ? `${khr(now.khr_per_usd)} / $1` : '—'} sub={now ? `${dateTime(now.set_at)} · ${staff(now.set_by)}` : undefined} />
        <Card>
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (Number(rate) > 0) set.mutate(); }}>
            <Field label={t('rate.new')} className="flex-1">{(id) => <Input id={id} inputMode="numeric" suffix="៛" value={rate} onChange={(e) => setRate(e.target.value.replace(/\D/g, ''))} />}</Field>
            <Button type="submit" variant="primary" disabled={!(Number(rate) > 0)} loading={set.isPending}>{t('rate.set')}</Button>
          </form>
          <ApiErrorAlert error={set.error} className="mt-3" />
        </Card>
      </div>
      <h2 className="text-[15px] font-semibold">{t('rate.history')}</h2>
      <Toolbar>
        <Input aria-label={t('common:label.from')} type="date" className="w-40" value={from} onChange={(e) => { setFrom(e.target.value); paging.reset(); }} />
        <Input aria-label={t('common:label.to')} type="date" className="w-40" value={to} onChange={(e) => { setTo(e.target.value); paging.reset(); }} />
      </Toolbar>
      <DataTable rows={rows} loading={hist.isLoading} error={hist.error} onRetry={() => void hist.refetch()} rowKey={(r) => r.set_at}
        paging={{ page: paging.page, size: paging.size, total, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'w', header: t('rate.when'), cell: (r) => <span className="tabular-nums">{dateTime(r.set_at)}</span> },
          { key: 'p', header: t('rate.previous'), align: 'right', cell: (r) => (r.previous ? khr(r.previous) : '—') },
          { key: 'n', header: t('rate.title'), align: 'right', cell: (r) => <span className="font-semibold">{khr(r.khr_per_usd)}</span> },
          { key: 'b', header: t('rate.by'), cell: (r) => staff(r.set_by) },
        ]} />
    </div>
  );
}
