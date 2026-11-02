// 14h Feature switches: on / off per feature (labels from the API); shows which menu entries an off switch hides.
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useFeatures } from '@/app/features';
import { ApiErrorAlert, DataTable, PageHeader, Switch, Tag } from '@/design';

export default function FeaturesPage() {
  const { t } = useTranslation(['settings', 'common', 'nav']);
  const qc = useQueryClient();
  const q = useFeatures();
  const set = useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) => call(api.branch.PUT('/api/branch/v1/features/{key}', { params: { path: { key } }, body: { enabled } })),
    onSuccess: (list) => qc.setQueryData(['branch', 'features'], list),
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('features.title')} />
      <ApiErrorAlert error={set.error} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.key}
        columns={[
          { key: 'l', header: t('common:label.name'), cell: (r) => <span className="font-medium">{r.label}<span className="ml-2 font-mono text-[11px] text-neutral-400">{r.key}</span></span> },
          { key: 'h', header: t('features.hides'), cell: (r) => <span className="flex flex-wrap gap-1">{r.hides.map((k) => <Tag key={k}>{t(`nav:item.${k}`, { defaultValue: k })}</Tag>)}</span> },
          { key: 's', header: '', align: 'right', cell: (r) => (
            <Switch label={<span className="sr-only">{r.label}</span>} checked={r.enabled} disabled={set.isPending && set.variables?.key === r.key} onChange={(enabled) => set.mutate({ key: r.key, enabled })} />
          ) },
        ]} />
    </div>
  );
}
