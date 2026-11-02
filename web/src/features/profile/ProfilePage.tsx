// 14i My profile: details, password, PIN (15j), 2FA + backup codes (15d/15k), signed-in devices (revoke).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useAuth, useUser } from '@/app/auth';
import { branchName, useBranch } from '@/app/branch';
import { ApiErrorAlert, BranchTag, Button, Card, ConfirmDialog, DataTable, DefinitionList, Dialog, Field, Input, PageHeader, StatusPill, useToast } from '@/design';
import { dateTime } from '@/lib/format';
import { BackupCodes, TwoFactorSetup } from '../auth/TwoFactorSetup';
import { SetPinDialog } from './SetPin';

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
  const [setup, setSetup] = useState(false);
  const [regen, setRegen] = useState(false);
  const [password, setPassword] = useState('');
  const codes = useMutation({ mutationFn: () => call(api.auth.POST('/api/auth/v1/2fa/backup-codes', { body: { password } })), onSuccess: () => void reloadMe() });
  const closeRegen = () => { setRegen(false); setPassword(''); codes.reset(); };
  return (
    <Card title={<span id="twofa">{t('twofa.title')}</span>}>
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill tone={user.totp_enabled ? 'success' : 'neutral'}>{user.totp_enabled ? t('twofa.on') : t('twofa.off')}</StatusPill>
        {user.totp_enabled && user.backup_codes_left !== null && user.backup_codes_left !== undefined && (
          <span className="text-[13px] text-neutral-700">{t('auth:backup.left', { count: user.backup_codes_left })}</span>
        )}
        {(user.role === 'owner' || user.role === 'branch_manager') && <span className="text-[12px] text-neutral-500">{t('twofa.required')}</span>}
        <span className="ml-auto" />
        {user.totp_enabled ? (
          <Button onClick={() => setRegen(true)}>{t('auth:backup.regenerate')}</Button>
        ) : (
          <Button variant="primary" onClick={() => setSetup(true)}>{t('twofa.turnOn')}</Button>
        )}
      </div>
      <Dialog open={setup} onClose={() => setSetup(false)} title={t('auth:setup.title')} width={520}>
        {setup && <TwoFactorSetup onEnabled={() => { setSetup(false); void reloadMe(); }} />}
      </Dialog>
      <Dialog open={regen} onClose={closeRegen} title={t('auth:backup.regenerate')} width={520}
        footer={codes.data ? <Button variant="primary" onClick={closeRegen}>{t('common:action.done')}</Button> : <><Button onClick={closeRegen}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!password} loading={codes.isPending} onClick={() => codes.mutate()}>{t('common:action.continue')}</Button></>}>
        {codes.data ? <BackupCodes codes={codes.data.codes} /> : (
          <div className="flex flex-col gap-3">
            <span className="text-[13px] text-neutral-700">{t('auth:backup.regenerateBody')}</span>
            <Field label={t('auth:password')}>{(id) => <Input id={id} type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
            <ApiErrorAlert error={codes.error} />
          </div>
        )}
      </Dialog>
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
        <TwoFactorCard />
      </div>
      <SessionsCard />
      <SetPinDialog open={pin} onClose={() => setPin(false)} onSaved={() => { toast.success(t('auth:pin.saved')); void reloadMe(); }} />
    </div>
  );
}
