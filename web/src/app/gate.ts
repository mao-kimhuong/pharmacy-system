// Who may open a page / see a menu item. `menu` is a key of GET auth/v1/me → menu (and is hidden when a
// switched-off feature lists it in `hides`); `perms` are "any of"; both must pass when both are given.
import type { CurrentUser } from './auth';

export interface Gate {
  menu?: string;
  perms?: string[];
  pharmacist?: boolean;
  owner?: boolean;
  dev?: boolean;
}

export function allowed(g: Gate | undefined, user: CurrentUser, hidden: Set<string>): boolean {
  if (!g) return true;
  if (g.dev && !import.meta.env.DEV && import.meta.env.VITE_APP_ENV !== 'development') return false;
  if (g.menu && (!user.menuKeys.has(g.menu) || hidden.has(g.menu))) return false;
  if (g.perms && !user.has(...g.perms)) return false;
  if (g.pharmacist && !user.is_pharmacist) return false;
  if (g.owner && !user.isOwner) return false;
  return true;
}
