import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { NavLink, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Kbd, cx, usePresence } from '@/design';
import type { NavGroup } from './useNav';

function activeGroup(groups: NavGroup[], pathname: string) {
  let best: { g: string; len: number } | null = null;
  for (const g of groups) for (const it of g.items) {
    const hit = it.path === '/' ? pathname === '/' : pathname === it.path || pathname.startsWith(`${it.path}/`);
    if (hit && (!best || it.path.length > best.len)) best = { g: g.key, len: it.path.length };
  }
  return best?.g;
}

const CLOSE_DELAY = 150; // time to move the mouse from the icon into its menu

/** Collapsed sidebar: hovering (or focusing) a group's icon shows its pages in a menu beside it. Fixed position in a
 * portal, so the scrolling nav does not clip it. → from the icon goes into the menu, Esc closes. */
function useFlyout() {
  const [fly, setFly] = useState<{ key: string; top: number; left: number } | null>(null);
  const timer = useRef(0);
  const open = (key: string, el: HTMLElement) => {
    window.clearTimeout(timer.current);
    const r = el.getBoundingClientRect();
    setFly({ key, top: r.top, left: r.right + 6 });
  };
  const keep = () => window.clearTimeout(timer.current);
  const closeSoon = () => { timer.current = window.setTimeout(() => setFly(null), CLOSE_DELAY); };
  const close = () => { window.clearTimeout(timer.current); setFly(null); };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return { fly, open, keep, closeSoon, close };
}

function Flyout({ group, top, left, onEnter, onLeave, onClose, title }: {
  group: NavGroup; top: number; left: number; onEnter: () => void; onLeave: () => void; onClose: () => void; title: string;
}) {
  const { t } = useTranslation('nav');
  const { mounted, shown } = usePresence(true, 0);
  if (!mounted) return null;
  const single = group.items.length === 1;
  return createPortal(
    <div id={`flyout-${group.key}`} role="menu" aria-label={title} onMouseEnter={onEnter} onMouseLeave={onLeave}
      onFocus={onEnter} onBlur={onLeave}
      onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
      className={cx('no-print fixed z-40 min-w-48 rounded-lg border border-neutral-200 bg-surface p-1.5 shadow-menu transition-[opacity,transform] duration-150 ease-out',
        shown ? 'translate-x-0 opacity-100' : '-translate-x-1 opacity-0')}
      style={{ top: Math.min(top, window.innerHeight - 48 - group.items.length * 34), left }}>
      <div className="px-2.5 pt-1 pb-1.5 text-[12px] font-semibold text-neutral-500">{title}</div>
      {group.items.map((it) => (
        <NavLink key={it.path} to={it.path} role="menuitem" onClick={onClose}
          end={single || group.items.some((o) => o.path !== it.path && o.path.startsWith(`${it.path}/`))}
          className={({ isActive }) => cx('block rounded-md px-2.5 py-1.5 text-[13px] no-underline',
            isActive ? 'bg-primary-50 font-semibold text-primary-700' : 'text-neutral-700 hover:bg-neutral-50')}>
          {single ? title : t(`item.${it.key}`)}
        </NavLink>
      ))}
    </div>,
    document.body,
  );
}

export function Sidebar({ groups, collapsed, onToggle }: { groups: NavGroup[]; collapsed: boolean; onToggle: () => void }) {
  const { t } = useTranslation(['nav', 'common', 'shell']);
  const { pathname } = useLocation();
  const current = activeGroup(groups, pathname);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const isOpen = (k: string) => open[k] ?? k === current;
  const flyout = useFlyout();
  const closeFlyout = flyout.close;
  useEffect(() => { closeFlyout(); }, [pathname, collapsed]); // eslint-disable-line react-hooks/exhaustive-deps
  const flyGroup = collapsed && flyout.fly ? groups.find((g) => g.key === flyout.fly!.key) : undefined;
  return (
    <aside className={cx('no-print flex flex-none flex-col border-r border-neutral-200 bg-surface transition-[width] duration-200', collapsed ? 'w-sidebar-collapsed' : 'w-sidebar')}>
      <div className="flex h-header items-center gap-2.5 border-b border-neutral-100 px-4">
        <span className="flex size-8 flex-none items-center justify-center rounded-lg bg-primary-600 text-[15px] font-bold text-white" aria-hidden>+</span>
        {!collapsed && (
          <span className="flex min-w-0 flex-col leading-4">
            <b className="text-[13px]">{t('common:app.name')}</b>
            <span className="text-[11px] text-neutral-500">{t('common:app.sub')}</span>
          </span>
        )}
      </div>
      <nav aria-label={t('shell:menu')} className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2" onScroll={flyout.close}>
        {groups.map((g) => {
          const active = g.key === current;
          const single = g.items.length === 1 && g.key === 'dashboard';
          if (collapsed || single) {
            const first = g.items[0];
            const label = t(`group.${g.key}`);
            const hover = collapsed ? {
              onMouseEnter: (e: React.MouseEvent<HTMLElement>) => flyout.open(g.key, e.currentTarget),
              onMouseLeave: flyout.closeSoon,
              onFocus: (e: React.FocusEvent<HTMLElement>) => flyout.open(g.key, e.currentTarget),
              onBlur: flyout.closeSoon,
              onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
                if (e.key === 'ArrowRight') {
                  e.preventDefault();
                  flyout.open(g.key, e.currentTarget);
                  window.setTimeout(() => document.querySelector<HTMLElement>(`#flyout-${g.key} [role=menuitem]`)?.focus(), 0);
                } else if (e.key === 'Escape') flyout.close();
              },
              'aria-haspopup': 'menu' as const,
              'aria-expanded': flyout.fly?.key === g.key,
            } : {};
            return (
              <NavLink key={g.key} to={first.path} end={first.path === '/'} {...hover}
                className={cx('flex min-h-9 items-center gap-2.5 rounded-md text-[13px] no-underline', collapsed ? 'justify-center' : 'px-2.5',
                  active ? 'bg-primary-100 font-semibold text-primary-700' : 'font-medium text-neutral-700 hover:bg-neutral-50')}>
                <span className="w-5 flex-none text-center text-[14px]" aria-hidden>{g.icon}</span>
                {!collapsed && <span className="flex-1">{label}</span>}
                {collapsed && <span className="sr-only">{label}</span>}
              </NavLink>
            );
          }
          return (
            <div key={g.key} className="flex flex-col">
              <button type="button" aria-expanded={isOpen(g.key)} onClick={() => setOpen((o) => ({ ...o, [g.key]: !isOpen(g.key) }))}
                className={cx('flex min-h-9 items-center gap-2.5 rounded-md px-2.5 text-left text-[13px]', active ? 'font-semibold text-primary-700' : 'font-medium text-neutral-700 hover:bg-neutral-50')}>
                <span className="w-5 flex-none text-center text-[14px]" aria-hidden>{g.icon}</span>
                <span className="flex-1">{t(`group.${g.key}`)}</span>
                <span className={cx('text-[11px] text-neutral-400 transition-transform duration-200', isOpen(g.key) && 'rotate-90')} aria-hidden>▸</span>
              </button>
              <div className={cx('grid transition-[grid-template-rows] duration-200 ease-out', isOpen(g.key) ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                <div className="flex flex-col gap-px overflow-hidden pl-[30px]" inert={!isOpen(g.key) || undefined}>
                  <div className="h-0.5" />
                  {g.items.map((it) => (
                    <NavLink key={it.path} to={it.path} end={g.items.some((o) => o.path !== it.path && o.path.startsWith(`${it.path}/`))}
                      className={({ isActive }) => cx('rounded-md border-l-2 px-2.5 py-1.5 text-[13px] no-underline',
                        isActive ? 'border-primary-600 bg-primary-50 font-semibold text-primary-700' : 'border-transparent text-neutral-700 hover:bg-neutral-50')}>
                      {t(`item.${it.key}`)}
                    </NavLink>
                  ))}
                  <div className="h-1.5" />
                </div>
              </div>
            </div>
          );
        })}
      </nav>
      <button type="button" onClick={onToggle} className={cx('flex items-center gap-2 border-t border-neutral-100 px-4 py-2.5 text-[12px] text-neutral-500 hover:bg-neutral-50', collapsed && 'justify-center')}
        aria-label={collapsed ? t('shell:expand') : t('shell:collapse')}>
        <span aria-hidden>{collapsed ? '»' : '«'}</span>
        {!collapsed && <><span>{t('shell:collapse')}</span><Kbd className="ml-auto text-[10px]">Ctrl B</Kbd></>}
      </button>
      {flyGroup && flyout.fly && (
        <Flyout key={flyGroup.key} group={flyGroup} top={flyout.fly.top} left={flyout.fly.left} title={t(`group.${flyGroup.key}`)}
          onEnter={flyout.keep} onLeave={flyout.closeSoon} onClose={flyout.close} />
      )}
    </aside>
  );
}
