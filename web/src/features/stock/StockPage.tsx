// Stock on hand (2a/2b; phone 2d/2e): per medicine and branch, batches FEFO, packs; value only when the API sent it.
import { Fragment, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { InventoryS } from '@/api/types';
import { useBranch } from '@/app/branch';
import { BranchTag, DataTable, Input, PageHeader, Qty, SafetyBadge, StatusPill, Usd, hasField, useDebounced } from '@/design';
import { date } from '@/lib/format';
import { useMediaQuery } from '@/lib/hooks';
import { usePaging } from '../shared/hooks';

type Item = InventoryS['StockItem'];

const packs = (p: InventoryS['PackQty'][]) => p.filter((x) => x.qty > 0).map((x) => `${x.qty} ${x.pack_unit}`).join(' + ') || '—';

export default function StockPage() {
  const { t, i18n } = useTranslation(['stock', 'common', 'nav']);
  const { branchParam, byId } = useBranch();
  const phone = useMediaQuery('(max-width: 1023px)');
  const paging = usePaging();
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const dq = useDebounced(q.trim());
  const list = useQuery({
    queryKey: ['inventory', 'stock', branchParam, dq, paging.page, paging.size],
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/stock', { params: { query: { branch_id: branchParam, q: dq || undefined, page: paging.page, size: paging.size } } })),
  });
  const rows = list.data?.items;
  const showCost = !!rows?.some((r) => hasField(r, 'stock_value'));
  const name = (r: Item) => (i18n.language === 'km' && r.name_km ? r.name_km : r.name);
  const status = (r: Item) => (r.qty_available <= 0 ? <StatusPill tone="danger">{t('onHand.out')}</StatusPill> : r.qty_quarantined > 0 ? <StatusPill tone="warning">{t('onHand.quarantined')}</StatusPill> : <StatusPill tone="success">{t('onHand.ok')}</StatusPill>);
  const search = <Input aria-label={t('onHand.search')} placeholder={`⌕ ${t('onHand.search')}`} className="w-72 max-w-full" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />;
  return (
    <div className="flex flex-col gap-4 p-4 tablet:px-7 tablet:py-5">
      <PageHeader crumb={`${t('nav:group.stock')}`} title={t('onHand.title')}>
        {rows && !showCost && rows.length > 0 && <span className="self-start rounded-md bg-neutral-100 px-2.5 py-1.5 text-[12px] text-neutral-700">🔒 {t('onHand.costHidden')}</span>}
      </PageHeader>
      {phone ? (
        <div className="flex flex-col gap-2">
          {search}
          {rows?.map((r) => (
            <div key={r.branch_id + r.medicine_id} className="flex flex-col gap-1.5 rounded-xl border border-neutral-200 bg-white p-3">
              <div className="flex items-start justify-between gap-2"><b className="text-[14px]">{name(r)}</b><Qty value={r.qty_on_hand} unit={r.base_unit} className="text-[16px] font-semibold" /></div>
              <div className="flex flex-wrap items-center gap-1.5">{r.controlled_schedule && <SafetyBadge kind="controlled" />}{status(r)}<span className="ml-auto text-[12px] text-neutral-500">{r.batches.length} {t('onHand.batches')}</span></div>
            </div>
          ))}
        </div>
      ) : (
        <DataTable toolbar={search} rows={rows} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(r) => r.branch_id + r.medicine_id}
          onRowClick={(r) => setOpen(open === r.branch_id + r.medicine_id ? null : r.branch_id + r.medicine_id)}
          paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
          columns={[
            { key: 'n', header: t('common:label.medicine'), cell: (r) => (
              <span className="flex flex-col gap-1">
                <span className="flex flex-wrap items-center gap-1.5 font-medium">{name(r)}{r.controlled_schedule && <SafetyBadge kind="controlled" />}</span>
                {open === r.branch_id + r.medicine_id && (
                  <span className="flex flex-col gap-0.5 text-[12px] text-neutral-700">
                    {r.batches.map((b) => <Fragment key={b.batch_id}><span><span className="font-mono">{b.lot_no}</span> · {date(b.expiry_date)} · {b.qty_on_hand}{b.qty_quarantined ? ` (${t('onHand.quarantined')} ${b.qty_quarantined})` : ''}{hasField(b, 'value') ? ` · ${b.value}` : ''}</span></Fragment>)}
                  </span>
                )}
              </span>
            ) },
            { key: 'b', header: t('common:label.branch'), cell: (r) => <BranchTag code={byId(r.branch_id)?.code ?? '?'} /> },
            { key: 'bt', header: t('onHand.batches'), align: 'right', cell: (r) => r.batches.length },
            { key: 'h', header: t('onHand.onHand'), align: 'right', cell: (r) => <Qty value={r.qty_on_hand} className="font-semibold" /> },
            { key: 'a', header: t('onHand.available'), align: 'right', cell: (r) => <Qty value={r.qty_available} /> },
            { key: 'u', header: t('common:label.unit'), cell: (r) => <span className="text-neutral-700">{r.base_unit} <span className="text-[12px] text-neutral-500">· {packs(r.on_hand_in_packs)}</span></span> },
            ...(showCost ? [{ key: 'v', header: t('onHand.value'), align: 'right' as const, cell: (r: Item) => <Usd value={r.stock_value} /> }] : []),
            { key: 's', header: t('common:label.status'), cell: status },
          ]} />
      )}
    </div>
  );
}
