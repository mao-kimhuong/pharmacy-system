// 15d (scan → confirm → backup codes) and 15e (forced for owner / branch manager, no skip). Also used from
// My profile to turn 2FA on.
import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { session } from '@/api/session';
import { ApiErrorAlert, Button, OtpInput, Spinner, Stepper } from '@/design';

export function BackupCodes({ codes, onDone, doneLabel }: { codes: string[]; onDone?: () => void; doneLabel?: string }) {
  const { t } = useTranslation(['auth', 'common']);
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <b className="text-[17px]">{t('backup.title')}</b>
        <span className="text-[13px] text-neutral-700">{t('backup.sub')}</span>
      </div>
      <ol aria-label={t('setup.step3')} className="m-0 grid list-none grid-cols-2 gap-2 rounded-lg border border-neutral-200 bg-neutral-50 p-4 font-mono text-[14px]">
        {codes.map((c, i) => <li key={c}><span className="mr-2 text-neutral-400">{i + 1}.</span>{c}</li>)}
      </ol>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => { void navigator.clipboard?.writeText(codes.join('\n')); setCopied(true); }}>{copied ? t('common:action.copied') : t('backup.copyAll')}</Button>
        <Button onClick={() => window.print()}>{t('common:action.print')}</Button>
        {onDone && <Button variant="primary" className="ml-auto" onClick={onDone}>{doneLabel ?? t('backup.saved')}</Button>}
      </div>
    </div>
  );
}

export function TwoFactorSetup({ onEnabled }: { onEnabled: (codes: string[] | null) => void }) {
  const { t } = useTranslation(['auth', 'common']);
  const [code, setCode] = useState('');
  const [copied, setCopied] = useState(false);
  const setup = useMutation({ mutationFn: () => call(api.auth.POST('/api/auth/v1/2fa/setup')) });
  const enable = useMutation({
    mutationFn: (c: string) => call(api.auth.POST('/api/auth/v1/2fa/enable', { body: { code: c } })),
    onSuccess: (res) => {
      if (res.access_token) session.set(res.access_token);
    },
  });
  const { mutate } = setup;
  useEffect(() => mutate(), [mutate]);
  return (
    <div className="flex flex-col gap-5">
      <Stepper current={enable.data ? 2 : 0} steps={[{ label: t('setup.step1') }, { label: t('setup.step2') }, { label: t('setup.step3') }]} />
      {enable.data ? (
        <BackupCodes codes={enable.data.backup_codes ?? []} onDone={() => onEnabled(enable.data.backup_codes ?? null)} />
      ) : (
        <>
          <div className="flex flex-col gap-1">
            <b className="text-[17px]">{t('setup.title')}</b>
            <span className="text-[13px] text-neutral-500">{t('setup.sub')}</span>
          </div>
          {setup.isPending && <Spinner />}
          <ApiErrorAlert error={setup.error} />
          {setup.data && (
            <div className="flex flex-wrap items-center gap-4">
              {/* qr_svg comes from our own auth service; shown as an image, never as inline markup. */}
              <img alt="QR" className="size-40 rounded-lg border border-neutral-200 bg-white p-2" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(setup.data.qr_svg)}`} />
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="text-[13px] text-neutral-500">{t('setup.cantScan')}</span>
                <code className="font-mono text-[14px] break-all">{setup.data.secret.replace(/(.{4})/g, '$1 ').trim()}</code>
                <button type="button" className="self-start text-[13px] font-medium text-primary-600" onClick={() => { void navigator.clipboard?.writeText(setup.data!.secret); setCopied(true); }}>
                  {copied ? t('common:action.copied') : t('setup.copyKey')}
                </button>
              </div>
            </div>
          )}
          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium">{t('setup.enterCode')}</span>
            <OtpInput value={code} onChange={setCode} autoFocus={false} invalid={!!enable.error} onComplete={(c) => enable.mutate(c)} />
          </div>
          <ApiErrorAlert error={enable.error} />
          <Button variant="primary" size="lg" block disabled={code.length !== 6 || !setup.data} loading={enable.isPending} onClick={() => enable.mutate(code)}>{t('setup.confirm')}</Button>
        </>
      )}
    </div>
  );
}
