// 12b Suspended carts: resume re-prices and re-checks stock; what changed is shown in the POS (3n).
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, DataTable, EmptyState, PageHeader, StatusPill, Usd } from '@/design';
import { dateTime } from '@/lib/format';
import { toneOf, useStaffNames } from '../shared/hooks';
import { customerRef, linesOf } from './toPos';

export default function SuspendedPage() {
  const { t } = useTranslation(['sales', 'common', 'nav']);
  const { oneBranch } = useBranch();
  const nav = useNavigate();
  const staff = useStaffNames();
  const q = useQuery({
    queryKey: ['sales', 'carts', oneBranch?.id],
    enabled: !!oneBranch,
    queryFn: () => call(api.sales.GET('/api/sales/v1/carts', { params: { query: { branch_id: oneBranch!.id, status: 'suspended' } } })),
  });
  const resume = useMutation({
    mutationFn: (id: string) => call(api.sales.POST('/api/sales/v1/carts/{cart_id}/resume', { params: { path: { cart_id: id } } })),
    onSuccess: async (r) => nav('/pos', { state: { load: { lines: linesOf(r.lines), customer: await customerRef(r.customer_id), resumed: { number: r.number, changes: r.changes } } } }),
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('suspended.title')} />
      <ApiErrorAlert error={resume.error} />
      <DataTable
        rows={q.data}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        rowKey={(r) => r.id}
        empty={<EmptyState title={t('suspended.empty')} body={t('suspended.emptyBody')} action={<Button variant="primary" onClick={() => nav('/pos')}>{t('suspended.toPos')}</Button>} />}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
          { key: 'note', header: t('suspended.note'), cell: (r) => r.note || '—' },
          { key: 'i', header: t('suspended.items'), align: 'right', cell: (r) => r.priced.length },
          { key: 't', header: t('common:label.total'), align: 'right', cell: (r) => <Usd value={r.total} strong /> },
          { key: 'b', header: t('suspended.by'), cell: (r) => `${staff(r.created_by)} · ${dateTime(r.created_at)}` },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (r) => <Button size="sm" variant="primary" loading={resume.isPending && resume.variables === r.id} onClick={() => resume.mutate(r.id)}>{t('suspended.resume')}</Button> },
        ]}
      />
    </div>
  );
}
