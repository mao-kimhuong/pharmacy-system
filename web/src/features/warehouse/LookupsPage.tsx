// 18a Categories & brands: add, rename, deactivate (reason) / activate. Code, manufacturer and country are not
// API fields (hidden).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CatalogS } from '@/api/types';
import { useUser } from '@/app/auth';
import { ApiErrorAlert, Button, DataTable, Dialog, Field, Input, PageHeader, ReasonDialog, StatusPill, Tabs } from '@/design';

type Row = CatalogS['LookupOut'];
type Kind = 'categories' | 'brands';

export default function LookupsPage() {
  const { t } = useTranslation(['warehouse', 'common', 'nav', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const [kind, setKind] = useState<Kind>('categories');
  const [edit, setEdit] = useState<Partial<Row> | null>(null);
  const [deact, setDeact] = useState<Row | null>(null);
  const q = useQuery({
    queryKey: ['catalog', kind, 'all'],
    queryFn: () => (kind === 'categories'
      ? call(api.catalog.GET('/api/catalog/v1/categories', { params: { query: { include_inactive: true } } }))
      : call(api.catalog.GET('/api/catalog/v1/brands', { params: { query: { include_inactive: true } } }))),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ['catalog'] });
  const save = useMutation({
    mutationFn: () => {
      const body = { name_en: edit!.name_en ?? '', name_km: edit!.name_km ?? '' };
      if (edit!.id) {
        const path = { row_id: edit!.id };
        return kind === 'categories' ? call(api.catalog.PATCH('/api/catalog/v1/categories/{row_id}', { params: { path }, body })) : call(api.catalog.PATCH('/api/catalog/v1/brands/{row_id}', { params: { path }, body }));
      }
      return kind === 'categories' ? call(api.catalog.POST('/api/catalog/v1/categories', { body })) : call(api.catalog.POST('/api/catalog/v1/brands', { body }));
    },
    onSuccess: () => { setEdit(null); void refresh(); },
  });
  const activate = useMutation({
    mutationFn: (id: string) => (kind === 'categories'
      ? call(api.catalog.POST('/api/catalog/v1/categories/{row_id}/activate', { params: { path: { row_id: id } } }))
      : call(api.catalog.POST('/api/catalog/v1/brands/{row_id}/activate', { params: { path: { row_id: id } } }))),
    onSuccess: () => void refresh(),
  });
  const manage = user.has('products.manage');
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.warehouse')} title={t('lookups.title')} actions={manage && <Button variant="primary" onClick={() => setEdit({})}>+ {t('lookups.new')}</Button>} />
      <Tabs value={kind} onChange={setKind} tabs={[{ value: 'categories', label: t('lookups.categories') }, { value: 'brands', label: t('lookups.brands') }]} />
      <ApiErrorAlert error={activate.error} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} columns={[
        { key: 'en', header: t('common:label.nameEn'), cell: (r) => r.name_en },
        { key: 'km', header: t('common:label.nameKm'), cell: (r) => <span className="km">{r.name_km || '—'}</span> },
        { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
        { key: 'a', header: '', align: 'right', cell: (r) => manage && (
          <span className="flex justify-end gap-1"><Button size="sm" onClick={() => setEdit(r)}>{t('common:action.edit')}</Button>
            {r.is_active ? <Button size="sm" onClick={() => setDeact(r)}>{t('common:action.deactivate')}</Button> : <Button size="sm" onClick={() => activate.mutate(r.id)}>{t('common:action.activate')}</Button>}</span>
        ) },
      ]} />
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? t('common:action.edit') : t('lookups.new')} width={440}
        footer={<><Button onClick={() => setEdit(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!edit?.name_en} loading={save.isPending} onClick={() => save.mutate()}>{t('common:action.save')}</Button></>}>
        {edit && <div className="flex flex-col gap-3">
          <Field label={t('common:label.nameEn')} required>{(id) => <Input id={id} autoFocus value={edit.name_en ?? ''} onChange={(e) => setEdit({ ...edit, name_en: e.target.value })} />}</Field>
          <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={edit.name_km ?? ''} onChange={(e) => setEdit({ ...edit, name_km: e.target.value })} />}</Field>
          <ApiErrorAlert error={save.error} />
        </div>}
      </Dialog>
      <ReasonDialog open={!!deact} onClose={() => setDeact(null)} title={t('common:confirm.deactivateTitle', { name: deact?.name_en })} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => {
          const path = { row_id: deact!.id };
          await (kind === 'categories' ? call(api.catalog.POST('/api/catalog/v1/categories/{row_id}/deactivate', { params: { path }, body: { reason } })) : call(api.catalog.POST('/api/catalog/v1/brands/{row_id}/deactivate', { params: { path }, body: { reason } })));
          await refresh();
        }} />
    </div>
  );
}
