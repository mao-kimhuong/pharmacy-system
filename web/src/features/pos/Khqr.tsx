// 3l / 4d: dynamic KHQR for the amount due (ABA PayWay or Bakong). Shows the QR, polls the status (GET
// payments/khqr/{id}); when paid, the payment {method: KHQR, khqr_id} joins the sale. Closing it while it waits
// cancels the QR (closed at PayWay; a payment that still arrives becomes a refund due). A different amount paid →
// review (a manager refunds it). Outside production the owner can mark it paid (fake provider).
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import QRCode from 'qrcode';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import type { SalesS } from '@/api/types';
import { ApiErrorAlert, Button, Dialog, Segmented, StatusPill } from '@/design';
import { khr, time, usd } from '@/lib/format';

/** USD due → riel due: × rate, to the nearest 100 riel, half up (sales money.round_riel). */
export function rielDue(usd: number, rate: number): number {
  return Math.floor((Math.round(usd * 100) * rate + 5000) / 10000) * 100; // in cents: no float drift
}

export function KhqrDialog({ open, branchId, amountUsd, rate, onClose, onPaid }: {
  open: boolean; branchId: string; amountUsd: number; rate: number | null; onClose: () => void; onPaid: (k: SalesS['KhqrOut']) => void;
}) {
  const { t } = useTranslation(['pos', 'common']);
  const user = useUser();
  const [currency, setCurrency] = useState<'USD' | 'KHR'>('USD');
  const [img, setImg] = useState<string | null>(null);
  // riel: what is due rounded to 100 riel half up, as the invoice's total_khr (the sale compares riel with riel)
  const amount = currency === 'USD' ? amountUsd.toFixed(2) : String(rielDue(amountUsd, rate ?? 0));
  const create = useMutation({ mutationFn: () => call(api.sales.POST('/api/sales/v1/payments/khqr', { body: { branch_id: branchId, amount, currency } })) });
  const k = create.data;
  const status = useQuery({
    queryKey: ['sales', 'khqr', k?.id],
    enabled: !!k && open,
    refetchInterval: (q) => (q.state.data?.status === 'pending' || !q.state.data ? 2000 : false),
    queryFn: () => call(api.sales.GET('/api/sales/v1/payments/khqr/{khqr_id}', { params: { path: { khqr_id: k!.id } } })),
  });
  const s = status.data ?? k;
  useEffect(() => {
    if (k) void QRCode.toDataURL(k.qr_string, { margin: 1, width: 260 }).then(setImg);
  }, [k]);
  useEffect(() => {
    if (s?.status === 'paid') onPaid(s);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s?.status]);
  useEffect(() => {
    if (!open) { create.reset(); setImg(null); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const cancel = useMutation({ mutationFn: (id: string) => call(api.sales.POST('/api/sales/v1/payments/khqr/{khqr_id}/cancel', { params: { path: { khqr_id: id } } })) });
  const close = () => {
    if (k && s?.status === 'pending') cancel.mutate(k.id); // the customer may not pay a QR the till gave up
    onClose();
  };
  const fake = useMutation({ mutationFn: () => call(api.sales.POST('/api/sales/v1/payments/khqr/{khqr_id}/fake-pay', { params: { path: { khqr_id: k!.id } } })), onSuccess: () => void status.refetch() });
  return (
    <Dialog open={open} onClose={close} title={t('khqr.title')} width={420}
      footer={<>
        <Button onClick={close}>{t('common:action.cancel')}</Button>
        {!k && <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()}>{t('common:action.continue')}</Button>}
        {(s?.status === 'expired' || s?.status === 'cancelled') && <Button variant="primary" onClick={() => create.mutate()}>{t('khqr.again')}</Button>}
      </>}>
      <div className="flex flex-col items-center gap-3">
        {!k && (
          <>
            <Segmented<'USD' | 'KHR'> value={currency} onChange={setCurrency} ariaLabel={t('khqr.currency')}
              options={rate ? [{ value: 'USD', label: 'USD' }, { value: 'KHR', label: 'KHR' }] : [{ value: 'USD', label: 'USD' }]} />
            <div className="num text-[32px] font-bold">{currency === 'USD' ? usd(amount) : khr(amount)}</div>
          </>
        )}
        <ApiErrorAlert error={create.error} className="w-full" />
        {k && (
          <>
            {img && <img src={img} alt="KHQR" className="size-[260px] rounded-lg border border-neutral-200" />}
            <div className="num text-[24px] font-bold">{k.currency === 'USD' ? usd(k.amount) : khr(k.amount)}</div>
            {s?.status === 'pending' && <StatusPill tone="warning">{t('khqr.waiting')}</StatusPill>}
            {s?.status === 'paid' && <StatusPill tone="success">{t('khqr.paid')}</StatusPill>}
            {s?.status === 'expired' && <StatusPill tone="danger">{t('khqr.expired')}</StatusPill>}
            {s?.status === 'cancelled' && <StatusPill tone="neutral">{t('khqr.cancelled')}</StatusPill>}
            {s?.status === 'review' && <StatusPill tone="danger">{t('khqr.review')}</StatusPill>}
            {s?.status === 'review' && <span className="text-center text-[12px] text-danger">{s.review_reason}</span>}
            {s?.deeplink && s.status === 'pending' && (
              <a className="text-[13px] font-medium text-primary underline pointer-fine:hidden" href={s.deeplink}>{t('khqr.openAba')}</a>
            )}
            <span className="text-[12px] text-neutral-500">{t('khqr.expires', { time: time(k.expires_at) })}</span>
            {user.isOwner && import.meta.env.VITE_APP_ENV !== 'production' && s?.status === 'pending' && (
              <Button size="sm" variant="ghost" loading={fake.isPending} onClick={() => fake.mutate()}>{t('khqr.fakePay')}</Button>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}
