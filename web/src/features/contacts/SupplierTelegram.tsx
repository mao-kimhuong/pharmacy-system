// T2 Supplier → Telegram: the supplier's linked chats (a contact per chat). Sent POs go there as a PDF with a
// "Received / Confirmed" button; the confirmation shows on the PO. A link: 7 days, once, private or group chat.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { Alert, ApiErrorAlert, Button, Card, Field, Input } from '@/design';
import { dateTime } from '@/lib/format';

export function SupplierTelegram({ supplierId }: { supplierId: string }) {
  const { t } = useTranslation(['contacts', 'common']);
  const user = useUser();
  const qc = useQueryClient();
  const key = ['notifications', 'supplier', supplierId];
  const q = useQuery({ queryKey: key, queryFn: () => call(api.notifications.GET('/api/notifications/v1/suppliers/{supplier_id}/telegram', { params: { path: { supplier_id: supplierId } } })) });
  const [label, setLabel] = useState('');
  const token = useMutation({ mutationFn: () => call(api.notifications.POST('/api/notifications/v1/suppliers/{supplier_id}/telegram/link-token', { params: { path: { supplier_id: supplierId } }, body: { label: label.trim() } })) });
  const unlink = useMutation({
    mutationFn: (linkId: string) => call(api.notifications.POST('/api/notifications/v1/suppliers/{supplier_id}/telegram/unlink', { params: { path: { supplier_id: supplierId } }, body: { link_id: linkId } })),
    onSuccess: (d) => qc.setQueryData(key, d),
  });
  const s = q.data;
  const can = user.has('purchasing.order');
  return (
    <Card title="Telegram">
      <div className="flex flex-col gap-2 text-[13px]">
        <span className="text-[12px] text-neutral-500">{t('stg.hint')}</span>
        {s && !s.bot_configured && <Alert tone="info">{t('telegram.notConfigured')}</Alert>}
        {s?.links.length === 0 && <span className="text-neutral-600">{t('stg.none')}</span>}
        {s?.links.map((l) => (
          <div key={l.id} className="flex items-center justify-between gap-2 border-b border-neutral-100 py-1">
            <span>{l.label || '—'} <span className="text-[12px] text-neutral-500">· {dateTime(l.linked_at)}</span></span>
            {can && <Button size="sm" variant="danger-outline" onClick={() => unlink.mutate(l.id)}>{t('telegram.unlink')}</Button>}
          </div>
        ))}
        {can && s?.bot_configured && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('stg.contact')} className="w-64">{(id) => <Input id={id} maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} />}</Field>
            <Button disabled={!label.trim()} loading={token.isPending} onClick={() => token.mutate()}>{t('stg.link')}</Button>
          </div>
        )}
        {token.data?.url && <p className="m-0 rounded-md bg-neutral-50 px-3 py-2">{t('stg.send', { when: dateTime(token.data.expires_at) })} <span className="break-all font-medium">{token.data.url}</span></p>}
        <ApiErrorAlert error={q.error ?? token.error ?? unlink.error} />
      </div>
    </Card>
  );
}
