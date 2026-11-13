// 14i My profile: details, password, PIN (15j), 2FA + backup codes (15d/15k), signed-in devices (revoke).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useAuth, useUser } from '@/app/auth';
import { branchName, useBranch } from '@/app/branch';
import { ApiErrorAlert, BranchTag, Button, Card, ConfirmDialog, DataTable, DefinitionList, Dialog, Field, Input, PageHeader, StatusPill, useToast } from '@/design';
import { dateTime } from '@/lib/format';
import { TwoFactorSetup } from '../auth/TwoFactorSetup';
import { SetPinDialog } from './SetPin';
import { NewCodesDialog, ResetKeyDialog, TurnOffDialog } from './TwoFactorDialogs';

function PasswordCard() {
  const { t } = useTranslation(['profile', 'states']);
  const toast = useToast();
  const [cur, setCur] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [touched, setTouched] = useState(false);
  const m = useMutation({
    mutationFn: () => call(api.auth.POST('/api/auth/v1/me/password', { body: { current_password: cur, new_password: next } })),
    onSuccess: () => { toast.success(t('password.changed')); setCur(''); setNext(''); setAgain(''); setTouched(false); },
  });
  const mismatch = touched && again !== next;
  return (
    <Card title={t('password.title')}>
      <form className="flex max-w-[420px] flex-col gap-3" onSubmit={(e) => { e.preventDefault(); setTouched(true); if (next && next === again && cur) m.mutate(); }}>
        <Field label={t('password.current')} required>{(id) => <Input id={id} type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} />}</Field>
        <Field label={t('password.new')} required hint={t('password.hint')}>{(id, d) => <Input id={id} aria-describedby={d} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />}</Field>
        <Field label={t('password.repeat')} required error={mismatch ? t('password.mismatch') : undefined}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} onBlur={() => setTouched(true)} />}</Field>
        <ApiErrorAlert error={m.error} />
        <div><Button type="submit" variant="primary" loading={m.isPending}>{t('password.change')}</Button></div>
      </form>
    </Card>
  );
}

function TwoFactorCard() {
  const { t } = useTranslation(['profile', 'auth', 'common']);
  const user = useUser();
  const { reloadMe } = useAuth();
  const [open, setOpen] = useState<'setup' | 'off' | 'codes' | 'reset' | null>(null);
  const close = () => setOpen(null);
  return (
    <Card title={<span id="twofa">{t('twofa.title')}</span>}>
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill tone={user.totp_enabled ? 'success' : 'neutral'}>{user.totp_enabled ? t('twofa.on') : t('twofa.off')}</StatusPill>
        {user.totp_enabled && user.backup_codes_left !== null && user.backup_codes_left !== undefined && (
          <span className="text-[13px] text-neutral-700">{t('auth:backup.left', { count: user.backup_codes_left })}</span>
        )}
        {user.mfa_required_for_role && <span className="text-[12px] text-neutral-500">{t('twofa.required')}</span>}
        <span className="ml-auto" />
        {user.totp_enabled ? <>
          <Button onClick={() => setOpen('codes')}>{t('auth:backup.regenerate')}</Button>
          {user.mfa_required_for_role
            ? <Button onClick={() => setOpen('reset')}>{t('twofa.reset')}</Button>
            : <Button variant="danger-outline" onClick={() => setOpen('off')}>{t('twofa.turnOff')}</Button>}
        </> : (
          <Button variant="primary" onClick={() => setOpen('setup')}>{t('twofa.turnOn')}</Button>
        )}
      </div>
      <Dialog open={open === 'setup'} onClose={close} title={t('auth:setup.title')} width={520}>
        {open === 'setup' && <TwoFactorSetup onEnabled={() => { close(); void reloadMe(); }} />}
      </Dialog>
      {open === 'off' && <TurnOffDialog onClose={close} />}
      {open === 'codes' && <NewCodesDialog onClose={close} />}
      {open === 'reset' && <ResetKeyDialog onClose={close} />}
    </Card>
  );
}

/** T2: link your own Telegram (approval buttons in the branch / owner chat, bot commands). */
function TelegramCard() {
  const { t } = useTranslation(['profile', 'common']);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['notifications', 'me'], queryFn: () => call(api.notifications.GET('/api/notifications/v1/me/telegram')) });
  const token = useMutation({ mutationFn: () => call(api.notifications.POST('/api/notifications/v1/me/telegram/link-token')) });
  const unlink = useMutation({ mutationFn: () => call(api.notifications.POST('/api/notifications/v1/me/telegram/unlink')), onSuccess: (d) => qc.setQueryData(['notifications', 'me'], d) });
  const s = q.data;
  return (
    <Card title={<span id="telegram">Telegram</span>}>
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          {s && <StatusPill tone={s.linked ? 'success' : 'neutral'}>{s.linked ? t('tg.linked', { when: dateTime(s.linked_at) }) : t('tg.notLinked')}</StatusPill>}
          <span className="ml-auto" />
          {s && !s.linked && s.bot_configured && <Button variant="primary" loading={token.isPending} onClick={() => token.mutate()}>{t('tg.link')}</Button>}
          {s?.linked && <Button variant="danger-outline" loading={unlink.isPending} onClick={() => unlink.mutate()}>{t('tg.unlink')}</Button>}
        </div>
        <span className="text-[13px] text-neutral-700">{s?.can_approve ? t('tg.approveHint') : t('tg.hint')}</span>
        {s && !s.bot_configured && <span className="text-[12px] text-neutral-500">{t('tg.notConfigured')}</span>}
        {token.data?.url && (
          <p className="m-0 rounded-md bg-neutral-50 px-3 py-2 text-[13px]">
            {t('tg.open', { when: dateTime(token.data.expires_at) })}{' '}
            <a className="font-medium text-primary-700 underline" href={token.data.url} target="_blank" rel="noreferrer" onClick={() => setTimeout(() => void q.refetch(), 15_000)}>{token.data.url}</a>
          </p>
        )}
        <ApiErrorAlert error={q.error ?? token.error ?? unlink.error} />
      </div>
    </Card>
  );
}

function SessionsCard() {
  const { t } = useTranslation(['profile', 'common']);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['auth', 'sessions'], queryFn: () => call(api.auth.GET('/api/auth/v1/me/sessions')) });
  const [revoke, setRevoke] = useState<string | null>(null);
  return (
    <Card title={t('sessions.title')} padded={false}>
      <DataTable
        className="rounded-none border-0"
        minWidth={560}
        rows={q.data}
        loading={q.isLoading}
        error={q.error}
        onRetry={() => void q.refetch()}
        rowKey={(r) => r.id}
        columns={[
          { key: 'ua', header: t('common:label.details'), cell: (r) => <span className="flex flex-col"><span>{r.user_agent ?? t('sessions.unknown')}</span><span className="text-[12px] text-neutral-500">{r.ip}</span></span> },
          { key: 'start', header: t('sessions.started'), cell: (r) => dateTime(r.started_at) },
          { key: 'last', header: t('sessions.lastUsed'), cell: (r) => dateTime(r.last_used_at) },
          { key: 'x', header: '', align: 'right', cell: (r) => r.current ? <StatusPill tone="primary">{t('sessions.current')}</StatusPill> : <Button size="sm" variant="danger-outline" onClick={() => setRevoke(r.id)}>{t('sessions.revoke')}</Button> },
        ]}
      />
      <ConfirmDialog open={!!revoke} onClose={() => setRevoke(null)} title={t('sessions.revokeTitle')} body={t('sessions.revokeBody')} confirmLabel={t('sessions.revoke')} variant="danger"
        onConfirm={async () => { await call(api.auth.POST('/api/auth/v1/me/sessions/{session_id}/revoke', { params: { path: { session_id: revoke! } } })); await qc.invalidateQueries({ queryKey: ['auth', 'sessions'] }); }} />
    </Card>
  );
}

export default function ProfilePage() {
  const { t, i18n } = useTranslation(['profile', 'shell', 'common', 'nav']);
  const user = useUser();
  const { reloadMe } = useAuth();
  const branches = useBranch();
  const toast = useToast();
  const [pin, setPin] = useState(false);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('title')} />
      <div className="grid gap-4 desktop:grid-cols-2">
        <Card title={t('details')}>
          <DefinitionList items={[
            { label: t('common:label.name'), value: user.name },
            { label: t('common:label.phone'), value: user.phone },
            { label: t('common:label.role'), value: t(`shell:role.${user.role}`, { defaultValue: user.role }) },
            { label: t('pharmacist'), value: user.is_pharmacist ? t('common:label.yes') : t('common:label.no') },
            { label: t('common:label.branches'), value: <span className="flex flex-wrap gap-1">{user.isOwner ? t('common:label.allBranches') : user.branch_ids.map((id) => { const b = branches.byId(id); return <span key={id} className="flex items-center gap-1"><BranchTag code={b?.code ?? '?'} />{branchName(b, i18n.language)}</span>; })}</span> },
          ]} />
        </Card>
        <Card title={<span id="pin">{t('pin.title')}</span>}>
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill tone={user.has_pin ? 'success' : 'warning'}>{user.has_pin ? t('pin.has') : t('pin.set')}</StatusPill>
            {!user.has_pin && <span className="text-[13px] text-neutral-700">{t('pin.none')}</span>}
            <Button className="ml-auto" variant={user.has_pin ? 'secondary' : 'primary'} onClick={() => setPin(true)}>{user.has_pin ? t('pin.change') : t('pin.set')}</Button>
          </div>
        </Card>
        <PasswordCard />
      </div>
      <h2 className="m-0 mt-2 text-[20px] leading-[28px] font-semibold">{t('security')}</h2>
      <TwoFactorCard />
      <TelegramCard />
      <SessionsCard />
      <SetPinDialog open={pin} onClose={() => setPin(false)} onSaved={() => { toast.success(t('auth:pin.saved')); void reloadMe(); }} />
    </div>
  );
}
