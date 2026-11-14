// Phone tab bar (2d–2f): Home, POS, Scan, Approvals, More. Each tab only when the user can open it.
import { NavLink, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { cx } from '@/design';
import { useBellCounts } from './Header';
import { useCanOpen } from './useNav';

export function MobileTabs({ onScan }: { onScan: () => void }) {
  const { t } = useTranslation('shell');
  const canOpen = useCanOpen();
  const nav = useNavigate();
  const bell = useBellCounts();
  const p = bell.data?.pending_approvals;
  const pending = p ? p.shrinkages + p.stock_takes + p.transfer_requests + p.purchase_requests : 0;
  const tab = (to: string, icon: string, label: string, badge?: number) => (
    <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => cx('relative flex flex-col items-center justify-center gap-0.5 no-underline', isActive ? 'font-semibold text-primary-700' : 'font-medium text-neutral-500')}>
      {({ isActive }) => (
        <>
          <span className={cx('flex size-7 items-center justify-center rounded-md text-[16px]', isActive && 'bg-primary-100')} aria-hidden>{icon}</span>
          <span className="text-[11px] leading-4 whitespace-nowrap">{label}</span>
          {!!badge && <span className="absolute top-0 right-3.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-danger text-[11px] font-semibold text-white">{badge}</span>}
        </>
      )}
    </NavLink>
  );
  return (
    <nav aria-label={t('menu')} className="no-print fixed inset-x-0 bottom-0 z-30 grid h-tabbar grid-cols-5 border-t border-neutral-200 bg-surface px-1 pt-1.5 pb-3.5">
      {tab('/', '⌂', t('tabs.home'))}
      {canOpen('/pos') ? tab('/pos', '◎', t('tabs.pos')) : <span />}
      <button type="button" onClick={onScan} className="flex flex-col items-center justify-center gap-0.5 font-medium text-neutral-500">
        <span className="-mt-[18px] flex size-12 items-center justify-center rounded-full bg-primary-600 text-[16px] text-white" aria-hidden>▦</span>
        <span className="text-[11px] leading-4">{t('tabs.scan')}</span>
      </button>
      {canOpen('/approvals') ? tab('/approvals', '✓', t('tabs.approvals'), pending) : <span />}
      <button type="button" onClick={() => nav('/more')} className="flex flex-col items-center justify-center gap-0.5 font-medium text-neutral-500">
        <span className="flex size-7 items-center justify-center text-[16px]" aria-hidden>☰</span>
        <span className="text-[11px] leading-4">{t('tabs.more')}</span>
      </button>
    </nav>
  );
}
