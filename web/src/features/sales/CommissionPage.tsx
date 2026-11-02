// 12g List Commission: per staff for a branch and month (commission.view_own: self only; commission.manage: the
// branch, close and mark paid). Drill-down shows the lines.
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { Button, ConfirmDialog, DataTable, Drawer, Field, Input, PageHeader, StatusPill, Usd } from '@/design';
import { dateTime, todayIso } from '@/lib/format';
import { toneOf, useStaffNames } from '../shared/hooks';

export default function CommissionPage() {
  const { t } = useTranslation(['sales', 'common', 'nav']);
  const user = useUser();
  const { oneBranch } = useBranch();
  const qc = useQueryClient();
  const staff = useStaffNames();
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const [drill, setDrill] = useState<string | null>(null);
  const [act, setAct] = useState<'' | 'close' | 'paid'>('');
  const m = `${month}-01`;
  const manage = user.has('commission.manage');
  const q = useQuery({
    queryKey: ['sales', 'commission', oneBranch?.id, m],
    enabled: !!oneBranch,
    queryFn: () => call(api.sales.GET('/api/sales/v1/commission/report', { params: { query: { branch_id: oneBranch!.id, month: m, staff_id: manage ? undefined : user.id } } })),
  });
  const lines = useQuery({
    queryKey: ['sales', 'commission-lines', oneBranch?.id, m, drill],
    enabled: !!drill && !!oneBranch,
    queryFn: () => call(api.sales.GET('/api/sales/v1/commission/report/{staff_id}', { params: { path: { staff_id: drill! }, query: { branch_id: oneBranch!.id, month: m } } })),
  });
  const period = async (what: 'close' | 'paid') => {
    const path = { branch_id: oneBranch!.id, month: m };
    if (what === 'close') await call(api.sales.POST('/api/sales/v1/commission/periods/{branch_id}/{month}/close', { params: { path } }));
    else await call(api.sales.POST('/api/sales/v1/commission/periods/{branch_id}/{month}/paid', { params: { path } }));
    await qc.invalidateQueries({ queryKey: ['sales', 'commission'] });
  };
  const status = q.data?.status ?? 'open';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('commission.title')}
        actions={manage && <>
          {status === 'open' && <Button onClick={() => setAct('close')}>{t('commission.close')}</Button>}
          {status === 'closed' && <Button variant="primary" onClick={() => setAct('paid')}>{t('commission.pay')}</Button>}
        </>} />
      <DataTable
        toolbar={<>
          <Field label={t('commission.month')}>{(id) => <Input id={id} type="month" value={month} onChange={(e) => setMonth(e.target.value)} />}</Field>
          <span className="ml-auto flex items-center gap-2 text-[13px]">{t('commission.period')} <StatusPill tone={toneOf(status)}>{t(`status.${status}`, { defaultValue: status })}</StatusPill></span>
        </>}
        rows={q.data?.staff} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.staff_id} onRowClick={(r) => setDrill(r.staff_id)}
        columns={[
          { key: 's', header: t('commission.staff'), cell: (r) => staff(r.staff_id), footer: t('common:table.totals') },
          { key: 'l', header: t('commission.lines'), align: 'right', cell: (r) => r.lines },
          { key: 'n', header: t('commission.net'), align: 'right', cell: (r) => <Usd value={r.net_usd} /> },
          { key: 'a', header: t('commission.amount'), align: 'right', cell: (r) => <Usd value={r.commission} strong />, footer: <Usd value={q.data?.total} strong /> },
        ]}
      />
      <Drawer open={!!drill} onClose={() => setDrill(null)} title={t('commission.drill', { name: staff(drill) })} width={640}>
        <DataTable rows={lines.data} loading={lines.isLoading} error={lines.error} rowKey={(r) => r.invoice_line_id + r.created_at} minWidth={520} dense
          columns={[
            { key: 'i', header: t('invoices.number'), cell: (r) => <span className="font-mono text-[12px]">{r.invoice_number}</span> },
            { key: 'sku', header: 'SKU', cell: (r) => r.sku },
            { key: 'src', header: t('commission.source'), cell: (r) => r.source },
            { key: 'n', header: t('commission.net'), align: 'right', cell: (r) => <Usd value={r.net_usd} /> },
            { key: 'a', header: t('commission.amount'), align: 'right', cell: (r) => <Usd value={r.amount} strong /> },
            { key: 'd', header: t('common:label.date'), cell: (r) => dateTime(r.created_at) },
          ]} />
      </Drawer>
      <ConfirmDialog open={act !== ''} onClose={() => setAct('')} title={act === 'close' ? t('commission.close') : t('commission.pay')} body={act === 'close' ? t('commission.closeBody') : undefined}
        confirmLabel={act === 'close' ? t('commission.close') : t('commission.pay')} onConfirm={() => period(act as 'close' | 'paid')} />
    </div>
  );
}
