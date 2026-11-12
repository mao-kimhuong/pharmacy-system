// A new version of the app is waiting and was not applied by itself (see pwa.ts): offer to reload.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/design';
import { pendingUpdate } from '../pwa';

export function UpdateBanner() {
  const { t } = useTranslation('states');
  const [apply, setApply] = useState<(() => void) | null>(pendingUpdate);
  useEffect(() => {
    const on = (e: Event) => setApply(() => (e as CustomEvent<() => void>).detail);
    window.addEventListener('pwa:update', on);
    return () => window.removeEventListener('pwa:update', on);
  }, []);
  if (!apply) return null;
  return (
    <div role="status" className="no-print flex items-center gap-3 bg-primary-700 px-4 py-2 text-[13px] text-white">
      <span className="flex-1">{t('update.ready')}</span>
      <Button size="sm" onClick={apply}>{t('update.reload')}</Button>
    </div>
  );
}
