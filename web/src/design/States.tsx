// Shared states 16a–16g: empty, skeleton (after 300 ms), server error with retry, 403, 404, alerts.
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError, isApiError } from '@/api/errors';
import { errorText } from '@/i18n/errors';
import type { Lang } from '@/lib/format';
import { dateTime } from '@/lib/format';
import { Button } from './Button';
import { cx } from './cx';

export function EmptyState({ title, body, action, icon = '⌕', className }: { title: ReactNode; body?: ReactNode; action?: ReactNode; icon?: ReactNode; className?: string }) {
  return (
    <div className={cx('flex flex-col items-center gap-2.5 px-6 py-10 text-center', className)}>
      <div className="flex size-10 items-center justify-center rounded-full bg-neutral-100 text-neutral-500" aria-hidden>{icon}</div>
      <div className="text-[15px] font-semibold">{title}</div>
      {body && <div className="max-w-[340px] text-[13px] text-neutral-500">{body}</div>}
      {action && <div className="mt-1.5">{action}</div>}
    </div>
  );
}

/** Nothing for 300 ms, then the skeleton (no flash on fast answers). */
export function useDelayed(active: boolean, ms = 300) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (!active) {
      setShow(false);
      return;
    }
    const id = setTimeout(() => setShow(true), ms);
    return () => clearTimeout(id);
  }, [active, ms]);
  return show;
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  const show = useDelayed(true);
  if (!show) return <div className={cx('min-h-40', className)} aria-busy />;
  return (
    <div role="status" className={cx('flex flex-col gap-3.5 p-4', className)} aria-busy aria-label="loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="shimmer size-8 rounded-md" />
          <div className="flex flex-1 flex-col gap-1.5">
            <div className="h-2.5 rounded bg-neutral-100" style={{ width: `${28 + ((i * 7) % 14)}%` }} />
            <div className="h-2.5 rounded bg-neutral-100" style={{ width: `${14 + ((i * 5) % 10)}%` }} />
          </div>
          <div className="h-2.5 w-16 rounded bg-neutral-100" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonTiles({ count = 3 }: { count?: number }) {
  const show = useDelayed(true);
  if (!show) return <div className="min-h-24" aria-busy />;
  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }} aria-busy>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-xl border border-neutral-200 bg-surface p-5">
          <div className="h-2.5 w-1/3 rounded bg-neutral-100" />
          <div className="shimmer h-6 w-1/2 rounded" />
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry, title, className }: { error: unknown; onRetry?: () => void; title?: ReactNode; className?: string }) {
  const { t, i18n } = useTranslation(['states', 'common']);
  const e = isApiError(error) ? error : new ApiError('INTERNAL_ERROR', String(error));
  const [copied, setCopied] = useState(false);
  const ref = e.requestId;
  return (
    <div role="alert" className={cx('flex flex-col items-center gap-2.5 px-6 py-10 text-center', className)}>
      <span className="flex size-10 items-center justify-center rounded-full bg-danger-bg font-bold text-danger" aria-hidden>!</span>
      <div className="text-[15px] font-semibold">{title ?? t('states:error.title')}</div>
      <div className="max-w-[420px] text-[13px] text-neutral-700">
        {e.code === 'INTERNAL_ERROR' || e.code === 'TEMPORARILY_UNAVAILABLE' || e.code === 'NETWORK_ERROR'
          ? t('states:error.body')
          : errorText(e.code, i18n.language as Lang, e.message)}
      </div>
      <div className="mt-1 flex gap-2">
        {onRetry && <Button variant="primary" onClick={onRetry}>{t('common:action.retry')}</Button>}
        {ref && (
          <Button onClick={() => { void navigator.clipboard?.writeText(ref); setCopied(true); }}>
            {copied ? t('common:action.copied') : t('states:error.copyId')}
          </Button>
        )}
      </div>
      <div className="font-mono text-[11px] text-neutral-500">
        {e.status ? `ERR ${e.status} · ` : ''}{e.code}{ref ? ` · req ${ref}` : ''} · {dateTime(new Date())}
      </div>
    </div>
  );
}

export type AlertTone = 'info' | 'success' | 'warning' | 'danger';
const ALERT: Record<AlertTone, { box: string; icon: string; glyph: string }> = {
  info: { box: 'bg-info-bg border-info-bd text-info-fg', icon: 'bg-info', glyph: 'i' },
  success: { box: 'bg-success-bg border-success-bd text-success-fg', icon: 'bg-success', glyph: '✓' },
  warning: { box: 'bg-warning-soft border-warning-bd text-warning-fg', icon: 'bg-warning', glyph: '!' },
  danger: { box: 'bg-danger-bg border-danger-bd text-danger-fg', icon: 'bg-danger', glyph: '✕' },
};

export function Alert({ tone = 'info', title, children, action, className }: { tone?: AlertTone; title?: ReactNode; children?: ReactNode; action?: ReactNode; className?: string }) {
  const a = ALERT[tone];
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cx('flex gap-3 rounded-lg border px-3.5 py-3', a.box, className)}>
      <span className={cx('flex size-5 flex-none items-center justify-center rounded-full text-[11px] font-bold text-white', a.icon)} aria-hidden>{a.glyph}</span>
      <div className="flex flex-1 flex-col gap-0.5 text-[13px] leading-5">
        {title && <b>{title}</b>}
        {children}
      </div>
      {action}
    </div>
  );
}

/** The API error as a friendly inline alert (KM/EN). */
export function ApiErrorAlert({ error, className }: { error: unknown; className?: string }) {
  const { i18n } = useTranslation();
  if (!error) return null;
  const e = isApiError(error) ? error : new ApiError('INTERNAL_ERROR', String(error));
  return (
    <Alert tone="danger" className={className}>
      <span>{errorText(e.code, i18n.language as Lang, e.message)}</span>
      {e.message && e.message !== errorText(e.code, 'en') && <span className="text-[12px] opacity-80">{e.code} · {e.message}</span>}
    </Alert>
  );
}

export function FullPageState({ icon, title, subtitle, body, actions }: { icon: ReactNode; title: ReactNode; subtitle?: ReactNode; body?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8">
      <div className="flex max-w-[480px] flex-col items-center gap-2.5 text-center">
        <span className="text-[32px] text-neutral-500" aria-hidden>{icon}</span>
        <h1 className="m-0 text-section-title">{title}</h1>
        {subtitle && <div className="km text-[14px] text-neutral-700">{subtitle}</div>}
        {body && <div className="text-[13px] text-neutral-500">{body}</div>}
        {actions && <div className="mt-2 flex gap-2">{actions}</div>}
      </div>
    </div>
  );
}
