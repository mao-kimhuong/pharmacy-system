import { useTranslation } from 'react-i18next';
import { useOnline } from '@/lib/hooks';

export function OfflineBanner() {
  const { t } = useTranslation('states');
  const online = useOnline();
  if (online) return null;
  return (
    <div role="status" className="no-print flex flex-wrap items-center gap-2.5 bg-inverse px-3.5 py-2.5 text-[13px] text-white">
      <span className="size-2 rounded-full bg-[#F3C24B]" aria-hidden />
      <b>{t('offline.title')}</b>
      <span>{t('offline.body')}</span>
    </div>
  );
}
