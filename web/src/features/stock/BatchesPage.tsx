// 8a Batches & expiry (+ value with cost permission), 8b release quarantine (pharmacist, inventory.adjust).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { InventoryS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, DataTable, Dialog, Field, Input, PageHeader, SafetyBadge, Select, StatusPill, TextArea, Usd, hasField, useToast } from '@/design';
import { date } from '@/lib/format';
import { usePaging } from '../shared/hooks';

type Batch = InventoryS['BatchItem'];

export default function BatchesPage() {
  const { t } = useTranslation(['stock', 'common', 'nav']);
  const user = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const { branchParam, oneBranch } = useBranch();
  const paging = usePaging();
  const [within, setWithin] = useState('90');
  const [rel, setRel] = useState<Batch | null>(null);
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const list = useQuery({
    queryKey: ['inventory', 'batches', branchParam, within, paging.page, paging.size],
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/batches', { params: { query: { branch_id: branchParam, expiring_within: within ? Number(within) : undefined, page: paging.page, size: paging.size } } })),
  });
  const release = useMutation({
    mutationFn: () => call(api.inventory.POST('/api/inventory/v1/quarantine/release', { body: { branch_id: rel!.branch_id ?? oneBranch!.id, batch_id: rel!.batch_id, qty_base: Number(qty), reason } })),
    onSuccess: () => { toast.success(t('batches.released')); setRel(null); void qc.invalidateQueries({ queryKey: ['inventory'] }); },
  });
  const rows = list.data?.items;
  const showCost = !!rows?.some((r) => hasField(r, 'value'));
  const canRelease = user.has('inventory.adjust') && user.is_pharmacist;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.stock')} title={t('batches.title')} />
      <DataTable
        toolbar={<Field label={t('batches.within')}>{(id) => (
          <Select id={id} value={within} onChange={(e) => { setWithin(e.target.value); paging.reset(); }}>
            {['30', '60', '90', '180'].map((d) => <option key={d} value={d}>{t('batches.days', { count: Number(d) })}</option>)}<option value="">{t('batches.any')}</option>
          </Select>
        )}</Field>}
        rows={rows} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(r) => r.batch_id + r.branch_id}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('common:label.medicine'), cell: (r) => <span className="flex flex-col"><span className="font-medium">{r.name}</span><span className="text-[12px] text-neutral-500">{r.sku}</span></span> },
          { key: 'l', header: t('common:label.lot'), cell: (r) => <span className="font-mono text-[12px]">{r.lot_no}</span> },
          { key: 'e', header: t('common:label.expiry'), cell: (r) => (
            <span className="flex items-center gap-1.5">{date(r.expiry_date)}
              {r.days_to_expiry < 0 ? <SafetyBadge kind="expired" /> : r.days_to_expiry <= 90 ? <SafetyBadge kind="near-expiry">{r.days_to_expiry}</SafetyBadge> : null}</span>
          ) },
          { key: 'h', header: t('onHand.onHand'), align: 'right', cell: (r) => <b>{r.qty_on_hand}</b> },
          { key: 'a', header: t('onHand.available'), align: 'right', cell: (r) => r.qty_available },
          { key: 'qq', header: t('onHand.quarantined'), align: 'right', cell: (r) => (r.qty_quarantined ? <SafetyBadge kind="quarantine">{r.qty_quarantined}</SafetyBadge> : '—') },
          ...(showCost ? [{ key: 'v', header: t('onHand.value'), align: 'right' as const, cell: (r: Batch) => <Usd value={r.value} /> }] : []),
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.status === 'active' ? 'success' : r.status === 'expired' || r.status === 'recalled' ? 'danger' : 'neutral'}>{t(`batches.status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
          { key: 'x', header: '', align: 'right', cell: (r) => canRelease && r.qty_quarantined > 0 && <Button size="sm" onClick={() => { setRel(r); setQty(String(r.qty_quarantined)); setReason(''); }}>{t('batches.release')}</Button> },
        ]} />
      <Dialog open={!!rel} onClose={() => setRel(null)} title={t('batches.release')} subtitle={rel ? `${rel.name} · ${rel.lot_no}` : undefined} width={460}
        footer={<><Button onClick={() => setRel(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!Number(qty) || !reason.trim()} loading={release.isPending} onClick={() => release.mutate()}>{t('batches.release')}</Button></>}>
        <div className="flex flex-col gap-3">
          <span className="text-[13px] text-neutral-700">{t('batches.releaseBody')}</span>
          <Field label={t('common:label.qty')} required>{(id) => <Input id={id} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ''))} />}</Field>
          <Field label={t('common:label.reason')} required>{(id) => <TextArea id={id} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <ApiErrorAlert error={release.error} />
        </div>
      </Dialog>
    </div>
  );
}
