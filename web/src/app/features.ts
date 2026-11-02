// Feature switches (GET branch/v1/features): a disabled feature hides the menu keys in its `hides`.
import { useQuery } from '@tanstack/react-query';
import { api, call } from '@/api/client';

export function useFeatures() {
  return useQuery({
    queryKey: ['branch', 'features'],
    staleTime: 5 * 60_000,
    queryFn: () => call(api.branch.GET('/api/branch/v1/features')),
  });
}

export function useHiddenMenuKeys(): Set<string> {
  const q = useFeatures();
  const hidden = new Set<string>();
  for (const f of q.data ?? []) if (!f.enabled) for (const k of f.hides) hidden.add(k);
  return hidden;
}
