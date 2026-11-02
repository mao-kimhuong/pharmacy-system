// 9d Hampers: a sellable medicine made of components (base units); no stock of its own. Availability = what
// the branch can make now (lowest component).
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CatalogS } from '@/api/types';
import { useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, Button, Card, DataTable, Dialog, Field, Input, PageHeader, Usd } from '@/design';
import { MedicinePicker, medName, type Medicine } from '../shared/MedicinePicker';
import { useMedicineNames } from '../shared/hooks';

type Hamper = CatalogS['MedicineOut'];
interface Comp { medicine_id: string; name: string; qty_base: string }

function Availability({ hamperId }: { hamperId: string }) {
  const { oneBranch } = useBranch();
  const q = useQuery({ queryKey: ['inventory', 'hamper', hamperId, oneBranch?.id], enabled: !!oneBranch, queryFn: () => call(api.inventory.GET('/api/inventory/v1/hampers/{hamper_id}/availability', { params: { path: { hamper_id: hamperId }, query: { branch_id: oneBranch!.id } } })) });
  return <b>{q.data?.available ?? '…'}</b>;
}

export default function HampersPage() {
  const { t } = useTranslation(['warehouse', 'common', 'nav']);
  const qc = useQueryClient();
  const [edit, setEdit] = useState<{ hamper: Hamper | null; sku: string; name: string; name_km: string; price: string; barcode: string; comps: Comp[] } | null>(null);
  const q = useQuery({ queryKey: ['catalog', 'hampers'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/hampers')) });
  const names = useMedicineNames((q.data ?? []).flatMap((h) => (h.components ?? []).map((c) => c.component_id)));
  const save = useMutation({
    mutationFn: () => {
      const e = edit!;
      const components = e.comps.map((c) => ({ medicine_id: c.medicine_id, qty_base: Number(c.qty_base) }));
      return e.hamper
        ? call(api.catalog.PUT('/api/catalog/v1/hampers/{hamper_id}/components', { params: { path: { hamper_id: e.hamper.id } }, body: { components } }))
        : call(api.catalog.POST('/api/catalog/v1/hampers', { body: { sku: e.sku, name: e.name, name_km: e.name_km, price: e.price, barcode: e.barcode || null, components } }));
    },
    onSuccess: () => { setEdit(null); void qc.invalidateQueries({ queryKey: ['catalog'] }); },
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.warehouse')} title={t('hampers.title')} actions={<Button variant="primary" onClick={() => setEdit({ hamper: null, sku: '', name: '', name_km: '', price: '', barcode: '', comps: [] })}>+ {t('hampers.new')}</Button>} />
      <Alert tone="info">{t('hampers.hint')}</Alert>
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(h) => h.id}
        onRowClick={(h) => setEdit({ hamper: h, sku: h.sku, name: h.brand_name, name_km: h.name_km, price: h.pack_units[0]?.sell_price ?? '', barcode: '', comps: (h.components ?? []).map((c) => ({ medicine_id: c.component_id, name: names(c.component_id), qty_base: String(c.qty_base) })) })}
        columns={[
          { key: 's', header: 'SKU', cell: (h) => <span className="font-mono text-[12px]">{h.sku}</span> },
          { key: 'n', header: t('common:label.name'), cell: (h) => h.brand_name },
          { key: 'c', header: t('hampers.components'), cell: (h) => <span className="text-[12px]">{(h.components ?? []).map((c) => `${names(c.component_id)} ×${c.qty_base}`).join(' · ')}</span> },
          { key: 'p', header: t('common:label.price'), align: 'right', cell: (h) => <Usd value={h.pack_units[0]?.sell_price} /> },
          { key: 'a', header: t('hampers.available'), align: 'right', cell: (h) => <Availability hamperId={h.id} /> },
        ]} />
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.hamper ? edit.hamper.brand_name : t('hampers.new')} width={680}
        footer={<><Button onClick={() => setEdit(null)}>{t('common:action.cancel')}</Button><Button variant="primary" loading={save.isPending} disabled={!edit?.comps.length || (!edit?.hamper && (!edit?.sku || !edit?.name || !edit?.price))} onClick={() => save.mutate()}>{edit?.hamper ? t('hampers.save') : t('common:action.save')}</Button></>}>
        {edit && (
          <div className="flex flex-col gap-3">
            {!edit.hamper && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="SKU" required>{(id) => <Input id={id} value={edit.sku} onChange={(e) => setEdit({ ...edit, sku: e.target.value.toUpperCase() })} />}</Field>
                <Field label={t('hampers.price')} required>{(id) => <Input id={id} prefix="$" inputMode="decimal" value={edit.price} onChange={(e) => setEdit({ ...edit, price: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
                <Field label={t('common:label.nameEn')} required>{(id) => <Input id={id} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />}</Field>
                <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={edit.name_km} onChange={(e) => setEdit({ ...edit, name_km: e.target.value })} />}</Field>
                <Field label={t('packs.barcode')}>{(id) => <Input id={id} value={edit.barcode} onChange={(e) => setEdit({ ...edit, barcode: e.target.value })} />}</Field>
              </div>
            )}
            <span className="text-[13px] font-medium">{t('hampers.components')}</span>
            {edit.comps.map((c, i) => (
              <div key={c.medicine_id} className="flex items-center gap-2">
                <span className="flex-1">{c.name}</span>
                <Input aria-label={`${t('common:label.qty')} ${c.name}`} className="w-24 text-right" inputMode="numeric" value={c.qty_base} onChange={(e) => setEdit({ ...edit, comps: edit.comps.map((x, j) => (j === i ? { ...x, qty_base: e.target.value.replace(/\D/g, '') } : x)) })} />
                <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setEdit({ ...edit, comps: edit.comps.filter((_, j) => j !== i) })}>✕</Button>
              </div>
            ))}
            <MedicinePicker value={null} clearOnPick filter={(m: Medicine) => m.kind !== 'hamper'} onChange={(m) => m && setEdit({ ...edit, comps: [...edit.comps, { medicine_id: m.id, name: medName(m), qty_base: '1' }] })} />
            <ApiErrorAlert error={save.error} />
          </div>
        )}
      </Dialog>
      <Card className="hidden"><span /></Card>
    </div>
  );
}
