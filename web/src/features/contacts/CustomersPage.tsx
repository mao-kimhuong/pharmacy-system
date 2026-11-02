// 12b Customers: search, group filter, balance and credit left (only when the API sends them), new customer
// (credit limit only with customers.credit_limit). 12c detail with unpaid invoices, statement (+ PDF in km/en),
// deposits, payments; edit, deactivate with a reason.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CustomersS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { QueryState } from '@/app/RouteError';
import { Alert, ApiErrorAlert, BranchTag, Button, Card, Checkbox, DataTable, DefinitionList, Dialog, Field, Input, PageHeader, ReasonDialog, Select, SkeletonRows, StatusPill, Tabs, TextArea, Usd, hasField, useDebounced, usePdf } from '@/design';
import { addDays, date, dateTime, daysUntil, todayIso } from '@/lib/format';
import { usePaging } from '../shared/hooks';

type Customer = CustomersS['CustomerOut'];
interface Form { phone: string; name: string; name_km: string; group_id: string; credit_limit: string; note: string }

function CustomerForm({ initial, onClose }: { initial: Customer | null; onClose: () => void }) {
  const { t, i18n } = useTranslation(['contacts', 'common']);
  const user = useUser();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [v, setV] = useState<Form>({ phone: initial?.phone ?? '', name: initial?.name ?? '', name_km: initial?.name_km ?? '', group_id: initial?.group?.id ?? '', credit_limit: initial?.credit_limit ?? '0', note: initial?.note ?? '' });
  const groups = useQuery({ queryKey: ['contacts', 'customer', 'groups'], queryFn: () => call(api.customers.GET('/api/customers/v1/customer-groups')) });
  const canLimit = user.has('customers.credit_limit');
  const m = useMutation({
    mutationFn: () => {
      const body = { phone: v.phone, name: v.name, name_km: v.name_km, group_id: v.group_id || null, note: v.note, ...(canLimit ? { credit_limit: v.credit_limit || '0' } : {}) };
      return initial ? call(api.customers.PATCH('/api/customers/v1/customers/{customer_id}', { params: { path: { customer_id: initial.id } }, body })) : call(api.customers.POST('/api/customers/v1/customers', { body }));
    },
    onSuccess: (c) => { void qc.invalidateQueries({ queryKey: ['customers'] }); onClose(); if (!initial) nav(`/contacts/customers/${c.id}`); },
  });
  return (
    <Dialog open onClose={onClose} title={initial ? t('common:action.edit') : t('customers.new')} width={560}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!v.name || !v.phone} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('common:label.name')} required>{(id) => <Input id={id} autoFocus value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={v.name_km} onChange={(e) => setV({ ...v, name_km: e.target.value })} />}</Field>
        <Field label={t('common:label.phone')} required>{(id) => <Input id={id} type="tel" prefix="+855" value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />}</Field>
        <Field label={t('customers.group')}>{(id) => <Select id={id} value={v.group_id} onChange={(e) => setV({ ...v, group_id: e.target.value })}><option value="">—</option>{groups.data?.filter((g) => g.is_active).map((g) => <option key={g.id} value={g.id}>{i18n.language === 'km' && g.name_km ? g.name_km : g.name_en}</option>)}</Select>}</Field>
        <Field label={t('customers.limit')} hint={canLimit ? undefined : t('customers.limitPerm')}>{(id, d) => <Input id={id} aria-describedby={d} prefix="$" inputMode="decimal" disabled={!canLimit} value={v.credit_limit} onChange={(e) => setV({ ...v, credit_limit: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
        <Field label={t('customers.note')} className="col-span-2">{(id) => <TextArea id={id} rows={2} value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />}</Field>
        <ApiErrorAlert error={m.error} className="col-span-2" />
      </div>
    </Dialog>
  );
}

export default function CustomersPage() {
  const { t, i18n } = useTranslation(['contacts', 'common', 'nav', 'sales']);
  const nav = useNavigate();
  const paging = usePaging();
  const [q, setQ] = useState('');
  const [group, setGroup] = useState('');
  const [inactive, setInactive] = useState(false);
  const [neu, setNeu] = useState(false);
  const dq = useDebounced(q.trim());
  const groups = useQuery({ queryKey: ['contacts', 'customer', 'groups'], queryFn: () => call(api.customers.GET('/api/customers/v1/customer-groups')) });
  const list = useQuery({
    queryKey: ['customers', 'list', dq, group, inactive, paging.page, paging.size],
    queryFn: () => call(api.customers.GET('/api/customers/v1/customers', { params: { query: { q: dq || undefined, group_id: group || undefined, include_inactive: inactive, page: paging.page, size: paging.size } } })),
  });
  const showBal = !!list.data?.items.some((c) => hasField(c, 'balance'));
  const km = i18n.language === 'km';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.contacts')} title={t('customers.title')} actions={<Button variant="primary" onClick={() => setNeu(true)}>+ {t('customers.new')}</Button>}>
        <span className="text-[12px] text-neutral-500">{t('customers.listHidden')}</span>
      </PageHeader>
      <DataTable
        toolbar={<>
          <Input aria-label={t('customers.search')} placeholder={`⌕ ${t('customers.search')}`} className="w-72" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />
          <Select aria-label={t('customers.group')} className="w-48" value={group} onChange={(e) => { setGroup(e.target.value); paging.reset(); }}><option value="">{t('customers.group')}: {t('common:label.all')}</option>{groups.data?.map((g) => <option key={g.id} value={g.id}>{km && g.name_km ? g.name_km : g.name_en}</option>)}</Select>
          <Checkbox label={t('common:label.inactive')} checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
        </>}
        rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(c) => c.id} onRowClick={(c) => nav(`/contacts/customers/${c.id}`)}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('common:label.name'), cell: (c) => <span className="flex flex-col"><span className="font-medium">{km && c.name_km ? c.name_km : c.name}</span><span className="text-[12px] text-neutral-500">{km ? c.name : c.name_km}</span></span> },
          { key: 'p', header: t('common:label.phone'), cell: (c) => c.phone },
          { key: 'g', header: t('customers.group'), cell: (c) => (c.group ? (km && c.group.name_km ? c.group.name_km : c.group.name_en) : '—') },
          { key: 'l', header: t('customers.limit'), align: 'right', cell: (c) => <Usd value={c.credit_limit} /> },
          ...(showBal ? [
            { key: 'b', header: t('customers.balance'), align: 'right' as const, cell: (c: Customer) => <Usd value={c.balance} strong /> },
            { key: 'a', header: t('customers.available'), align: 'right' as const, cell: (c: Customer) => <Usd value={c.available_credit} /> },
          ] : []),
          { key: 's', header: t('common:label.status'), cell: (c) => <StatusPill tone={c.is_active ? 'success' : 'neutral'}>{c.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
        ]} />
      {neu && <CustomerForm initial={null} onClose={() => setNeu(false)} />}
    </div>
  );
}

export function CustomerDetailPage() {
  const { id = '' } = useParams();
  const { t, i18n } = useTranslation(['contacts', 'common', 'nav', 'sales', 'pos']);
  const qc = useQueryClient();
  const pdf = usePdf();
  const { byId } = useBranch();
  const [tab, setTab] = useState<'unpaid' | 'statement' | 'deposits' | 'payments'>('unpaid');
  const [edit, setEdit] = useState(false);
  const [deact, setDeact] = useState(false);
  const [from, setFrom] = useState(addDays(todayIso(), -90));
  const [to, setTo] = useState(todayIso());
  const q = useQuery({ queryKey: ['customers', 'customer', id], queryFn: () => call(api.customers.GET('/api/customers/v1/customers/{customer_id}', { params: { path: { customer_id: id } } })) });
  const unpaid = useQuery({ queryKey: ['customers', 'unpaid', id], enabled: tab === 'unpaid', queryFn: () => call(api.customers.GET('/api/customers/v1/customers/{customer_id}/unpaid', { params: { path: { customer_id: id } } })) });
  const statement = useQuery({ queryKey: ['customers', 'statement', id, from, to], enabled: tab === 'statement', queryFn: () => call(api.customers.GET('/api/customers/v1/customers/{customer_id}/statement', { params: { path: { customer_id: id }, query: { from, to } } })) });
  const deposits = useQuery({ queryKey: ['customers', 'deposits', id], enabled: tab === 'deposits', queryFn: () => call(api.customers.GET('/api/customers/v1/customers/{customer_id}/deposits', { params: { path: { customer_id: id } } })) });
  const payments = useQuery({ queryKey: ['customers', 'payments', id], enabled: tab === 'payments', queryFn: () => call(api.customers.GET('/api/customers/v1/customer-payments', { params: { query: { customer_id: id, size: 100 } } })) });
  const activate = useMutation({ mutationFn: () => call(api.customers.POST('/api/customers/v1/customers/{customer_id}/activate', { params: { path: { customer_id: id } } })), onSuccess: () => void qc.invalidateQueries({ queryKey: ['customers'] }) });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  const c = q.data;
  if (!c) return <SkeletonRows />;
  const km = i18n.language === 'km';
  const lang = (km ? 'km' : 'en') as 'km' | 'en';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.contacts')} / ${t('customers.title')}`} title={km && c.name_km ? c.name_km : c.name}
        actions={<>
          <Button onClick={() => pdf.open({ type: 'customer_statement', customer_id: c.id, date_from: from, date_to: to, lang }, t('detail.pdf'), `statement-${c.phone}.pdf`)}>{t('detail.pdf')}</Button>
          <Button onClick={() => setEdit(true)}>{t('common:action.edit')}</Button>
          {c.is_active ? <Button onClick={() => setDeact(true)}>{t('common:action.deactivate')}</Button> : <Button onClick={() => activate.mutate()}>{t('common:action.activate')}</Button>}
        </>}>
        {!c.is_active && <StatusPill tone="neutral">{t('sales:status.inactive')}</StatusPill>}
      </PageHeader>
      <Card>
        <DefinitionList cols={4} items={[
          { label: t('common:label.phone'), value: c.phone },
          { label: t('customers.group'), value: c.group ? (km && c.group.name_km ? c.group.name_km : c.group.name_en) : '—' },
          { label: t('customers.limit'), value: <Usd value={c.credit_limit} /> },
          ...(hasField(c, 'balance') ? [{ label: t('customers.balance'), value: <Usd value={c.balance} strong /> }, { label: t('customers.available'), value: <Usd value={c.available_credit} /> }] : []),
          { label: t('customers.note'), value: c.note || '—' },
        ]} />
      </Card>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: 'unpaid', label: t('detail.unpaid') }, { value: 'statement', label: t('detail.statement') }, { value: 'deposits', label: t('detail.deposits') }, { value: 'payments', label: t('detail.payments') }]} />
      {tab === 'unpaid' && (<>
        <span className="text-[12px] text-neutral-500">{t('detail.agingNote')}</span>
        <DataTable rows={unpaid.data} loading={unpaid.isLoading} error={unpaid.error} rowKey={(d) => d.invoice_id} columns={[
          { key: 'n', header: t('sales:invoices.number'), cell: (d) => <span className="font-mono text-[12px]">{d.invoice_no}</span> },
          { key: 'b', header: t('common:label.branch'), cell: (d) => <BranchTag code={byId(d.branch_id)?.code ?? '?'} /> },
          { key: 'd', header: t('common:label.date'), cell: (d) => dateTime(d.created_at) },
          { key: 'age', header: t('detail.age'), align: 'right', cell: (d) => -daysUntil(d.created_at.slice(0, 10)) },
          { key: 'a', header: t('common:label.amount'), align: 'right', cell: (d) => <Usd value={d.amount} /> },
          { key: 'p', header: t('common:label.paid'), align: 'right', cell: (d) => <Usd value={d.paid} /> },
          { key: 'r', header: t('detail.reduced'), align: 'right', cell: (d) => <Usd value={d.reduced} /> },
          { key: 'u', header: t('detail.due'), align: 'right', cell: (d) => <Usd value={d.due} strong /> },
        ]} />
      </>)}
      {tab === 'statement' && (
        <DataTable toolbar={<>
          <Field label={t('common:label.from')}>{(fid) => <Input id={fid} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
          <Field label={t('common:label.to')}>{(fid) => <Input id={fid} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
          {statement.data && <span className="ml-auto text-[13px]">{t('detail.opening')}: <Usd value={statement.data.opening_balance} /> · {t('detail.closing')}: <Usd value={statement.data.closing_balance} strong /></span>}
        </>} rows={statement.data?.entries} loading={statement.isLoading} error={statement.error} rowKey={(e, i) => `${e.document_no}${i}`} columns={[
          { key: 'd', header: t('common:label.date'), cell: (e) => date(e.on) },
          { key: 'k', header: t('detail.kind'), cell: (e) => e.kind },
          { key: 'n', header: t('detail.doc'), cell: (e) => <span className="font-mono text-[12px]">{e.document_no}</span> },
          { key: 'dr', header: t('detail.debit'), align: 'right', cell: (e) => (Number(e.debit) ? <Usd value={e.debit} /> : '') },
          { key: 'cr', header: t('detail.credit'), align: 'right', cell: (e) => (Number(e.credit) ? <Usd value={e.credit} /> : '') },
          { key: 'b', header: t('common:label.balance'), align: 'right', cell: (e) => <Usd value={e.balance} strong /> },
        ]} />
      )}
      {tab === 'deposits' && (
        <DataTable rows={deposits.data} loading={deposits.isLoading} error={deposits.error} rowKey={(d) => d.deposit_id} columns={[
          { key: 'n', header: t('detail.doc'), cell: (d) => d.document_no || d.ref },
          { key: 'm', header: t('common:label.method'), cell: (d) => `${d.method} · ${d.currency}` },
          { key: 'a', header: t('common:label.amount'), align: 'right', cell: (d) => <Usd value={d.amount} /> },
          { key: 'u', header: t('detail.used'), align: 'right', cell: (d) => <Usd value={d.used} /> },
          { key: 'r', header: t('detail.remaining'), align: 'right', cell: (d) => <Usd value={d.remaining} strong /> },
          { key: 's', header: t('common:label.status'), cell: (d) => d.status },
        ]} />
      )}
      {tab === 'payments' && (
        <DataTable rows={payments.data?.items} loading={payments.isLoading} error={payments.error} rowKey={(p) => p.id} columns={[
          { key: 'n', header: t('common:label.number'), cell: (p) => <span className="font-mono text-[12px]">{p.number}</span> },
          { key: 'd', header: t('common:label.date'), cell: (p) => date(p.paid_on) },
          { key: 'm', header: t('common:label.method'), cell: (p) => t(`cpay.method.${p.method}`, { defaultValue: p.method }) },
          { key: 'a', header: t('common:label.amount'), align: 'right', cell: (p) => <Usd value={p.amount} strong /> },
          { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={p.status === 'posted' ? 'success' : 'cancelled'}>{t(`sales:status.${p.status}`, { defaultValue: p.status })}</StatusPill> },
        ]} />
      )}
      {edit && <CustomerForm initial={c} onClose={() => setEdit(false)} />}
      <ReasonDialog open={deact} onClose={() => setDeact(false)} title={t('common:confirm.deactivateTitle', { name: c.name })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => { await call(api.customers.POST('/api/customers/v1/customers/{customer_id}/deactivate', { params: { path: { customer_id: id } }, body: { reason } })); void qc.invalidateQueries({ queryKey: ['customers'] }); }} />
      <ApiErrorAlert error={activate.error} />
      {pdf.element}
      <Alert tone="info" className="hidden">{null}</Alert>
    </div>
  );
}
