// 18b Re-order settings: min / max / lead time / preferred supplier per medicine, or for a whole category.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, DataTable, Dialog, Field, Input, PageHeader, Select, useToast } from '@/design';
import { MedicinePicker, type Medicine } from '../shared/MedicinePicker';
import { SupplierPicker, type Supplier } from '../shared/SupplierPicker';
import { useMedicineNames } from '../shared/hooks';

interface Form { medicine: Medicine | null; category_id: string; min: string; max: string; lead: string; supplier: Supplier | null }
const n = (v: string) => (v === '' ? null : Number(v));

export default function ReorderSettingsPage() {
  const { t, i18n } = useTranslation(['stock', 'common', 'nav']);
  const qc = useQueryClient();
  const toast = useToast();
  const { oneBranch } = useBranch();
  const [form, setForm] = useState<(Form & { bulk: boolean }) | null>(null);
  const q = useQuery({ queryKey: ['inventory', 'reorder-settings', oneBranch?.id], enabled: !!oneBranch, queryFn: () => call(api.inventory.GET('/api/inventory/v1/reorder-settings', { params: { query: { branch_id: oneBranch!.id } } })) });
  const cats = useQuery({ queryKey: ['catalog', 'categories'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/categories')) });
  const names = useMedicineNames(q.data?.map((s) => s.medicine_id) ?? []);
  const save = useMutation({
    mutationFn: async () => {
      const f = form!;
      const common = { branch_id: oneBranch!.id, min_qty: n(f.min), max_qty: n(f.max), lead_time_days: n(f.lead), preferred_supplier_id: f.supplier?.id ?? null };
      if (f.bulk) {
        const r = await call(api.inventory.POST('/api/inventory/v1/reorder-settings/bulk', { body: { ...common, category_id: f.category_id } }));
        toast.success(t('reorder.updated', { count: (r as { updated?: number }).updated ?? 0 }));
      } else await call(api.inventory.PUT('/api/inventory/v1/reorder-settings', { body: { ...common, medicine_id: f.medicine!.id } }));
    },
    onSuccess: () => { setForm(null); void qc.invalidateQueries({ queryKey: ['inventory', 'reorder-settings'] }); },
  });
  const blank: Form = { medicine: null, category_id: '', min: '', max: '', lead: '', supplier: null };
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.stock')} title={t('reorder.settings')}
        actions={<><Button onClick={() => setForm({ ...blank, bulk: true })}>{t('reorder.bulk')}</Button><Button variant="primary" onClick={() => setForm({ ...blank, bulk: false })}>+ {t('reorder.add')}</Button></>} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(s) => s.medicine_id}
        onRowClick={(s) => setForm({ bulk: false, medicine: { id: s.medicine_id } as Medicine, category_id: '', min: s.min_qty?.toString() ?? '', max: s.max_qty?.toString() ?? '', lead: s.lead_time_days?.toString() ?? '', supplier: null })}
        columns={[
          { key: 'm', header: t('common:label.medicine'), cell: (s) => names(s.medicine_id) },
          { key: 'mi', header: t('reorder.min'), align: 'right', cell: (s) => s.min_qty ?? '—' },
          { key: 'ma', header: t('reorder.max'), align: 'right', cell: (s) => s.max_qty ?? '—' },
          { key: 'l', header: t('reorder.lead'), align: 'right', cell: (s) => s.lead_time_days ?? '—' },
          { key: 's', header: t('reorder.supplier'), cell: (s) => (s.preferred_supplier_id ? '✓' : '—') },
        ]} />
      <Dialog open={!!form} onClose={() => setForm(null)} title={form?.bulk ? t('reorder.bulk') : t('reorder.settings')} width={520}
        footer={<><Button onClick={() => setForm(null)}>{t('common:action.cancel')}</Button><Button variant="primary" loading={save.isPending} disabled={form ? (form.bulk ? !form.category_id : !form.medicine) : true} onClick={() => save.mutate()}>{t('common:action.save')}</Button></>}>
        {form && (
          <div className="flex flex-col gap-3">
            {form.bulk
              ? <Field label={t('common:label.category')}>{(id) => <Select id={id} value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}><option value="">—</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{i18n.language === 'km' && c.name_km ? c.name_km : c.name_en}</option>)}</Select>}</Field>
              : form.medicine?.sku || !form.medicine ? <Field label={t('common:label.medicine')}>{(id) => <MedicinePicker id={id} value={form.medicine} onChange={(m) => setForm({ ...form, medicine: m })} />}</Field>
                : <b>{names(form.medicine.id)}</b>}
            <div className="grid grid-cols-3 gap-3">
              <Field label={t('reorder.min')}>{(id) => <Input id={id} inputMode="numeric" value={form.min} onChange={(e) => setForm({ ...form, min: e.target.value.replace(/\D/g, '') })} />}</Field>
              <Field label={t('reorder.max')}>{(id) => <Input id={id} inputMode="numeric" value={form.max} onChange={(e) => setForm({ ...form, max: e.target.value.replace(/\D/g, '') })} />}</Field>
              <Field label={t('reorder.lead')}>{(id) => <Input id={id} inputMode="numeric" value={form.lead} onChange={(e) => setForm({ ...form, lead: e.target.value.replace(/\D/g, '') })} />}</Field>
            </div>
            <Field label={t('reorder.supplier')}>{(id) => <SupplierPicker id={id} value={form.supplier} onChange={(s) => setForm({ ...form, supplier: s })} />}</Field>
            <ApiErrorAlert error={save.error} />
          </div>
        )}
      </Dialog>
    </div>
  );
}
