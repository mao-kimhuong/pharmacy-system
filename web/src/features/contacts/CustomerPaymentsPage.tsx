// 18g Customer payments: record (oldest unpaid invoices first, USD; KHR has no API field), cancel with a reason.
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { CustomersS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, Button, DataTable, Dialog, Field, Input, PageHeader, ReasonDialog, Select, StatusPill, Usd, useToast } from '@/design';
import { date, todayIso } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';
import { CustomerPicker, type Customer } from '../shared/CustomerPicker';
import { useCustomerNames, usePaging } from '../shared/hooks';

type Pay = CustomersS['PaymentOut'];

export default function CustomerPaymentsPage() {
  const { t } = useTranslation(['contacts', 'common', 'nav', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const { oneBranch } = useBranch();
  const paging = usePaging();
  const [open, setOpen] = useState(false);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [method, setMethod] = useState<'cash' | 'card' | 'ABA' | 'KHQR'>('cash');
  const [amount, setAmount] = useState('');
  const [reference, setReference] = useState('');
  const [cancel, setCancel] = useState<Pay | null>(null);
  const list = useQuery({ queryKey: ['customers', 'payments', 'all', paging.page], queryFn: () => call(api.customers.GET('/api/customers/v1/customer-payments', { params: { query: { page: paging.page, size: paging.size } } })) });
  const names = useCustomerNames(list.data?.items.map((p) => p.customer_id) ?? []);
  const body = useMemo(() => ({ customer_id: customer?.id ?? '', branch_id: oneBranch?.id ?? '', method, amount, reference, paid_on: todayIso() }), [customer, oneBranch, method, amount, reference]);
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: () => call(api.customers.POST('/api/customers/v1/customer-payments', { body, ...withKey(key) })),
    onSuccess: (p) => { toast.success(t('cpay.done', { number: p.number })); setOpen(false); setAmount(''); void qc.invalidateQueries({ queryKey: ['customers'] }); },
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.contacts')} title={t('cpay.title')} actions={<Button variant="primary" onClick={() => setOpen(true)}>+ {t('cpay.new')}</Button>} />
      <DataTable rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(p) => p.id}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage }}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (p) => <span className="font-mono text-[12px]">{p.number}</span> },
          { key: 'c', header: t('common:label.customer'), cell: (p) => names(p.customer_id)?.name ?? '…' },
          { key: 'd', header: t('common:label.date'), cell: (p) => date(p.paid_on) },
          { key: 'm', header: t('common:label.method'), cell: (p) => t(`cpay.method.${p.method}`, { defaultValue: p.method }) },
          { key: 'a', header: t('common:label.amount'), align: 'right', cell: (p) => <Usd value={p.amount} strong /> },
          { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={p.status === 'posted' ? 'success' : 'cancelled'}>{t(`sales:status.${p.status}`, { defaultValue: p.status })}</StatusPill> },
          { key: 'x', header: '', align: 'right', cell: (p) => p.status === 'posted' && user.has('contacts.customers') && <Button size="sm" variant="danger-outline" onClick={() => setCancel(p)}>{t('cpay.cancel')}</Button> },
        ]} />
      <Dialog open={open} onClose={() => setOpen(false)} title={t('cpay.new')} width={480}
        footer={<><Button onClick={() => setOpen(false)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!customer || !(Number(amount) > 0)} loading={m.isPending} onClick={() => m.mutate()}>{t('cpay.new')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('common:label.customer')} required>{(id) => <CustomerPicker id={id} value={customer} onChange={setCustomer} autoFocus />}</Field>
          {customer?.balance != null && <span className="text-[13px]">{t('customers.balance')}: <Usd value={customer.balance} strong /></span>}
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('common:label.method')}>{(id) => <Select id={id} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>{(['cash', 'card', 'ABA', 'KHQR'] as const).map((x) => <option key={x} value={x}>{t(`cpay.method.${x}`)}</option>)}</Select>}</Field>
            <Field label={`${t('common:label.amount')} (USD)`} required>{(id) => <Input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} />}</Field>
            <Field label={t('purchase:pay.reference')} className="col-span-2">{(id) => <Input id={id} value={reference} onChange={(e) => setReference(e.target.value)} />}</Field>
          </div>
          <Alert tone="info">{t('cpay.hint')}</Alert>
          <ApiErrorAlert error={m.error} />
        </div>
      </Dialog>
      <ReasonDialog open={!!cancel} onClose={() => setCancel(null)} title={t('cpay.cancel')} confirmLabel={t('cpay.cancel')}
        onConfirm={async (reason) => { await call(api.customers.POST('/api/customers/v1/customer-payments/{payment_id}/cancel', { params: { path: { payment_id: cancel!.id } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['customers'] }); }} />
    </div>
  );
}
