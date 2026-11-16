// KHQR in the payment modal: pick USD or riel, then a big QR with the amount (KM / EN), a countdown and "waiting for
// payment" (GET payments/khqr/{id}); paid → the modal closes by itself and {method: KHQR, khqr_id} joins the sale.
// Closing while it waits asks, then cancels the QR (closed at PayWay; a payment that still arrives becomes a refund
// due). A different amount paid → review (a manager refunds it). Development: the owner can mark it paid.
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import QRCode from 'qrcode';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { useUser } from '@/app/auth';
import type { SalesS } from '@/api/types';
import { ApiErrorAlert, Button, Segmented } from '@/design';
import { khr, usd } from '@/lib/format';
import { PaymentModal, type PayState } from './PaymentModal';

/** USD due → riel due: × rate, to the nearest 100 riel, half up (sales money.round_riel). */
export function rielDue(usd: number, rate: number): number {
  return Math.floor((Math.round(usd * 100) * rate + 5000) / 10000) * 100; // in cents: no float drift
}

export function stateOf(p: SalesS['KhqrOut'] | undefined): PayState {
  if (!p) return 'start';
  if (p.status === 'pending') return p.provider_status === 'declined' ? 'declined' : 'pending';
  if (p.status === 'paid' || p.status === 'expired' || p.status === 'cancelled' || p.status === 'review') return p.status;
  return 'cancelled';
}

/** Follows one attempt (QR or checkout) until it is settled; a paid one is handed back once, a moment later. */
export function useAttempt(start: SalesS['KhqrOut'] | undefined, open: boolean, onPaid: (p: SalesS['KhqrOut']) => void) {
  const status = useQuery({
    queryKey: ['sales', 'khqr', start?.id],
    enabled: !!start && open,
    refetchInterval: (q) => (!q.state.data || q.state.data.status === 'pending' ? 2000 : false),
    queryFn: () => call(api.sales.GET('/api/sales/v1/payments/khqr/{khqr_id}', { params: { path: { khqr_id: start!.id } } })),
  });
  const p = status.data ?? start;
  useEffect(() => {
    if (p?.status !== 'paid') return;
    const timer = window.setTimeout(() => onPaid(p), 900); // let the cashier see the check
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p?.status]);
  const cancel = useMutation({ mutationFn: (id: string) => call(api.sales.POST('/api/sales/v1/payments/khqr/{khqr_id}/cancel', { params: { path: { khqr_id: id } } })) });
  const fakePay = useMutation({ mutationFn: (id: string) => call(api.sales.POST('/api/sales/v1/payments/khqr/{khqr_id}/fake-pay', { params: { path: { khqr_id: id } } })), onSuccess: () => void status.refetch() });
  const fakeDecline = useMutation({ mutationFn: (id: string) => call(api.sales.POST('/api/sales/v1/payments/khqr/{khqr_id}/fake-decline', { params: { path: { khqr_id: id } } })), onSuccess: () => void status.refetch() });
  return { p, state: stateOf(p), cancel, fakePay, fakeDecline };
}

export function KhqrDialog({ open, branchId, amountUsd, rate, onClose, onPaid, onOther }: {
  open: boolean; branchId: string; amountUsd: number; rate: number | null; onClose: () => void;
  onPaid: (k: SalesS['KhqrOut']) => void; onOther?: () => void;
}) {
  const { t } = useTranslation(['pos', 'common']);
  const user = useUser();
  const [currency, setCurrency] = useState<'USD' | 'KHR'>('USD');
  const [img, setImg] = useState<string | null>(null);
  const amount = currency === 'USD' ? amountUsd.toFixed(2) : String(rielDue(amountUsd, rate ?? 0));
  const create = useMutation({ mutationFn: () => call(api.sales.POST('/api/sales/v1/payments/khqr', { body: { branch_id: branchId, amount, currency }, ...withKey(crypto.randomUUID()) })) });
  const k = create.data;
  const a = useAttempt(k, open, onPaid);
  useEffect(() => {
    if (k) void QRCode.toDataURL(k.qr_string, { margin: 1, width: 320 }).then(setImg);
  }, [k]);
  useEffect(() => {
    if (!open) { create.reset(); setImg(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const shown = a.p ?? null;
  return (
    <PaymentModal open={open} title={t('khqr.title')} testid="khqr-modal"
      amountUsd={shown ? (shown.currency === 'USD' ? Number(shown.amount) : amountUsd) : amountUsd}
      amountKhr={rate ? (shown?.currency === 'KHR' ? Number(shown.amount) : rielDue(amountUsd, rate)) : null}
      reference={shown?.tran_id ? shown.tran_id.slice(-6) : shown?.md5.slice(-6)} expiresAt={shown?.expires_at} state={a.state}
      onClose={onClose} onCancelAttempt={() => k && a.cancel.mutate(k.id)} onRetry={() => { setImg(null); create.mutate(); }}
      onOther={() => { onClose(); onOther?.(); }}
      footerExtra={user.isOwner && import.meta.env.VITE_APP_ENV !== 'production' && k && a.state === 'pending'
        ? <Button size="sm" variant="ghost" loading={a.fakePay.isPending} onClick={() => a.fakePay.mutate(k.id)}>{t('khqr.fakePay')}</Button> : null}>
      {!k ? (
        <div className="flex flex-col items-center gap-3 py-2">
          <Segmented<'USD' | 'KHR'> value={currency} onChange={setCurrency} ariaLabel={t('khqr.currency')}
            options={rate ? [{ value: 'USD', label: 'USD' }, { value: 'KHR', label: 'KHR' }] : [{ value: 'USD', label: 'USD' }]} />
          <div className="num text-[32px] font-bold">{currency === 'USD' ? usd(amount) : khr(amount)}</div>
          <ApiErrorAlert error={create.error} className="w-full" />
          <Button variant="primary" size="lg" loading={create.isPending} onClick={() => create.mutate()}>{t('khqr.show')}</Button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          {img && a.state !== 'paid' && <img src={img} alt="KHQR" className="size-[320px] rounded-lg border border-neutral-200" />}
          {a.state === 'paid' && <div className="flex size-[200px] items-center justify-center rounded-full bg-success-bg text-[72px] text-pill-success-fg" aria-hidden>✓</div>}
          <div className="text-center">
            <div lang="km" className="text-[16px] font-semibold">{t('khqr.payKm', { amount: k.currency === 'USD' ? usd(k.amount) : khr(k.amount) })}</div>
            <div lang="en" className="text-[13px] text-neutral-600">{t('khqr.payEn', { amount: k.currency === 'USD' ? usd(k.amount) : khr(k.amount) })}</div>
          </div>
        </div>
      )}
    </PaymentModal>
  );
}
