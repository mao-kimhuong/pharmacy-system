import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { BranchTag, Kbd, MenuItem, Popover, Segmented, cx } from '@/design';
import { setLang } from '@/i18n';
import { initials, type Lang } from '@/lib/format';
import { useAuth, useUser } from '../auth';
import { ALL, branchName, useBranch } from '../branch';

export function LangToggle({ size = 'md' }: { size?: 'sm' | 'md' }) {
  const { i18n } = useTranslation();
  return (
    <Segmented<Lang>
      ariaLabel="Language"
      size={size}
      value={i18n.language as Lang}
      onChange={setLang}
      options={[{ value: 'km', label: 'ខ្មែរ', className: 'km' }, { value: 'en', label: 'EN' }]}
    />
  );
}

export function BranchSwitcher({ compact }: { compact?: boolean }) {
  const { t, i18n } = useTranslation('shell');
  const b = useBranch();
  const cur = b.current === ALL ? null : b.byId(b.current);
  return (
    <Popover label={t('branchSwitch')} trigger={({ toggle, props }) => (
      <button type="button" onClick={toggle} {...props} aria-label={t('branchSwitch')}
        className={cx('flex h-control items-center gap-2 rounded-md border border-neutral-300 bg-white px-3 text-[13px] whitespace-nowrap pointer-coarse:h-11', compact && 'h-11 px-2.5')}>
        <BranchTag code={cur?.code ?? 'ALL'} />
        {!compact && (cur ? (i18n.language === 'km' ? cur.name_km : cur.name_en) : t('branchAll'))}
        <span className="text-neutral-500" aria-hidden>▾</span>
      </button>
    )}>
      {(close) => (
        <>
          {b.canSeeAll && (
            <MenuItem active={b.current === ALL} onClick={() => { b.setCurrent(ALL); close(); }}><BranchTag code="ALL" />{t('branchAll')}</MenuItem>
          )}
          {b.branches.map((x) => (
            <MenuItem key={x.id} active={b.current === x.id} onClick={() => { b.setCurrent(x.id); close(); }}>
              <BranchTag code={x.code} />{branchName(x, i18n.language)}
            </MenuItem>
          ))}
        </>
      )}
    </Popover>
  );
}

export function useBellCounts() {
  const user = useUser();
  const { branchParam } = useBranch();
  return useQuery({
    queryKey: ['reports', 'dashboard', branchParam ?? 'all'],
    enabled: user.has('dashboard.view'),
    refetchInterval: 60_000,
    queryFn: () => call(api.reports.GET('/api/reports/v1/dashboard', { params: { query: { branch_id: branchParam } } })),
  });
}

/** The bell shows only the dashboard's pending counts (there is no per-user notification feed yet). */
export function Bell({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const { t } = useTranslation('shell');
  const nav = useNavigate();
  const user = useUser();
  const q = useBellCounts();
  if (!user.has('dashboard.view')) return null;
  const p = q.data?.pending_approvals;
  const pending = p ? p.shrinkages + p.stock_takes + p.transfer_requests + p.purchase_requests : 0;
  const disc = q.data?.open_controlled_discrepancies ?? 0;
  const count = pending + disc;
  return (
    <Popover align="right" width={300} label={t('notifications')} trigger={({ toggle, props }) => (
      <button type="button" onClick={toggle} {...props} aria-label={`${t('notifications')} (${count})`}
        className={cx('relative flex items-center justify-center rounded-md border border-neutral-300 bg-white text-[15px]', size === 'lg' ? 'size-11 rounded-lg' : 'size-9')}>
        <span aria-hidden>🔔</span>
        {count > 0 && <span className="absolute -top-1.5 -right-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-danger px-1 text-[11px] font-semibold text-white">{count}</span>}
      </button>
    )}>
      {(close) => (
        <>
          <div className="border-b border-neutral-100 px-2.5 py-2 text-[14px] font-semibold">{t('notifications')}</div>
          {count === 0 && <div className="px-2.5 py-3 text-neutral-500">{t('noNotifications')}</div>}
          {pending > 0 && <MenuItem onClick={() => { close(); nav('/approvals'); }}>{t('pendingApprovals', { count: pending })}</MenuItem>}
          {disc > 0 && <MenuItem onClick={() => { close(); nav('/controlled/discrepancies'); }}>{t('openDiscrepancies', { count: disc })}</MenuItem>}
        </>
      )}
    </Popover>
  );
}

export function UserMenu({ compact }: { compact?: boolean }) {
  const { t } = useTranslation('shell');
  const user = useUser();
  const { logout } = useAuth();
  const nav = useNavigate();
  return (
    <Popover align="right" width={260} label={user.name} trigger={({ toggle, props, open }) => (
      <button type="button" onClick={toggle} {...props} aria-label={user.name} className={cx('flex items-center gap-2 rounded-md px-1.5 py-1 text-[13px]', open && 'bg-neutral-100')}>
        <span className={cx('flex items-center justify-center rounded-full bg-primary-600 text-[12px] font-semibold text-white', compact ? 'size-11' : 'size-8')}>{initials(user.name)}</span>
        {!compact && (
          <span className="flex flex-col text-left leading-[17px]">
            <b>{user.name}</b>
            <span className="text-[12px] text-neutral-500">{t(`role.${user.role}`, { defaultValue: user.role })}</span>
          </span>
        )}
        {!compact && <span className="text-neutral-500" aria-hidden>▾</span>}
      </button>
    )}>
      {(close) => (
        <>
          <div className="mb-1 flex flex-col gap-0.5 border-b border-neutral-100 p-2.5">
            <b>{user.name}</b>
            <span className="text-neutral-500">{t(`role.${user.role}`, { defaultValue: user.role })} · {user.phone}</span>
          </div>
          <MenuItem onClick={() => { close(); nav('/profile'); }}>{t('user.profile')}</MenuItem>
          <MenuItem onClick={() => { close(); nav('/profile#pin'); }}>{t('user.pin')}</MenuItem>
          <MenuItem onClick={() => { close(); nav('/profile#twofa'); }} aside={user.totp_enabled ? t('user.on') : t('user.off')}>{t('user.twofa')}</MenuItem>
          <div className="flex items-center justify-between px-2.5 py-1.5"><span>{t('user.language')}</span><LangToggle size="sm" /></div>
          <MenuItem danger onClick={() => { close(); void logout(); }}>{t('user.logout')}</MenuItem>
        </>
      )}
    </Popover>
  );
}

export function SearchButton({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation('shell');
  return (
    <button type="button" onClick={onOpen} className="flex h-control max-w-[440px] flex-1 items-center gap-2 rounded-md border border-neutral-200 bg-neutral-50 px-3 text-left text-[13px] text-neutral-500">
      <span aria-hidden>⌕</span>
      <span className="flex-1 truncate">{t('search')}</span>
      <Kbd>Ctrl K</Kbd>
    </button>
  );
}
