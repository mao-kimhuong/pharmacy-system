// 7e Chain verification: re-computes every hash chain of the branch.
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useBranch } from '@/app/branch';
import { Alert, Button, DataTable, PageHeader, StatusPill } from '@/design';
import { useMedicineNames } from '../shared/hooks';

export default function ChainPage() {
  const { t } = useTranslation(['controlled', 'common', 'nav']);
  const { oneBranch } = useBranch();
  const nav = useNavigate();
  const q = useQuery({
    queryKey: ['controlled', 'verify', oneBranch?.id],
    enabled: !!oneBranch,
    queryFn: () => call(api.controlled.GET('/api/controlled/v1/register/verify', { params: { query: { branch_id: oneBranch!.id } } })),
  });
  const names = useMedicineNames(q.data?.chains.map((c) => c.medicine_id) ?? []);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.controlled')} title={t('chain.title')} actions={<Button variant="primary" loading={q.isFetching} onClick={() => void q.refetch()}>{t('chain.run')}</Button>} />
      {q.data && (q.data.valid ? <Alert tone="success">{t('chain.allOk')}</Alert> : <Alert tone="danger">{t('register.chainBad')}</Alert>)}
      <DataTable rows={q.data?.chains} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(c) => c.medicine_id}
        columns={[
          { key: 'm', header: t('register.medicine'), cell: (c) => names(c.medicine_id) },
          { key: 'e', header: t('chain.entries'), align: 'right', cell: (c) => c.entries },
          { key: 'v', header: t('common:label.status'), cell: (c) => <StatusPill tone={c.valid ? 'success' : 'danger'}>{c.valid ? t('chain.valid') : t('chain.broken')}</StatusPill> },
          { key: 'p', header: t('chain.problem'), cell: (c) => c.problem || '—' },
          { key: 'f', header: t('chain.firstBad'), cell: (c) => c.first_bad_entry_id ? <Button size="sm" onClick={() => nav(`/controlled/entries/${c.first_bad_entry_id}`)}>→</Button> : '—' },
        ]} />
    </div>
  );
}
