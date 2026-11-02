// 8g Recalls: start (medicine + lots; owner: every branch, manager: own branches), detail with the stock per
// branch and its action (return to supplier = draft supplier return, or destroy = shrinkage "recalled"),
// affected sales, close, lift (owner, reason).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { QueryState } from '@/app/RouteError';
import { ApiErrorAlert, BranchTag, Button, Card, ConfirmDialog, DataTable, Dialog, EmptyState, Field, Input, PageHeader, ReasonDialog, SkeletonRows, StatusPill, TextArea, useToast } from '@/design';
import { date, dateTime } from '@/lib/format';
import { MedicinePicker, type Medicine } from '../shared/MedicinePicker';
import { toneOf, useMedicineNames } from '../shared/hooks';

export function RecallsPage() {
  const { t } = useTranslation(['stock', 'common', 'nav', 'sales']);
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [med, setMed] = useState<Medicine | null>(null);
  const [lots, setLots] = useState('');
  const [reason, setReason] = useState('');
  const [source, setSource] = useState('');
  const q = useQuery({ queryKey: ['inventory', 'recalls'], queryFn: () => call(api.inventory.GET('/api/inventory/v1/recalls')) });
  const names = useMedicineNames(q.data?.map((r) => r.medicine_id) ?? []);
  const start = useMutation({
    mutationFn: () => call(api.inventory.POST('/api/inventory/v1/recalls', { body: { medicine_id: med!.id, lot_nos: lots.split(',').map((x) => x.trim()).filter(Boolean), reason, source } })),
    onSuccess: (r) => nav(`/stock/recalls/${r.id}`),
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.stock')} title={t('recall.title')} actions={<Button variant="primary" onClick={() => setOpen(true)}>+ {t('recall.new')}</Button>} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} onRowClick={(r) => nav(`/stock/recalls/${r.id}`)} empty={<EmptyState title={t('recall.empty')} />}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
          { key: 'm', header: t('common:label.medicine'), cell: (r) => names(r.medicine_id) },
          { key: 'l', header: t('common:label.lot'), cell: (r) => r.lot_nos.join(', ') },
          { key: 'a', header: t('common:label.branches'), cell: (r) => (r.all_branches ? t('recall.allBranches') : '—') },
          { key: 'd', header: t('common:label.date'), cell: (r) => dateTime(r.created_at) },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`sales:status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
        ]} />
      <Dialog open={open} onClose={() => setOpen(false)} title={t('recall.new')} width={520}
        footer={<><Button onClick={() => setOpen(false)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!med || !lots.trim() || reason.trim().length < 3} loading={start.isPending} onClick={() => start.mutate()}>{t('recall.new')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('common:label.medicine')} required>{(id) => <MedicinePicker id={id} value={med} onChange={setMed} />}</Field>
          <Field label={t('recall.lots')} required>{(id) => <Input id={id} value={lots} onChange={(e) => setLots(e.target.value)} />}</Field>
          <Field label={t('common:label.reason')} required>{(id) => <TextArea id={id} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <Field label={t('recall.source')}>{(id) => <Input id={id} value={source} onChange={(e) => setSource(e.target.value)} />}</Field>
          <ApiErrorAlert error={start.error} />
        </div>
      </Dialog>
    </div>
  );
}

export function RecallDetailPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['stock', 'common', 'nav', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const { byId } = useBranch();
  const [dlg, setDlg] = useState<'' | 'close' | 'lift'>('');
  const q = useQuery({ queryKey: ['inventory', 'recall', id], queryFn: () => call(api.inventory.GET('/api/inventory/v1/recalls/{recall_id}', { params: { path: { recall_id: id } } })) });
  const r = q.data;
  const sold = useQuery({
    queryKey: ['sales', 'by-batches', r?.lines.map((l) => l.batch_id).join(',')],
    enabled: !!r && r.lines.length > 0 && user.has('sales.view'),
    queryFn: () => call(api.sales.GET('/api/sales/v1/invoices/by-batches', { params: { query: { batch_ids: [...new Set(r!.lines.map((l) => l.batch_id))] } } })),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['inventory'] });
  const act = useMutation({
    mutationFn: ({ line, kind }: { line: string; kind: 'return' | 'destroy' }) => kind === 'return'
      ? call(api.inventory.POST('/api/inventory/v1/recalls/{recall_id}/lines/{line_id}/return', { params: { path: { recall_id: id, line_id: line } } })).then((x) => x.number)
      : call(api.inventory.POST('/api/inventory/v1/recalls/{recall_id}/lines/{line_id}/destroy', { params: { path: { recall_id: id, line_id: line } }, body: {} })).then((x) => x.number),
    onSuccess: (n) => { toast.success(n); void refresh(); },
  });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!r) return <SkeletonRows />;
  const open = r.status === 'open' || r.status === 'active';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.stock')} / ${t('recall.title')}`} title={`${r.number} · ${r.sku}`}
        actions={<>
          {open && <Button onClick={() => setDlg('close')}>{t('recall.close')}</Button>}
          {user.isOwner && r.status !== 'lifted' && <Button variant="danger-outline" onClick={() => setDlg('lift')}>{t('recall.lift')}</Button>}
        </>}>
        <div className="flex flex-wrap items-center gap-2 text-[13px]"><StatusPill tone={toneOf(r.status)}>{t(`sales:status.${r.status}`, { defaultValue: r.status })}</StatusPill><span>{r.lot_nos.join(', ')} · {r.reason}{r.source ? ` · ${r.source}` : ''}</span></div>
      </PageHeader>
      <ApiErrorAlert error={act.error} />
      <Card title={t('recall.lines')} padded={false}>
        <DataTable className="rounded-none border-0" rows={r.lines} rowKey={(l) => l.id} columns={[
          { key: 'b', header: t('common:label.branch'), cell: (l) => <BranchTag code={byId(l.branch_id)?.code ?? '?'} /> },
          { key: 'l', header: t('common:label.lot'), cell: (l) => `${l.lot_no} · ${date(l.expiry_date)}` },
          { key: 's', header: t('recall.atStart'), align: 'right', cell: (l) => l.qty_at_start },
          { key: 'h', header: t('onHand.onHand'), align: 'right', cell: (l) => <b>{l.on_hand}</b> },
          { key: 't', header: t('recall.openTransfers'), align: 'right', cell: (l) => l.in_transit + l.on_open_transfers || '—' },
          { key: 'a', header: t('recall.action'), cell: (l) => (l.action && !['none', 'pending'].includes(l.action) ? `${l.action}${l.action_ref ? ` · ${l.action_ref}` : ''}` : open && l.on_hand > 0 ? (
            <span className="flex gap-1">
              <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ line: l.id, kind: 'return' })}>{t('recall.return')}</Button>
              <Button size="sm" variant="danger-outline" loading={act.isPending} onClick={() => act.mutate({ line: l.id, kind: 'destroy' })}>{t('recall.destroy')}</Button>
            </span>
          ) : '—') },
        ]} />
      </Card>
      {sold.data && (
        <Card title={t('recall.sales')} padded={false}>
          <DataTable className="rounded-none border-0" rows={sold.data} rowKey={(s) => s.invoice_id + s.batch_id} columns={[
            { key: 'n', header: t('sales:invoices.number'), cell: (s) => s.number },
            { key: 'd', header: t('common:label.date'), cell: (s) => dateTime(s.completed_at) },
            { key: 'q', header: t('recall.sold'), align: 'right', cell: (s) => s.qty_base },
            { key: 'c', header: t('common:label.customer'), cell: (s) => (s.customer ? `${s.customer.name} · ${s.customer.phone ?? ''}` : '—') },
            { key: 'p', header: t('common:label.name'), cell: (s) => (s.patient ? `${s.patient.name_en ?? s.patient.name_km ?? ''} · ${s.patient.prescription_number ?? ''}` : '—') },
          ]} />
        </Card>
      )}
      <ConfirmDialog open={dlg === 'close'} onClose={() => setDlg('')} title={t('recall.close')} confirmLabel={t('recall.close')}
        onConfirm={async () => { await call(api.inventory.POST('/api/inventory/v1/recalls/{recall_id}/close', { params: { path: { recall_id: id } } })); await refresh(); }} />
      <ReasonDialog open={dlg === 'lift'} onClose={() => setDlg('')} title={t('recall.lift')} body={t('recall.liftBody')} confirmLabel={t('recall.lift')}
        onConfirm={async (reason) => { await call(api.inventory.POST('/api/inventory/v1/recalls/{recall_id}/lift', { params: { path: { recall_id: id } }, body: { reason } })); await refresh(); }} />
    </div>
  );
}
