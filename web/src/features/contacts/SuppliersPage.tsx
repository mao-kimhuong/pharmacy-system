// 12l Suppliers (+ groups tab is its own page) and 12d supplier detail: balance (owed / overdue per branch),
// statement, bills, payments, purchase orders, returns; edit, deactivate with a reason.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PurchasingS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { QueryState } from '@/app/RouteError';
import { Alert, ApiErrorAlert, BranchTag, Button, Card, Checkbox, DataTable, DefinitionList, Dialog, Field, Input, PageHeader, ReasonDialog, Select, SkeletonRows, StatusPill, Tabs, Usd, hasField, useDebounced } from '@/design';
import { date, dateTime } from '@/lib/format';
import { PayDialog } from '../purchase/PaymentsPage';
import { toneOf, usePaging } from '../shared/hooks';

type Supplier = PurchasingS['SupplierOut'];

function SupplierForm({ initial, onClose }: { initial: Supplier | null; onClose: () => void }) {
  const { t, i18n } = useTranslation(['contacts', 'common']);
  const qc = useQueryClient();
  const [v, setV] = useState({ code: initial?.code ?? '', name: initial?.name ?? '', name_km: initial?.name_km ?? '', phone: initial?.phone ?? '', address: initial?.address ?? '', payment_terms_days: String(initial?.payment_terms_days ?? 30), group_id: initial?.group?.id ?? '' });
  const groups = useQuery({ queryKey: ['contacts', 'supplier', 'groups'], queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/supplier-groups')) });
  const m = useMutation({
    mutationFn: () => {
      const { code, ...rest } = { ...v, payment_terms_days: Number(v.payment_terms_days) || 0, group_id: v.group_id || null };
      return initial ? call(api.purchasing.PATCH('/api/purchasing/v1/suppliers/{supplier_id}', { params: { path: { supplier_id: initial.id } }, body: rest })) : call(api.purchasing.POST('/api/purchasing/v1/suppliers', { body: { code, ...rest } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['purchasing'] }); onClose(); },
  });
  return (
    <Dialog open onClose={onClose} title={initial ? t('common:action.edit') : t('suppliers.new')} width={600}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!v.code || !v.name} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('suppliers.code')} required>{(id) => <Input id={id} disabled={!!initial} value={v.code} onChange={(e) => setV({ ...v, code: e.target.value.toUpperCase() })} autoFocus />}</Field>
        <Field label={t('common:label.name')} required>{(id) => <Input id={id} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={v.name_km} onChange={(e) => setV({ ...v, name_km: e.target.value })} />}</Field>
        <Field label={t('common:label.phone')}>{(id) => <Input id={id} value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />}</Field>
        <Field label={t('common:label.address')} className="col-span-2">{(id) => <Input id={id} value={v.address} onChange={(e) => setV({ ...v, address: e.target.value })} />}</Field>
        <Field label={t('suppliers.terms')}>{(id) => <Input id={id} inputMode="numeric" value={v.payment_terms_days} onChange={(e) => setV({ ...v, payment_terms_days: e.target.value.replace(/\D/g, '') })} />}</Field>
        <Field label={t('customers.group')}>{(id) => <Select id={id} value={v.group_id} onChange={(e) => setV({ ...v, group_id: e.target.value })}><option value="">—</option>{groups.data?.filter((g) => g.is_active).map((g) => <option key={g.id} value={g.id}>{i18n.language === 'km' && g.name_km ? g.name_km : g.name_en}</option>)}</Select>}</Field>
        <ApiErrorAlert error={m.error} className="col-span-2" />
      </div>
    </Dialog>
  );
}

export default function SuppliersPage() {
  const { t, i18n } = useTranslation(['contacts', 'common', 'nav', 'sales']);
  const nav = useNavigate();
  const paging = usePaging();
  const [q, setQ] = useState('');
  const [inactive, setInactive] = useState(false);
  const [neu, setNeu] = useState(false);
  const dq = useDebounced(q.trim());
  const list = useQuery({ queryKey: ['purchasing', 'suppliers', dq, inactive, paging.page], queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/suppliers', { params: { query: { q: dq || undefined, include_inactive: inactive, page: paging.page, size: paging.size } } })) });
  const km = i18n.language === 'km';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.contacts')} title={t('suppliers.title')} actions={<Button variant="primary" onClick={() => setNeu(true)}>+ {t('suppliers.new')}</Button>} />
      <DataTable toolbar={<><Input aria-label={t('common:action.search')} placeholder={`⌕ ${t('common:action.search')}`} className="w-72" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />
        <Checkbox label={t('common:label.inactive')} checked={inactive} onChange={(e) => setInactive(e.target.checked)} /></>}
        rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(s) => s.id} onRowClick={(s) => nav(`/contacts/suppliers/${s.id}`)}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage }}
        columns={[
          { key: 'c', header: t('suppliers.code'), cell: (s) => <span className="font-mono text-[12px]">{s.code}</span> },
          { key: 'n', header: t('common:label.name'), cell: (s) => (km && s.name_km ? s.name_km : s.name) },
          { key: 'p', header: t('common:label.phone'), cell: (s) => s.phone || '—' },
          { key: 'g', header: t('customers.group'), cell: (s) => (s.group ? (km && s.group.name_km ? s.group.name_km : s.group.name_en) : '—') },
          { key: 't', header: t('suppliers.terms'), align: 'right', cell: (s) => s.payment_terms_days },
          { key: 's', header: t('common:label.status'), cell: (s) => <StatusPill tone={s.is_active ? 'success' : 'neutral'}>{s.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
        ]} />
      {neu && <SupplierForm initial={null} onClose={() => setNeu(false)} />}
    </div>
  );
}

export function SupplierDetailPage() {
  const { id = '' } = useParams();
  const { t, i18n } = useTranslation(['contacts', 'common', 'nav', 'sales', 'purchase']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { byId } = useBranch();
  const [tab, setTab] = useState<'bills' | 'statement' | 'payments' | 'orders' | 'returns'>('bills');
  const [edit, setEdit] = useState(false);
  const [deact, setDeact] = useState(false);
  const [pay, setPay] = useState(false);
  const q = useQuery({ queryKey: ['purchasing', 'supplier', id], queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/suppliers/{supplier_id}', { params: { path: { supplier_id: id } } })) });
  const seeMoney = user.has('purchasing.order', 'purchasing.pay', 'finance.cost_profit');
  const bal = useQuery({ queryKey: ['purchasing', 'balance', id], enabled: seeMoney, queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/suppliers/{supplier_id}/balance', { params: { path: { supplier_id: id } } })) });
  const bills = useQuery({ queryKey: ['purchasing', 'receipts', 'of', id], enabled: tab === 'bills', queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/receipts', { params: { query: { supplier_id: id, size: 100 } } })) });
  const stmt = useQuery({ queryKey: ['purchasing', 'statement', id], enabled: tab === 'statement' && seeMoney, queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/suppliers/{supplier_id}/statement', { params: { path: { supplier_id: id } } })) });
  const pays = useQuery({ queryKey: ['purchasing', 'payments', 'of', id], enabled: tab === 'payments', queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/supplier-payments', { params: { query: { supplier_id: id, size: 100 } } })) });
  const pos = useQuery({ queryKey: ['purchasing', 'pos', 'of', id], enabled: tab === 'orders', queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/purchase-orders', { params: { query: { supplier_id: id, size: 100 } } })) });
  const rets = useQuery({ queryKey: ['purchasing', 'sreturns', 'all'], enabled: tab === 'returns', queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/supplier-returns')) });
  const activate = useMutation({ mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/suppliers/{supplier_id}/activate', { params: { path: { supplier_id: id } } })), onSuccess: () => void qc.invalidateQueries({ queryKey: ['purchasing'] }) });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  const s = q.data;
  if (!s) return <SkeletonRows />;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.contacts')} / ${t('suppliers.title')}`} title={i18n.language === 'km' && s.name_km ? s.name_km : s.name}
        actions={<>
          {user.has('purchasing.pay') && <Button variant="primary" onClick={() => setPay(true)}>{t('purchase:pay.new')}</Button>}
          <Button onClick={() => setEdit(true)}>{t('common:action.edit')}</Button>
          {s.is_active ? <Button onClick={() => setDeact(true)}>{t('common:action.deactivate')}</Button> : <Button onClick={() => activate.mutate()}>{t('common:action.activate')}</Button>}
        </>} />
      <Card>
        <DefinitionList cols={4} items={[
          { label: t('suppliers.code'), value: s.code },
          { label: t('common:label.phone'), value: s.phone || '—' },
          { label: t('suppliers.terms'), value: s.payment_terms_days },
          { label: t('common:label.address'), value: s.address || '—' },
          ...(bal.data ? [{ label: t('suppliers.owed'), value: <Usd value={bal.data.owed} strong /> }, { label: t('suppliers.overdue'), value: <Usd value={bal.data.overdue} /> }] : []),
        ]} />
        {bal.data && bal.data.branches.length > 1 && <div className="mt-3 flex flex-wrap gap-3 text-[12px]">{bal.data.branches.map((b) => <span key={b.branch_id} className="flex items-center gap-1"><BranchTag code={byId(b.branch_id)?.code ?? '?'} /><Usd value={b.owed} /></span>)}</div>}
      </Card>
      <Alert tone="info">{t('suppliers.hidden')}</Alert>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: 'bills', label: t('suppliers.bills') }, ...(seeMoney ? [{ value: 'statement' as const, label: t('detail.statement') }] : []), { value: 'payments', label: t('detail.payments') }, { value: 'orders', label: t('suppliers.orders') }, { value: 'returns', label: t('suppliers.returns') }]} />
      {tab === 'bills' && <DataTable rows={bills.data?.items} loading={bills.isLoading} error={bills.error} rowKey={(r) => r.id} columns={[
        { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
        { key: 'b', header: t('common:label.branch'), cell: (r) => <BranchTag code={byId(r.branch_id)?.code ?? '?'} /> },
        { key: 'd', header: t('common:label.date'), cell: (r) => dateTime(r.received_at) },
        { key: 'due', header: t('purchase:receipts.due'), cell: (r) => date(r.due_on) },
        ...(bills.data?.items.some((r) => hasField(r, 'total')) ? [{ key: 't', header: t('common:label.total'), align: 'right' as const, cell: (r: PurchasingS['ReceiptOut']) => <Usd value={r.total} /> }, { key: 'bal', header: t('purchase:receipts.balance'), align: 'right' as const, cell: (r: PurchasingS['ReceiptOut']) => <Usd value={r.balance} strong /> }] : []),
        { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.status === 'paid' ? 'success' : 'warning'}>{t(`sales:status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
      ]} />}
      {tab === 'statement' && <DataTable rows={stmt.data?.entries} loading={stmt.isLoading} error={stmt.error} rowKey={(e, i) => e.number + i} columns={[
        { key: 'd', header: t('common:label.date'), cell: (e) => date(e.on) },
        { key: 'k', header: t('detail.kind'), cell: (e) => e.kind },
        { key: 'n', header: t('detail.doc'), cell: (e) => <span className="font-mono text-[12px]">{e.number}</span> },
        { key: 'dr', header: t('detail.debit'), align: 'right', cell: (e) => (Number(e.debit) ? <Usd value={e.debit} /> : '') },
        { key: 'cr', header: t('detail.credit'), align: 'right', cell: (e) => (Number(e.credit) ? <Usd value={e.credit} /> : '') },
        { key: 'b', header: t('common:label.balance'), align: 'right', cell: (e) => <Usd value={e.balance} strong /> },
      ]} />}
      {tab === 'payments' && <DataTable rows={pays.data?.items} loading={pays.isLoading} error={pays.error} rowKey={(p) => p.id} columns={[
        { key: 'n', header: t('common:label.number'), cell: (p) => <span className="font-mono text-[12px]">{p.number}</span> },
        { key: 'd', header: t('purchase:pay.paidOn'), cell: (p) => date(p.paid_on) },
        { key: 'a', header: t('common:label.amount'), align: 'right', cell: (p) => <Usd value={p.amount} strong /> },
        { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={p.status === 'posted' ? 'success' : 'cancelled'}>{t(`sales:status.${p.status}`, { defaultValue: p.status })}</StatusPill> },
      ]} />}
      {tab === 'orders' && <DataTable rows={pos.data?.items} loading={pos.isLoading} error={pos.error} rowKey={(p) => p.id} onRowClick={(p) => nav(`/purchase/orders/${p.id}`)} columns={[
        { key: 'n', header: t('common:label.number'), cell: (p) => <span className="font-mono text-[12px]">{p.number}</span> },
        { key: 'd', header: t('common:label.date'), cell: (p) => dateTime(p.created_at) },
        { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={toneOf(p.status)}>{t(`purchase:po.status.${p.status}`)}</StatusPill> },
      ]} />}
      {tab === 'returns' && <DataTable rows={rets.data?.filter((r) => r.supplier_id === id)} loading={rets.isLoading} error={rets.error} rowKey={(r) => r.id} columns={[
        { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
        { key: 'r', header: t('common:label.reason'), cell: (r) => t(`purchase:sret.reason.${r.reason}`, { defaultValue: r.reason }) },
        { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`sales:status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
      ]} />}
      {edit && <SupplierForm initial={s} onClose={() => setEdit(false)} />}
      {pay && <PayDialog open onClose={() => setPay(false)} supplierPre={s} />}
      <ReasonDialog open={deact} onClose={() => setDeact(false)} title={t('common:confirm.deactivateTitle', { name: s.name })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => { await call(api.purchasing.POST('/api/purchasing/v1/suppliers/{supplier_id}/deactivate', { params: { path: { supplier_id: id } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['purchasing'] }); }} />
      <ApiErrorAlert error={activate.error} />
    </div>
  );
}
