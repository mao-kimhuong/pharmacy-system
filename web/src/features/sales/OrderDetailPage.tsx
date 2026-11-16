// 12c Sale order detail: confirm (reserve + deposit), invoice open quantities (normal sale checks; the deposit
// can pay), cancel with a reason, close, print (17e).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { SalesS } from '@/api/types';
import { useUser } from '@/app/auth';
import { QueryState } from '@/app/RouteError';
import { ApiErrorAlert, Button, Card, Checkbox, ConfirmDialog, DataTable, DefinitionList, Dialog, Field, Input, PageHeader, ReasonDialog, Select, SkeletonRows, StatusPill, Usd, usePdf, useToast } from '@/design';
import { date, dateTime } from '@/lib/format';
import { toneOf, useCustomerNames } from '../shared/hooks';
import { useRequestKey } from '../pos/hooks';

type Order = SalesS['OrderOut'];

function ConfirmOrder({ order, open, onClose }: { order: Order; open: boolean; onClose: () => void }) {
  const { t } = useTranslation(['sales', 'common', 'pos']);
  const qc = useQueryClient();
  const [reserve, setReserve] = useState(true);
  const [days, setDays] = useState('3');
  const [method, setMethod] = useState<'cash' | 'card' | 'ABA' | 'KHQR'>('cash');
  const [currency, setCurrency] = useState<'USD' | 'KHR'>('USD');
  const [amount, setAmount] = useState('');
  const body: SalesS['ConfirmIn'] = { reserve, reserve_days: Number(days) || 3, deposit: Number(amount) > 0 ? { method, currency, amount } : null };
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/sale-orders/{order_id}/confirm', { params: { path: { order_id: order.id } }, body, ...withKey(key) })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['sales', 'order', order.id] }); onClose(); },
  });
  return (
    <Dialog open={open} onClose={onClose} title={t('orders.confirm')} width={480}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>{t('orders.confirm')}</Button></>}>
      <div className="flex flex-col gap-3">
        <Checkbox label={t('orders.reserve')} checked={reserve} onChange={(e) => setReserve(e.target.checked)} />
        {reserve && <Field label={t('orders.reserveDays')}>{(id) => <Input id={id} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/\D/g, ''))} className="w-24" />}</Field>}
        <div className="grid grid-cols-3 gap-2">
          <Field label={t('orders.deposit')}>{(id) => <Select id={id} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>{(['cash', 'card', 'ABA', 'KHQR'] as const).map((x) => <option key={x} value={x}>{t(`pos:pay.method.${x}`)}</option>)}</Select>}</Field>
          <Field label={t('common:label.currency')}>{(id) => <Select id={id} value={currency} onChange={(e) => setCurrency(e.target.value as 'USD' | 'KHR')}><option>USD</option><option>KHR</option></Select>}</Field>
          <Field label={t('common:label.amount')}>{(id) => <Input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} />}</Field>
        </div>
        <ApiErrorAlert error={m.error} />
      </div>
    </Dialog>
  );
}

function InvoiceOrder({ order, open, onClose }: { order: Order; open: boolean; onClose: () => void }) {
  const { t } = useTranslation(['sales', 'common', 'pos']);
  const qc = useQueryClient();
  const toast = useToast();
  const [qty, setQty] = useState<Record<string, string>>(() => Object.fromEntries(order.lines.map((l) => [l.id, String(l.qty_open)])));
  const [method, setMethod] = useState<'cash' | 'card' | 'ABA' | 'credit' | 'deposit'>(order.deposit_id ? 'deposit' : 'cash');
  const [amount, setAmount] = useState('');
  const [cash, setCash] = useState('');
  const payments: SalesS['PaymentIn'][] = [];
  if (Number(amount) > 0) payments.push({ method, currency: 'USD', amount, deposit_id: method === 'deposit' ? order.deposit_id : null });
  if (Number(cash) > 0 && method !== 'cash') payments.push({ method: 'cash', currency: 'USD', amount: cash });
  const body: SalesS['OrderInvoiceIn'] = { lines: order.lines.filter((l) => Number(qty[l.id]) > 0).map((l) => ({ order_line_id: l.id, qty: Number(qty[l.id]) })), payments };
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/sale-orders/{order_id}/invoice', { params: { path: { order_id: order.id } }, body, ...withKey(key) })),
    onSuccess: (inv) => { toast.success(inv.number ?? ''); void qc.invalidateQueries({ queryKey: ['sales'] }); onClose(); },
  });
  return (
    <Dialog open={open} onClose={onClose} title={t('orders.invoice')} width={640}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={body.lines.length === 0 || payments.length === 0} loading={m.isPending} onClick={() => m.mutate()}>{t('orders.invoice')}</Button></>}>
      <div className="flex flex-col gap-3">
        <span className="text-[13px] font-medium">{t('orders.invoiceLines')}</span>
        {order.lines.filter((l) => l.qty_open > 0).map((l) => (
          <div key={l.id} className="flex items-center gap-3 text-[13px]">
            <span className="flex-1">{l.name} · {l.pack_unit} <span className="text-neutral-500">({t('orders.open')} {l.qty_open})</span></span>
            <Input aria-label={`${t('common:label.qty')} ${l.name}`} className="w-24 text-right" inputMode="numeric" value={qty[l.id] ?? ''} onChange={(e) => setQty({ ...qty, [l.id]: String(Math.min(l.qty_open, Number(e.target.value.replace(/\D/g, '')) || 0)) })} />
          </div>
        ))}
        <div className="grid grid-cols-3 gap-2">
          <Field label={t('common:label.method')}>{(id) => <Select id={id} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
            {(['cash', 'card', 'ABA', 'credit', ...(order.deposit_id ? ['deposit'] as const : [])] as const).map((x) => <option key={x} value={x}>{t(`pos:pay.method.${x}`)}</option>)}
          </Select>}</Field>
          <Field label={`${t('common:label.amount')} (USD)`}>{(id) => <Input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} />}</Field>
          {method !== 'cash' && <Field label={`${t('pos:pay.method.cash')} (USD)`}>{(id) => <Input id={id} inputMode="decimal" value={cash} onChange={(e) => setCash(e.target.value.replace(/[^\d.]/g, ''))} />}</Field>}
        </div>
        <ApiErrorAlert error={m.error} />
      </div>
    </Dialog>
  );
}

export default function OrderDetailPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['sales', 'common', 'nav']);
  const user = useUser();
  const qc = useQueryClient();
  const pdf = usePdf();
  const [dlg, setDlg] = useState<'' | 'confirm' | 'invoice' | 'cancel' | 'close'>('');
  const q = useQuery({ queryKey: ['sales', 'order', id], queryFn: () => call(api.sales.GET('/api/sales/v1/sale-orders/{order_id}', { params: { path: { order_id: id } } })) });
  const toast = useToast();
  const ready = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/sale-orders/{order_id}/ready', { params: { path: { order_id: id } } })),
    onSuccess: (r) => { qc.setQueryData(['sales', 'order', id], r); toast.success(t('orders.readyDone')); },
  });
  const o = q.data;
  const names = useCustomerNames([o?.customer_id]);
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!o) return <SkeletonRows />;
  const open = o.status === 'ordered' || o.status === 'partly_fulfilled';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.sales')} / ${t('orders.title')}`} title={o.number}
        actions={<>
          <Button onClick={() => pdf.open({ type: 'sale_order', sale_order_id: o.id }, o.number, `${o.number}.pdf`)}>{t('orders.print')}</Button>
          {o.status === 'quote' && <Button variant="primary" onClick={() => setDlg('confirm')}>{t('orders.confirm')}</Button>}
          {open && <Button loading={ready.isPending} onClick={() => ready.mutate()} title={t('orders.readyHint')}>{t('orders.ready')}</Button>}
          {open && user.has('pos.sell') && <Button variant="primary" onClick={() => setDlg('invoice')}>{t('orders.invoice')}</Button>}
          {open && <Button onClick={() => setDlg('close')}>{t('orders.close')}</Button>}
          {(o.status === 'quote' || open) && <Button variant="danger-outline" onClick={() => setDlg('cancel')}>{t('orders.cancel')}</Button>}
        </>}>
        <StatusPill tone={toneOf(o.status)}>{t(`status.${o.status}`, { defaultValue: o.status })}</StatusPill>
      </PageHeader>
      <ApiErrorAlert error={ready.error} />
      <div className="grid gap-4 desktop:grid-cols-[2fr_1fr]">
        <Card title={t('invoice.lines')} padded={false}>
          <DataTable className="rounded-none border-0" rows={o.lines} rowKey={(l) => l.id} minWidth={600} columns={[
            { key: 'n', header: t('common:label.medicine'), cell: (l) => l.name },
            { key: 'u', header: t('common:label.unit'), cell: (l) => l.pack_unit },
            { key: 'q', header: t('common:label.qty'), align: 'right', cell: (l) => l.qty },
            { key: 'i', header: t('orders.invoiced'), align: 'right', cell: (l) => l.qty_invoiced },
            { key: 'o', header: t('orders.open'), align: 'right', cell: (l) => l.qty_open },
            { key: 'p', header: t('common:label.price'), align: 'right', cell: (l) => <Usd value={l.unit_price} /> },
            { key: 't', header: t('common:label.total'), align: 'right', cell: (l) => <Usd value={l.line_total} strong /> },
          ]} />
        </Card>
        <Card title={t('common:label.summary')}>
          <DefinitionList cols={1} items={[
            { label: t('invoices.customer'), value: names(o.customer_id)?.name ?? '…' },
            { label: t('orders.validUntil'), value: date(o.valid_until) },
            { label: t('common:label.total'), value: <Usd value={o.total} strong /> },
            { label: t('orders.deposit'), value: <Usd value={o.deposit_usd} /> },
            ...(o.reserve_until && !o.reservation_released_at ? [{ label: t('orders.reserve'), value: t('orders.reservedUntil', { date: dateTime(o.reserve_until) }) }] : []),
            ...(o.ready_at ? [{ label: t('orders.readyAt'), value: dateTime(o.ready_at) }] : []),
            ...(o.note ? [{ label: t('common:label.notes'), value: o.note }] : []),
            ...(o.cancel_reason ? [{ label: t('common:label.reason'), value: o.cancel_reason }] : []),
          ]} />
        </Card>
      </div>
      {dlg === 'confirm' && <ConfirmOrder order={o} open onClose={() => setDlg('')} />}
      {dlg === 'invoice' && <InvoiceOrder order={o} open onClose={() => setDlg('')} />}
      <ReasonDialog open={dlg === 'cancel'} onClose={() => setDlg('')} title={t('orders.cancel')} confirmLabel={t('orders.cancel')} body={t('common:confirm.cancelBody')}
        onConfirm={async (reason) => { await call(api.sales.POST('/api/sales/v1/sale-orders/{order_id}/cancel', { params: { path: { order_id: o.id } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['sales', 'order', o.id] }); }} />
      <ConfirmDialog open={dlg === 'close'} onClose={() => setDlg('')} title={t('orders.close')} confirmLabel={t('orders.close')}
        onConfirm={async () => { await call(api.sales.POST('/api/sales/v1/sale-orders/{order_id}/close', { params: { path: { order_id: o.id } } })); await qc.invalidateQueries({ queryKey: ['sales', 'order', o.id] }); }} />
      {pdf.element}
    </div>
  );
}
