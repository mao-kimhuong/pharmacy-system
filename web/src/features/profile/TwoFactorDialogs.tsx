// Turning 2FA off, a new key (two steps) and new backup codes: each asks for the password and a code or backup code.
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { isApiError } from '@/api/errors';
import { useAuth } from '@/app/auth';
import { ApiErrorAlert, Button, Dialog, Field, Input, OtpInput, useToast } from '@/design';
import { BackupCodes, KeyPanel } from '../auth/TwoFactorSetup';

export interface Proof { password: string; code?: string; backup_code?: string }

function ProofFields({ value, onChange, error }: { value: Proof; onChange: (p: Proof) => void; error: unknown }) {
  const { t } = useTranslation(['profile', 'auth']);
  const [backup, setBackup] = useState(false);
  const code = isApiError(error) ? error.code : '';
  return (
    <div className="flex flex-col gap-3">
      <Field label={t('auth:password')} required error={code === 'INVALID_CREDENTIALS' ? t('twofa.wrongPassword') : undefined}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} type="password" autoComplete="current-password" autoFocus value={value.password} onChange={(e) => onChange({ ...value, password: e.target.value })} />}</Field>
      {backup ? (
        <Field label={t('auth:code.backupLabel')} required hint={t('auth:code.backupHint')} error={code === 'INVALID_MFA_CODE' ? t('twofa.wrongCode') : undefined}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} autoComplete="off" value={value.backup_code ?? ''} onChange={(e) => onChange({ password: value.password, backup_code: e.target.value.trim() })} />}</Field>
      ) : (
        <div className="flex flex-col gap-2">
          <span className="text-[13px] font-medium">{t('auth:setup.enterCode')}</span>
          <OtpInput value={value.code ?? ''} onChange={(c) => onChange({ password: value.password, code: c })} autoFocus={false} invalid={code === 'INVALID_MFA_CODE'} />
          {code === 'INVALID_MFA_CODE' && <span role="alert" className="text-[12px] text-danger">✕ {t('twofa.wrongCode')}</span>}
        </div>
      )}
      <button type="button" className="self-start text-[13px] font-medium text-primary-600" onClick={() => { setBackup(!backup); onChange({ password: value.password }); }}>{backup ? t('auth:code.useApp') : t('auth:code.useBackup')}</button>
      {code !== 'INVALID_CREDENTIALS' && code !== 'INVALID_MFA_CODE' && <ApiErrorAlert error={error} />}
    </div>
  );
}

const ready = (p: Proof) => !!p.password && ((p.code?.length ?? 0) === 6 || (p.backup_code?.length ?? 0) >= 10);

export function TurnOffDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(['profile', 'common']);
  const { reloadMe } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [proof, setProof] = useState<Proof>({ password: '' });
  const off = useMutation({
    mutationFn: () => call(api.auth.POST('/api/auth/v1/me/2fa/disable', { body: proof })),
    onSuccess: async () => { toast.success(t('twofa.turnedOff')); await reloadMe(); await qc.invalidateQueries({ queryKey: ['auth', 'sessions'] }); onClose(); },
  });
  return (
    <Dialog open onClose={onClose} title={t('twofa.turnOffTitle')} width={480}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="danger" disabled={!ready(proof)} loading={off.isPending} onClick={() => off.mutate()}>{t('twofa.turnOff')}</Button></>}>
      <div className="flex flex-col gap-3">
        <span className="text-[13px] text-neutral-700">{t('twofa.turnOffBody')}</span>
        <ProofFields value={proof} onChange={setProof} error={off.error} />
      </div>
    </Dialog>
  );
}

export function NewCodesDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(['profile', 'auth', 'common']);
  const { reloadMe } = useAuth();
  const [proof, setProof] = useState<Proof>({ password: '' });
  const codes = useMutation({ mutationFn: () => call(api.auth.POST('/api/auth/v1/2fa/backup-codes', { body: proof })), onSuccess: () => void reloadMe() });
  return (
    <Dialog open onClose={onClose} title={t('auth:backup.regenerate')} width={520}
      footer={codes.data ? <Button variant="primary" onClick={onClose}>{t('common:action.done')}</Button> : <><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!ready(proof)} loading={codes.isPending} onClick={() => codes.mutate()}>{t('common:action.continue')}</Button></>}>
      {codes.data ? <BackupCodes codes={codes.data.codes} /> : (
        <div className="flex flex-col gap-3">
          <span className="text-[13px] text-neutral-700">{t('auth:backup.regenerateBody')}</span>
          <ProofFields value={proof} onChange={setProof} error={codes.error} />
        </div>
      )}
    </Dialog>
  );
}

/** Step 1 proof → step 2 scan and confirm → the new backup codes. The old key works until step 2 is confirmed. */
export function ResetKeyDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(['profile', 'auth', 'common']);
  const { reloadMe } = useAuth();
  const qc = useQueryClient();
  const [proof, setProof] = useState<Proof>({ password: '' });
  const [code, setCode] = useState('');
  const start = useMutation({ mutationFn: () => call(api.auth.POST('/api/auth/v1/me/2fa/reset', { body: proof })) });
  const confirm = useMutation({
    mutationFn: (c: string) => call(api.auth.POST('/api/auth/v1/me/2fa/reset/confirm', { body: { code: c } })),
    onSuccess: async () => { await reloadMe(); await qc.invalidateQueries({ queryKey: ['auth', 'sessions'] }); },
  });
  const done = confirm.data;
  return (
    <Dialog open onClose={onClose} title={t('twofa.resetTitle')} width={520}
      footer={done ? <Button variant="primary" onClick={onClose}>{t('common:action.done')}</Button>
        : start.data ? <><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={code.length !== 6} loading={confirm.isPending} onClick={() => confirm.mutate(code)}>{t('auth:setup.confirm')}</Button></>
          : <><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!ready(proof)} loading={start.isPending} onClick={() => start.mutate()}>{t('common:action.continue')}</Button></>}>
      {done ? <BackupCodes codes={done.codes} /> : start.data ? (
        <div className="flex flex-col gap-4">
          <span className="text-[13px] text-neutral-700">{t('twofa.resetScan')}</span>
          <KeyPanel secret={start.data.secret} qr={start.data.qr_svg} />
          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium">{t('auth:setup.enterCode')}</span>
            <OtpInput value={code} onChange={setCode} autoFocus={false} invalid={!!confirm.error} />
          </div>
          <ApiErrorAlert error={confirm.error} />
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <span className="text-[13px] text-neutral-700">{t('twofa.resetBody')}</span>
          <ProofFields value={proof} onChange={setProof} error={start.error} />
        </div>
      )}
    </Dialog>
  );
}
