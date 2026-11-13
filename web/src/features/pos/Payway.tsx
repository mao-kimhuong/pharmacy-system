// Card / Wallet: ABA PayWay's checkout (cards, ABA PAY, KHQR, Alipay, WeChat, Google Pay) INSIDE our payment modal.
// The server signs the form; the browser posts it into an iframe in the modal (PayWay's checkout page sends no
// X-Frame-Options / frame-ancestors; our CSP frame-src allows only ABA's two checkout hosts). A step that will not run
// in a frame (a card's 3-D Secure page, ABA PAY on a phone) has "Continue in PayWay" – their page in a window – while
// the modal keeps following the status (check-transaction). Paid → closes and adds {method: PAYWAY, khqr_id}.
// Closing while it waits asks, then cancels the attempt at PayWay.
import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { useUser } from '@/app/auth';
import type { SalesS } from '@/api/types';
import { ApiErrorAlert, Button, Dialog, Field, Input, Segmented, Select } from '@/design';
import { khr, usd } from '@/lib/format';
import { rielDue, useAttempt } from './Khqr';
import { PaymentModal } from './PaymentModal';

type Option = NonNullable<SalesS['CheckoutCreate']['payment_option']> | '';
const OPTIONS: Option[] = ['', 'cards', 'abapay_khqr', 'alipay', 'wechat', 'google_pay'];
export const FRAME = 'payway-frame';

/** Posts the signed fields to PayWay as multipart/form-data into the named iframe or window. */
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

export function PaywayDialog({ open, branchId, amountUsd, rate, onClose, onPaid, onOther }: {
  open: boolean; branchId: string; amountUsd: number; rate: number | null; onClose: () => void;
  onPaid: (p: SalesS['KhqrOut']) => void; onOther?: () => void;
}) {
  const { t } = useTranslation(['pos', 'common']);
  const user = useUser();
  const [currency, setCurrency] = useState<'USD' | 'KHR'>('USD');
  const [option, setOption] = useState<Option>('');
  const [loaded, setLoaded] = useState(false);
  const [slow, setSlow] = useState(false);
  const win = useRef<Window | null>(null);
  const amount = currency === 'USD' ? amountUsd.toFixed(2) : String(rielDue(amountUsd, rate ?? 0));
  const create = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/payments/payway/checkout', {
      body: { branch_id: branchId, amount, currency, payment_option: option || undefined }, ...withKey(crypto.randomUUID()) })),
  });
  const c = create.data;
  const a = useAttempt(c?.payment, open, (p) => { win.current?.close(); onPaid(p); });
  useEffect(() => { // the iframe exists once the attempt does: post the form into it
    if (!c?.form) return;
    setLoaded(false);
    setSlow(false);
    const post = window.setTimeout(() => postToPayway(c.form!, FRAME), 0);
    const late = window.setTimeout(() => setSlow(true), 10_000);
    return () => { window.clearTimeout(post); window.clearTimeout(late); };
  }, [c]);
  useEffect(() => {
    if (!open) { create.reset(); win.current?.close(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const continueOutside = () => {
    if (!c?.form) return;
    win.current = window.open('', 'payway-checkout', 'width=480,height=760');
    postToPayway(c.form, 'payway-checkout');
  };
  const p = a.p;
  const tests = user.isOwner && import.meta.env.VITE_APP_ENV !== 'production' && c && !c.form && (a.state === 'pending' || a.state === 'declined');
  return (
    <PaymentModal open={open} title={t('payway.title')} testid="payway-modal"
      amountUsd={p && p.currency === 'USD' ? Number(p.amount) : amountUsd}
      amountKhr={rate ? (p?.currency === 'KHR' ? Number(p.amount) : rielDue(amountUsd, rate)) : null}
      reference={p?.tran_id?.slice(-6)} expiresAt={p?.expires_at} state={a.state}
      onClose={onClose} onCancelAttempt={() => { if (c) a.cancel.mutate(c.payment.id); win.current?.close(); }}
      onRetry={() => create.mutate()} onOther={() => { onClose(); onOther?.(); }}
      footerExtra={c?.form && (a.state === 'pending' || a.state === 'declined') ? (
        <button type="button" className={slow && !loaded ? 'font-semibold text-primary-700 underline' : 'text-primary-700 underline'} onClick={continueOutside}>
          {t(slow && !loaded ? 'payway.notLoading' : 'payway.continue')} ↗
        </button>
      ) : tests ? (
        <span className="flex gap-1">
          <Button size="sm" variant="ghost" loading={a.fakePay.isPending} onClick={() => a.fakePay.mutate(c!.payment.id)}>{t('khqr.fakePay')}</Button>
          <Button size="sm" variant="ghost" loading={a.fakeDecline.isPending} onClick={() => a.fakeDecline.mutate(c!.payment.id)}>{t('payway.fakeDecline')}</Button>
        </span>
      ) : null}>
      {!c ? (
        <div className="flex flex-col items-center gap-3 py-2">
          <Segmented<'USD' | 'KHR'> value={currency} onChange={setCurrency} ariaLabel={t('khqr.currency')}
            options={rate ? [{ value: 'USD', label: 'USD' }, { value: 'KHR', label: 'KHR' }] : [{ value: 'USD', label: 'USD' }]} />
          <div className="num text-[32px] font-bold">{currency === 'USD' ? usd(amount) : khr(amount)}</div>
          <Field label={t('payway.method')} className="w-full">{(id) => (
            <Select id={id} value={option} onChange={(e) => setOption(e.target.value as Option)}>
              {OPTIONS.map((o) => <option key={o} value={o}>{t(`payway.options.${o || 'any'}`)}</option>)}
            </Select>)}
          </Field>
          <ApiErrorAlert error={create.error} className="w-full" />
          <Button variant="primary" size="lg" loading={create.isPending} onClick={() => create.mutate()}>{t('payway.open')}</Button>
        </div>
      ) : a.state === 'paid' ? (
        <div className="flex justify-center py-6"><div className="flex size-[160px] items-center justify-center rounded-full bg-success-bg text-[64px] text-pill-success-fg" aria-hidden>✓</div></div>
      ) : c.form ? (
        <iframe name={FRAME} title={t('payway.frame')} onLoad={() => setLoaded(true)} data-testid="payway-frame"
          className="h-[560px] w-full rounded-md border border-neutral-200 bg-white" referrerPolicy="no-referrer"
          sandbox="allow-forms allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation" />
      ) : (
        <p className="m-0 rounded-md bg-neutral-50 px-3 py-3 text-center text-[13px] text-neutral-700">{t('payway.testNote')}</p>
      )}
    </PaymentModal>
  );
}

/** Bank transfer (and a card on the card terminal when PayWay is not set up): the amount and its reference. */
export function ReferenceDialog({ open, method, amountUsd, onClose, onAdd }: {
  open: boolean; method: 'ABA' | 'card'; amountUsd: number; onClose: () => void; onAdd: (amount: string, reference: string) => void;
}) {
  const { t } = useTranslation(['pos', 'common']);
  const [amount, setAmount] = useState('');
  const [ref, setRef] = useState('');
  useEffect(() => { if (open) { setAmount(amountUsd.toFixed(2)); setRef(''); } }, [open, amountUsd]);
  const value = Number(amount);
  const refOk = /^[\w ./#:-]{0,40}$/.test(ref) && (method === 'card' || ref.trim().length > 0);
  const ok = value > 0 && value <= amountUsd + 1e-9 && refOk;
  return (
    <Dialog open={open} onClose={onClose} title={t(`refDialog.${method}.title`)} width={420}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button>
        <Button variant="primary" disabled={!ok} onClick={() => onAdd(value.toFixed(2), ref.trim())}>{t('refDialog.add')}</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label={t('refDialog.amount')}>{(id) => <Input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))} />}</Field>
        <Field label={t(`refDialog.${method}.ref`)} required={method === 'ABA'} hint={t(`refDialog.${method}.hint`)}>
          {(id) => <Input id={id} value={ref} maxLength={40} onChange={(e) => setRef(e.target.value)} autoFocus />}
        </Field>
        {!refOk && ref && <span className="text-[12px] text-danger">{t('refDialog.bad')}</span>}
      </div>
    </Dialog>
  );
}
