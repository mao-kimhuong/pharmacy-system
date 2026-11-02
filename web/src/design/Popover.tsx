// Anchored menu (branch switcher, bell, user menu): click outside or Esc closes.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cx } from './cx';

export function Popover({
  trigger, children, align = 'left', width = 260, label,
}: {
  trigger: (p: { open: boolean; toggle: () => void; props: Record<string, unknown> }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: 'left' | 'right';
  width?: number;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      {trigger({ open, toggle: () => setOpen((o) => !o), props: { 'aria-expanded': open, 'aria-haspopup': 'menu' } })}
      {open && (
        <div role="menu" aria-label={label} className={cx('absolute top-[calc(100%+6px)] z-40 flex flex-col rounded-xl border border-neutral-200 bg-white p-1.5 text-[13px] shadow-menu', align === 'right' ? 'right-0' : 'left-0')}
          style={{ width }}>
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ children, onClick, danger, aside, active }: { children: ReactNode; onClick?: () => void; danger?: boolean; aside?: ReactNode; active?: boolean }) {
  return (
    <button type="button" role="menuitem" onClick={onClick}
      className={cx('flex items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left hover:bg-neutral-50 pointer-coarse:min-h-11', danger ? 'text-danger' : 'text-neutral-900', active && 'bg-primary-50 font-semibold')}>
      <span className="flex items-center gap-2">{children}</span>
      {aside && <span className="text-[12px] text-neutral-500">{aside}</span>}
    </button>
  );
}
