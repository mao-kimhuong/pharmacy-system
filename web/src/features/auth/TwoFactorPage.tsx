// 15c / 15i: 6-digit code (paste fills the boxes), or a backup code instead.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isApiError } from '@/api/errors';
import { useAuth } from '@/app/auth';
import { ApiErrorAlert, Button, Field, Input, OtpInput } from '@/design';
import { AuthLayout, AuthTitle } from './AuthLayout';

export function TwoFactorPage() {
  const { t } = useTranslation('auth');
  const { verify2fa, cancelMfa } = useAuth();
  const [code, setCode] = useState('');
  const [backup, setBackup] = useState('');
  const [useBackup, setUseBackup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const submit = async (c = code) => {
    if (busy) return;
    if (!useBackup && c.length !== 6) return;
    setBusy(true);
    setError(null);
    try {
      await verify2fa(useBackup ? { backup_code: backup.trim() } : { code: c });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const invalid = isApiError(error) && error.code === 'INVALID_MFA_CODE';
  return (
    <AuthLayout>
      <form className="flex flex-col gap-[18px]" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <button type="button" onClick={cancelMfa} className="self-start text-[13px] font-medium text-primary-600">‹ {t('common:action.back')}</button>
        <AuthTitle title={t('code.title')} sub={useBackup ? t('code.backupHint') : t('code.sub')} />
        {useBackup ? (
          <Field label={t('code.backupLabel')}>
            {(id) => <Input id={id} fieldSize="lg" autoFocus autoComplete="off" className="font-mono" value={backup} onChange={(e) => setBackup(e.target.value)} invalid={invalid} />}
          </Field>
        ) : (
          <OtpInput value={code} onChange={setCode} onComplete={(c) => void submit(c)} invalid={invalid} />
        )}
        <ApiErrorAlert error={error} />
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={useBackup ? backup.trim().length < 10 : code.length !== 6}>{t('code.verify')}</Button>
        <button type="button" className="text-[13px] font-medium text-primary-600" onClick={() => { setUseBackup((u) => !u); setError(null); }}>
          {useBackup ? t('code.useApp') : t('code.useBackup')}
        </button>
      </form>
    </AuthLayout>
  );
}
