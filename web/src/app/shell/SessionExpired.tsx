// 16h: the refresh failed while working. Re-enter the password (2FA again if needed); the page stays as it was.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { session } from '@/api/session';
import { ApiErrorAlert, Button, Dialog, Field, Input } from '@/design';
import { useAuth } from '../auth';

export function SessionExpiredDialog() {
  const { t } = useTranslation(['states', 'auth']);
  const { sessionExpired, me, logout } = useAuth();
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [mfa, setMfa] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!sessionExpired || !me) return null;
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = mfa
        ? await call(api.auth.POST('/api/auth/v1/login/2fa', { body: { mfa_token: mfa, code }, headers: { 'X-Refresh-Cookie': '1' } }))
        : await call(api.auth.POST('/api/auth/v1/login', { body: { phone: me.phone, password }, headers: { 'X-Refresh-Cookie': '1' } }));
      if (res.mfa_required && res.mfa_token) setMfa(res.mfa_token);
      else if (res.access_token) {
        session.set(res.access_token);
        setPassword('');
        setCode('');
        setMfa(null);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onClose={() => {}} dismissable={false} title={t('session.title')} width={400}
      footer={<><Button onClick={() => void logout()}>{t('session.switchUser')}</Button><Button variant="primary" loading={busy} onClick={submit}>{t('common:action.continue')}</Button></>}>
      <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <p className="m-0 text-[13px] text-neutral-700">{t('session.body')}</p>
        <div className="text-[13px] font-medium">{me.name} · {me.phone}</div>
        {mfa ? (
          <Field label={t('auth:code.title')}>{(id) => <Input id={id} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />}</Field>
        ) : (
          <Field label={t('auth:password')}>{(id) => <Input id={id} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />}</Field>
        )}
        <ApiErrorAlert error={error} />
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
