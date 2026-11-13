// 8e Re-order list: latest run (or run now), select lines → one purchase request, or transfer requests from the
// suggested branch. Last cost only when the API sent it.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { isApiError } from '@/api/errors';
import type { InventoryS } from '@/api/types';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, BranchTag, Button, DataTable, EmptyState, PageHeader, StatusPill, Usd, hasField, useToast } from '@/design';
import { date } from '@/lib/format';

type Line = InventoryS['ReorderLineOut'];

export default function ReorderPage() {
  const { t } = useTranslation(['stock', 'common', 'nav']);
  const qc = useQueryClient();
  const toast = useToast();
  const { oneBranch, byId } = useBranch();
  const [sel, setSel] = useState(new Set<string>());
  const q = useQuery({
    queryKey: ['inventory', 'reorder', oneBranch?.id],
    enabled: !!oneBranch,
    retry: false,
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/reorder-lists/latest', { params: { query: { branch_id: oneBranch!.id } } })),
  });
  const run = useMutation({
    mutationFn: () => call(api.inventory.POST('/api/inventory/v1/reorder-lists/run', { params: { query: { branch_id: oneBranch!.id } } })),
    onSuccess: (r) => { qc.setQueryData(['inventory', 'reorder', oneBranch?.id], r); setSel(new Set()); }, // a new list: old ticks are gone
  });
  const act = useMutation({
    mutationFn: (kind: 'pr' | 'tr') => {
      const body = { line_ids: [...sel] };
      const path = { list_id: q.data!.id };
      return kind === 'pr'
        ? call(api.inventory.POST('/api/inventory/v1/reorder-lists/{list_id}/purchase-requests', { params: { path }, body }))
        : call(api.inventory.POST('/api/inventory/v1/reorder-lists/{list_id}/transfer-requests', { params: { path }, body }));
    },
    onSuccess: (r) => {
      qc.setQueryData(['inventory', 'reorder', oneBranch?.id], r);
      const nums = [...new Set(r.lines.filter((l) => sel.has(l.id) && l.request_number).map((l) => l.request_number))];
      toast.success(nums.map((n) => t('reorder.done', { number: n })).join(', '));
      setSel(new Set());
    },
  });
  const list = q.data;
  const none = !list && (q.isSuccess || (isApiError(q.error) && q.error.code === 'NOT_FOUND'));
  const showCost = !!list?.lines.some((l) => hasField(l, 'last_cost_per_base'));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.stock')} title={t('reorder.title')} actions={<Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>{t('reorder.run')}</Button>}>
        {list && <span className="text-[13px] text-neutral-700">{t('reorder.runDate', { date: date(list.run_date), days: list.sales_days })}</span>}
      </PageHeader>
      <ApiErrorAlert error={run.error ?? act.error} />
      {none ? <EmptyState title={t('reorder.none')} /> : (
        <DataTable rows={list?.lines} loading={q.isLoading} error={none ? null : q.error} rowKey={(l) => l.id} minWidth={1100} dense
          selection={{ selected: sel, onChange: setSel, actions: <>
            <Button size="sm" variant="link" loading={act.isPending && act.variables === 'pr'} onClick={() => act.mutate('pr')}>{t('reorder.toPr')}</Button>
            <Button size="sm" variant="link" loading={act.isPending && act.variables === 'tr'} onClick={() => act.mutate('tr')}>{t('reorder.toTr')}</Button>
          </> }}
          columns={[
            { key: 'n', header: t('common:label.medicine'), cell: (l) => <span className="flex flex-col"><span className="font-medium">{l.name}</span><span className="text-[12px] text-neutral-500">{l.sku}</span></span> },
            { key: 'h', header: t('onHand.onHand'), align: 'right', cell: (l) => l.on_hand },
            { key: 'it', header: t('reorder.inTransit'), align: 'right', cell: (l) => l.in_transit || '—' },
            { key: 'o', header: t('reorder.onOrder'), align: 'right', cell: (l) => l.on_order || '—' },
            { key: 'a', header: t('reorder.avg'), align: 'right', cell: (l) => l.avg_daily },
            { key: 'p', header: t('reorder.point'), align: 'right', cell: (l) => l.reorder_point },
            { key: 't', header: t('reorder.target'), align: 'right', cell: (l) => l.target },
            { key: 's', header: t('reorder.suggest'), align: 'right', cell: (l) => <b>{l.pack_qty} {l.pack_unit}</b> },
            ...(showCost ? [{ key: 'c', header: t('reorder.lastCost'), align: 'right' as const, cell: (l: Line) => <Usd value={l.last_cost_per_base} /> }] : []),
            { key: 'src', header: t('reorder.source'), cell: (l) => (l.source_branch_id ? <span className="flex items-center gap-1"><BranchTag code={byId(l.source_branch_id)?.code ?? '?'} />{l.source_qty}</span> : '—') },
            { key: 'st', header: t('common:label.status'), cell: (l) => <StatusPill tone={l.request_number ? 'success' : 'neutral'}>{l.request_number ?? l.status}</StatusPill> },
          ]} />
      )}
    </div>
  );
}
