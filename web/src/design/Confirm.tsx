// Cancel / deactivate always ask for a reason when the API takes one (min length per endpoint).
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, type ButtonVariant } from './Button';
import { Dialog } from './Dialog';
import { Field, TextArea } from './Field';
import { ApiErrorAlert } from './States';

export function ReasonDialog({
  open, onClose, title, body, confirmLabel, onConfirm, minLength = 3, variant = 'danger', keepLabel, presets,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  body?: ReactNode;
  confirmLabel: ReactNode;
  onConfirm: (reason: string) => Promise<unknown> | void;
  minLength?: number;
  variant?: ButtonVariant;
  keepLabel?: ReactNode;
  presets?: string[];
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (open) {
      setReason('');
      setError(null);
      setTouched(false);
    }
  }, [open]);
  const ok = reason.trim().length >= minLength;
  const submit = async () => {
    setTouched(true);
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      onClose();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<><Button onClick={onClose}>{keepLabel ?? t('action.back')}</Button><Button variant={variant} loading={busy} disabled={!ok} onClick={submit}>{confirmLabel}</Button></>}>
      <div className="flex flex-col gap-3 text-[13px]">
        {body && <div className="leading-5 text-neutral-700">{body}</div>}
        {presets && presets.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {presets.map((p) => (
              <button key={p} type="button" onClick={() => setReason(p)} className="rounded-full border border-neutral-300 px-2.5 py-1 text-[12px] hover:bg-neutral-50">{p}</button>
            ))}
          </div>
        )}
        <Field label={t('confirm.reasonLabel')} required hint={t('confirm.reasonHint', { min: minLength })} error={touched && !ok ? t('states:fieldErrors.minChars', { min: minLength }) : undefined}>
          {(id, d, invalid) => <TextArea id={id} aria-describedby={d} invalid={invalid} value={reason} onBlur={() => setTouched(true)} onChange={(e) => setReason(e.target.value)} autoFocus />}
        </Field>
        <ApiErrorAlert error={error} />
      </div>
    </Dialog>
  );
}

export function ConfirmDialog({
  open, onClose, title, body, confirmLabel, onConfirm, variant = 'primary',
}: { open: boolean; onClose: () => void; title: ReactNode; body?: ReactNode; confirmLabel: ReactNode; onConfirm: () => Promise<unknown> | void; variant?: ButtonVariant }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (open) setError(null);
  }, [open]);
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<><Button onClick={onClose}>{t('action.back')}</Button><Button variant={variant} loading={busy} onClick={async () => {
        setBusy(true); setError(null);
        try { await onConfirm(); onClose(); } catch (e) { setError(e); } finally { setBusy(false); }
      }}>{confirmLabel}</Button></>}>
      <div className="flex flex-col gap-3 text-[13px] leading-5 text-neutral-700">
        {body}
        <ApiErrorAlert error={error} />
      </div>
    </Dialog>
  );
}
