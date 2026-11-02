// Safety badges (reserved colours, icon + colour + text, never colour alone) and status pills.
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import tokens from '@design/tokens.json';
import { cx } from './cx';

export type SafetyKind =
  | 'rx' | 'controlled' | 'expired' | 'near-expiry' | 'quarantine' | 'allergy' | 'recalled' | 'hamper' | 'promotion'
  | 'duplicate-therapy';

const SAFETY = tokens.color.safety as unknown as Record<SafetyKind, { bg: string; fg: string; icon: string }>;

export function SafetyBadge({ kind, children, className }: { kind: SafetyKind; children?: ReactNode; className?: string }) {
  const { t } = useTranslation('badges');
  const s = SAFETY[kind];
  return (
    <span
      className={cx('inline-flex h-5 items-center gap-1 rounded-sm pr-1.5 pl-1 text-[11px] font-semibold whitespace-nowrap', className)}
      style={{ background: s.bg, color: s.fg }}
    >
      <span aria-hidden>{s.icon}</span>
      {children ?? t(kind)}
    </span>
  );
}

export type PillTone = 'neutral' | 'info' | 'primary' | 'warning' | 'success' | 'danger' | 'cancelled' | 'purple';

const PILL: Record<PillTone, [string, string]> = {
  neutral: ['bg-pill-neutral text-pill-neutral-fg border-pill-neutral-bd', 'bg-pill-neutral-dot'],
  info: ['bg-pill-info text-pill-info-fg border-pill-info-bd', 'bg-pill-info-dot'],
  primary: ['bg-pill-primary text-pill-primary-fg border-pill-primary-bd', 'bg-pill-primary-dot'],
  warning: ['bg-pill-warning text-pill-warning-fg border-pill-warning-bd', 'bg-pill-warning-dot'],
  success: ['bg-pill-success text-pill-success-fg border-pill-success-bd', 'bg-pill-success-dot'],
  danger: ['bg-pill-danger text-pill-danger-fg border-pill-danger-bd', 'bg-pill-danger-dot'],
  cancelled: ['bg-pill-cancelled text-pill-cancelled-fg border-pill-cancelled-bd line-through', 'bg-pill-cancelled-dot'],
  purple: ['bg-pill-purple text-pill-purple-fg border-pill-purple-bd', 'bg-pill-purple-dot'],
};

export function StatusPill({ tone = 'neutral', children, className }: { tone?: PillTone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        'inline-flex items-center gap-1.5 rounded-full border py-0.5 pr-2.5 pl-2 text-[12px] font-medium whitespace-nowrap',
        PILL[tone][0],
        className,
      )}
    >
      <span className={cx('size-1.5 rounded-full', PILL[tone][1])} aria-hidden />
      {children}
    </span>
  );
}

export function Tag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cx('inline-flex items-center rounded-sm bg-neutral-100 px-1.5 py-0.5 font-mono text-[11px] text-neutral-900', className)}>
      {children}
    </span>
  );
}

export function BranchTag({ code, className }: { code: string; className?: string }) {
  return (
    <span className={cx('rounded-sm bg-primary-100 px-1.5 py-0.5 font-mono text-[11px] font-medium text-primary-700', className)}>
      {code}
    </span>
  );
}
