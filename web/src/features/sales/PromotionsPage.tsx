// Items promotions (12h): list, editor with the API's preview on a sample cart (same pricing engine as the POS)
// and the conflicts with other promotions. "Priority", daily hours and a per-invoice limit are not API fields.
// API errors show next to their field (fieldErrors); dates are Phnom Penh time.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { fieldErrors } from '@/api/fieldErrors';
import type { CatalogS } from '@/api/types';
import { useUser } from '@/app/auth';
import { useBranch, branchName } from '@/app/branch';
import { Alert, ApiErrorAlert, Button, Card, Checkbox, DataTable, Dialog, Field, Input, MultiSelect, PageHeader, Select, StatusPill, Usd, cx, useToast } from '@/design';
import { errorText } from '@/i18n/errors';
import { dateTime, fromPhnomPenhInput, phnomPenhInput } from '@/lib/format';
import { CustomerPicker, type Customer } from '../shared/CustomerPicker';
import { LinesEditor, type EditLine } from '../shared/LinesEditor';
import { MedicinePicker, medName } from '../shared/MedicinePicker';
import { TYPES, hasValue, promotionBody, type Create } from './promotionForm';

type Promo = CatalogS['PromotionOut'];

function empty(branchIds: string[]): Create {
  return { code: '', name: '', name_km: '', type: 'percent_off', value: '', medicine_ids: [], category_ids: [], brand_ids: [], days_of_week: [], branch_ids: branchIds, customer_group_ids: [], tiers: [], bundle_items: [], stackable: false, include_rx: false, starts_at: null, ends_at: null, max_uses_total: null, max_uses_per_customer: null };
}

function fromPromo(p: Promo): Create {
  return {
    code: p.code, name: p.name, name_km: p.name_km, type: p.type as Create['type'], value: p.value, buy_qty: p.buy_qty, get_qty: p.get_qty,
    tiers: p.tiers as Create['tiers'], bundle_items: p.bundle_items as Create['bundle_items'], medicine_ids: p.medicine_ids, category_ids: p.category_ids, brand_ids: p.brand_ids,
    starts_at: p.starts_at, ends_at: p.ends_at, days_of_week: p.days_of_week, branch_ids: p.branch_ids, customer_group_ids: p.customer_group_ids,
    max_uses_total: p.max_uses_total, max_uses_per_customer: p.max_uses_per_customer, stackable: p.stackable, include_rx: p.include_rx,
  };
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" aria-pressed={on} onClick={onClick}
    className={cx('rounded-full border px-3 py-1.5 text-[13px] font-medium', on ? 'border-primary-600 bg-primary-600 text-white' : 'border-neutral-300 bg-surface text-neutral-900')}>{children}</button>;
}

function Editor({ promo, onClose }: { promo: Promo | null; onClose: () => void }) {
  const { t, i18n } = useTranslation(['sales', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const user = useUser();
  const { branches, oneBranch } = useBranch();
  const [v, setV] = useState<Create>(() => (promo ? fromPromo(promo) : empty(user.isOwner ? [] : branches.map((b) => b.id))));
  const [sample, setSample] = useState<EditLine[]>([]);
  const [sampleBranch, setSampleBranch] = useState(oneBranch?.id ?? promo?.branch_ids[0] ?? branches[0]?.id ?? '');
  const [sampleCustomer, setSampleCustomer] = useState<Customer | null>(null);
  const [meds, setMeds] = useState<{ id: string; label: string }[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  const form = useRef<HTMLDivElement>(null);
  const cats = useQuery({ queryKey: ['catalog', 'categories'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/categories')) });
  const brands = useQuery({ queryKey: ['catalog', 'brands'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/brands')) });
  const groups = useQuery({ queryKey: ['customers', 'groups'], queryFn: () => call(api.customers.GET('/api/customers/v1/customer-groups')) });
  const km = i18n.language === 'km';
  const set = (p: Partial<Create>) => setV((x) => ({ ...x, ...p }));
  const body = useMemo(() => promotionBody(v), [v]);
  // names of the medicines already on a saved promotion
  const ids = useMemo(() => [...new Set([...(v.medicine_ids ?? []), ...(v.bundle_items ?? []).map((b) => b.medicine_id)])], [v.medicine_ids, v.bundle_items]);
  const named = useQueries({ queries: ids.filter((id) => !meds.some((m) => m.id === id)).map((id) => ({
    queryKey: ['catalog', 'medicine', id],
    queryFn: () => call(api.catalog.GET('/api/catalog/v1/medicines/{medicine_id}', { params: { path: { medicine_id: id } } })),
  })) });
  const medLabel = (id: string) => meds.find((x) => x.id === id)?.label ?? (() => { const m = named.find((q) => q.data?.id === id)?.data; return m ? medName(m) : '…'; })();
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
    // a draft needs no real code or name to be priced
    mutationFn: () => call(api.catalog.POST('/api/catalog/v1/promotions/preview', { body: { promotion: { ...body, code: body.code || 'PREVIEW', name: body.name || 'Preview' }, cart: { branch_id: sampleBranch, customer_id: sampleCustomer?.id ?? null, lines: sample.filter((l) => l.qty > 0).map((l) => ({ medicine_id: l.medicine.id, pack_unit_id: l.pack_unit_id, qty: l.qty })) } } })),
  });
  const resetPreview = preview.reset;
  useEffect(() => resetPreview(), [body, sample, sampleBranch, sampleCustomer, resetPreview]);
  const apiErrors = useMemo(() => fieldErrors(save.error ?? preview.error, { DUPLICATE_CODE: 'code' }), [save.error, preview.error]);
  const errors = useMemo(() => ({ ...Object.fromEntries(missing.map((f) => [f, { reason: 'required' }])), ...apiErrors }), [missing, apiErrors]);
  const count = Object.keys(errors).length;
  useEffect(() => { if (count) form.current?.querySelector('[role="alert"]')?.scrollIntoView({ block: 'center' }); }, [count, save.error]);
  const err = (f: string) => {
    const r = errors[f]?.reason;
    if (!r) return undefined;
    const key = `promotions.err.${r}`;
    return i18n.exists(key, { ns: 'sales' }) ? t(key) : errorText(r, km ? 'km' : 'en', t('promotions.err.invalid'));
  };
  const submit = () => {
    const blank = (['code', 'name'] as const).filter((f) => !v[f]?.trim());
    setMissing(blank);
    if (!blank.length) save.mutate();
  };
  const dayNames = t('promotions.dayNames').split(',');
  const money = v.type === 'percent_off' ? '%' : '$';
  const valueLabel = { percent_off: t('promotions.valuePct'), amount_off: t('promotions.valueAmount'), bundle_price: t('promotions.bundle'), group_price: t('promotions.valueGroup') }[v.type as string];
  const num = (s: string) => Number(s.replace(/\D/g, '')) || null;
  return (
    <Dialog open onClose={onClose} title={promo ? t('promotions.edit') : t('promotions.new')} width={1100}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" loading={save.isPending} onClick={submit}>{t('common:action.save')}</Button></>}>
      <div className="grid gap-5 desktop:grid-cols-[minmax(0,1fr)_400px]">
        <div ref={form} className="flex flex-col gap-3">
          {count > 0 && <Alert tone="danger">{t('promotions.err.count', { count })}</Alert>}
          <div className="grid grid-cols-3 gap-3">
            <Field label={t('promotions.code')} required error={err('code')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} disabled={!!promo} value={v.code} maxLength={30} onChange={(e) => set({ code: e.target.value })} />}</Field>
            <Field label={t('common:label.nameEn')} required className="col-span-2" error={err('name')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} value={v.name} onChange={(e) => set({ name: e.target.value })} />}</Field>
          </div>
          <Field label={t('common:label.nameKm')}>{(id) => <Input id={id} className="km" value={v.name_km ?? ''} onChange={(e) => set({ name_km: e.target.value })} />}</Field>
          <Field label={t('promotions.type')} hint={promo ? t('promotions.typeFixed') : undefined}>{() => (
            <div className="flex flex-wrap gap-1.5">{TYPES.map((x) => <Chip key={x} on={v.type === x} onClick={() => { if (!promo) set({ type: x }); }}>{t(`promotions.t.${x}`)}</Chip>)}</div>
          )}</Field>
          <div className="grid grid-cols-3 gap-3">
            {hasValue(v.type) && (
              <Field label={valueLabel} required error={err('value')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} suffix={money} inputMode="decimal" value={String(v.value ?? '')} onChange={(e) => set({ value: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
            )}
            {v.type === 'buy_x_get_y' && <>
              <Field label={t('promotions.buy')} required hint={t('promotions.baseUnits')} error={err('buy_qty')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} inputMode="numeric" value={v.buy_qty ?? ''} onChange={(e) => set({ buy_qty: num(e.target.value) })} />}</Field>
              <Field label={t('promotions.get')} required error={err('get_qty')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} inputMode="numeric" value={v.get_qty ?? ''} onChange={(e) => set({ get_qty: num(e.target.value) })} />}</Field>
            </>}
          </div>
          {v.type === 'qty_tiers' && (
            <Field label={t('promotions.tiers')} required error={err('tiers')}>{() => (
              <div className="flex flex-col gap-1.5">
                {(v.tiers ?? []).map((tr, i) => (
                  <div key={i} className="flex gap-2">
                    <Input aria-label={t('promotions.tierQty')} inputMode="numeric" value={tr.min_qty} onChange={(e) => set({ tiers: (v.tiers ?? []).map((x, j) => (j === i ? { ...x, min_qty: Number(e.target.value.replace(/\D/g, '')) || 0 } : x)) })} />
                    <Input aria-label={t('promotions.tierPct')} suffix="%" inputMode="decimal" value={String(tr.percent)} onChange={(e) => set({ tiers: (v.tiers ?? []).map((x, j) => (j === i ? { ...x, percent: e.target.value.replace(/[^\d.]/g, '') } : x)) })} />
                    <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => set({ tiers: (v.tiers ?? []).filter((_, j) => j !== i) })}>✕</Button>
                  </div>
                ))}
                <Button variant="link" className="self-start" onClick={() => set({ tiers: [...(v.tiers ?? []), { min_qty: 2, percent: '5' }] })}>+ {t('promotions.addTier')}</Button>
              </div>
            )}</Field>
          )}
          {v.type === 'bundle_price' ? (
            <Field label={t('promotions.bundleItems')} required hint={t('promotions.bundleHint')} error={err('bundle_items')}>{() => (
              <div className="flex flex-col gap-1.5">
                {(v.bundle_items ?? []).map((b, i) => (
                  <div key={b.medicine_id} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 text-[13px]">{medLabel(b.medicine_id)}</span>
                    <Input aria-label={`${t('promotions.bundleQty')} · ${medLabel(b.medicine_id)}`} className="w-24" inputMode="numeric" value={b.qty_base} onChange={(e) => set({ bundle_items: (v.bundle_items ?? []).map((x, j) => (j === i ? { ...x, qty_base: Number(e.target.value.replace(/\D/g, '')) || 0 } : x)) })} />
                    <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => set({ bundle_items: (v.bundle_items ?? []).filter((_, j) => j !== i) })}>✕</Button>
                  </div>
                ))}
                <MedicinePicker value={null} clearOnPick onChange={(m) => { if (m && !(v.bundle_items ?? []).some((b) => b.medicine_id === m.id)) { setMeds((x) => [...x, { id: m.id, label: medName(m) }]); set({ bundle_items: [...(v.bundle_items ?? []), { medicine_id: m.id, qty_base: 1 }] }); } }} />
              </div>
            )}</Field>
          ) : <>
            <Field label={t('promotions.targets')} error={err('medicine_ids')}>{() => (
              <div className="flex flex-col gap-1.5">
                <div className="flex flex-wrap gap-1">{(v.medicine_ids ?? []).map((mid) => (
                  <span key={mid} className="inline-flex items-center gap-1 rounded-sm bg-primary-100 px-2 py-0.5 text-[13px] text-primary-700">{medLabel(mid)}
                    <button type="button" aria-label={t('common:action.remove')} onClick={() => set({ medicine_ids: (v.medicine_ids ?? []).filter((x) => x !== mid) })}>×</button></span>
                ))}</div>
                <MedicinePicker value={null} clearOnPick onChange={(m) => { if (m) { setMeds((x) => [...x, { id: m.id, label: medName(m) }]); set({ medicine_ids: [...new Set([...(v.medicine_ids ?? []), m.id])] }); } }} />
              </div>
            )}</Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('promotions.categories')} error={err('category_ids')}>{(id) => <MultiSelect id={id} value={v.category_ids ?? []} onChange={(x) => set({ category_ids: x })} options={(cats.data ?? []).map((c) => ({ value: c.id, label: km ? c.name_km || c.name_en : c.name_en }))} />}</Field>
              <Field label={t('promotions.brands')} error={err('brand_ids')}>{(id) => <MultiSelect id={id} value={v.brand_ids ?? []} onChange={(x) => set({ brand_ids: x })} options={(brands.data ?? []).map((c) => ({ value: c.id, label: km ? c.name_km || c.name_en : c.name_en }))} />}</Field>
            </div>
          </>}
          <div className="grid grid-cols-2 gap-3">
            <Field label={`${t('promotions.window')} · ${t('common:label.from')}`} hint={t('promotions.timeZone')} error={err('starts_at')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} type="datetime-local" value={phnomPenhInput(v.starts_at)} onChange={(e) => set({ starts_at: fromPhnomPenhInput(e.target.value) })} />}</Field>
            <Field label={t('common:label.to')} error={err('ends_at')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} type="datetime-local" value={phnomPenhInput(v.ends_at)} onChange={(e) => set({ ends_at: fromPhnomPenhInput(e.target.value) })} />}</Field>
          </div>
          <Field label={t('promotions.days')} hint={t('promotions.daysHint')} error={err('days_of_week')}>{() => (
            <div className="flex flex-wrap gap-1.5">{dayNames.map((d, i) => {
              const on = (v.days_of_week ?? []).includes(i);
              return <button key={d} type="button" aria-pressed={on} onClick={() => set({ days_of_week: on ? (v.days_of_week ?? []).filter((x) => x !== i) : [...(v.days_of_week ?? []), i] })}
                className={on ? 'rounded-md border border-primary-600 bg-primary-600 px-2.5 py-1 text-[13px] text-white' : 'rounded-md border border-neutral-300 px-2.5 py-1 text-[13px]'}>{d}</button>;
            })}</div>
          )}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={user.isOwner ? t('promotions.branches') : t('promotions.branchesOwn')} required={!user.isOwner} error={err('branch_ids')}>{(id) => <MultiSelect id={id} value={v.branch_ids ?? []} onChange={(x) => set({ branch_ids: x })} options={branches.map((b) => ({ value: b.id, label: `${b.code} ${branchName(b, i18n.language)}` }))} />}</Field>
            <Field label={v.type === 'group_price' ? t('promotions.groupsRequired') : t('promotions.groups')} required={v.type === 'group_price'} hint={v.type === 'group_price' && groups.data?.length === 0 ? t('promotions.noGroups') : undefined} error={err('customer_group_ids')}>{(id) => <MultiSelect id={id} value={v.customer_group_ids ?? []} onChange={(x) => set({ customer_group_ids: x })} options={(groups.data ?? []).map((g) => ({ value: g.id, label: km ? g.name_km || g.name_en : g.name_en }))} />}</Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('promotions.maxTotal')} error={err('max_uses_total')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} inputMode="numeric" value={v.max_uses_total ?? ''} onChange={(e) => set({ max_uses_total: num(e.target.value) })} />}</Field>
            <Field label={t('promotions.maxCustomer')} error={err('max_uses_per_customer')}>{(id, d, inv) => <Input id={id} aria-describedby={d} invalid={inv} inputMode="numeric" value={v.max_uses_per_customer ?? ''} onChange={(e) => set({ max_uses_per_customer: num(e.target.value) })} />}</Field>
          </div>
          <Field label={t('promotions.combination')}>{() => (
            <div className="flex gap-1.5"><Chip on={!!v.stackable} onClick={() => set({ stackable: true })}>{t('promotions.stackable')}</Chip><Chip on={!v.stackable} onClick={() => set({ stackable: false })}>{t('promotions.exclusive')}</Chip></div>
          )}</Field>
          <Checkbox label={t('promotions.includeRx')} checked={!!v.include_rx} onChange={(e) => set({ include_rx: e.target.checked })} />
          {!Object.keys(apiErrors).length && <ApiErrorAlert error={save.error} />}
        </div>
        <Card title={t('promotions.preview')}>
          <div className="flex flex-col gap-3">
            <Field label={t('common:label.branch')}>{(id) => <Select id={id} value={sampleBranch} onChange={(e) => setSampleBranch(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.code} {branchName(b, i18n.language)}</option>)}</Select>}</Field>
            <Field label={t('promotions.sampleCustomer')} hint={t('promotions.sampleCustomerHint')}>{(id) => <CustomerPicker id={id} value={sampleCustomer} onChange={setSampleCustomer} />}</Field>
            <span className="text-[12px] font-medium text-neutral-500">{t('promotions.sampleCart')}</span>
            <LinesEditor lines={sample} onChange={setSample} compact />
            <Button variant="primary" disabled={!sample.length || !sampleBranch} loading={preview.isPending} onClick={() => preview.mutate()}>{t('common:action.preview')}</Button>
            {!sample.length && <span className="text-[12px] text-neutral-500">{t('promotions.sampleHint')}</span>}
            {!Object.keys(apiErrors).length && <ApiErrorAlert error={preview.error} />}
            {preview.data && (
              <div className="flex flex-col gap-2 text-[13px]" data-testid="promo-preview">
                {(preview.data.lines as { line_no: number; name?: string; net?: string; promo_discount?: string; promotions?: { name_en?: string; name_km?: string }[] }[]).map((l) => (
                  <div key={l.line_no} className="flex justify-between gap-2"><span>{l.name}{l.promotions?.length ? ` · ${l.promotions.map((p) => (km && p.name_km) || p.name_en).join(', ')}` : ''}</span>
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
