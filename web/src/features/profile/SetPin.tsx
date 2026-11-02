// 15j: enter the PIN twice on the pad, then the password to save it (PUT auth me/pin).
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { Alert, ApiErrorAlert, Button, Dialog, Field, Input, PinPad } from '@/design';

export function SetPinDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation(['auth', 'common']);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [first, setFirst] = useState('');
  const [second, setSecond] = useState('');
  const [password, setPassword] = useState('');
  const [mismatch, setMismatch] = useState(false);
  const save = useMutation({
    mutationFn: () => call(api.auth.PUT('/api/auth/v1/me/pin', { body: { password, pin: first } })),
    onSuccess: () => { onSaved(); close(); },
  });
  const close = () => {
    setStep(1); setFirst(''); setSecond(''); setPassword(''); setMismatch(false); save.reset();
    onClose();
  };
  return (
    <Dialog open={open} onClose={close} width={400} title={step === 1 ? t('pin.setTitle') : step === 2 ? t('pin.confirmTitle') : t('pin.passwordToSave')}
      subtitle={step < 3 ? t('pin.step', { n: step }) : undefined}
      footer={
        <>
          <Button onClick={close}>{t('common:action.cancel')}</Button>
          {step === 1 && <Button variant="primary" disabled={first.length < 4} onClick={() => { setStep(2); setMismatch(false); }}>{t('common:action.next')}</Button>}
          {step === 2 && <Button variant="primary" disabled={second.length < 4} onClick={() => {
            if (second !== first) { setMismatch(true); setFirst(''); setSecond(''); setStep(1); } else setStep(3);
          }}>{t('common:action.next')}</Button>}
          {step === 3 && <Button variant="primary" loading={save.isPending} disabled={!password} onClick={() => save.mutate()}>{t('common:action.save')}</Button>}
        </>
      }>
      <div className="flex flex-col items-center gap-4">
        {step < 3 && <span className="text-center text-[13px] text-neutral-700">{t('pin.sub')}</span>}
        {mismatch && <Alert tone="danger" className="w-full">{t('pin.mismatch')}</Alert>}
        {step === 1 && <PinPad key="a" value={first} onChange={setFirst} />}
        {step === 2 && <PinPad key="b" value={second} onChange={setSecond} />}
        {step < 3 && <span className="text-center text-[12px] text-neutral-500">{t('pin.rule')}</span>}
        {step === 3 && (
          <Field label={t('password')} className="w-full">
            {(id) => <Input id={id} type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />}
          </Field>
        )}
        <ApiErrorAlert error={save.error} className="w-full" />
      </div>
    </Dialog>
  );
}
