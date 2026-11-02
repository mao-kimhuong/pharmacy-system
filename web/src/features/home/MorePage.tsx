import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/design';
import { MenuTiles } from './MenuTiles';

export default function MorePage() {
  const { t } = useTranslation('shell');
  return (
    <div className="flex flex-col gap-3 p-4">
      <PageHeader crumb={t('tabs.more')} title={t('more.title')} />
      <MenuTiles skip={['dashboard']} />
    </div>
  );
}
