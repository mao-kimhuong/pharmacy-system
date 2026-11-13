// T2 Customer detail → Telegram: linked or not (since when, through which QR), each consent with when and where it
// changed. Staff with notifications.customers show a counter QR (no phone check: they see who scans it), record what the
// customer asked for (promotions can only be turned ON by the customer, in the bot) and unlink.
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import QRCode from 'qrcode';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { NotificationsS } from '@/api/types';
import { useUser } from '@/app/auth';
import { Alert, ApiErrorAlert, Button, Card, ConfirmDialog, Dialog, StatusPill, Switch, useToast } from '@/design';
import { dateTime } from '@/lib/format';

type Topic = NotificationsS['ConsentOut']['topic'];

export function CustomerTelegram({ customerId }: { customerId: string }) {
  const { t } = useTranslation(['contacts', 'common']);
  const user = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const canManage = user.has('notifications.customers');
  const key = ['notifications', 'customer', customerId];
  const q = useQuery({ queryKey: key, queryFn: () => call(api.notifications.GET('/api/notifications/v1/customers/{customer_id}/telegram', { params: { path: { customer_id: customerId } } })) });
  const set = (data: NotificationsS['CustomerTelegramOut']) => qc.setQueryData(key, data);
  const consent = useMutation({
    mutationFn: (v: { topic: Topic; on: boolean }) => call(api.notifications.PUT('/api/notifications/v1/customers/{customer_id}/telegram/consents', { params: { path: { customer_id: customerId } }, body: { consents: { [v.topic]: v.on } } })),
    onSuccess: (d) => { set(d); toast.success(t('telegram.saved')); },
  });
  const unlink = useMutation({ mutationFn: () => call(api.notifications.POST('/api/notifications/v1/customers/{customer_id}/telegram/unlink', { params: { path: { customer_id: customerId } } })), onSuccess: set });
  const token = useMutation({ mutationFn: () => call(api.notifications.POST('/api/notifications/v1/customers/{customer_id}/telegram/link-token', { params: { path: { customer_id: customerId } } })) });
  const [askUnlink, setAskUnlink] = useState(false);
  const [img, setImg] = useState<string | null>(null);
  useEffect(() => { if (token.data?.url) void QRCode.toDataURL(token.data.url, { margin: 1, width: 280 }).then(setImg); }, [token.data]);
  const s = q.data;
  return (
    <Card title={t('telegram.title')}
      actions={s && canManage && <>
        {!s.linked && s.bot_configured && <Button size="sm" loading={token.isPending} onClick={() => token.mutate()}>{t('telegram.showQr')}</Button>}
        {s.linked && <Button size="sm" variant="danger-outline" onClick={() => setAskUnlink(true)}>{t('telegram.unlink')}</Button>}
      </>}>
      <ApiErrorAlert error={q.error ?? consent.error ?? unlink.error ?? token.error} />
      {s && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <StatusPill tone={s.linked ? 'success' : 'neutral'}>{s.linked ? t('telegram.linked') : t('telegram.notLinked')}</StatusPill>
            {s.links.map((l) => <span key={l.id} className="text-neutral-600">{t('telegram.since', { when: dateTime(l.linked_at), via: t(`telegram.via.${l.via}`, { defaultValue: l.via }) })}</span>)}
          </div>
          {!s.bot_configured && <Alert tone="info">{t('telegram.notConfigured')}</Alert>}
          <div className="text-[12px] font-semibold text-neutral-600">{t('telegram.consent')}</div>
          <ul className="m-0 grid list-none grid-cols-1 gap-2 p-0 tablet:grid-cols-2">
            {s.consents.map((c) => (
              <li key={c.topic} className="flex flex-col gap-0.5 rounded-md border border-neutral-100 px-3 py-2" data-topic={c.topic}>
                <Switch label={<span className="text-[13px]">{t(`telegram.topic.${c.topic}`)}</span>} checked={c.granted}
                  disabled={!canManage || !s.linked || consent.isPending || (c.topic === 'marketing' && !c.granted)}
                  onChange={(on) => consent.mutate({ topic: c.topic, on })} />
                <span className="pl-11 text-[11px] text-neutral-500">{c.source ? `${t(`telegram.source.${c.source}`, { defaultValue: c.source })} · ${dateTime(c.changed_at)}` : t('telegram.never')}</span>
              </li>
            ))}
          </ul>
          <span className="text-[11px] text-neutral-500">{t('telegram.marketingNote')}</span>
        </div>
      )}
      <Dialog open={!!token.data} onClose={() => { token.reset(); setImg(null); void q.refetch(); }} title={t('telegram.qrTitle')} width={360}
        footer={<Button onClick={() => { token.reset(); setImg(null); void q.refetch(); }}>{t('common:action.close')}</Button>}>
        <div className="flex flex-col items-center gap-2 text-center">
          {img && <img src={img} alt="Telegram QR" className="size-[280px]" />}
          <p className="m-0 text-[13px] text-neutral-700">{t('telegram.qrBody', { when: token.data ? dateTime(token.data.expires_at) : '' })}</p>
        </div>
      </Dialog>
      <ConfirmDialog open={askUnlink} onClose={() => setAskUnlink(false)} title={t('telegram.unlinkTitle')} body={t('telegram.unlinkBody')}
        confirmLabel={t('telegram.unlink')} variant="danger" onConfirm={() => { setAskUnlink(false); unlink.mutate(); }} />
    </Card>
  );
}
