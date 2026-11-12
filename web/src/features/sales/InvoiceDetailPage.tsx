// 12e Invoice detail: lines with lots and Rx, payments, returns; reprint (80 mm / A4 / labels), cancel with a
// reason (sales.cancel; earlier days need sales.cancel_any — the API decides), return (sales.return).
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { QueryState } from '@/app/RouteError';
import { Alert, Button, Card, DataTable, DefinitionList, Khr, PageHeader, ReasonDialog, SafetyBadge, SkeletonRows, StatusPill, Usd, hasField, usePdf, useToast } from '@/design';
import { date, dateTime, khr, usd } from '@/lib/format';
import { toneOf, useCustomerNames, useStaffNames } from '../shared/hooks';
import { ReturnDialog } from './ReturnDialog';

export default function InvoiceDetailPage() {
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const { t } = useTranslation(['sales', 'common', 'pos', 'nav']);
  const user = useUser();
  const toast = useToast();
  const qc = useQueryClient();
  const pdf = usePdf();
  const staff = useStaffNames();
  const [cancel, setCancel] = useState(false);
  const [ret, setRet] = useState(params.get('return') === '1');
  const q = useQuery({ queryKey: ['sales', 'invoice', id], queryFn: () => call(api.sales.GET('/api/sales/v1/invoices/{invoice_id}', { params: { path: { invoice_id: id } } })) });
  const returns = useQuery({ queryKey: ['sales', 'returns', id], enabled: !!q.data, queryFn: () => call(api.sales.GET('/api/sales/v1/invoices/{invoice_id}/returns', { params: { path: { invoice_id: id } } })) });
  const inv = q.data;
  const paidByKhqr = !!inv?.payments.some((p) => p.method === 'KHQR');
  // a cancel or a return "back to the KHQR" leaves a refund due: offer it here to who may give it
  const khqrDue = useQuery({
    queryKey: ['sales', 'khqr-refunds', 'invoice', id],
    enabled: paidByKhqr && user.has('sales.khqr_refund') && (inv?.status === 'cancelled' || Number(inv?.returned_total) > 0),
    queryFn: () => call(api.sales.GET('/api/sales/v1/payments/khqr/refunds', { params: { query: { branch_id: inv!.branch_id } } })),
    select: (rows) => rows.filter((r) => r.payment.invoice_id === id && r.status !== 'refunded'),
  });
  const customer = useCustomerNames([inv?.customer_id]);
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!inv) return <SkeletonRows />;
  const done = inv.status === 'completed';
  const canReturn = done && user.has('sales.return') && inv.lines.some((l) => l.qty_base > l.returned_qty_base);
  const canCancel = done && user.has('sales.cancel') && Number(inv.returned_total) === 0;
  const showCost = hasField(inv, 'cost_total');
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.sales')} / ${t('invoices.title')}`} title={t('invoice.title', { number: inv.number ?? '—' })}
        actions={<>
          {done && <Button onClick={() => pdf.open({ type: 'receipt_80mm', invoice_id: inv.id }, t('invoice.receipt'), `${inv.number}-receipt.pdf`)}>{t('invoice.receipt')}</Button>}
          {done && <Button onClick={() => pdf.open({ type: 'invoice_a4', invoice_id: inv.id }, t('invoice.a4'), `${inv.number}.pdf`)}>{t('invoice.a4')}</Button>}
          {done && inv.lines.some((l) => l.rx_item_id) && <Button onClick={() => pdf.open({ type: 'dispensing_label', invoice_id: inv.id }, t('invoice.labels'), `${inv.number}-labels.pdf`)}>{t('invoice.labels')}</Button>}
          {canReturn && <Button onClick={() => setRet(true)}>{t('invoice.return')}</Button>}
          {canCancel && <Button variant="danger-outline" onClick={() => setCancel(true)}>{t('invoice.cancel')}</Button>}
        </>}>
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone={toneOf(inv.status)}>{t(`status.${inv.status}`, { defaultValue: inv.status })}</StatusPill>
          {Number(inv.returned_total) > 0 && <StatusPill tone="purple">{t('status.partly_returned')} · {usd(inv.returned_total)}</StatusPill>}
        </div>
      </PageHeader>
      {inv.failure_reason && <Alert tone="danger">{t('invoice.failure', { reason: inv.failure_reason })}</Alert>}
      {inv.cancel_reason && <Alert tone="warning" title={t('status.cancelled')}>{inv.cancel_reason} · {dateTime(inv.cancelled_at)}</Alert>}
      {!!khqrDue.data?.length && (
        <Alert tone="info" title={t('khqrRefunds.dueOnInvoice', { count: khqrDue.data.length })}>
          <Link className="font-medium text-primary underline" to="/sales/khqr-refunds">{t('khqrRefunds.goRefund')}</Link>
        </Alert>
      )}
      <div className="grid gap-4 desktop:grid-cols-[2fr_1fr]">
        <Card title={t('invoice.lines')} padded={false}>
          <DataTable className="rounded-none border-0" rows={inv.lines} rowKey={(l) => l.id} minWidth={640}
            columns={[
              { key: 'n', header: t('common:label.medicine'), cell: (l) => (
                <span className="flex flex-col gap-1">
                  <span className="flex flex-wrap items-center gap-1.5 font-medium">{l.name}
                    {l.is_controlled && <SafetyBadge kind="controlled" />}
                    {l.prescription_number && <SafetyBadge kind="rx">{l.prescription_number}</SafetyBadge>}
                    {l.is_hamper && <SafetyBadge kind="hamper" />}
                  </span>
                  <span className="text-[12px] text-neutral-500">{l.batches.map((b) => `${b.lot_no} · ${date(b.expiry_date)} · ${b.qty_base}`).join('  |  ')}</span>
                  {l.allergy_override_reason && <span className="text-[12px] text-pill-danger-fg">! {l.allergy_override_reason}</span>}
                </span>
              ) },
              { key: 'u', header: t('common:label.unit'), cell: (l) => l.pack_unit },
              { key: 'q', header: t('common:label.qty'), align: 'right', cell: (l) => l.qty },
              { key: 'p', header: t('common:label.price'), align: 'right', cell: (l) => <Usd value={l.unit_price} /> },
              { key: 'd', header: t('pos:cols.disc'), align: 'right', cell: (l) => { const d = Number(l.promo_discount ?? 0) + Number(l.manual_discount ?? 0); return d > 0 ? `−${usd(d).slice(1)}` : '—'; } },
              { key: 't', header: t('common:label.total'), align: 'right', cell: (l) => <Usd value={l.net ?? l.line_total} strong /> },
              ...(showCost ? [{ key: 'c', header: t('invoice.cost'), align: 'right' as const, cell: (l: typeof inv.lines[number]) => <Usd value={l.cost} /> }] : []),
              { key: 'r', header: t('invoice.returned'), align: 'right', cell: (l) => (l.returned_qty_base ? `${l.returned_qty_base}` : '—') },
            ]} />
        </Card>
        <div className="flex flex-col gap-4">
          <Card title={t('common:label.summary')}>
            <DefinitionList cols={1} items={[
              { label: t('invoices.date'), value: dateTime(inv.completed_at ?? inv.created_at) },
              { label: t('invoices.customer'), value: inv.customer_id ? customer(inv.customer_id)?.name ?? '…' : t('invoices.walkIn') },
              { label: t('invoices.staff'), value: staff(inv.created_by) },
              { label: t('pos:totals.subtotal'), value: <Usd value={inv.subtotal} /> },
              { label: t('pos:totals.discount'), value: <Usd value={inv.discount} /> },
              { label: t('pos:totals.total'), value: <span className="flex gap-2"><Usd value={inv.total} strong />{inv.total_khr != null && <Khr value={inv.total_khr} className="text-primary-700" />}</span> },
              { label: t('invoice.rate'), value: inv.khr_per_usd ? `1 USD = ${khr(inv.khr_per_usd)}` : '—' },
              ...(showCost ? [{ label: t('invoice.margin'), value: <Usd value={inv.margin} /> }] : []),
              ...(inv.note ? [{ label: t('invoice.note'), value: inv.note }] : []),
            ]} />
          </Card>
          <Card title={t('invoice.payments')}>
            <div className="flex flex-col gap-1.5 text-[13px]">
              {inv.payments.map((p, i) => (
                <div key={i} className="flex justify-between"><span>{t(`pos:pay.method.${p.method}`, { defaultValue: p.method })} · {p.currency}</span><span className="num font-medium">{p.currency === 'KHR' ? khr(p.amount) : usd(p.amount)}</span></div>
              ))}
              {Number(inv.credit_amount) > 0 && <div className="flex justify-between"><span>{t('invoice.credit')}</span><span className="num">{usd(inv.credit_amount)}</span></div>}
              <div className="flex justify-between border-t border-neutral-100 pt-1.5"><span>{t('invoice.change')}</span>
                <span className="num">{[Number(inv.change_given_usd) > 0 ? usd(inv.change_given_usd) : null, inv.change_given_khr > 0 ? khr(inv.change_given_khr) : null].filter(Boolean).join(' + ') || usd(0)}</span></div>
            </div>
          </Card>
          {returns.data && returns.data.length > 0 && (
            <Card title={t('invoice.returns')}>
              <div className="flex flex-col gap-2 text-[13px]">
                {returns.data.map((r) => (
                  <div key={r.id} className="flex flex-col"><span className="flex justify-between"><b className="font-mono text-[12px]">{r.number}</b><Usd value={r.refund_usd} /></span>
                    <span className="text-neutral-500">{dateTime(r.created_at)} · {r.reason}</span></div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
      <ReasonDialog open={cancel} onClose={() => setCancel(false)} title={`${t('invoice.cancel')} ${inv.number}`} body={t('invoice.cancelBody')}
        confirmLabel={t('invoice.cancel')} keepLabel={t('invoice.keep')} minLength={3}
        onConfirm={async (reason) => {
          await call(api.sales.POST('/api/sales/v1/invoices/{invoice_id}/cancel', { params: { path: { invoice_id: inv.id } }, body: { reason } }));
          toast.success(t('invoice.cancelled'));
          await qc.invalidateQueries({ queryKey: ['sales'] });
        }} />
      <ReturnDialog invoice={inv} open={ret && canReturn} onClose={() => setRet(false)} />
      {pdf.element}
    </div>
  );
}
