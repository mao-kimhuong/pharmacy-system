import { useState } from 'react';
import { NavLink, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Kbd, cx } from '@/design';
import type { NavGroup } from './useNav';

function activeGroup(groups: NavGroup[], pathname: string) {
  let best: { g: string; len: number } | null = null;
  for (const g of groups) for (const it of g.items) {
    const hit = it.path === '/' ? pathname === '/' : pathname === it.path || pathname.startsWith(`${it.path}/`);
    if (hit && (!best || it.path.length > best.len)) best = { g: g.key, len: it.path.length };
  }
  return best?.g;
}

export function Sidebar({ groups, collapsed, onToggle }: { groups: NavGroup[]; collapsed: boolean; onToggle: () => void }) {
  const { t } = useTranslation(['nav', 'common', 'shell']);
  const { pathname } = useLocation();
  const current = activeGroup(groups, pathname);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const isOpen = (k: string) => open[k] ?? k === current;
  return (
    <aside className={cx('no-print flex flex-none flex-col border-r border-neutral-200 bg-white transition-[width]', collapsed ? 'w-sidebar-collapsed' : 'w-sidebar')}>
      <div className="flex h-header items-center gap-2.5 border-b border-neutral-100 px-4">
        <span className="flex size-8 flex-none items-center justify-center rounded-lg bg-primary-600 text-[15px] font-bold text-white" aria-hidden>+</span>
        {!collapsed && (
          <span className="flex min-w-0 flex-col leading-4">
            <b className="text-[13px]">{t('common:app.name')}</b>
            <span className="text-[11px] text-neutral-500">{t('common:app.sub')}</span>
          </span>
        )}
      </div>
      <nav aria-label={t('shell:menu')} className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2">
        {groups.map((g) => {
          const active = g.key === current;
          const single = g.items.length === 1 && g.key === 'dashboard';
          if (collapsed || single) {
            const first = g.items[0];
            return (
              <NavLink key={g.key} to={first.path} title={t(`group.${g.key}`)} end={first.path === '/'}
                className={cx('flex min-h-9 items-center gap-2.5 rounded-md text-[13px] no-underline', collapsed ? 'justify-center' : 'px-2.5',
                  active ? 'bg-primary-100 font-semibold text-primary-700' : 'font-medium text-neutral-700 hover:bg-neutral-50')}>
                <span className="w-5 flex-none text-center text-[14px]" aria-hidden>{g.icon}</span>
                {!collapsed && <span className="flex-1">{t(`group.${g.key}`)}</span>}
                {collapsed && <span className="sr-only">{t(`group.${g.key}`)}</span>}
              </NavLink>
            );
          }
          return (
            <div key={g.key} className="flex flex-col">
              <button type="button" aria-expanded={isOpen(g.key)} onClick={() => setOpen((o) => ({ ...o, [g.key]: !isOpen(g.key) }))}
                className={cx('flex min-h-9 items-center gap-2.5 rounded-md px-2.5 text-left text-[13px]', active ? 'font-semibold text-primary-700' : 'font-medium text-neutral-700 hover:bg-neutral-50')}>
                <span className="w-5 flex-none text-center text-[14px]" aria-hidden>{g.icon}</span>
                <span className="flex-1">{t(`group.${g.key}`)}</span>
                <span className="text-[11px] text-neutral-400" aria-hidden>{isOpen(g.key) ? '▾' : '▸'}</span>
              </button>
              {isOpen(g.key) && (
                <div className="flex flex-col gap-px pt-0.5 pb-1.5 pl-[30px]">
                  {g.items.map((it) => (
                    <NavLink key={it.path} to={it.path} end={it.path === '/'}
                      className={({ isActive }) => cx('rounded-md border-l-2 px-2.5 py-1.5 text-[13px] no-underline',
                        isActive ? 'border-primary-600 bg-primary-50 font-semibold text-primary-700' : 'border-transparent text-neutral-700 hover:bg-neutral-50')}>
                      {t(`item.${it.key}`)}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>
      <button type="button" onClick={onToggle} className={cx('flex items-center gap-2 border-t border-neutral-100 px-4 py-2.5 text-[12px] text-neutral-500 hover:bg-neutral-50', collapsed && 'justify-center')}
        aria-label={collapsed ? t('shell:expand') : t('shell:collapse')}>
        <span aria-hidden>{collapsed ? '»' : '«'}</span>
        {!collapsed && <><span>{t('shell:collapse')}</span><Kbd className="ml-auto text-[10px]">Ctrl B</Kbd></>}
      </button>
    </aside>
  );
}
