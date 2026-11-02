import { useTranslation } from 'react-i18next';
import { useUser } from '@/app/auth';
import { PageHeader } from '@/design';
import { MenuTiles } from './MenuTiles';

export default function HomePage() {
  const { t } = useTranslation('home');
  const user = useUser();
  return (
    <div className="flex flex-col gap-4 p-4 tablet:px-7 tablet:py-5">
      <PageHeader title={t('hello', { name: user.name })} crumb={t('sub')} />
      <MenuTiles skip={['dashboard']} />
    </div>
  );
}
