import type { ReactNode } from 'react';
import { cx } from './cx';

export function PageHeader({ crumb, title, actions, children }: { crumb?: ReactNode; title: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-0.5">
          {crumb && <div className="text-[12px] text-neutral-500">{crumb}</div>}
          <h1 className="m-0 text-page-title">{title}</h1>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Card({ children, className, title, actions, padded = true }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; padded?: boolean }) {
  return (
    <section className={cx('rounded-xl border border-neutral-200 bg-white', className)}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-neutral-100 px-5 py-3.5">
          <h2 className="m-0 text-[15px] font-semibold">{title}</h2>
          {actions && <div className="flex gap-2">{actions}</div>}
        </div>
      )}
      <div className={cx(padded && 'p-5')}>{children}</div>
    </section>
  );
}

export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('text-[12px] font-semibold tracking-[.06em] text-neutral-500 uppercase', className)}>{children}</div>;
}

export function KpiTile({ label, value, sub, scope, deltas, className }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; scope?: ReactNode;
  deltas?: { value: string; tone: 'up' | 'down' | 'flat'; label: ReactNode }[]; className?: string;
}) {
  return (
    <div className={cx('flex flex-col gap-1.5 rounded-xl border border-neutral-200 bg-white px-5 py-4', className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-neutral-700">{label}</span>
        {scope && <span className="font-mono text-[11px] text-neutral-500">{scope}</span>}
      </div>
      <div className="num text-[28px] leading-9 font-semibold">{value}</div>
      {sub && <div className="min-h-5 text-[13px] text-neutral-500">{sub}</div>}
      {deltas && deltas.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 border-t border-neutral-100 pt-2 text-[12px]">
          {deltas.map((d, i) => (
            <span key={i} className="flex gap-1.5">
              <span className={cx('font-semibold', d.tone === 'up' ? 'text-success' : d.tone === 'down' ? 'text-danger' : 'text-neutral-500')}>{d.value}</span>
              <span className="text-neutral-500">{d.label}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs, className }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: ReactNode; count?: number }[]; className?: string }) {
  return (
    <div role="tablist" className={cx('flex gap-1 overflow-x-auto border-b border-neutral-200', className)}>
      {tabs.map((tb) => (
        <button
          key={tb.value}
          role="tab"
          type="button"
          aria-selected={tb.value === value}
          onClick={() => onChange(tb.value)}
          className={cx(
            '-mb-px border-b-2 px-3 py-2 text-[13px] whitespace-nowrap',
            tb.value === value ? 'border-primary-600 font-semibold text-primary-700' : 'border-transparent text-neutral-700 hover:text-neutral-900',
          )}
        >
          {tb.label}
          {tb.count !== undefined && <span className="ml-1.5 rounded-full bg-neutral-100 px-1.5 text-[11px] text-neutral-700">{tb.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Stepper({ steps, current }: { steps: { label: ReactNode; sub?: ReactNode }[]; current: number }) {
  return (
    <ol className="m-0 flex list-none items-start p-0">
      {steps.map((s, i) => {
        const done = i < current;
        const on = i === current;
        return (
          <li key={i} className="flex flex-1 flex-col gap-2" aria-current={on ? 'step' : undefined}>
            <div className="flex items-center">
              <span className={cx('flex size-7 flex-none items-center justify-center rounded-full border-2 text-[12px] font-semibold',
                done ? 'border-primary-600 bg-primary-600 text-white' : on ? 'border-primary-600 bg-white text-primary-600' : 'border-neutral-300 bg-white text-neutral-500')}>
                {done ? '✓' : i + 1}
              </span>
              {i < steps.length - 1 && <span className={cx('mx-2 h-0.5 flex-1', done ? 'bg-primary-600' : 'bg-neutral-200')} />}
            </div>
            <div className="flex flex-col pr-3">
              <span className={cx('text-[13px]', on ? 'font-semibold' : 'font-medium')}>{s.label}</span>
              {s.sub && <span className="text-[12px] text-neutral-500">{s.sub}</span>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function Timeline({ items }: { items: { title: ReactNode; meta?: ReactNode; tone?: 'done' | 'current' | 'todo' | 'danger' }[] }) {
  const dot = { done: 'bg-primary-600', current: 'bg-warning', todo: 'bg-neutral-300', danger: 'bg-danger' } as const;
  return (
    <ol className="m-0 flex list-none flex-col p-0">
      {items.map((it, i) => (
        <li key={i} className="grid grid-cols-[16px_1fr] gap-3">
          <div className="flex flex-col items-center">
            <span className={cx('mt-1.5 size-2.5 rounded-full', dot[it.tone ?? 'done'])} />
            {i < items.length - 1 && <span className="w-0.5 flex-1 bg-neutral-200" />}
          </div>
          <div className="flex flex-col gap-0.5 pb-4 text-[13px]">
            <b>{it.title}</b>
            {it.meta && <span className="text-neutral-500">{it.meta}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function DefinitionList({ items, className, cols = 2 }: { items: { label: ReactNode; value: ReactNode }[]; className?: string; cols?: number }) {
  return (
    <dl className={cx('m-0 grid gap-x-6 gap-y-3', className)} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
      {items.map((it, i) => (
        <div key={i} className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-[12px] text-neutral-500">{it.label}</dt>
          <dd className="m-0 text-[14px] break-words">{it.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Toolbar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('flex flex-wrap items-center gap-2', className)}>{children}</div>;
}
