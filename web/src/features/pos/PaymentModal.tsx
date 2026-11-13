// The one payment modal for KHQR and Card / Wallet (PayWay): header with the amount in USD and riel, the payment
// reference (there is no invoice number before the sale completes), a countdown to the attempt's expires_at and the
// status; the method's body; actions for the end states. Closing while it waits asks first, then the caller
// cancels the attempt (closed at PayWay).
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, ConfirmDialog, Dialog, StatusPill, type PillTone } from '@/design';
import { khr, usd } from '@/lib/format';

export type PayState = 'start' | 'pending' | 'declined' | 'paid' | 'expired' | 'cancelled' | 'review';

/** Seconds left until `expiresAt` (never negative), ticking every second. */
export function useCountdown(expiresAt: string | null | undefined, now: () => number = Date.now): number | null {
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (!expiresAt) { setLeft(null); return; }
    const end = Date.parse(expiresAt);
    const tick = () => setLeft(Math.max(0, Math.round((end - now()) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt, now]);
  return left;
}

export function mmss(seconds: number): string {
  const m = Math.floor(seconds / 60);
  return `${m}:${String(seconds % 60).padStart(2, '0')}`;
}

const TONE: Record<PayState, PillTone> = {
  start: 'neutral', pending: 'warning', declined: 'danger', paid: 'success', expired: 'danger', cancelled: 'neutral', review: 'danger',
};

export function PaymentModal({ open, title, amountUsd, amountKhr, reference, expiresAt, state, onClose, onCancelAttempt, onRetry,
  onOther, children, footerExtra, testid }: {
  open: boolean; title: ReactNode; amountUsd: number | null; amountKhr: number | null; reference?: string | null;
  expiresAt?: string | null; state: PayState; onClose: () => void; onCancelAttempt?: () => void; onRetry: () => void;
  onOther: () => void; children: ReactNode; footerExtra?: ReactNode; testid?: string;
}) {
  const { t } = useTranslation(['pos', 'common']);
  const left = useCountdown(state === 'pending' || state === 'declined' ? expiresAt : null);
  const [confirm, setConfirm] = useState(false);
  const waiting = state === 'pending' || state === 'declined';
  const close = () => (waiting ? setConfirm(true) : onClose());
  const ended = state === 'expired' || state === 'cancelled' || state === 'declined' || state === 'review';
  return (
    <>
      <Dialog open={open && !confirm} onClose={close} title={title} width={560}
        footer={<div className="flex w-full flex-wrap items-center justify-between gap-2" data-testid={testid}>
          <span className="min-w-0 text-[12px] text-neutral-600">{footerExtra}</span>
          <span className="flex gap-2">
            {ended && <Button onClick={onOther}>{t('modal.other')}</Button>}
            {ended && state !== 'review' && <Button variant="primary" onClick={onRetry}>{t('modal.retry')}</Button>}
            {waiting && <Button variant="danger-outline" onClick={close}>{t('modal.cancel')}</Button>}
            {!waiting && !ended && state !== 'paid' && <Button onClick={onClose}>{t('common:action.close')}</Button>}
          </span>
        </div>}>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end justify-between gap-2 border-b border-neutral-100 pb-3">
            <div className="flex flex-col">
              <span className="num text-[28px] font-bold leading-none" data-testid="modal-amount">{amountUsd !== null ? usd(amountUsd) : ''}</span>
              {amountKhr !== null && <span className="num text-[15px] text-neutral-600">{khr(amountKhr)}</span>}
            </div>
            <div className="flex flex-col items-end gap-1">
              <StatusPill tone={TONE[state]}><span data-testid="modal-state" data-state={state}>{t(`modal.state.${state}`)}</span></StatusPill>
              <span className="flex gap-2 text-[12px] text-neutral-500">
                {reference && <span>{t('modal.ref', { ref: reference })}</span>}
                {left !== null && <span className="num" aria-live="off" data-testid="modal-countdown">⏱ {mmss(left)}</span>}
              </span>
            </div>
          </div>
          {state !== 'start' && state !== 'pending' && state !== 'paid' && (
            <p role="alert" className="m-0 rounded-md bg-neutral-50 px-3 py-2 text-[13px]">
              <span lang="km" className="block">{t(`modal.msg.${state}.km`)}</span>
              <span lang="en" className="block text-[12px] text-neutral-600">{t(`modal.msg.${state}.en`)}</span>
            </p>
          )}
          {children}
        </div>
      </Dialog>
      <ConfirmDialog open={open && confirm} onClose={() => setConfirm(false)} title={t('modal.confirmTitle')} body={t('modal.confirmBody')}
        confirmLabel={t('modal.cancel')} variant="danger" onConfirm={() => { setConfirm(false); onCancelAttempt?.(); onClose(); }} />
    </>
  );
}
