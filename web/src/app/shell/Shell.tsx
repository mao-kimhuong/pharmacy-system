// App shell 2a–2f: sidebar (Ctrl B), header (branch, Ctrl K, KM/EN, bell, user), content; phones get a compact
// header and the tab bar. Session expired (16h) and offline banners live here.
import { Suspense, useCallback, useEffect, useState } from 'react';
import { Outlet } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Scanner, Sheet, SkeletonRows } from '@/design';
import { useMediaQuery } from '@/lib/hooks';
import { RouteErrorBoundary } from '../RouteError';
import { OfflineBanner } from './OfflineBanner';
import { SessionExpiredDialog } from './SessionExpired';
import { CommandPalette } from './CommandPalette';
import { Bell, BranchSwitcher, LangToggle, SearchButton, UserMenu } from './Header';
import { MobileTabs } from './MobileTabs';
import { Sidebar } from './Sidebar';
import { useNav } from './useNav';

const COLLAPSE_KEY = 'pharmacy.sidebar.collapsed';

export function Shell() {
  const { t } = useTranslation('shell');
  const groups = useNav();
  const phone = useMediaQuery('(max-width: 1023px)');
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1');
  const [palette, setPalette] = useState<{ open: boolean; initial: string }>({ open: false, initial: '' });
  const [scan, setScan] = useState(false);
  const toggle = useCallback(() => setCollapsed((c) => {
    localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1');
    return !c;
  }), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette({ open: true, initial: '' }); }
      else if (e.key.toLowerCase() === 'b') { e.preventDefault(); toggle(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [toggle]);

  const content = (
    <main id="main" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
      <OfflineBanner />
      <RouteErrorBoundary>
        <Suspense fallback={<SkeletonRows />}>
          <Outlet />
        </Suspense>
      </RouteErrorBoundary>
    </main>
  );

  return (
    <div className="flex h-dvh bg-neutral-50">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-2">{t('skip')}</a>
      {!phone && <Sidebar groups={groups} collapsed={collapsed} onToggle={toggle} />}
      <div className="flex min-w-0 flex-1 flex-col">
        {phone ? (
          <header className="no-print flex flex-none items-center gap-2 border-b border-neutral-200 bg-white px-4 pt-2 pb-2.5">
            <BranchSwitcher compact />
            <span className="ml-auto" />
            <LangToggle size="sm" />
            <Bell size="lg" />
            <UserMenu compact />
          </header>
        ) : (
          <header className="no-print flex h-header flex-none items-center gap-3 border-b border-neutral-200 bg-white px-5">
            <BranchSwitcher />
            <SearchButton onOpen={() => setPalette({ open: true, initial: '' })} />
            <span className="ml-auto" />
            <LangToggle />
            <Bell />
            <UserMenu />
          </header>
        )}
        <div className={phone ? 'flex min-h-0 flex-1 flex-col pb-tabbar' : 'flex min-h-0 flex-1 flex-col'}>{content}</div>
      </div>
      {phone && <MobileTabs onScan={() => setScan(true)} />}
      <CommandPalette open={palette.open} initial={palette.initial} onClose={() => setPalette({ open: false, initial: '' })} />
      <Sheet open={scan} onClose={() => setScan(false)} title={t('tabs.scan')}>
        {scan && <Scanner onClose={() => setScan(false)} onCode={(code) => { setScan(false); setPalette({ open: true, initial: code }); }} />}
      </Sheet>
      <SessionExpiredDialog />
    </div>
  );
}
