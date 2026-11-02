// Items promotions (12h): list, editor with the API's preview on a sample cart (same pricing engine as the POS)
// and the conflicts with other promotions. "Priority", daily hours and a per-invoice limit are not API fields.
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CatalogS } from '@/api/types';
import { useBranch, branchName } from '@/app/branch';
import { ApiErrorAlert, Button, Card, Checkbox, DataTable, Dialog, Field, Input, MultiSelect, PageHeader, Select, StatusPill, Usd, useToast } from '@/design';
import { dateTime } from '@/lib/format';
import { LinesEditor, type EditLine } from '../shared/LinesEditor';
import { MedicinePicker, medName } from '../shared/MedicinePicker';

type Promo = CatalogS['PromotionOut'];
type Create = CatalogS['PromotionCreate'];
const TYPES: Create['type'][] = ['percent_off', 'amount_off', 'buy_x_get_y', 'bundle_price', 'qty_tiers', 'group_price'];

function empty(): Create {
  return { code: '', name: '', name_km: '', type: 'percent_off', value: '', medicine_ids: [], category_ids: [], brand_ids: [], days_of_week: [], branch_ids: [], customer_group_ids: [], tiers: [], bundle_items: [], stackable: false, include_rx: false, starts_at: null, ends_at: null, max_uses_total: null, max_uses_per_customer: null };
}

function fromPromo(p: Promo): Create {
  return {
    code: p.code, name: p.name, name_km: p.name_km, type: p.type as Create['type'], value: p.value, buy_qty: p.buy_qty, get_qty: p.get_qty,
    tiers: p.tiers as Create['tiers'], bundle_items: p.bundle_items as Create['bundle_items'], medicine_ids: p.medicine_ids, category_ids: p.category_ids, brand_ids: p.brand_ids,
    starts_at: p.starts_at, ends_at: p.ends_at, days_of_week: p.days_of_week, branch_ids: p.branch_ids, customer_group_ids: p.customer_group_ids,
    max_uses_total: p.max_uses_total, max_uses_per_customer: p.max_uses_per_customer, stackable: p.stackable, include_rx: p.include_rx,
  };
}

const toLocal = (iso: string | null | undefined) => (iso ? iso.slice(0, 16) : '');
const fromLocal = (v: string) => (v ? new Date(`${v}:00+07:00`).toISOString() : null);

function Editor({ promo, onClose }: { promo: Promo | null; onClose: () => void }) {
  const { t, i18n } = useTranslation(['sales', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const { branches, oneBranch } = useBranch();
  const [v, setV] = useState<Create>(() => (promo ? fromPromo(promo) : empty()));
  const [sample, setSample] = useState<EditLine[]>([]);
  const [meds, setMeds] = useState<{ id: string; label: string }[]>([]);
  const cats = useQuery({ queryKey: ['catalog', 'categories'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/categories')) });
  const brands = useQuery({ queryKey: ['catalog', 'brands'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/brands')) });
  const groups = useQuery({ queryKey: ['customers', 'groups'], queryFn: () => call(api.customers.GET('/api/customers/v1/customer-groups')) });
  const km = i18n.language === 'km';
  const set = (p: Partial<Create>) => setV((x) => ({ ...x, ...p }));
  const body = useMemo(() => ({ ...v, value: v.value === '' ? null : v.value }), [v]);
  const save = useMutation({
    mutationFn: () => {
      if (promo) {
        const { code: _c, type: _t, ...upd } = body;
        return call(api.catalog.PATCH('/api/catalog/v1/promotions/{promotion_id}', { params: { path: { promotion_id: promo.id } }, body: upd }));
      }
      return call(api.catalog.POST('/api/catalog/v1/promotions', { body }));
    },
    onSuccess: () => { toast.success(t('promotions.saved')); void qc.invalidateQueries({ queryKey: ['catalog', 'promotions'] }); onClose(); },
  });
  const preview = useMutation({
    mutationFn: () => call(api.catalog.POST('/api/catalog/v1/promotions/preview', { body: { promotion: body, cart: { branch_id: oneBranch!.id, lines: sample.filter((l) => l.qty > 0).map((l) => ({ medicine_id: l.medicine.id, pack_unit_id: l.pack_unit_id, qty: l.qty })) } } })),
  });
  const resetPreview = preview.reset;
  useEffect(() => resetPreview(), [body, sample, resetPreview]);
  const dayNames = t('promotions.dayNames').split(',');
  return (
    <Dialog open onClose={onClose} title={promo ? t('promotions.edit') : t('promotions.new')} width={980}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" loading={save.isPending} disabled={!v.code || !v.name} onClick={() => save.mutate()}>{t('common:action.save')}</Button></>}>
      <div className="grid gap-5 desktop:grid-cols-[1.3fr_1fr]">
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-3">
            <Field label={t('promotions.code')} required>{(id) => <Input id={id} disabled={!!promo} value={v.code} maxLength={30} onChange={(e) => set({ code: e.target.value })} />}</Field>
            <Field label={t('common:label.nameEn')} required className="col-span-2">{(id) => <Input id={id} value={v.name} onChange={(e) => set({ name: e.target.value })} />}</Field>
          </div>
          <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={v.name_km ?? ''} onChange={(e) => set({ name_km: e.target.value })} />}</Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label={t('promotions.type')}>{(id) => <Select id={id} disabled={!!promo} value={v.type} onChange={(e) => set({ type: e.target.value as Create['type'] })}>{TYPES.map((x) => <option key={x} value={x}>{t(`promotions.t.${x}`)}</option>)}</Select>}</Field>
            {(v.type === 'percent_off' || v.type === 'amount_off' || v.type === 'group_price' || v.type === 'bundle_price') && (
              <Field label={v.type === 'bundle_price' ? t('promotions.bundle') : t('promotions.value')}>{(id) => <Input id={id} inputMode="decimal" value={String(v.value ?? '')} onChange={(e) => set({ value: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
            )}
            {v.type === 'buy_x_get_y' && <>
              <Field label={t('promotions.buy')}>{(id) => <Input id={id} inputMode="numeric" value={v.buy_qty ?? ''} onChange={(e) => set({ buy_qty: Number(e.target.value) || null })} />}</Field>
              <Field label={t('promotions.get')}>{(id) => <Input id={id} inputMode="numeric" value={v.get_qty ?? ''} onChange={(e) => set({ get_qty: Number(e.target.value) || null })} />}</Field>
            </>}
          </div>
          {v.type === 'qty_tiers' && (
            <Field label={t('promotions.tiers')}>{() => (
              <div className="flex flex-col gap-1.5">
                {(v.tiers ?? []).map((tr, i) => (
                  <div key={i} className="flex gap-2">
                    <Input aria-label="min qty" inputMode="numeric" value={tr.min_qty} onChange={(e) => set({ tiers: (v.tiers ?? []).map((x, j) => (j === i ? { ...x, min_qty: Number(e.target.value) || 0 } : x)) })} />
                    <Input aria-label="%" suffix="%" inputMode="decimal" value={String(tr.percent)} onChange={(e) => set({ tiers: (v.tiers ?? []).map((x, j) => (j === i ? { ...x, percent: e.target.value } : x)) })} />
                    <Button variant="ghost" onClick={() => set({ tiers: (v.tiers ?? []).filter((_, j) => j !== i) })}>✕</Button>
                  </div>
                ))}
                <Button variant="link" className="self-start" onClick={() => set({ tiers: [...(v.tiers ?? []), { min_qty: 2, percent: '5' }] })}>+ {t('common:action.add')}</Button>
              </div>
            )}</Field>
          )}
          <Field label={t('promotions.targets')}>{() => (
            <div className="flex flex-col gap-1.5">
              <div className="flex flex-wrap gap-1">{(v.medicine_ids ?? []).map((mid) => (
                <span key={mid} className="inline-flex items-center gap-1 rounded-sm bg-primary-100 px-2 py-0.5 text-[13px] text-primary-700">{meds.find((x) => x.id === mid)?.label ?? mid.slice(0, 8)}
                  <button type="button" aria-label={t('common:action.remove')} onClick={() => set({ medicine_ids: (v.medicine_ids ?? []).filter((x) => x !== mid) })}>×</button></span>
              ))}</div>
              <MedicinePicker value={null} clearOnPick onChange={(m) => { if (m) { setMeds((x) => [...x, { id: m.id, label: medName(m) }]); set({ medicine_ids: [...new Set([...(v.medicine_ids ?? []), m.id])] }); } }} />
            </div>
          )}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('promotions.categories')}>{(id) => <MultiSelect id={id} value={v.category_ids ?? []} onChange={(x) => set({ category_ids: x })} options={(cats.data ?? []).map((c) => ({ value: c.id, label: km ? c.name_km || c.name_en : c.name_en }))} />}</Field>
            <Field label={t('promotions.brands')}>{(id) => <MultiSelect id={id} value={v.brand_ids ?? []} onChange={(x) => set({ brand_ids: x })} options={(brands.data ?? []).map((c) => ({ value: c.id, label: km ? c.name_km || c.name_en : c.name_en }))} />}</Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={`${t('promotions.window')} · ${t('common:label.from')}`}>{(id) => <Input id={id} type="datetime-local" value={toLocal(v.starts_at)} onChange={(e) => set({ starts_at: fromLocal(e.target.value) })} />}</Field>
            <Field label={t('common:label.to')}>{(id) => <Input id={id} type="datetime-local" value={toLocal(v.ends_at)} onChange={(e) => set({ ends_at: fromLocal(e.target.value) })} />}</Field>
          </div>
          <Field label={t('promotions.days')}>{() => (
            <div className="flex flex-wrap gap-1.5">{dayNames.map((d, i) => {
              const on = (v.days_of_week ?? []).includes(i);
              return <button key={d} type="button" aria-pressed={on} onClick={() => set({ days_of_week: on ? (v.days_of_week ?? []).filter((x) => x !== i) : [...(v.days_of_week ?? []), i] })}
                className={on ? 'rounded-md border border-primary-600 bg-primary-600 px-2.5 py-1 text-[13px] text-white' : 'rounded-md border border-neutral-300 px-2.5 py-1 text-[13px]'}>{d}</button>;
            })}</div>
          )}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('promotions.branches')}>{(id) => <MultiSelect id={id} value={v.branch_ids ?? []} onChange={(x) => set({ branch_ids: x })} options={branches.map((b) => ({ value: b.id, label: `${b.code} ${branchName(b, i18n.language)}` }))} />}</Field>
            <Field label={t('promotions.groups')}>{(id) => <MultiSelect id={id} value={v.customer_group_ids ?? []} onChange={(x) => set({ customer_group_ids: x })} options={(groups.data ?? []).map((g) => ({ value: g.id, label: km ? g.name_km || g.name_en : g.name_en }))} />}</Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('promotions.maxTotal')}>{(id) => <Input id={id} inputMode="numeric" value={v.max_uses_total ?? ''} onChange={(e) => set({ max_uses_total: Number(e.target.value) || null })} />}</Field>
            <Field label={t('promotions.maxCustomer')}>{(id) => <Input id={id} inputMode="numeric" value={v.max_uses_per_customer ?? ''} onChange={(e) => set({ max_uses_per_customer: Number(e.target.value) || null })} />}</Field>
          </div>
          <Checkbox label={t('promotions.stackable')} checked={!!v.stackable} onChange={(e) => set({ stackable: e.target.checked })} />
          <Checkbox label={t('promotions.includeRx')} checked={!!v.include_rx} onChange={(e) => set({ include_rx: e.target.checked })} />
          <ApiErrorAlert error={save.error} />
        </div>
        <Card title={t('promotions.preview')}>
          <div className="flex flex-col gap-3">
            <span className="text-[12px] font-medium text-neutral-500">{t('promotions.sampleCart')}</span>
            <LinesEditor lines={sample} onChange={setSample} />
            <Button variant="primary" disabled={!sample.length || !oneBranch} loading={preview.isPending} onClick={() => preview.mutate()}>{t('common:action.preview')}</Button>
            <ApiErrorAlert error={preview.error} />
            {preview.data && (
              <div className="flex flex-col gap-2 text-[13px]">
                {(preview.data.lines as { line_no: number; name?: string; net?: string; promo_discount?: string; promotions?: { name_en?: string }[] }[]).map((l) => (
                  <div key={l.line_no} className="flex justify-between gap-2"><span>{l.name}{l.promotions?.length ? ` · ${l.promotions.map((p) => p.name_en).join(', ')}` : ''}</span>
                    <span className="num">{Number(l.promo_discount) > 0 && <span className="mr-2 text-safety-promotion">−{l.promo_discount}</span>}<Usd value={l.net} /></span></div>
                ))}
                <div className="flex justify-between border-t border-neutral-100 pt-2 font-semibold"><span>{t('common:label.total')}</span><Usd value={preview.data.total} /></div>
                {preview.data.conflicts.length > 0 && (
                  <div className="rounded-md bg-warning-bg p-2.5"><b>{t('promotions.conflicts')}</b>
                    {(preview.data.conflicts as { line_no: number; promotions: string[]; draft_wins: boolean }[]).map((c, i) => <div key={i}>#{c.line_no}: {c.promotions.join(', ')} → {c.draft_wins ? t('promotions.draftWins') : t('promotions.otherWins')}</div>)}
                  </div>
                )}
              </div>
            )}
          </div>
        </Card>
      </div>
    </Dialog>
  );
}

export default function PromotionsPage() {
  const { t, i18n } = useTranslation(['sales', 'common', 'nav']);
  const qc = useQueryClient();
  const [edit, setEdit] = useState<Promo | null | 'new'>(null);
  const q = useQuery({ queryKey: ['catalog', 'promotions'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/promotions')) });
  const toggle = useMutation({
    mutationFn: (p: Promo) => p.is_active
      ? call(api.catalog.POST('/api/catalog/v1/promotions/{promotion_id}/deactivate', { params: { path: { promotion_id: p.id } } }))
      : call(api.catalog.POST('/api/catalog/v1/promotions/{promotion_id}/activate', { params: { path: { promotion_id: p.id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['catalog', 'promotions'] }),
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('promotions.title')} actions={<Button variant="primary" onClick={() => setEdit('new')}>+ {t('promotions.new')}</Button>} />
      <ApiErrorAlert error={toggle.error} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(p) => p.id} onRowClick={(p) => setEdit(p)}
        columns={[
          { key: 'c', header: t('promotions.code'), cell: (p) => <span className="font-mono text-[12px]">{p.code}</span> },
          { key: 'n', header: t('common:label.name'), cell: (p) => (i18n.language === 'km' && p.name_km ? p.name_km : p.name) },
          { key: 't', header: t('promotions.type'), cell: (p) => t(`promotions.t.${p.type}`, { defaultValue: p.type }) },
          { key: 'w', header: t('promotions.window'), cell: (p) => `${dateTime(p.starts_at)} → ${dateTime(p.ends_at)}` },
          { key: 's', header: t('common:label.status'), cell: (p) => <StatusPill tone={p.is_active ? 'success' : 'neutral'}>{p.is_active ? t('status.active') : t('status.inactive')}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (p) => <Button size="sm" onClick={(e) => { e.stopPropagation(); toggle.mutate(p); }}>{p.is_active ? t('common:action.deactivate') : t('common:action.activate')}</Button> },
        ]} />
      {edit && <Editor promo={edit === 'new' ? null : edit} onClose={() => setEdit(null)} />}
    </div>
  );
}
