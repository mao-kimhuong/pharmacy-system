// PIN pad (Design System §09) and the step-up dialogs: own PIN (POST auth pin/verify) and own PIN + witness
// (pin/verify, then pin/witness). The services consume the one-time tokens; the PIN never leaves auth.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { ApiError, isApiError } from '@/api/errors';
import { errorText } from '@/i18n/errors';
import { time, type Lang } from '@/lib/format';
import { Button } from './Button';
import { Dialog } from './Dialog';
import { Field, Select } from './Field';
import { Alert } from './States';
import { cx } from './cx';

export interface PinPadProps {
  length?: number;
  value: string;
  onChange: (v: string) => void;
  onComplete?: (v: string) => void;
  disabled?: boolean;
  error?: boolean;
  autoFocus?: boolean;
}

/** Dots + 3×4 keypad; the keyboard works too (digits, Backspace). Accepts 4–6 digits (length = max). */
export function PinPad({ length = 6, value, onChange, onComplete, disabled, error, autoFocus = true }: PinPadProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);
  const press = (k: string) => {
    if (disabled) return;
    if (k === '⌫') return onChange(value.slice(0, -1));
    if (k === 'C') return onChange('');
    if (value.length >= length) return;
    const next = value + k;
    onChange(next);
    if (next.length === length) onComplete?.(next);
  };
  return (
    <div
      ref={ref}
      tabIndex={0}
      role="group"
      data-pinpad
      aria-label={t('pin.title')}
      onKeyDown={(e) => {
        if (/^\d$/.test(e.key)) press(e.key);
        else if (e.key === 'Backspace') press('⌫');
        else if (e.key === 'Enter' && value.length >= 4) onComplete?.(value);
        else return;
        e.preventDefault();
      }}
      className="flex flex-col items-center gap-4 rounded-lg outline-none"
    >
      <div className="flex gap-3" aria-live="polite" aria-label={`${value.length} / ${length}`}>
        {Array.from({ length }, (_, i) => (
          <span key={i} className={cx('size-3.5 rounded-full border-2', error ? 'border-danger' : 'border-primary-600', i < value.length && (error ? 'bg-danger' : 'bg-primary-600'))} />
        ))}
      </div>
      <div className="grid w-full max-w-[280px] grid-cols-3 gap-2">
        {['1', '2', '3', '4', '5', '6', '7', '8', '9', 'C', '0', '⌫'].map((k) => (
          <button
            key={k}
            type="button"
            tabIndex={-1}
            disabled={disabled}
            onClick={() => press(k)}
            aria-label={k === '⌫' ? t('pin.delete') : k === 'C' ? t('pin.clear') : k}
            className={cx('h-[52px] rounded-lg border border-neutral-200 text-[20px] font-medium select-none active:bg-primary-100 disabled:opacity-50',
              k === 'C' || k === '⌫' ? 'bg-white text-neutral-700' : 'bg-neutral-50')}
          >
            {k}
          </button>
        ))}
      </div>
    </div>
  );
}

function pinErrorMessage(e: unknown, lang: Lang, t: (k: string, o?: Record<string, unknown>) => string): ReactNode {
  if (!isApiError(e)) return errorText('INTERNAL_ERROR', lang);
  if (e.code === 'PIN_LOCKED') {
    const until = typeof e.details.locked_until === 'string' ? time(e.details.locked_until) : '';
    return (
      <span className="flex flex-col gap-1">
        <b>{t('states:pinLocked.title')}</b>
        <span>{until ? t('states:pinLocked.body', { time: until }) : errorText('PIN_LOCKED', lang)}</span>
        <span>{t('states:pinLocked.hint')}</span>
      </span>
    );
  }
  if (e.code === 'PIN_INVALID' && typeof e.details.attempts_left === 'number') {
    return `${errorText('PIN_INVALID', lang)} (${e.details.attempts_left})`;
  }
  if (e.code === 'PIN_REQUIRED') return t('pin.noPin');
  return errorText(e.code, lang, e.message);
}

export interface PinToken {
  pin_token: string;
  user_id: string;
  name: string;
  expires_at: string;
}

/** Asks the signed-in user's PIN for an action; resolves with the one-time pin_token. */
export function PinDialog({
  open, action, title, context, onClose, onToken,
}: { open: boolean; action: string; title?: ReactNode; context?: ReactNode; onClose: () => void; onToken: (t: PinToken) => void }) {
  const { t, i18n } = useTranslation(['common', 'states']);
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (open) {
      setPin('');
      setError(null);
    }
  }, [open]);
  const submit = async (value: string) => {
    if (value.length < 4 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const out = await call(api.auth.POST('/api/auth/v1/pin/verify', { body: { pin: value, action } }));
      onToken(out);
    } catch (e) {
      setError(e);
      setPin('');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title={title ?? t('pin.title')} width={380} initialFocus="[data-pinpad]"
      footer={<><Button onClick={onClose}>{t('action.cancel')}</Button><Button variant="primary" loading={busy} disabled={pin.length < 4} onClick={() => submit(pin)}>{t('action.confirm')}</Button></>}>
      <div className="flex flex-col items-center gap-4">
        {context && <div className="w-full">{context}</div>}
        <PinPad value={pin} onChange={setPin} onComplete={submit} disabled={busy} error={!!error} />
        {error ? <Alert tone="danger" className="w-full">{pinErrorMessage(error, i18n.language as Lang, t)}</Alert> : null}
        <div className="text-center text-[12px] text-neutral-500">{t('pin.triesHint')}</div>
      </div>
    </Dialog>
  );
}

export const MANAGER_ROLES = ['owner', 'branch_manager'];

/**
 * Two-person sign-off (7c, 11c, 18h, discount approval 3j): step 1 the user's own PIN (optional), step 2 a
 * witness from the same branch with their PIN. Resolves with both tokens.
 */
export function WitnessDialog({
  open, action, branchId, onClose, onTokens, context, managerOnly, ownPin = true, title,
}: {
  open: boolean;
  action: string;
  branchId: string;
  onClose: () => void;
  onTokens: (t: { pin?: PinToken; witness: PinToken }) => void;
  context?: ReactNode;
  managerOnly?: boolean;
  ownPin?: boolean;
  title?: ReactNode;
}) {
  const { t, i18n } = useTranslation(['common', 'states']);
  const [step, setStep] = useState<1 | 2>(ownPin ? 1 : 2);
  const [pin, setPin] = useState('');
  const [own, setOwn] = useState<PinToken | undefined>();
  const [witnessId, setWitnessId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (open) {
      setStep(ownPin ? 1 : 2);
      setPin('');
      setOwn(undefined);
      setWitnessId('');
      setError(null);
    }
  }, [open, ownPin]);
  const witnesses = useQuery({
    queryKey: ['auth', 'pin-witnesses', branchId],
    enabled: open && !!branchId,
    queryFn: () => call(api.auth.GET('/api/auth/v1/pin/witnesses', { params: { query: { branch_id: branchId } } })),
  });
  const list = (witnesses.data ?? []).filter((w) => !managerOnly || MANAGER_ROLES.includes(w.role));
  // the witness types next: choosing them moves the keyboard to the PIN pad
  const focusPad = (from: HTMLElement) => from.closest('[role=dialog]')?.querySelector<HTMLElement>('[data-pinpad]')?.focus();
  const submit = async (value: string) => {
    if (value.length < 4 || busy) return;
    if (step === 2 && !witnessId) {
      setError(new ApiError('WITNESS_REQUIRED', ''));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (step === 1) {
        setOwn(await call(api.auth.POST('/api/auth/v1/pin/verify', { body: { pin: value, action } })));
        setStep(2);
      } else {
        const w = await call(api.auth.POST('/api/auth/v1/pin/witness', { body: { pin: value, action, witness_user_id: witnessId } }));
        onTokens({ pin: own, witness: w });
      }
    } catch (e) {
      setError(e);
    } finally {
      setPin('');
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title={title ?? t('pin.witnessTitle')} width={440} initialFocus="[data-pinpad]"
      footer={<><Button onClick={onClose}>{t('action.back')}</Button><Button variant="primary" loading={busy} disabled={pin.length < 4} onClick={() => submit(pin)}>{step === 1 ? t('action.continue') : t('pin.sign')}</Button></>}>
      <div className="flex flex-col gap-4 text-[13px]">
        {context && <div className="rounded-lg bg-neutral-50 px-3 py-2.5 leading-5">{context}</div>}
        {ownPin && (
          <div className="flex items-center gap-2.5">
            <span className={cx('flex size-[22px] flex-none items-center justify-center rounded-full text-[11px]', own ? 'bg-success text-white' : 'border-2 border-primary-600 font-bold text-primary-600')}>{own ? '✓' : '1'}</span>
            <div className="flex flex-col">
              <b>{t('pin.step1')}</b>
              {own && <span className="text-neutral-500">{own.name} · {t('pin.verified', { time: time(new Date()) })}</span>}
            </div>
          </div>
        )}
        {step === 2 && (
          <div className="flex items-start gap-2.5">
            {ownPin && <span className="flex size-[22px] flex-none items-center justify-center rounded-full border-2 border-primary-600 text-[11px] font-bold text-primary-600">2</span>}
            <div className="flex flex-1 flex-col gap-2">
              <b>{managerOnly ? t('pin.witnessManager') : t('pin.witnessAny')}</b>
              <Field label={t('pin.chooseWitness')}>
                {(id) => (
                  <Select id={id} value={witnessId} onChange={(e) => { setWitnessId(e.target.value); focusPad(e.currentTarget); }}>
                    <option value="">—</option>
                    {list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </Select>
                )}
              </Field>
              {witnesses.isSuccess && list.length === 0 && <Alert tone="warning">{t('pin.noWitnesses')}</Alert>}
              <span className="text-neutral-500">{t('pin.differentUser')}</span>
            </div>
          </div>
        )}
        <PinPad key={step} value={pin} onChange={setPin} onComplete={submit} disabled={busy} error={!!error} />
        {error ? <Alert tone="danger">{pinErrorMessage(error, i18n.language as Lang, t)}</Alert> : null}
      </div>
    </Dialog>
  );
}
