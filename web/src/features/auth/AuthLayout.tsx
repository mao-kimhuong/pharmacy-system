// 15a / 15h: brand panel (desktop) + card; on phones the brand sits in a top bar.
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { LangToggle, ThemeToggle } from '@/app/shell/Header';
import { useMediaQuery } from '@/lib/hooks';

export function AuthLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation('auth');
  const phone = useMediaQuery('(max-width: 1023px)');
  if (phone) {
    return (
      <div className="flex min-h-dvh flex-col bg-surface">
        <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3">
          <span className="flex items-center gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary-600 font-bold text-white" aria-hidden>+</span>
            <b className="text-[15px]">{t('brand')}</b>
          </span>
          <LangToggle size="sm" />
        </div>
        <main className="flex flex-1 flex-col gap-5 px-5 py-7">{children}</main>
      </div>
    );
  }
  return (
    <div className="grid min-h-dvh grid-cols-[520px_1fr]">
      <div className="flex flex-col justify-between bg-primary-deep p-12 text-white">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-surface text-[20px] font-bold text-primary-700" aria-hidden>+</span>
          <div className="flex flex-col"><b className="text-[17px] leading-[26px]">{t('brand')}</b><span className="text-[13px] opacity-80">{t('brandSub')}</span></div>
        </div>
        <div className="flex max-w-[380px] flex-col gap-2.5">
          <b className="text-[26px] leading-[34px] font-semibold">{t('hero')}</b>
          <span className="text-[14px] leading-[22px] opacity-85">{t('heroSub')}</span>
        </div>
        <div className="flex gap-4 font-sans text-[12px] opacity-75"><span>v{import.meta.env.VITE_APP_VERSION ?? '0.1.0'}</span><span>Asia/Phnom_Penh</span></div>
      </div>
      <div className="relative flex items-center justify-center bg-neutral-50">
        <div className="absolute top-6 right-7 flex items-center gap-2"><LangToggle /><ThemeToggle /></div>
        <main className="flex w-[440px] flex-col gap-[18px] rounded-2xl border border-neutral-200 bg-surface p-8 shadow-card">{children}</main>
      </div>
    </div>
  );
}

export function AuthTitle({ title, sub }: { title: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h1 className="m-0 text-[24px] leading-8 font-bold">{title}</h1>
      {sub && <span className="text-[14px] text-neutral-500">{sub}</span>}
    </div>
  );
}
