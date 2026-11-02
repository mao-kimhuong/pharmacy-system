// The user's menu as tiles (2f "More" on phones; home for roles without the dashboard).
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useNav } from '@/app/shell/useNav';

export function MenuTiles({ skip = [] as string[] }) {
  const { t } = useTranslation('nav');
  const groups = useNav().filter((g) => !skip.includes(g.key));
  return (
    <div className="grid gap-2 tablet:grid-cols-2 desktop:grid-cols-3">
      {groups.map((g) => (
        <div key={g.key} className="flex flex-col gap-1.5 rounded-xl border border-neutral-200 bg-white px-3 py-2.5">
          <div className="flex items-center gap-2.5 text-[14px] font-semibold">
            <span className="w-5 text-center text-primary-600" aria-hidden>{g.icon}</span>
            {t(`group.${g.key}`)}
            <span className="ml-auto text-[12px] font-normal text-neutral-500">{g.items.length}</span>
          </div>
          <div className="flex flex-wrap gap-1.5 pl-[30px]">
            {g.items.map((it) => (
              <Link key={it.path} to={it.path} className="flex min-h-touch items-center rounded-md bg-neutral-50 px-2.5 text-[12px] text-neutral-700 no-underline tablet:min-h-0 tablet:py-1.5">
                {t(`item.${it.key}`)}
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
