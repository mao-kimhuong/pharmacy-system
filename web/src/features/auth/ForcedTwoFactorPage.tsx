// 15e: owner / branch manager without 2FA. Only /me, /2fa/setup, /2fa/enable and /logout work until it is on.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '@/app/auth';
import { Alert, Button } from '@/design';
import { AuthLayout } from './AuthLayout';
import { TwoFactorSetup } from './TwoFactorSetup';

export function ForcedTwoFactorPage() {
  const { t } = useTranslation(['auth', 'shell']);
  const { me, logout, completeSetup } = useAuth();
  const [started, setStarted] = useState(false);
  return (
    <AuthLayout>
      {started ? (
        <TwoFactorSetup onEnabled={() => completeSetup(null)} />
      ) : (
        <>
          <span className="text-[32px]" aria-hidden>🔐</span>
          <div className="flex flex-col gap-1">
            <h1 className="m-0 text-[24px] leading-8 font-bold">{t('forced.title')}</h1>
            <span className="text-[14px] text-neutral-700">{t('forced.body')}</span>
          </div>
          <Alert tone="warning">MFA_SETUP_REQUIRED · {me?.name} · {t(`shell:role.${me?.role}`, { defaultValue: me?.role })}. {t('forced.note')}</Alert>
          <Button variant="primary" size="lg" block onClick={() => setStarted(true)}>{t('setup.start')}</Button>
          <Button size="lg" block onClick={() => void logout()}>{t('forced.logout')}</Button>
        </>
      )}
    </AuthLayout>
  );
}
