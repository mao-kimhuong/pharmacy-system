// 14g Telegram: one chat per branch (+ the owner's chat, owner only), on / off, test message; the message log with
// status and errors; the owner can queue today's 20:00 summary now. 18c Notification settings: the large-discount
// alert thresholds (the only settings the API has).
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { useFeatures } from '@/app/features';
import { branchName, useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, Button, Card, DataTable, Field, Input, PageHeader, Select, SkeletonRows, StatusPill, Switch, TextArea, Toolbar, useToast, type PillTone } from '@/design';
import { dateTime } from '@/lib/format';
import { FridgeSensors } from './FridgeSensors';

const STATUS: Record<string, PillTone> = { sent: 'success', queued: 'info', failed: 'danger', skipped: 'neutral' };

function ChatRow({ target, label, chat }: { target: string; label: string; chat?: { chat_id: string; is_active: boolean } }) {
  const { t } = useTranslation(['settings', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const [id, setId] = useState(chat?.chat_id ?? '');
  const [on, setOn] = useState(chat?.is_active ?? true);
  useEffect(() => { setId(chat?.chat_id ?? ''); setOn(chat?.is_active ?? true); }, [chat?.chat_id, chat?.is_active]);
  const save = useMutation({
    mutationFn: () => call(api.notifications.PUT('/api/notifications/v1/chats/{target}', { params: { path: { target } }, body: { chat_id: id.trim(), is_active: on } })),
    onSuccess: () => { toast.success(t('branches.saved')); void qc.invalidateQueries({ queryKey: ['notifications'] }); },
  });
  const test = useMutation({
    mutationFn: () => call(api.notifications.POST('/api/notifications/v1/test', { body: { target } })),
    onSuccess: () => { toast.success(t('telegram.queued')); void qc.invalidateQueries({ queryKey: ['notifications', 'messages'] }); },
  });
  const dirty = id.trim() !== (chat?.chat_id ?? '') || on !== (chat?.is_active ?? true);
  return (
    <div className="flex flex-col gap-2 border-t border-neutral-100 py-3 first:border-t-0">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-40 flex-1 text-[14px] font-medium">{label}</div>
        <Field label={t('telegram.chatId')} className="w-56">{(fid) => <Input id={fid} placeholder="-1001234567890" value={id} onChange={(e) => setId(e.target.value)} />}</Field>
        <div className="pb-2"><Switch label={t('telegram.active')} checked={on} onChange={setOn} /></div>
        <Button disabled={!dirty || !id.trim()} loading={save.isPending} onClick={() => save.mutate()}>{t('common:action.save')}</Button>
        <Button disabled={!chat || dirty} loading={test.isPending} onClick={() => test.mutate()}>{t('telegram.test')}</Button>
      </div>
      <ApiErrorAlert error={save.error ?? test.error} />
    </div>
  );
}

export default function TelegramPage() {
  const { t, i18n } = useTranslation(['settings', 'common', 'nav']);
  const user = useUser();
  const toast = useToast();
  const qc = useQueryClient();
  const { branches, byId } = useBranch();
  const [status, setStatus] = useState('');
  const chats = useQuery({ queryKey: ['notifications', 'chats'], queryFn: () => call(api.notifications.GET('/api/notifications/v1/chats')) });
  const msgs = useQuery({ queryKey: ['notifications', 'messages', status], queryFn: () => call(api.notifications.GET('/api/notifications/v1/messages', { params: { query: { status: status || undefined, limit: 200 } } })) });
  const run = useMutation({
    mutationFn: () => call(api.notifications.POST('/api/notifications/v1/daily-summary/run')),
    onSuccess: (r) => { toast.success(`${t('telegram.queued')}: ${r.queued}`); void qc.invalidateQueries({ queryKey: ['notifications', 'messages'] }); },
  });
  const chat = (target: string) => chats.data?.find((c) => c.target === target);
  const targetLabel = (target: string) => (target === 'owner' ? t('telegram.owner')
    : ['customer', 'supplier', 'staff', 'chat'].includes(target.split(':')[0]) ? t(`telegram.role.${target.split(':')[0]}`)
      : branchName(byId(target), i18n.language));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('telegram.title')}
        actions={user.isOwner && <Button loading={run.isPending} onClick={() => run.mutate()}>{t('telegram.runSummary')}</Button>} />
      <ApiErrorAlert error={run.error ?? chats.error} />
      <Card title={t('telegram.chats')}>
        {/* rows only once the saved chats are here: arriving later they would reset what was typed */}
        {chats.isPending ? <SkeletonRows rows={branches.length + (user.isOwner ? 1 : 0)} /> : <>
          {user.isOwner && <ChatRow target="owner" label={t('telegram.owner')} chat={chat('owner')} />}
          {branches.map((b) => <ChatRow key={b.id} target={b.id} label={`${b.code} · ${branchName(b, i18n.language)}`} chat={chat(b.id)} />)}
        </>}
      </Card>
      {user.has('notifications.customers') && <Campaign />}
      <h2 className="text-[15px] font-semibold">{t('telegram.messages')}</h2>
      <span className="text-[12px] text-neutral-500">{t('telegram.privateNote')}</span>
      <Toolbar>
        <Select aria-label={t('common:label.status')} className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t('common:label.status')}: —</option>
          {Object.keys(STATUS).map((s) => <option key={s} value={s}>{t(`telegram.status.${s}`)}</option>)}
        </Select>
      </Toolbar>
      <DataTable rows={msgs.data} loading={msgs.isLoading} error={msgs.error} onRetry={() => void msgs.refetch()} rowKey={(r) => r.id} dense
        columns={[
          { key: 'w', header: t('log.when'), cell: (r) => <span className="whitespace-nowrap tabular-nums">{dateTime(r.sent_at ?? r.created_at)}</span> },
          { key: 't', header: t('telegram.target'), cell: (r) => targetLabel(r.target) },
          { key: 'k', header: t('common:label.type'), cell: (r) => <span className="font-mono text-[12px]">{r.kind}</span> },
          { key: 'x', header: t('telegram.messages'), cell: (r) => <span className="line-clamp-2 whitespace-pre-line text-[12px]">{r.text || <i className="text-neutral-500">{r.summary}</i>}</span> },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={STATUS[r.status] ?? 'neutral'}>{t(`telegram.status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
          { key: 'a', header: t('telegram.attempts'), align: 'right', cell: (r) => r.attempts },
          { key: 'e', header: t('telegram.error'), cell: (r) => <span className="text-[12px] text-danger">{r.last_error ?? ''}</span> },
        ]} />
    </div>
  );
}

/** A promotion to linked customers who allow promotions (at most 2 a month each; sent 07:00–21:00). */
function Campaign() {
  const { t } = useTranslation(['settings', 'common']);
  const qc = useQueryClient();
  const [v, setV] = useState({ title: '', text_km: '', text_en: '' });
  const send = useMutation({
    mutationFn: () => call(api.notifications.POST('/api/notifications/v1/campaigns', { body: v })),
    onSuccess: () => { setV({ title: '', text_km: '', text_en: '' }); void qc.invalidateQueries({ queryKey: ['notifications', 'messages'] }); },
  });
  return (
    <Card title={t('telegram.campaign')}>
      <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
        <span className="text-[12px] text-neutral-500">{t('telegram.campaignHint')}</span>
        <Field label={t('telegram.campaignTitle')} required>{(id) => <Input id={id} maxLength={120} value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />}</Field>
        <div className="grid grid-cols-1 gap-3 tablet:grid-cols-2">
          <Field label={t('telegram.textKm')} required>{(id) => <TextArea id={id} rows={3} maxLength={900} className="km" value={v.text_km} onChange={(e) => setV({ ...v, text_km: e.target.value })} />}</Field>
          <Field label={t('telegram.textEn')} required>{(id) => <TextArea id={id} rows={3} maxLength={900} value={v.text_en} onChange={(e) => setV({ ...v, text_en: e.target.value })} />}</Field>
        </div>
        {send.data && <Alert tone="success">{t('telegram.campaignDone', { queued: send.data.queued, over: send.data.over_cap })}</Alert>}
        <ApiErrorAlert error={send.error} />
        <div><Button type="submit" variant="primary" disabled={!v.title.trim() || !v.text_km.trim() || !v.text_en.trim()} loading={send.isPending}>{t('telegram.campaignSend')}</Button></div>
      </form>
    </Card>
  );
}

export function NotificationSettingsPage() {
  const { t } = useTranslation(['settings', 'common', 'nav']);
  const toast = useToast();
  const q = useQuery({ queryKey: ['notifications', 'settings'], queryFn: () => call(api.notifications.GET('/api/notifications/v1/settings')) });
  const fridges = !!useFeatures().data?.find((f) => f.key === 'fridge_sensors')?.enabled;
  const [v, setV] = useState({ pct: '', usd: '', tg: '' });
  useEffect(() => { if (q.data) setV({ pct: q.data.large_discount_pct, usd: q.data.large_discount_usd, tg: String(q.data.telegram_approval_max_usd ?? '100') }); }, [q.data]);
  const save = useMutation({
    mutationFn: () => call(api.notifications.PUT('/api/notifications/v1/settings', { body: { large_discount_pct: v.pct, large_discount_usd: v.usd, telegram_approval_max_usd: v.tg || '0' } })),
    onSuccess: () => toast.success(t('branches.saved')),
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('notify.title')} />
      <Alert tone="info">{t('notify.fixed')}</Alert>
      <Card>
        <form className="grid grid-cols-1 items-end gap-3 tablet:grid-cols-[1fr_1fr_1fr_auto]" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label={t('notify.largePct')}>{(id) => <Input id={id} inputMode="decimal" suffix="%" disabled={!q.data} value={v.pct} onChange={(e) => setV({ ...v, pct: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
          <Field label={t('notify.largeUsd')}>{(id) => <Input id={id} inputMode="decimal" prefix="$" disabled={!q.data} value={v.usd} onChange={(e) => setV({ ...v, usd: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
          <Field label={t('notify.tgLimit')} hint={t('notify.tgLimitHint')}>{(id, d) => <Input id={id} aria-describedby={d} inputMode="decimal" prefix="$" disabled={!q.data} value={v.tg} onChange={(e) => setV({ ...v, tg: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
          <Button type="submit" variant="primary" disabled={!q.data || !v.pct || !v.usd} loading={save.isPending}>{t('common:action.save')}</Button>
        </form>
        <ApiErrorAlert error={q.error ?? save.error} className="mt-3" />
      </Card>
      {fridges && <FridgeSensors />}
    </div>
  );
}
