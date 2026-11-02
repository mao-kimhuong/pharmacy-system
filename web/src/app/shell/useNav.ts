import { useMemo } from 'react';
import { useUser } from '../auth';
import { useHiddenMenuKeys } from '../features';
import { allowed } from '../gate';
import { GROUPS, PAGES, type GroupKey, type PageDef } from '../pages';

export interface NavGroup {
  key: GroupKey;
  icon: string;
  items: PageDef[];
}

/** Sidebar groups: only the pages the user may open (role menu + permissions + feature switches). */
export function useNav(): NavGroup[] {
  const user = useUser();
  const hidden = useHiddenMenuKeys();
  return useMemo(
    () =>
      GROUPS.map((g) => ({
        ...g,
        items: PAGES.filter((p) => p.group === g.key && p.nav !== false && allowed(p.gate, user, hidden)),
      })).filter((g) => g.items.length > 0),
    [user, hidden],
  );
}

export function useCanOpen() {
  const user = useUser();
  const hidden = useHiddenMenuKeys();
  return (path: string) => {
    const p = PAGES.find((x) => x.path === path);
    return !!p && allowed(p.gate, user, hidden);
  };
}
