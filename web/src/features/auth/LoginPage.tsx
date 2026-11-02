// 15a/15b/15f/15h: phone + password. Wrong password never says which field. ACCOUNT_LOCKED shows the unlock
// time (details.locked_until, UTC) in Phnom Penh with a countdown. "Forgot password?" has no API: the help line
// says who to contact.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isApiError } from '@/api/errors';
import { useAuth } from '@/app/auth';
import { Alert, ApiErrorAlert, Button, Field, Input } from '@/design';
import { date, time } from '@/lib/format';
import { useNow } from '@/lib/hooks';
import { AuthLayout, AuthTitle } from './AuthLayout';

/** "+855 12 334 551" / "012334551" → "012334551" (what the API stores). */
export function normalizePhone(v: string): string {
  const d = v.replace(/\D/g, '');
  if (d.startsWith('855')) return `0${d.slice(3)}`;
  return d.startsWith('0') ? d : d ? `0${d}` : '';
}

function Locked({ until, onBack }: { until: string; onBack: () => void }) {
  const { t } = useTranslation('auth');
  const now = useNow(15_000);
  const mins = Math.max(0, Math.ceil((Date.parse(until) - now.getTime()) / 60_000));
  return (
    <>
      <span className="text-[32px]" aria-hidden>🔒</span>
      <AuthTitle title={t('locked.title')} sub={t('locked.body')} />
      <div className="flex flex-col gap-1 rounded-lg bg-neutral-50 p-4">
        <span className="text-[13px] text-neutral-500">{t('locked.tryAt')}</span>
        <b className="text-[28px] leading-9">{time(until)}</b>
        <span className="text-[13px] text-neutral-700">{t('locked.inMinutes', { count: mins, date: date(until) })}</span>
      </div>
      <span className="text-[13px] text-neutral-700">{t('locked.help')}</span>
      <Button size="lg" block onClick={onBack}>{t('locked.back')}</Button>
    </>
  );
}

export function LoginPage() {
  const { t } = useTranslation(['auth', 'states']);
  const { login } = useAuth();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [touched, setTouched] = useState(false);
  const lockedUntil = isApiError(error) && error.code === 'ACCOUNT_LOCKED' && typeof error.details.locked_until === 'string' ? error.details.locked_until : null;

  if (lockedUntil) return <AuthLayout><Locked until={lockedUntil} onBack={() => setError(null)} /></AuthLayout>;

  const wrong = isApiError(error) && error.code === 'INVALID_CREDENTIALS';
  const attemptsLeft = wrong && typeof error.details.attempts_left === 'number' ? error.details.attempts_left : null;
  const submit = async () => {
    setTouched(true);
    if (!phone || !password) return;
    setBusy(true);
    setError(null);
    try {
      await login(normalizePhone(phone), password);
    } catch (e) {
      setError(e);
      setPassword('');
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthLayout>
      <form className="flex flex-col gap-[18px]" onSubmit={(e) => { e.preventDefault(); void submit(); }} noValidate>
        <AuthTitle title={t('title')} sub={t('sub')} />
        {wrong ? (
          <Alert tone="danger">{t('wrong')}{attemptsLeft !== null ? ` (${attemptsLeft})` : ''}</Alert>
        ) : (
          <ApiErrorAlert error={error} />
        )}
        <Field label={t('phone')} error={touched && !phone ? t('states:fieldErrors.required') : undefined}>
          {(id, d, invalid) => (
            <Input id={id} aria-describedby={d} invalid={invalid} fieldSize="lg" prefix="+855" type="tel" inputMode="tel" autoComplete="username" autoFocus
              value={phone} onChange={(e) => setPhone(e.target.value)} />
          )}
        </Field>
        <Field label={t('password')} error={touched && !password ? t('states:fieldErrors.required') : undefined}>
          {(id, d, invalid) => (
            <Input id={id} aria-describedby={d} invalid={invalid || wrong} fieldSize="lg" type={show ? 'text' : 'password'} autoComplete="current-password"
              value={password} onChange={(e) => setPassword(e.target.value)}
              suffix={<button type="button" className="text-[13px] text-neutral-500" onClick={() => setShow((s) => !s)}>{show ? t('hide') : t('show')}</button>} />
          )}
        </Field>
        <Button type="submit" variant="primary" size="lg" block loading={busy}>{t('cta')}</Button>
        <span className="text-center text-[12px] text-neutral-500">{t('help')}</span>
      </form>
    </AuthLayout>
  );
}
