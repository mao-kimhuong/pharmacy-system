// 8f Shelf locations: medicine → code like "A3" (inventory.locations); filter by location.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, Card, DataTable, Field, Input, PageHeader } from '@/design';
import { MedicinePicker, type Medicine } from '../shared/MedicinePicker';

export default function LocationsPage() {
  const { t } = useTranslation(['stock', 'common', 'nav']);
  const user = useUser();
  const qc = useQueryClient();
  const { oneBranch } = useBranch();
  const [filter, setFilter] = useState('');
  const [med, setMed] = useState<Medicine | null>(null);
  const [code, setCode] = useState('');
  const q = useQuery({
    queryKey: ['inventory', 'locations', oneBranch?.id, filter],
    enabled: !!oneBranch,
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/shelf-locations', { params: { query: { branch_id: oneBranch!.id, code: filter || undefined } } })),
  });
  const set = useMutation({
    mutationFn: (v: { medicine_id: string; code: string }) => call(api.inventory.PUT('/api/inventory/v1/shelf-locations', { body: { branch_id: oneBranch!.id, ...v } })),
    onSuccess: () => { setMed(null); setCode(''); void qc.invalidateQueries({ queryKey: ['inventory', 'locations'] }); },
  });
  const can = user.has('inventory.locations');
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.stock')} title={t('locations.title')} />
      {can && (
        <Card>
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (med) set.mutate({ medicine_id: med.id, code }); }}>
            <Field label={t('common:label.medicine')} className="w-80">{(id) => <MedicinePicker id={id} value={med} onChange={setMed} />}</Field>
            <Field label={t('locations.code')}>{(id) => <Input id={id} className="w-32" maxLength={12} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />}</Field>
            <Button type="submit" variant="primary" disabled={!med} loading={set.isPending}>{t('locations.set')}</Button>
            <ApiErrorAlert error={set.error} className="w-full" />
          </form>
        </Card>
      )}
      <DataTable toolbar={<Field label={t('locations.filter')}>{(id) => <Input id={id} className="w-40" value={filter} onChange={(e) => setFilter(e.target.value.toUpperCase())} />}</Field>}
        rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.medicine_id}
        columns={[
          { key: 'c', header: t('locations.code'), cell: (r) => <b className="font-mono">{r.code}</b> },
          { key: 'n', header: t('common:label.medicine'), cell: (r) => r.name },
          { key: 's', header: 'SKU', cell: (r) => r.sku },
          { key: 'a', header: '', align: 'right', cell: (r) => can && <Button size="sm" onClick={() => set.mutate({ medicine_id: r.medicine_id, code: '' })}>{t('locations.clear')}</Button> },
        ]} />
    </div>
  );
}
