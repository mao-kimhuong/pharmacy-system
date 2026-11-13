// T2: a discount above the cap can be approved on Telegram instead of the approver's PIN here. The cart is sent
// (POST /carts/discount-approvals), the manager / owner taps Approve in their chat, the till polls; approved → the
// token "tg:<id>" goes into the sale like a PIN approval (valid for exactly this cart, once, 10 minutes).
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { SalesS } from '@/api/types';
import { ApiErrorAlert, Button, type PinToken } from '@/design';
import { mmss, useCountdown } from './PaymentModal';

type Body = SalesS['CartPreviewIn'];

export function AskTelegram({ body, onApproved }: { body: Body | null; onApproved: (t: PinToken) => void }) {
  const { t } = useTranslation('pos');
  const [id, setId] = useState<string | null>(null);
  const ask = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/carts/discount-approvals', { body: { ...body!, discount_approval_token: null } })),
    onSuccess: (a) => setId(a.id),
  });
  const status = useQuery({
    queryKey: ['sales', 'discount-approval', id],
    enabled: !!id,
    refetchInterval: (q) => (!q.state.data || q.state.data.status === 'pending' ? 2000 : false),
    queryFn: () => call(api.sales.GET('/api/sales/v1/carts/discount-approvals/{approval_id}', { params: { path: { approval_id: id! } } })),
  });
  const a = status.data ?? ask.data;
  const left = useCountdown(a?.status === 'pending' ? a.expires_at : null);
  useEffect(() => {
    if (a?.status === 'approved' && a.token) {
      const until = new Date(Date.parse(a.decided_at ?? new Date().toISOString()) + 10 * 60_000).toISOString();
      onApproved({ pin_token: a.token, user_id: '', name: 'Telegram', expires_at: until });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a?.status, a?.token]);
  const expired = a?.status === 'pending' && left === 0;
  return (
    <div className="flex flex-col gap-2 rounded-md border border-neutral-200 px-3 py-2" data-testid="ask-telegram">
      <span className="text-[12px] text-neutral-600">{t('tg.hint')}</span>
      {!a || expired || a.status === 'rejected' ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={!body} loading={ask.isPending} onClick={() => { setId(null); ask.mutate(); }}>{t('tg.ask')}</Button>
          {a?.status === 'rejected' && <span className="text-[12px] text-danger">{t('tg.rejected')}</span>}
          {expired && <span className="text-[12px] text-danger">{t('tg.expired')}</span>}
        </div>
      ) : a.status === 'pending' ? (
        <span className="text-[13px]" role="status">⏳ {t('tg.waiting', { left: left !== null ? mmss(left) : '' })}</span>
      ) : (
        <span className="text-[13px] text-success" role="status">✓ {t('tg.approved')}</span>
      )}
      <ApiErrorAlert error={ask.error} />
    </div>
  );
}
