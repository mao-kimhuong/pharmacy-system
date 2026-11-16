// Purchase orders: list; create (12j: supplier, lines with pack unit, qty, unit cost); detail (lines with
// received, send, cancel, PDF 17i, receive). Purchase prices only when the API sends them.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PurchasingS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { QueryState } from '@/app/RouteError';
import { ApiErrorAlert, BranchTag, Button, Card, ConfirmDialog, DataTable, DefinitionList, EmptyState, Field, Input, PageHeader, ReasonDialog, Select, SkeletonRows, StatusPill, TextArea, Usd, hasField, usePdf } from '@/design';
import { date, dateTime } from '@/lib/format';
import { LinesEditor, type EditLine } from '../shared/LinesEditor';
import { SupplierPicker, type Supplier } from '../shared/SupplierPicker';
import { toneOf, useMedicineNames, usePaging } from '../shared/hooks';

type PO = PurchasingS['POOut'];
const STATUSES = ['draft', 'sent', 'partially_received', 'received', 'cancelled'];

export default function OrdersPage() {
  const { t } = useTranslation(['purchase', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const { branchParam, byId } = useBranch();
  const paging = usePaging();
  const [status, setStatus] = useState('');
  const q = useQuery({
    queryKey: ['purchasing', 'pos', branchParam, status, paging.page, paging.size],
    queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/purchase-orders', { params: { query: { branch_id: branchParam, status: (status || undefined) as never, page: paging.page, size: paging.size } } })),
  });
  const showCost = !!q.data?.items.some((p) => hasField(p, 'total'));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.purchase')} title={t('po.title')} actions={user.has('purchasing.order') && <Button variant="primary" onClick={() => nav('/purchase/orders/new')}>+ {t('po.new')}</Button>} />
      <DataTable
        toolbar={<Select aria-label={t('common:label.status')} className="w-48" value={status} onChange={(e) => { setStatus(e.target.value); paging.reset(); }}><option value="">{t('common:label.all')}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`po.status.${s}`)}</option>)}</Select>}
        rows={q.data?.items} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(p) => p.id} onRowClick={(p) => nav(`/purchase/orders/${p.id}`)}
        empty={<EmptyState title={t('po.empty')} />}
        paging={{ page: paging.page, size: paging.size, total: q.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (p) => <span className="font-mono text-[12px]">{p.number}</span> },
          { key: 'b', header: t('common:label.branch'), cell: (p) => <BranchTag code={byId(p.branch_id)?.code ?? '?'} /> },
          { key: 's', header: t('common:label.supplier'), cell: (p) => p.supplier.name },
          { key: 'e', header: t('po.expected'), cell: (p) => date(p.expected_on) },
          ...(showCost ? [{ key: 't', header: t('common:label.total'), align: 'right' as const, cell: (p: PO) => <Usd value={p.total} strong /> }] : []),
          { key: 'd', header: t('common:label.createdAt'), cell: (p) => dateTime(p.created_at) },
          { key: 'st', header: t('common:label.status'), cell: (p) => <StatusPill tone={toneOf(p.status)}>{t(`po.status.${p.status}`)}</StatusPill> },
        ]} />
    </div>
  );
}

export function NewOrderPage() {
  const { t } = useTranslation(['purchase', 'common', 'nav']);
  const nav = useNavigate();
  const { oneBranch } = useBranch();
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [lines, setLines] = useState<EditLine[]>([]);
  const [expected, setExpected] = useState('');
  const [note, setNote] = useState('');
  const m = useMutation({
    mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/purchase-orders', { body: { branch_id: oneBranch!.id, supplier_id: supplier!.id, note, expected_on: expected || null,
      lines: lines.map((l) => ({ medicine_id: l.medicine.id, pack_unit_id: l.pack_unit_id, qty: l.qty, unit_cost: l.extra?.cost ?? '' })) } })),
    onSuccess: (po) => nav(`/purchase/orders/${po.id}`),
  });
  const ok = supplier && lines.length > 0 && lines.every((l) => l.qty > 0 && Number(l.extra?.cost) >= 0 && l.extra?.cost);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.purchase')} / ${t('po.title')}`} title={t('po.new')} actions={<Button variant="primary" disabled={!ok} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button>} />
      <Card>
        <div className="grid gap-3 tablet:grid-cols-3">
          <Field label={t('common:label.supplier')} required>{(id) => <SupplierPicker id={id} value={supplier} onChange={setSupplier} autoFocus />}</Field>
          <Field label={t('po.expected')}>{(id) => <Input id={id} type="date" value={expected} onChange={(e) => setExpected(e.target.value)} />}</Field>
          <Field label={t('common:label.notes')}>{(id) => <TextArea id={id} rows={1} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        </div>
      </Card>
      <Card><LinesEditor lines={lines} onChange={setLines} filter={(x) => x.kind !== 'hamper'}
        extraColumns={[{ key: 'cost', header: t('pr.unitCost'), width: '140px', render: (l, set) => <Input aria-label={t('pr.unitCost')} inputMode="decimal" className="text-right" value={l.extra?.cost ?? ''} onChange={(e) => set(e.target.value.replace(/[^\d.]/g, ''))} /> }]} /></Card>
      <ApiErrorAlert error={m.error} />
    </div>
  );
}

export function OrderDetailPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['purchase', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const pdf = usePdf();
  const { byId } = useBranch();
  const [dlg, setDlg] = useState<'' | 'send' | 'cancel'>('');
  const q = useQuery({ queryKey: ['purchasing', 'po', id], queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/purchase-orders/{po_id}', { params: { path: { po_id: id } } })) });
  const po = q.data;
  const names = useMedicineNames(po?.lines.map((l) => l.medicine_id) ?? []);
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!po) return <SkeletonRows />;
  const showCost = hasField(po, 'total');
  const refresh = () => qc.invalidateQueries({ queryKey: ['purchasing'] });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.purchase')} / ${t('po.title')}`} title={po.number}
        actions={<>
          <Button onClick={() => pdf.open({ type: 'purchase_order', purchase_order_id: po.id }, po.number, `${po.number}.pdf`)}>{t('po.print')}</Button>
          {po.group_id && <Button onClick={() => nav(`/purchase/groups/${po.group_id}`)}>{t('po.group')}</Button>}
          {po.status === 'draft' && user.has('purchasing.order') && <Button variant="primary" onClick={() => setDlg('send')}>{t('po.send')}</Button>}
          {['sent', 'partially_received'].includes(po.status) && user.has('purchasing.receive') && <Button variant="primary" onClick={() => nav(`/purchase/receiving?po=${po.id}`)}>{t('po.receive')}</Button>}
          {['draft', 'sent'].includes(po.status) && user.has('purchasing.order') && <Button variant="danger-outline" onClick={() => setDlg('cancel')}>{t('po.cancel')}</Button>}
        </>}>
        <StatusPill tone={toneOf(po.status)}>{t(`po.status.${po.status}`)}</StatusPill>
      </PageHeader>
      <div className="grid gap-4 desktop:grid-cols-[2fr_1fr]">
        <Card padded={false} title={t('common:label.lines')}>
          <DataTable className="rounded-none border-0" rows={po.lines} rowKey={(l) => l.id} columns={[
            { key: 'm', header: t('common:label.medicine'), cell: (l) => names(l.medicine_id) },
            { key: 'q', header: t('po.ordered'), align: 'right', cell: (l) => `${l.qty} × ${l.qty_in_base}` },
            { key: 'r', header: t('po.received'), align: 'right', cell: (l) => `${l.qty_received_base} / ${l.qty_base}` },
            ...(showCost ? [{ key: 'c', header: t('pr.unitCost'), align: 'right' as const, cell: (l: PO['lines'][number]) => <Usd value={l.unit_cost} /> },
              { key: 't', header: t('po.lineTotal'), align: 'right' as const, cell: (l: PO['lines'][number]) => <Usd value={l.line_total} strong />, footer: <Usd value={po.total} strong /> }] : []),
          ]} />
        </Card>
        <Card title={t('common:label.summary')}>
          <DefinitionList cols={1} items={[
            { label: t('common:label.branch'), value: <BranchTag code={byId(po.branch_id)?.code ?? '?'} /> },
            { label: t('common:label.supplier'), value: po.supplier.name },
            { label: t('po.expected'), value: date(po.expected_on) },
            ...(po.supplier_confirmed_at ? [{ label: t('po.supplierConfirmed'), value: `${po.supplier_confirmed_by ?? ''} · ${dateTime(po.supplier_confirmed_at)}` }] : []),
            { label: t('common:label.notes'), value: po.note || '—' },
            ...(po.cancel_reason ? [{ label: t('common:label.reason'), value: po.cancel_reason }] : []),
          ]} />
        </Card>
      </div>
      <ConfirmDialog open={dlg === 'send'} onClose={() => setDlg('')} title={t('po.send')} confirmLabel={t('po.send')} onConfirm={async () => { await call(api.purchasing.POST('/api/purchasing/v1/purchase-orders/{po_id}/send', { params: { path: { po_id: id } } })); await refresh(); }} />
      <ReasonDialog open={dlg === 'cancel'} onClose={() => setDlg('')} title={t('po.cancel')} confirmLabel={t('po.cancel')} onConfirm={async (reason) => { await call(api.purchasing.POST('/api/purchasing/v1/purchase-orders/{po_id}/cancel', { params: { path: { po_id: id } }, body: { reason } })); await refresh(); }} />
      {pdf.element}
    </div>
  );
}

export function GroupPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['purchase', 'common', 'nav']);
  const nav = useNavigate();
  const pdf = usePdf();
  const { byId } = useBranch();
  const q = useQuery({ queryKey: ['purchasing', 'group', id], queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/po-groups/{group_id}', { params: { path: { group_id: id } } })) });
  if (q.error) return <QueryState error={q.error} />;
  const g = q.data;
  if (!g) return <SkeletonRows />;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.purchase')} / ${t('po.title')}`} title={g.number}
        actions={<Button onClick={() => pdf.open({ type: 'purchase_order_group', group_id: g.id }, g.number, `${g.number}.pdf`)}>{t('po.groupPdf')}</Button>} />
      <DataTable rows={g.purchase_orders ?? []} rowKey={(p) => p.id} onRowClick={(p) => nav(`/purchase/orders/${p.id}`)} columns={[
        { key: 'n', header: t('common:label.number'), cell: (p) => <span className="font-mono text-[12px]">{p.number}</span> },
        { key: 'b', header: t('common:label.branch'), cell: (p) => <BranchTag code={byId(p.branch_id)?.code ?? '?'} /> },
        { key: 'l', header: t('common:label.lines'), align: 'right', cell: (p) => p.lines.length },
        { key: 't', header: t('common:label.total'), align: 'right', cell: (p) => (hasField(p, 'total') ? <Usd value={p.total} /> : '—') },
        { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={toneOf(p.status)}>{t(`po.status.${p.status}`)}</StatusPill> },
      ]} />
      {pdf.element}
    </div>
  );
}
