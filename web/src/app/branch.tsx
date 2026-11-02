// Branch switcher state. The API filters by the user's branches anyway; this only picks which one the screens
// show. The owner can choose "All branches" for lists and reports; screens that act on one branch (POS, stock
// take, receiving) use `oneBranch`.
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, call } from '@/api/client';
import type { Branch } from '@/api/types';
import { useUser } from './auth';

export const ALL = 'all' as const;
const KEY = 'pharmacy.branch';

interface BranchState {
  branches: Branch[];
  loading: boolean;
  current: string; // branch id or ALL
  setCurrent: (id: string) => void;
  /** Branch to act on: the chosen one, or the first when "All branches" is chosen. */
  oneBranch: Branch | null;
  /** branch_id query value: undefined for "All branches". */
  branchParam: string | undefined;
  canSeeAll: boolean;
  byId: (id: string | null | undefined) => Branch | undefined;
}

const Ctx = createContext<BranchState | null>(null);

export function useBranchesQuery(enabled = true) {
  return useQuery({
    queryKey: ['branch', 'branches'],
    enabled,
    staleTime: 5 * 60_000,
    queryFn: () => call(api.branch.GET('/api/branch/v1/branches')),
  });
}

export function BranchProvider({ children }: { children: ReactNode }) {
  const user = useUser();
  const q = useBranchesQuery();
  const mine = useMemo(() => {
    const all = (q.data ?? []).filter((b) => b.is_active);
    return user.isOwner ? all : all.filter((b) => user.branch_ids.includes(b.id));
  }, [q.data, user]);
  const canSeeAll = user.isOwner || mine.length > 1;
  const [stored, setStored] = useState<string>(() => {
    try {
      return localStorage.getItem(KEY) ?? '';
    } catch {
      return '';
    }
  });
  const current = stored === ALL && canSeeAll ? ALL : mine.some((b) => b.id === stored) ? stored : canSeeAll && user.isOwner ? ALL : (mine[0]?.id ?? ALL);
  const value = useMemo<BranchState>(() => {
    const one = current === ALL ? (mine[0] ?? null) : (mine.find((b) => b.id === current) ?? null);
    return {
      branches: mine,
      loading: q.isLoading,
      current,
      setCurrent: (id) => {
        setStored(id);
        try {
          localStorage.setItem(KEY, id);
        } catch {
          /* private mode */
        }
      },
      oneBranch: one,
      branchParam: current === ALL ? undefined : current,
      canSeeAll,
      byId: (id) => (q.data ?? []).find((b) => b.id === id),
    };
  }, [current, mine, q.isLoading, q.data, canSeeAll]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBranch(): BranchState {
  const c = useContext(Ctx);
  if (!c) throw new Error('useBranch outside BranchProvider');
  return c;
}

/** Branch name in the current language. */
export function branchName(b: Branch | undefined | null, lang: string): string {
  if (!b) return '—';
  return lang === 'km' ? b.name_km || b.name_en : b.name_en || b.name_km;
}
