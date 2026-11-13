// PayWay checkout at the till (cards, ABA PAY, KHQR, Alipay, WeChat, Google Pay on PayWay's hosted page). The server
// signs the form; the browser posts it to PayWay in a new window (opened on the click, so no popup blocker) and the
// POS follows GET payments/khqr/{id}. Paid → the payment {method: PAYWAY, khqr_id} joins the sale. Closing it while it
// waits cancels the attempt (closed at PayWay; a payment that still arrives becomes a refund due). With the fake
// provider (development) there is no form: the owner marks it paid.
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { useUser } from '@/app/auth';
import type { SalesS } from '@/api/types';
import { ApiErrorAlert, Button, Dialog, Field, Segmented, Select, StatusPill } from '@/design';
import { khr, usd } from '@/lib/format';
import { rielDue } from './Khqr';

type Option = NonNullable<SalesS['CheckoutCreate']['payment_option']> | '';
const OPTIONS: Option[] = ['', 'cards', 'abapay_khqr', 'alipay', 'wechat', 'google_pay'];

/** Posts the signed fields to PayWay as multipart/form-data into the named window. */
export function postToPayway(form: SalesS['CheckoutForm'], target: string, doc: Document = document): void {
  const el = doc.createElement('form');
  el.method = 'POST';
  el.action = form.action;
  el.enctype = 'multipart/form-data';
  el.target = target;
  for (const [name, value] of Object.entries(form.fields)) {
    const input = doc.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = value;
    el.appendChild(input);
  }
  doc.body.appendChild(el);
  el.submit();
  el.remove();
}

export function PaywayDialog({ open, branchId, amountUsd, rate, onClose, onPaid }: {
  open: boolean; branchId: string; amountUsd: number; rate: number | null; onClose: () => void; onPaid: (p: SalesS['KhqrOut']) => void;
}) {
  const { t } = useTranslation(['pos', 'common']);
  const user = useUser();
  const [currency, setCurrency] = useState<'USD' | 'KHR'>('USD');
  const [option, setOption] = useState<Option>('');
  const win = useRef<Window | null>(null);
  const amount = currency === 'USD' ? amountUsd.toFixed(2) : String(rielDue(amountUsd, rate ?? 0));
  const create = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/payments/payway/checkout', {
      body: { branch_id: branchId, amount, currency, payment_option: option || undefined }, ...withKey(crypto.randomUUID()) })),
    onSuccess: (r) => {
      if (r.form && win.current) postToPayway(r.form, 'payway-checkout');
      else win.current?.close();
    },
    onError: () => win.current?.close(),
  });
  const c = create.data?.payment;
  const status = useQuery({
    queryKey: ['sales', 'khqr', c?.id],
    enabled: !!c && open,
    refetchInterval: (q) => (q.state.data?.status === 'pending' || !q.state.data ? 2000 : false),
    queryFn: () => call(api.sales.GET('/api/sales/v1/payments/khqr/{khqr_id}', { params: { path: { khqr_id: c!.id } } })),
  });
  const s = status.data ?? c;
  useEffect(() => {
    if (s?.status === 'paid') { win.current?.close(); onPaid(s); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s?.status]);
  useEffect(() => {
    if (!open) create.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const cancel = useMutation({ mutationFn: (id: string) => call(api.sales.POST('/api/sales/v1/payments/khqr/{khqr_id}/cancel', { params: { path: { khqr_id: id } } })) });
  const fake = useMutation({ mutationFn: () => call(api.sales.POST('/api/sales/v1/payments/khqr/{khqr_id}/fake-pay', { params: { path: { khqr_id: c!.id } } })), onSuccess: () => void status.refetch() });
  const start = () => {
    win.current = window.open('', 'payway-checkout', 'width=480,height=760'); // on the click: not blocked
    create.mutate();
  };
  const close = () => {
    if (c && s?.status === 'pending') cancel.mutate(c.id);
    win.current?.close();
    onClose();
  };
  return (
    <Dialog open={open} onClose={close} title={t('payway.title')} width={440}
      footer={<>
        <Button onClick={close}>{t('common:action.cancel')}</Button>
        {!c && <Button variant="primary" loading={create.isPending} onClick={start}>{t('payway.open')}</Button>}
        {(s?.status === 'expired' || s?.status === 'cancelled') && <Button variant="primary" onClick={start}>{t('khqr.again')}</Button>}
      </>}>
      <div className="flex flex-col items-center gap-3">
        {!c && (
          <>
            <Segmented<'USD' | 'KHR'> value={currency} onChange={setCurrency} ariaLabel={t('khqr.currency')}
              options={rate ? [{ value: 'USD', label: 'USD' }, { value: 'KHR', label: 'KHR' }] : [{ value: 'USD', label: 'USD' }]} />
            <div className="num text-[32px] font-bold">{currency === 'USD' ? usd(amount) : khr(amount)}</div>
            <Field label={t('payway.method')} className="w-full">{(id) => (
              <Select id={id} value={option} onChange={(e) => setOption(e.target.value as Option)}>
                {OPTIONS.map((o) => <option key={o} value={o}>{t(`payway.options.${o || 'any'}`)}</option>)}
              </Select>)}
            </Field>
            <p className="m-0 text-center text-[12px] text-neutral-500">{t('payway.hint')}</p>
          </>
        )}
        <ApiErrorAlert error={create.error} className="w-full" />
        {c && (
          <>
            <div className="num text-[24px] font-bold">{c.currency === 'USD' ? usd(c.amount) : khr(c.amount)}</div>
            {s?.status === 'pending' && <StatusPill tone="warning">{t('payway.waiting')}</StatusPill>}
            {s?.status === 'paid' && <StatusPill tone="success">{t('khqr.paid')}</StatusPill>}
            {s?.status === 'expired' && <StatusPill tone="danger">{t('khqr.expired')}</StatusPill>}
            {s?.status === 'cancelled' && <StatusPill tone="neutral">{t('khqr.cancelled')}</StatusPill>}
            {s?.status === 'review' && <StatusPill tone="danger">{t('khqr.review')}</StatusPill>}
            {s?.status === 'review' && <span className="text-center text-[12px] text-danger">{s.review_reason}</span>}
            {s?.status === 'pending' && create.data?.form && (
              <Button size="sm" variant="ghost" onClick={() => { win.current = window.open('', 'payway-checkout', 'width=480,height=760'); postToPayway(create.data!.form!, 'payway-checkout'); }}>
                {t('payway.reopen')}
              </Button>
            )}
            {user.isOwner && import.meta.env.VITE_APP_ENV !== 'production' && s?.status === 'pending' && !create.data?.form && (
              <Button size="sm" variant="ghost" loading={fake.isPending} onClick={() => fake.mutate()}>{t('khqr.fakePay')}</Button>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}
