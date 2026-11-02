// 9b / 12n Medicine detail: information (edit), pack units & prices (add, edit, deactivate with reason), price
// history (sell prices; cost history is the Cost Change report), deactivate / activate.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CatalogS } from '@/api/types';
import { useUser } from '@/app/auth';
import { QueryState } from '@/app/RouteError';
import { ApiErrorAlert, Button, Card, DataTable, DefinitionList, Dialog, Field, Input, PageHeader, ReasonDialog, SafetyBadge, SkeletonRows, StatusPill, Tabs, Usd, useToast } from '@/design';
import { dateTime } from '@/lib/format';
import { useStaffNames } from '../shared/hooks';
import { MedicineFields, fromMedicine, toUpdate, type MedForm } from './MedicineForm';

type Pack = CatalogS['PackUnitOut'];

export default function ProductDetailPage() {
  const { id = '' } = useParams();
  const { t, i18n } = useTranslation(['warehouse', 'common', 'nav', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const staff = useStaffNames();
  const [tab, setTab] = useState<'info' | 'packs' | 'history'>('info');
  const [edit, setEdit] = useState<MedForm | null>(null);
  const [pack, setPack] = useState<Partial<Pack> & { sell_price?: string } | null>(null);
  const [deactPack, setDeactPack] = useState<Pack | null>(null);
  const [deact, setDeact] = useState(false);
  const q = useQuery({ queryKey: ['catalog', 'medicine', id], queryFn: () => call(api.catalog.GET('/api/catalog/v1/medicines/{medicine_id}', { params: { path: { medicine_id: id } } })) });
  const hist = useQuery({ queryKey: ['catalog', 'price-history', id], enabled: tab === 'history', queryFn: () => call(api.catalog.GET('/api/catalog/v1/medicines/{medicine_id}/price-history', { params: { path: { medicine_id: id } } })) });
  const refresh = () => qc.invalidateQueries({ queryKey: ['catalog'] });
  const save = useMutation({ mutationFn: () => call(api.catalog.PATCH('/api/catalog/v1/medicines/{medicine_id}', { params: { path: { medicine_id: id } }, body: toUpdate(edit!) })), onSuccess: () => { setEdit(null); toast.success(t('products.saved')); void refresh(); } });
  const savePack = useMutation({
    mutationFn: () => {
      const body = { name: pack!.name ?? '', qty_in_base: Number(pack!.qty_in_base), barcode: pack!.barcode || null, sell_price: pack!.sell_price ?? '' };
      return pack!.id
        ? call(api.catalog.PATCH('/api/catalog/v1/pack-units/{pack_unit_id}', { params: { path: { pack_unit_id: pack!.id } }, body }))
        : call(api.catalog.POST('/api/catalog/v1/medicines/{medicine_id}/pack-units', { params: { path: { medicine_id: id } }, body }));
    },
    onSuccess: () => { setPack(null); void refresh(); },
  });
  const activate = useMutation({ mutationFn: () => call(api.catalog.POST('/api/catalog/v1/medicines/{medicine_id}/activate', { params: { path: { medicine_id: id } } })), onSuccess: () => void refresh() });
  const packOn = useMutation({ mutationFn: (pid: string) => call(api.catalog.POST('/api/catalog/v1/pack-units/{pack_unit_id}/activate', { params: { path: { pack_unit_id: pid } } })), onSuccess: () => void refresh() });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  const m = q.data;
  if (!m) return <SkeletonRows />;
  const manage = user.has('products.manage');
  const km = i18n.language === 'km';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.warehouse')} / ${t('products.title')}`} title={`${m.brand_name} ${m.strength}`}
        actions={manage && <>
          <Button onClick={() => setEdit(fromMedicine(m))}>{t('common:action.edit')}</Button>
          {m.is_active ? <Button onClick={() => setDeact(true)}>{t('common:action.deactivate')}</Button> : <Button onClick={() => activate.mutate()}>{t('common:action.activate')}</Button>}
        </>}>
        <div className="flex flex-wrap items-center gap-1.5"><span className="font-mono text-[12px]">{m.sku}</span>{m.is_rx_only && <SafetyBadge kind="rx" />}{m.controlled_schedule && <SafetyBadge kind="controlled">{m.controlled_schedule}</SafetyBadge>}
          <StatusPill tone={m.is_active ? 'success' : 'neutral'}>{m.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill></div>
      </PageHeader>
      <ApiErrorAlert error={activate.error ?? packOn.error} />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: 'info', label: t('products.info') }, { value: 'packs', label: t('packs.title'), count: m.pack_units.length }, { value: 'history', label: t('history.title') }]} />
      {tab === 'info' && (
        <Card>
          <DefinitionList cols={3} items={[
            { label: t('products.generic'), value: m.generic_name },
            { label: t('common:label.nameKm'), value: <span className="km">{m.name_km || '—'}</span> },
            { label: t('products.form'), value: m.dosage_form || '—' },
            { label: t('common:label.category'), value: m.category ? (km && m.category.name_km ? m.category.name_km : m.category.name_en) : '—' },
            { label: t('common:label.brand'), value: m.brand ? (km && m.brand.name_km ? m.brand.name_km : m.brand.name_en) : '—' },
            { label: t('products.manufacturer'), value: m.manufacturer || '—' },
            { label: t('products.baseUnit'), value: m.base_unit },
            { label: t('products.storage'), value: m.storage === 'cold' ? t('products.cold') : t('products.room') },
            { label: t('products.reorderLevel'), value: m.reorder_level },
            { label: t('products.ingredients'), value: m.active_ingredients.join('; ') || '—' },
            { label: t('products.classes'), value: m.drug_classes.join('; ') || '—' },
          ]} />
        </Card>
      )}
      {tab === 'packs' && (
        <Card padded={false} title={t('packs.title')} actions={manage && <Button size="sm" onClick={() => setPack({ qty_in_base: 1 })}>+ {t('packs.add')}</Button>}>
          <DataTable className="rounded-none border-0" rows={m.pack_units} rowKey={(p) => p.id} columns={[
            { key: 'n', header: t('packs.name'), cell: (p) => <span className="flex items-center gap-1.5">{p.name}{p.is_base && <StatusPill tone="primary">{t('packs.base')}</StatusPill>}</span> },
            { key: 'q', header: t('packs.qtyInBase'), align: 'right', cell: (p) => p.qty_in_base },
            { key: 'b', header: t('packs.barcode'), cell: (p) => <span className="font-mono text-[12px]">{p.barcode ?? '—'}</span> },
            { key: 'p', header: t('packs.price'), align: 'right', cell: (p) => <Usd value={p.sell_price} strong /> },
            { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={p.is_active ? 'success' : 'neutral'}>{p.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
            { key: 'a', header: '', align: 'right', cell: (p) => manage && (
              <span className="flex justify-end gap-1">
                <Button size="sm" onClick={() => setPack({ ...p, sell_price: p.sell_price })}>{t('common:action.edit')}</Button>
                {!p.is_base && (p.is_active ? <Button size="sm" onClick={() => setDeactPack(p)}>{t('common:action.deactivate')}</Button> : <Button size="sm" onClick={() => packOn.mutate(p.id)}>{t('common:action.activate')}</Button>)}
              </span>
            ) },
          ]} />
        </Card>
      )}
      {tab === 'history' && (
        <Card padded={false} title={t('history.title')} actions={<span className="text-[12px] text-neutral-500">{t('history.costNote')}</span>}>
          <DataTable className="rounded-none border-0" rows={hist.data} loading={hist.isLoading} error={hist.error} rowKey={(h, i) => `${h.pack_unit_id}${h.changed_at}${i}`} columns={[
            { key: 'w', header: t('history.when'), cell: (h) => dateTime(h.changed_at) },
            { key: 'p', header: t('packs.name'), cell: (h) => h.pack_unit },
            { key: 'o', header: t('history.old'), align: 'right', cell: (h) => <Usd value={h.old_price} /> },
            { key: 'n', header: t('history.new'), align: 'right', cell: (h) => <Usd value={h.new_price} strong /> },
            { key: 's', header: t('history.source'), cell: (h) => `${h.source} · ${staff(h.changed_by)}` },
          ]} />
        </Card>
      )}
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={t('common:action.edit')} width={960}
        footer={<><Button onClick={() => setEdit(null)}>{t('common:action.cancel')}</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>{t('common:action.save')}</Button></>}>
        {edit && <><MedicineFields v={edit} set={(p) => setEdit({ ...edit, ...p })} editing /><ApiErrorAlert error={save.error} className="mt-3" /></>}
      </Dialog>
      <Dialog open={!!pack} onClose={() => setPack(null)} title={pack?.id ? t('packs.edit') : t('packs.add')} width={480}
        footer={<><Button onClick={() => setPack(null)}>{t('common:action.cancel')}</Button><Button variant="primary" loading={savePack.isPending} disabled={!pack?.name || !Number(pack?.qty_in_base) || !pack?.sell_price} onClick={() => savePack.mutate()}>{t('common:action.save')}</Button></>}>
        {pack && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('packs.name')} required>{(fid) => <Input id={fid} value={pack.name ?? ''} disabled={pack.is_base} onChange={(e) => setPack({ ...pack, name: e.target.value })} autoFocus />}</Field>
            <Field label={t('packs.qtyInBase')} required>{(fid) => <Input id={fid} inputMode="numeric" disabled={pack.is_base} value={pack.qty_in_base ?? ''} onChange={(e) => setPack({ ...pack, qty_in_base: Number(e.target.value.replace(/\D/g, '')) })} />}</Field>
            <Field label={t('packs.barcode')}>{(fid) => <Input id={fid} value={pack.barcode ?? ''} onChange={(e) => setPack({ ...pack, barcode: e.target.value })} />}</Field>
            <Field label={t('packs.price')} required>{(fid) => <Input id={fid} prefix="$" inputMode="decimal" value={pack.sell_price ?? ''} onChange={(e) => setPack({ ...pack, sell_price: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
            <ApiErrorAlert error={savePack.error} className="col-span-2" />
          </div>
        )}
      </Dialog>
      <ReasonDialog open={deact} onClose={() => setDeact(false)} title={t('common:confirm.deactivateTitle', { name: m.brand_name })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => { await call(api.catalog.POST('/api/catalog/v1/medicines/{medicine_id}/deactivate', { params: { path: { medicine_id: id } }, body: { reason } })); await refresh(); }} />
      <ReasonDialog open={!!deactPack} onClose={() => setDeactPack(null)} title={t('common:confirm.deactivateTitle', { name: deactPack?.name })} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => { await call(api.catalog.POST('/api/catalog/v1/pack-units/{pack_unit_id}/deactivate', { params: { path: { pack_unit_id: deactPack!.id } }, body: { reason } })); await refresh(); }} />
    </div>
  );
}
