// 18f / 10c Receipts (supplier bills) and supplier payments: pay a supplier (oldest open bills of the branch first;
// more than owed → SUPPLIER_OVERPAYMENT), cancel a payment with a reason. Amounts only with purchase permissions.
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { PurchasingS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, BranchTag, Button, DataTable, Dialog, Field, Input, PageHeader, ReasonDialog, Select, StatusPill, Tabs, Usd, hasField, useToast } from '@/design';
import { date, dateTime, todayIso } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';
import { SupplierPicker, type Supplier } from '../shared/SupplierPicker';
import { usePaging } from '../shared/hooks';

type Pay = PurchasingS['PaymentOut'];

export function PayDialog({ open, onClose, supplierPre }: { open: boolean; onClose: () => void; supplierPre?: Supplier | null }) {
  const { t } = useTranslation(['purchase', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const { oneBranch } = useBranch();
  const [supplier, setSupplier] = useState<Supplier | null>(supplierPre ?? null);
  const [method, setMethod] = useState<'cash' | 'bank' | 'ABA' | 'KHQR'>('cash');
  const [amount, setAmount] = useState('');
  const [reference, setReference] = useState('');
  const [paidOn, setPaidOn] = useState(todayIso());
  const bal = useQuery({ queryKey: ['purchasing', 'balance', supplier?.id], enabled: !!supplier, queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/suppliers/{supplier_id}/balance', { params: { path: { supplier_id: supplier!.id } } })) });
  const body = useMemo(() => ({ supplier_id: supplier?.id ?? '', branch_id: oneBranch?.id ?? '', method, amount, reference, paid_on: paidOn }), [supplier, oneBranch, method, amount, reference, paidOn]);
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/supplier-payments', { body, ...withKey(key) })),
    onSuccess: (p) => { toast.success(t('pay.done', { number: p.number })); void qc.invalidateQueries({ queryKey: ['purchasing'] }); onClose(); },
  });
  const branchOwed = bal.data?.branches.find((b) => (b as { branch_id?: string }).branch_id === oneBranch?.id) as { owed?: string } | undefined;
  return (
    <Dialog open={open} onClose={onClose} title={t('pay.title')} width={520}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!supplier || !(Number(amount) > 0)} loading={m.isPending} onClick={() => m.mutate()}>{t('pay.new')}</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label={t('common:label.supplier')} required>{(id) => <SupplierPicker id={id} value={supplier} onChange={setSupplier} autoFocus />}</Field>
        {bal.data && <div className="flex gap-4 rounded-md bg-neutral-50 p-3 text-[13px]"><span>{t('pay.owed')}: <Usd value={branchOwed?.owed ?? bal.data.owed} strong /></span><span>{t('pay.overdue')}: <Usd value={bal.data.overdue} /></span></div>}
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('common:label.method')}>{(id) => <Select id={id} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>{(['cash', 'bank', 'ABA', 'KHQR'] as const).map((x) => <option key={x} value={x}>{t(`pay.method.${x}`)}</option>)}</Select>}</Field>
          <Field label={`${t('common:label.amount')} (USD)`} required>{(id) => <Input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} />}</Field>
          <Field label={t('pay.reference')}>{(id) => <Input id={id} value={reference} onChange={(e) => setReference(e.target.value)} />}</Field>
          <Field label={t('pay.paidOn')}>{(id) => <Input id={id} type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />}</Field>
        </div>
        <Alert tone="info">{t('pay.allocHint')}</Alert>
        <ApiErrorAlert error={m.error} />
      </div>
    </Dialog>
  );
}

export default function PaymentsPage() {
  const { t } = useTranslation(['purchase', 'common', 'nav', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const { branchParam, byId } = useBranch();
  const paging = usePaging();
  const [tab, setTab] = useState<'receipts' | 'payments'>('receipts');
  const [pay, setPay] = useState(false);
  const [cancel, setCancel] = useState<Pay | null>(null);
  const receipts = useQuery({ queryKey: ['purchasing', 'receipts', branchParam, paging.page], enabled: tab === 'receipts', queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/receipts', { params: { query: { branch_id: branchParam, page: paging.page, size: paging.size } } })) });
  const payments = useQuery({ queryKey: ['purchasing', 'payments', branchParam, paging.page], enabled: tab === 'payments', queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/supplier-payments', { params: { query: { branch_id: branchParam, page: paging.page, size: paging.size } } })) });
  const showR = !!receipts.data?.items.some((r) => hasField(r, 'total'));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.purchase')} title={t('receipts.title')} actions={user.has('purchasing.pay') && <Button variant="primary" onClick={() => setPay(true)}>+ {t('pay.new')}</Button>} />
      <Tabs value={tab} onChange={(v) => { setTab(v); paging.reset(); }} tabs={[{ value: 'receipts', label: t('receipts.receipts') }, { value: 'payments', label: t('receipts.payments') }]} />
      {tab === 'receipts' ? (
        <DataTable rows={receipts.data?.items} loading={receipts.isLoading} error={receipts.error} rowKey={(r) => r.id}
          paging={{ page: paging.page, size: paging.size, total: receipts.data?.total ?? 0, onPage: paging.setPage }}
          columns={[
            { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
            { key: 'b', header: t('common:label.branch'), cell: (r) => <BranchTag code={byId(r.branch_id)?.code ?? '?'} /> },
            { key: 'i', header: t('receive.invoiceNo'), cell: (r) => r.supplier_invoice_no || '—' },
            { key: 'r', header: t('common:label.date'), cell: (r) => dateTime(r.received_at) },
            { key: 'd', header: t('receipts.due'), cell: (r) => date(r.due_on) },
            ...(showR ? [
              { key: 't', header: t('common:label.total'), align: 'right' as const, cell: (r: PurchasingS['ReceiptOut']) => <Usd value={r.total} /> },
              { key: 'bal', header: t('receipts.balance'), align: 'right' as const, cell: (r: PurchasingS['ReceiptOut']) => <Usd value={r.balance} strong /> },
            ] : []),
            { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.status === 'paid' ? 'success' : 'warning'}>{t(`sales:status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
          ]} />
      ) : (
        <DataTable rows={payments.data?.items} loading={payments.isLoading} error={payments.error} rowKey={(p) => p.id}
          paging={{ page: paging.page, size: paging.size, total: payments.data?.total ?? 0, onPage: paging.setPage }}
          columns={[
            { key: 'n', header: t('common:label.number'), cell: (p) => <span className="font-mono text-[12px]">{p.number}</span> },
            { key: 'b', header: t('common:label.branch'), cell: (p) => <BranchTag code={byId(p.branch_id)?.code ?? '?'} /> },
            { key: 'm', header: t('common:label.method'), cell: (p) => t(`pay.method.${p.method}`, { defaultValue: p.method }) },
            { key: 'a', header: t('common:label.amount'), align: 'right', cell: (p) => <Usd value={p.amount} strong /> },
            { key: 'd', header: t('pay.paidOn'), cell: (p) => date(p.paid_on) },
            { key: 'al', header: t('pay.allocations'), align: 'right', cell: (p) => p.allocations.filter((a) => !a.reversed).length },
            { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={p.status === 'posted' ? 'success' : 'cancelled'}>{t(`sales:status.${p.status}`, { defaultValue: p.status })}</StatusPill> },
            { key: 'x', header: '', align: 'right', cell: (p) => p.status === 'posted' && user.has('purchasing.pay') && <Button size="sm" variant="danger-outline" onClick={() => setCancel(p)}>{t('pay.cancel')}</Button> },
          ]} />
      )}
      {pay && <PayDialog open onClose={() => setPay(false)} />}
      <ReasonDialog open={!!cancel} onClose={() => setCancel(null)} title={t('pay.cancel')} confirmLabel={t('pay.cancel')}
        onConfirm={async (reason) => { await call(api.purchasing.POST('/api/purchasing/v1/supplier-payments/{payment_id}/cancel', { params: { path: { payment_id: cancel!.id } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['purchasing'] }); }} />
      <ApiErrorAlert error={null} />
    </div>
  );
}
