// 12a Customer groups / supplier groups: add, rename (+ default discount for customers), deactivate with a
// reason / activate.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { Alert, ApiErrorAlert, Button, DataTable, Dialog, Field, Input, PageHeader, ReasonDialog, StatusPill } from '@/design';
import { pct } from '@/lib/format';

interface Row { id: string; name_en: string; name_km: string; is_active: boolean; default_discount_pct?: string }

export function GroupsPage({ kind }: { kind: 'customer' | 'supplier' }) {
  const { t } = useTranslation(['contacts', 'common', 'nav', 'sales']);
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Partial<Row> | null>(null);
  const [deact, setDeact] = useState<Row | null>(null);
  const cust = kind === 'customer';
  const key = ['contacts', kind, 'groups'];
  const q = useQuery<Row[]>({
    queryKey: key,
    queryFn: () => (cust
      ? call(api.customers.GET('/api/customers/v1/customer-groups', { params: { query: { include_inactive: true } } }))
      : call(api.purchasing.GET('/api/purchasing/v1/supplier-groups', { params: { query: { include_inactive: true } } }))),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: key });
  const save = useMutation({
    mutationFn: () => {
      const e = edit!;
      const base = { name_en: e.name_en ?? '', name_km: e.name_km ?? '' };
      if (cust) {
        const body = { ...base, default_discount_pct: e.default_discount_pct || '0' };
        return e.id ? call(api.customers.PATCH('/api/customers/v1/customer-groups/{group_id}', { params: { path: { group_id: e.id } }, body })) : call(api.customers.POST('/api/customers/v1/customer-groups', { body }));
      }
      return e.id ? call(api.purchasing.PATCH('/api/purchasing/v1/supplier-groups/{group_id}', { params: { path: { group_id: e.id } }, body: base })) : call(api.purchasing.POST('/api/purchasing/v1/supplier-groups', { body: base }));
    },
    onSuccess: () => { setEdit(null); void refresh(); },
  });
  const activate = useMutation({
    mutationFn: (id: string) => (cust ? call(api.customers.POST('/api/customers/v1/customer-groups/{group_id}/activate', { params: { path: { group_id: id } } })) : call(api.purchasing.POST('/api/purchasing/v1/supplier-groups/{group_id}/activate', { params: { path: { group_id: id } } }))),
    onSuccess: () => void refresh(),
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.contacts')} title={t(`groups.${kind}`)} actions={<Button variant="primary" onClick={() => setEdit({})}>+ {t('groups.new')}</Button>} />
      {cust && <Alert tone="info">{t('groups.hidden')}</Alert>}
      <ApiErrorAlert error={activate.error} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} columns={[
        { key: 'en', header: t('common:label.nameEn'), cell: (r) => r.name_en },
        { key: 'km', header: t('common:label.nameKm'), cell: (r) => <span className="km">{r.name_km || '—'}</span> },
        ...(cust ? [{ key: 'd', header: t('groups.discount'), align: 'right' as const, cell: (r: Row) => pct(r.default_discount_pct) }] : []),
        { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
        { key: 'a', header: '', align: 'right', cell: (r) => (
          <span className="flex justify-end gap-1"><Button size="sm" onClick={() => setEdit(r)}>{t('common:action.edit')}</Button>
            {r.is_active ? <Button size="sm" onClick={() => setDeact(r)}>{t('common:action.deactivate')}</Button> : <Button size="sm" onClick={() => activate.mutate(r.id)}>{t('common:action.activate')}</Button>}</span>
        ) },
      ]} />
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? t('common:action.edit') : t('groups.new')} width={460}
        footer={<><Button onClick={() => setEdit(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!edit?.name_en} loading={save.isPending} onClick={() => save.mutate()}>{t('common:action.save')}</Button></>}>
        {edit && <div className="flex flex-col gap-3">
          <Field label={t('common:label.nameEn')} required>{(id) => <Input id={id} autoFocus value={edit.name_en ?? ''} onChange={(e) => setEdit({ ...edit, name_en: e.target.value })} />}</Field>
          <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={edit.name_km ?? ''} onChange={(e) => setEdit({ ...edit, name_km: e.target.value })} />}</Field>
          {cust && <Field label={t('groups.discount')}>{(id) => <Input id={id} suffix="%" inputMode="decimal" value={edit.default_discount_pct ?? ''} onChange={(e) => setEdit({ ...edit, default_discount_pct: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>}
          <ApiErrorAlert error={save.error} />
        </div>}
      </Dialog>
      <ReasonDialog open={!!deact} onClose={() => setDeact(null)} title={t('common:confirm.deactivateTitle', { name: deact?.name_en })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => {
          const path = { group_id: deact!.id };
          await (cust ? call(api.customers.POST('/api/customers/v1/customer-groups/{group_id}/deactivate', { params: { path }, body: { reason } })) : call(api.purchasing.POST('/api/purchasing/v1/supplier-groups/{group_id}/deactivate', { params: { path }, body: { reason } })));
          await refresh();
        }} />
    </div>
  );
}

export const CustomerGroupsPage = () => <GroupsPage kind="customer" />;
export const SupplierGroupsPage = () => <GroupsPage kind="supplier" />;
