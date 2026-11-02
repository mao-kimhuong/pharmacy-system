// 9c Add / edit medicine. Controlled ⇒ Rx-only (the API enforces it too). No cost in the catalog.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CatalogS } from '@/api/types';
import { Alert, Checkbox, Field, Input, Select } from '@/design';

export interface MedForm {
  sku: string; brand_name: string; generic_name: string; strength: string; dosage_form: string; name_km: string; manufacturer: string;
  category_id: string; brand_id: string; base_unit: string; base_price: string; base_barcode: string; is_rx_only: boolean;
  controlled_schedule: '' | 'I' | 'II' | 'III' | 'IV'; storage: 'room' | 'cold'; reorder_level: string; active_ingredients: string; drug_classes: string;
}

export const emptyMed: MedForm = { sku: '', brand_name: '', generic_name: '', strength: '', dosage_form: '', name_km: '', manufacturer: '', category_id: '', brand_id: '', base_unit: '', base_price: '', base_barcode: '', is_rx_only: false, controlled_schedule: '', storage: 'room', reorder_level: '0', active_ingredients: '', drug_classes: '' };

export function fromMedicine(m: CatalogS['MedicineOut']): MedForm {
  return { ...emptyMed, sku: m.sku, brand_name: m.brand_name, generic_name: m.generic_name, strength: m.strength, dosage_form: m.dosage_form, name_km: m.name_km, manufacturer: m.manufacturer,
    category_id: m.category?.id ?? '', brand_id: m.brand?.id ?? '', base_unit: m.base_unit, is_rx_only: m.is_rx_only, controlled_schedule: m.controlled_schedule ?? '', storage: m.storage,
    reorder_level: String(m.reorder_level), active_ingredients: m.active_ingredients.join('; '), drug_classes: m.drug_classes.join('; ') };
}

const list = (s: string) => s.split(';').map((x) => x.trim()).filter(Boolean);

export function toCreate(f: MedForm): CatalogS['MedicineCreate'] {
  return { sku: f.sku, brand_name: f.brand_name, generic_name: f.generic_name, strength: f.strength, dosage_form: f.dosage_form, name_km: f.name_km, manufacturer: f.manufacturer,
    category_id: f.category_id || null, brand_id: f.brand_id || null, base_unit: f.base_unit, base_price: f.base_price, base_barcode: f.base_barcode || null,
    is_rx_only: f.is_rx_only || !!f.controlled_schedule, controlled_schedule: f.controlled_schedule || null, storage: f.storage, reorder_level: Number(f.reorder_level) || 0,
    active_ingredients: f.active_ingredients ? list(f.active_ingredients) : null, drug_classes: list(f.drug_classes) };
}

export function toUpdate(f: MedForm): CatalogS['MedicineUpdate'] {
  const { base_price: _p, base_barcode: _b, ...c } = toCreate(f);
  return { ...c, active_ingredients: list(f.active_ingredients) };
}

export function MedicineFields({ v, set, editing }: { v: MedForm; set: (p: Partial<MedForm>) => void; editing?: boolean }) {
  const { t, i18n } = useTranslation(['warehouse', 'common']);
  const cats = useQuery({ queryKey: ['catalog', 'categories'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/categories')) });
  const brands = useQuery({ queryKey: ['catalog', 'brands'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/brands')) });
  const km = i18n.language === 'km';
  const [touched] = useState(false);
  return (
    <div className="grid gap-3 tablet:grid-cols-2 desktop:grid-cols-3">
      <Field label={t('products.sku')} required>{(id) => <Input id={id} value={v.sku} onChange={(e) => set({ sku: e.target.value.toUpperCase() })} autoFocus={!editing} />}</Field>
      <Field label={t('products.brandName')} required>{(id) => <Input id={id} value={v.brand_name} onChange={(e) => set({ brand_name: e.target.value })} />}</Field>
      <Field label={t('products.generic')} required>{(id) => <Input id={id} value={v.generic_name} onChange={(e) => set({ generic_name: e.target.value })} />}</Field>
      <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={v.name_km} onChange={(e) => set({ name_km: e.target.value })} />}</Field>
      <Field label={t('products.strength')}>{(id) => <Input id={id} value={v.strength} onChange={(e) => set({ strength: e.target.value })} />}</Field>
      <Field label={t('products.form')}>{(id) => <Input id={id} value={v.dosage_form} onChange={(e) => set({ dosage_form: e.target.value })} />}</Field>
      <Field label={t('common:label.category')}>{(id) => <Select id={id} value={v.category_id} onChange={(e) => set({ category_id: e.target.value })}><option value="">—</option>{cats.data?.filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{km && c.name_km ? c.name_km : c.name_en}</option>)}</Select>}</Field>
      <Field label={t('common:label.brand')}>{(id) => <Select id={id} value={v.brand_id} onChange={(e) => set({ brand_id: e.target.value })}><option value="">—</option>{brands.data?.filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{km && c.name_km ? c.name_km : c.name_en}</option>)}</Select>}</Field>
      <Field label={t('products.manufacturer')}>{(id) => <Input id={id} value={v.manufacturer} onChange={(e) => set({ manufacturer: e.target.value })} />}</Field>
      <Field label={t('products.baseUnit')} required>{(id) => <Input id={id} value={v.base_unit} onChange={(e) => set({ base_unit: e.target.value })} />}</Field>
      {!editing && <Field label={t('products.basePrice')} required>{(id) => <Input id={id} prefix="$" inputMode="decimal" value={v.base_price} onChange={(e) => set({ base_price: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>}
      {!editing && <Field label={t('products.baseBarcode')}>{(id) => <Input id={id} value={v.base_barcode} onChange={(e) => set({ base_barcode: e.target.value })} />}</Field>}
      <Field label={t('products.schedule')}>{(id) => <Select id={id} value={v.controlled_schedule} onChange={(e) => set({ controlled_schedule: e.target.value as MedForm['controlled_schedule'] })}><option value="">{t('products.none')}</option>{['I', 'II', 'III', 'IV'].map((s) => <option key={s} value={s}>{s}</option>)}</Select>}</Field>
      <Field label={t('products.storage')}>{(id) => <Select id={id} value={v.storage} onChange={(e) => set({ storage: e.target.value as 'room' | 'cold' })}><option value="room">{t('products.room')}</option><option value="cold">{t('products.cold')}</option></Select>}</Field>
      <Field label={t('products.reorderLevel')}>{(id) => <Input id={id} inputMode="numeric" value={v.reorder_level} onChange={(e) => set({ reorder_level: e.target.value.replace(/\D/g, '') })} />}</Field>
      <Field label={t('products.ingredients')} className="tablet:col-span-2">{(id) => <Input id={id} value={v.active_ingredients} onChange={(e) => set({ active_ingredients: e.target.value })} />}</Field>
      <Field label={t('products.classes')}>{(id) => <Input id={id} value={v.drug_classes} onChange={(e) => set({ drug_classes: e.target.value })} />}</Field>
      <Checkbox label={t('products.rxOnly')} checked={v.is_rx_only || !!v.controlled_schedule} disabled={!!v.controlled_schedule} onChange={(e) => set({ is_rx_only: e.target.checked })} />
      {v.controlled_schedule && !touched && <Alert tone="info" className="tablet:col-span-2">{t('products.controlledRx')}</Alert>}
    </div>
  );
}
