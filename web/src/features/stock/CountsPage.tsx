// 8c Stock takes: list and start (scope: whole branch, a category, a shelf location, controlled).
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, DataTable, Dialog, EmptyState, Field, Input, PageHeader, Select, StatusPill, TextArea, Usd, hasField } from '@/design';
import { dateTime } from '@/lib/format';
import { toneOf, useStaffNames } from '../shared/hooks';

type Scope = 'full' | 'category' | 'location' | 'controlled';

export default function CountsPage() {
  const { t, i18n } = useTranslation(['stock', 'common', 'nav', 'sales']);
  const user = useUser();
  const nav = useNavigate();
  const staff = useStaffNames();
  const { branchParam, oneBranch } = useBranch();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState<{ scope: Scope; category_id: string; location: string; note: string }>({ scope: 'full', category_id: '', location: '', note: '' });
  const q = useQuery({ queryKey: ['stockcount', 'counts', branchParam], queryFn: () => call(api.stockcount.GET('/api/stockcount/v1/counts', { params: { query: { branch_id: branchParam } } })) });
  const cats = useQuery({ queryKey: ['catalog', 'categories'], enabled: open, queryFn: () => call(api.catalog.GET('/api/catalog/v1/categories')) });
  const start = useMutation({
    mutationFn: () => call(api.stockcount.POST('/api/stockcount/v1/counts', { body: { branch_id: oneBranch!.id, scope: v.scope, category_id: v.scope === 'category' ? v.category_id : null, location: v.scope === 'location' ? v.location : null, note: v.note } })),
    onSuccess: (c) => nav(`/stock/counts/${c.id}`),
  });
  const canStart = user.has('stockcount.approve') || user.has('inventory.adjust');
  return (
    <div className="flex flex-col gap-4 p-4 tablet:px-7 tablet:py-5">
      <PageHeader crumb={t('nav:group.stock')} title={t('counts.title')} actions={canStart && <Button variant="primary" onClick={() => setOpen(true)}>+ {t('counts.new')}</Button>} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(c) => c.id} onRowClick={(c) => nav(`/stock/counts/${c.id}`)}
        empty={<EmptyState title={t('counts.empty')} />}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (c) => <span className="font-mono text-[12px]">{c.number}</span> },
          { key: 's', header: t('counts.scope'), cell: (c) => `${t(`counts.scopes.${c.scope}`, { defaultValue: c.scope })}${c.location ? ` · ${c.location}` : ''}` },
          { key: 'p', header: t('counts.progress'), cell: (c) => Object.entries(c.progress ?? {}).map(([k, n]) => `${t(`counts.lineStatus.${k}`, { defaultValue: k })} ${n}`).join(' · ') },
          { key: 'b', header: t('common:label.createdBy'), cell: (c) => `${staff(c.started_by)} · ${dateTime(c.started_at)}` },
          ...(q.data?.some((c) => hasField(c, 'variance_value')) ? [{ key: 'v', header: t('counts.varianceValue'), align: 'right' as const, cell: (c: NonNullable<typeof q.data>[number]) => <Usd value={c.variance_value} /> }] : []),
          { key: 'st', header: t('common:label.status'), cell: (c) => <StatusPill tone={toneOf(c.status)}>{t(`sales:status.${c.status}`, { defaultValue: c.status })}</StatusPill> },
        ]} />
      <Dialog open={open} onClose={() => setOpen(false)} title={t('counts.new')} width={480}
        footer={<><Button onClick={() => setOpen(false)}>{t('common:action.cancel')}</Button><Button variant="primary" loading={start.isPending} disabled={(v.scope === 'category' && !v.category_id) || (v.scope === 'location' && !v.location)} onClick={() => start.mutate()}>{t('counts.start')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('counts.scope')}>{(id) => <Select id={id} value={v.scope} onChange={(e) => setV({ ...v, scope: e.target.value as Scope })}>{(['full', 'category', 'location', 'controlled'] as const).map((s) => <option key={s} value={s}>{t(`counts.scopes.${s}`)}</option>)}</Select>}</Field>
          {v.scope === 'category' && <Field label={t('common:label.category')}>{(id) => <Select id={id} value={v.category_id} onChange={(e) => setV({ ...v, category_id: e.target.value })}><option value="">—</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{i18n.language === 'km' && c.name_km ? c.name_km : c.name_en}</option>)}</Select>}</Field>}
          {v.scope === 'location' && <Field label={t('counts.location')}>{(id) => <Input id={id} value={v.location} onChange={(e) => setV({ ...v, location: e.target.value.toUpperCase() })} />}</Field>}
          <Field label={t('counts.note')}>{(id) => <TextArea id={id} rows={2} value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />}</Field>
          <ApiErrorAlert error={start.error} />
        </div>
      </Dialog>
    </div>
  );
}
