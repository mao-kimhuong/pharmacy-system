// 14e Branches: list (with inactive), new / edit (code fixed once created), deactivate with a reason / activate;
// branch settings per branch (/settings/branches/:id): receipts, Rx, counts, shrinkage, re-order, discounts, KHQR.
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { BranchS } from '@/api/types';
import { useUser } from '@/app/auth';
import { QueryState } from '@/app/RouteError';
import { ApiErrorAlert, Button, Card, Checkbox, DataTable, Dialog, Field, Input, PageHeader, ReasonDialog, Select, SkeletonRows, StatusPill, TextArea, useToast } from '@/design';

type Branch = BranchS['BranchOut'];
type Settings = BranchS['BranchSettingsOut'];
type Update = BranchS['BranchSettingsUpdate'];
const ROLES = ['cashier', 'pharmacist', 'branch_manager'] as const;
const KEY = ['branch', 'branches', 'admin'];

function BranchForm({ initial, onClose }: { initial: Branch | null; onClose: () => void }) {
  const { t } = useTranslation(['settings', 'common']);
  const qc = useQueryClient();
  const [v, setV] = useState({ code: initial?.code ?? '', name_en: initial?.name_en ?? '', name_km: initial?.name_km ?? '', phone: initial?.phone ?? '', address: initial?.address ?? '', license_no: initial?.license_no ?? '' });
  const m = useMutation({
    mutationFn: () => {
      const { code, ...rest } = v;
      return initial
        ? call(api.branch.PATCH('/api/branch/v1/branches/{branch_id}', { params: { path: { branch_id: initial.id } }, body: rest }))
        : call(api.branch.POST('/api/branch/v1/branches', { body: { code, ...rest } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['branch'] }); onClose(); },
  });
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  return (
    <Dialog open onClose={onClose} title={initial ? t('common:action.edit') : t('branches.new')} width={560}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!v.code || !v.name_en || !v.name_km} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button></>}>
      <div className="grid grid-cols-1 gap-3 tablet:grid-cols-2">
        <Field label={t('branches.code')} required>{(id) => <Input id={id} autoFocus={!initial} disabled={!!initial} value={v.code} onChange={(e) => setV({ ...v, code: e.target.value.toUpperCase() })} />}</Field>
        <Field label={t('branches.licence')}>{(id) => <Input id={id} value={v.license_no} onChange={set('license_no')} />}</Field>
        <Field label={t('common:label.nameEn')} required>{(id) => <Input id={id} value={v.name_en} onChange={set('name_en')} />}</Field>
        <Field label={t('common:label.nameKm')} required>{(id) => <Input id={id} className="km" value={v.name_km} onChange={set('name_km')} />}</Field>
        <Field label={t('common:label.phone')}>{(id) => <Input id={id} type="tel" value={v.phone} onChange={set('phone')} />}</Field>
        <Field label={t('common:label.address')} className="tablet:col-span-2">{(id) => <TextArea id={id} rows={2} value={v.address} onChange={set('address')} />}</Field>
        <ApiErrorAlert error={m.error} className="tablet:col-span-2" />
      </div>
    </Dialog>
  );
}

export default function BranchesPage() {
  const { t } = useTranslation(['settings', 'common', 'nav', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const manage = user.has('settings.branches');
  const [form, setForm] = useState<Branch | 'new' | null>(null);
  const [deact, setDeact] = useState<Branch | null>(null);
  const q = useQuery({ queryKey: KEY, queryFn: () => call(api.branch.GET('/api/branch/v1/branches', { params: { query: { include_inactive: manage } } })) });
  const refresh = () => qc.invalidateQueries({ queryKey: ['branch'] });
  const activate = useMutation({ mutationFn: (id: string) => call(api.branch.POST('/api/branch/v1/branches/{branch_id}/activate', { params: { path: { branch_id: id } } })), onSuccess: () => void refresh() });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('branches.title')} actions={manage && <Button variant="primary" onClick={() => setForm('new')}>+ {t('branches.new')}</Button>} />
      <ApiErrorAlert error={activate.error} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id}
        columns={[
          { key: 'c', header: t('branches.code'), cell: (r) => <span className="font-semibold">{r.code}</span> },
          { key: 'n', header: t('common:label.name'), cell: (r) => <span>{r.name_en}<span className="km block text-[12px] text-neutral-500">{r.name_km}</span></span> },
          { key: 'p', header: t('common:label.phone'), cell: (r) => r.phone || '—' },
          { key: 'l', header: t('branches.licence'), cell: (r) => r.license_no || '—' },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (r) => (
            <span className="flex justify-end gap-1">
              <Link to={`/settings/branches/${r.id}`} className="inline-flex min-h-8 items-center rounded-md border border-neutral-300 px-2.5 text-[13px] font-medium hover:bg-neutral-50">{t('branches.settings')}</Link>
              {manage && <Button size="sm" onClick={() => setForm(r)}>{t('common:action.edit')}</Button>}
              {manage && (r.is_active ? <Button size="sm" onClick={() => setDeact(r)}>{t('common:action.deactivate')}</Button> : <Button size="sm" onClick={() => activate.mutate(r.id)}>{t('common:action.activate')}</Button>)}
            </span>
          ) },
        ]} />
      {form && <BranchForm initial={form === 'new' ? null : form} onClose={() => setForm(null)} />}
      <ReasonDialog open={!!deact} onClose={() => setDeact(null)} title={t('common:confirm.deactivateTitle', { name: deact?.name_en })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => {
          await call(api.branch.POST('/api/branch/v1/branches/{branch_id}/deactivate', { params: { path: { branch_id: deact!.id } }, body: { reason } }));
          await refresh();
        }} />
    </div>
  );
}

interface Form {
  receipt_header: string; receipt_footer: string; receipt_lang: 'km' | 'en'; rx_valid_days: string; controlled_rx_valid_days: string;
  dispensing_label_size: NonNullable<Update['dispensing_label_size']>; expiry_alert_days: string; allow_opened_pack_returns: boolean; price_override_enabled: boolean;
  double_count_above_usd: string; owner_approval_above_usd: string; shrinkage_approval_usd: string; reorder_sales_days: string; reorder_safety_days: string;
  reorder_lead_days: string; near_expiry_transfer_days: string; order_deposit_on_cancel: NonNullable<Update['order_deposit_on_cancel']>;
  max_discount_pct: Record<string, string>; khqr_account: string; khqr_name: string; khqr_city: string;
  refill_reminder_days: string; hours: Record<Day, { open: boolean; from: string; to: string }>;
}

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
type Day = (typeof DAYS)[number];

const toForm = (s: Settings): Form => {
  const k = (s.khqr ?? {}) as { account_id?: string; merchant_name?: string; city?: string };
  return {
    receipt_header: s.receipt_header, receipt_footer: s.receipt_footer, receipt_lang: s.receipt_lang as 'km' | 'en', rx_valid_days: String(s.rx_valid_days),
    controlled_rx_valid_days: String(s.controlled_rx_valid_days), dispensing_label_size: s.dispensing_label_size as Form['dispensing_label_size'],
    expiry_alert_days: s.expiry_alert_days.join(', '), allow_opened_pack_returns: s.allow_opened_pack_returns, price_override_enabled: s.price_override_enabled,
    double_count_above_usd: s.double_count_above_usd, owner_approval_above_usd: s.owner_approval_above_usd, shrinkage_approval_usd: s.shrinkage_approval_usd,
    reorder_sales_days: String(s.reorder_sales_days), reorder_safety_days: String(s.reorder_safety_days), reorder_lead_days: String(s.reorder_lead_days),
    near_expiry_transfer_days: String(s.near_expiry_transfer_days), order_deposit_on_cancel: s.order_deposit_on_cancel as Form['order_deposit_on_cancel'],
    max_discount_pct: Object.fromEntries(ROLES.map((r) => [r, s.max_discount_pct[r] === undefined ? '' : String(s.max_discount_pct[r])])),
    khqr_account: k.account_id ?? '', khqr_name: k.merchant_name ?? '', khqr_city: k.city ?? '',
    refill_reminder_days: String(s.refill_reminder_days ?? 3),
    hours: Object.fromEntries(DAYS.map((d) => {
      const h = s.opening_hours?.[d];
      return [d, { open: !!h, from: h?.[0] ?? '07:00', to: h?.[1] ?? '21:00' }];
    })) as Form['hours'],
  };
};

const int = (s: string) => Number.parseInt(s, 10);

export function BranchSettingsPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['settings', 'common', 'nav', 'shell']);
  const qc = useQueryClient();
  const toast = useToast();
  const branch = useQuery({ queryKey: ['branch', 'branch', id], queryFn: () => call(api.branch.GET('/api/branch/v1/branches/{branch_id}', { params: { path: { branch_id: id } } })) });
  const q = useQuery({ queryKey: ['branch', 'settings', id], queryFn: () => call(api.branch.GET('/api/branch/v1/branches/{branch_id}/settings', { params: { path: { branch_id: id } } })) });
  const [v, setV] = useState<Form | null>(null);
  useEffect(() => { if (q.data) setV(toForm(q.data)); }, [q.data]);
  const save = useMutation({
    mutationFn: () => {
      const f = v!;
      const caps = Object.fromEntries(Object.entries(f.max_discount_pct).filter(([, x]) => x !== '').map(([r, x]) => [r, int(x)]));
      const body: Update = {
        receipt_header: f.receipt_header, receipt_footer: f.receipt_footer, receipt_lang: f.receipt_lang, rx_valid_days: int(f.rx_valid_days),
        controlled_rx_valid_days: int(f.controlled_rx_valid_days), dispensing_label_size: f.dispensing_label_size,
        expiry_alert_days: f.expiry_alert_days.split(/[,\s]+/).filter(Boolean).map(int),
        allow_opened_pack_returns: f.allow_opened_pack_returns, price_override_enabled: f.price_override_enabled,
        double_count_above_usd: f.double_count_above_usd, owner_approval_above_usd: f.owner_approval_above_usd, shrinkage_approval_usd: f.shrinkage_approval_usd,
        reorder_sales_days: int(f.reorder_sales_days), reorder_safety_days: int(f.reorder_safety_days), reorder_lead_days: int(f.reorder_lead_days),
        near_expiry_transfer_days: int(f.near_expiry_transfer_days), order_deposit_on_cancel: f.order_deposit_on_cancel, max_discount_pct: caps,
        khqr: f.khqr_account ? { account_id: f.khqr_account.trim(), merchant_name: f.khqr_name.trim(), city: f.khqr_city.trim() || undefined } : null,
        refill_reminder_days: int(f.refill_reminder_days),
        opening_hours: DAYS.some((d) => f.hours[d].open)
          ? Object.fromEntries(DAYS.filter((d) => f.hours[d].open).map((d) => [d, [f.hours[d].from, f.hours[d].to]])) : null,
      };
      return call(api.branch.PUT('/api/branch/v1/branches/{branch_id}/settings', { params: { path: { branch_id: id } }, body }));
    },
    onSuccess: (s) => { qc.setQueryData(['branch', 'settings', id], s); toast.success(t('branches.saved')); },
  });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  const set = <K extends keyof Form>(k: K) => (x: Form[K]) => setV((f) => (f ? { ...f, [k]: x } : f));
  const num = (k: keyof Form, label: string, prefix?: string) => (
    <Field label={label}>{(fid) => <Input id={fid} inputMode="decimal" prefix={prefix} value={v![k] as string} onChange={(e) => set(k)(e.target.value.replace(/[^\d.]/g, '') as never)} />}</Field>
  );
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={<Link to="/settings/branches" className="hover:underline">{t('branches.title')}</Link>} title={`${t('branches.settings')} · ${branch.data?.code ?? ''}`}
        actions={<Button variant="primary" disabled={!v} loading={save.isPending} onClick={() => save.mutate()}>{t('common:action.save')}</Button>} />
      {!v ? <SkeletonRows rows={8} /> : (
        <div className="grid grid-cols-1 gap-4 desktop:grid-cols-2">
          <Card title={t('branches.receiptHeader')}>
            <div className="flex flex-col gap-3">
              <Field label={t('branches.receiptHeader')}>{(fid) => <TextArea id={fid} rows={3} maxLength={500} value={v.receipt_header} onChange={(e) => set('receipt_header')(e.target.value)} />}</Field>
              <Field label={t('branches.receiptFooter')}>{(fid) => <TextArea id={fid} rows={2} maxLength={500} value={v.receipt_footer} onChange={(e) => set('receipt_footer')(e.target.value)} />}</Field>
              <Field label={t('branches.receiptLang')}>{(fid) => <Select id={fid} value={v.receipt_lang} onChange={(e) => set('receipt_lang')(e.target.value as 'km' | 'en')}><option value="km">ខ្មែរ</option><option value="en">English</option></Select>}</Field>
              <Checkbox label={t('branches.openedPacks')} checked={v.allow_opened_pack_returns} onChange={(e) => set('allow_opened_pack_returns')(e.target.checked)} />
              <Checkbox label={t('branches.priceOverride')} checked={v.price_override_enabled} onChange={(e) => set('price_override_enabled')(e.target.checked)} />
              <Field label={t('branches.deposit')}>{(fid) => (
                <Select id={fid} value={v.order_deposit_on_cancel} onChange={(e) => set('order_deposit_on_cancel')(e.target.value as Form['order_deposit_on_cancel'])}>
                  {(['keep_as_credit', 'refund', 'forfeit'] as const).map((o) => <option key={o} value={o}>{t(`branches.depositOpt.${o}`)}</option>)}
                </Select>
              )}</Field>
            </div>
          </Card>
          <Card title={t('nav:group.prescriptions')}>
            <div className="grid grid-cols-1 gap-3 tablet:grid-cols-2">
              {num('rx_valid_days', t('branches.rxDays'))}
              {num('controlled_rx_valid_days', t('branches.ctlRxDays'))}
              <Field label={t('branches.labelSize')}>{(fid) => (
                <Select id={fid} value={v.dispensing_label_size} onChange={(e) => set('dispensing_label_size')(e.target.value as Form['dispensing_label_size'])}>
                  {(['70x40', '50x30', '100x50', 'a4_sheet'] as const).map((o) => <option key={o} value={o}>{o === 'a4_sheet' ? 'A4' : `${o.replace('x', ' × ')} mm`}</option>)}
                </Select>
              )}</Field>
              <Field label={t('branches.expiryAlert')}>{(fid) => <Input id={fid} value={v.expiry_alert_days} onChange={(e) => set('expiry_alert_days')(e.target.value.replace(/[^\d,\s]/g, ''))} />}</Field>
              {num('refill_reminder_days', t('branches.refillDays'))}
            </div>
          </Card>
          <Card title={t('branches.hours')}>
            <div className="flex flex-col gap-2">
              <span className="text-[12px] text-neutral-500">{t('branches.hoursHint')}</span>
              {DAYS.map((d) => {
                const h = v.hours[d];
                const put = (p: Partial<typeof h>) => set('hours')({ ...v.hours, [d]: { ...h, ...p } });
                return (
                  <div key={d} className="grid grid-cols-[110px_1fr_1fr] items-center gap-2" data-day={d}>
                    <Checkbox label={t(`branches.day.${d}`)} checked={h.open} onChange={(e) => put({ open: e.target.checked })} />
                    <Input type="time" aria-label={`${t(`branches.day.${d}`)} ${t('branches.opens')}`} disabled={!h.open} value={h.from} onChange={(e) => put({ from: e.target.value })} />
                    <Input type="time" aria-label={`${t(`branches.day.${d}`)} ${t('branches.closes')}`} disabled={!h.open} value={h.to} onChange={(e) => put({ to: e.target.value })} />
                  </div>
                );
              })}
            </div>
          </Card>
          <Card title={t('nav:group.stock')}>
            <div className="grid grid-cols-1 gap-3 tablet:grid-cols-2">
              {num('double_count_above_usd', t('branches.doubleCount'), '$')}
              {num('owner_approval_above_usd', t('branches.ownerApproval'), '$')}
              {num('shrinkage_approval_usd', t('branches.shrinkApproval'), '$')}
              {num('near_expiry_transfer_days', t('branches.nearTransfer'))}
              {num('reorder_sales_days', t('branches.reorderSales'))}
              {num('reorder_lead_days', t('branches.reorderLead'))}
              {num('reorder_safety_days', t('branches.reorderSafety'))}
            </div>
          </Card>
          <Card title={t('branches.discountCaps')}>
            <div className="grid grid-cols-1 gap-3 tablet:grid-cols-3">
              {ROLES.map((r) => (
                <Field key={r} label={t(`shell:role.${r}`)}>{(fid) => <Input id={fid} inputMode="numeric" suffix="%" value={v.max_discount_pct[r] ?? ''} onChange={(e) => set('max_discount_pct')({ ...v.max_discount_pct, [r]: e.target.value.replace(/\D/g, '') })} />}</Field>
              ))}
            </div>
          </Card>
          <Card title={t('branches.khqr')} className="desktop:col-span-2">
            <div className="grid grid-cols-1 gap-3 tablet:grid-cols-3">
              <Field label={t('branches.khqrAccount')} hint={t('branches.khqrShared')}>{(fid, d) => <Input id={fid} aria-describedby={d} placeholder="pharmacy@aclb" value={v.khqr_account} onChange={(e) => set('khqr_account')(e.target.value.trim())} />}</Field>
              <Field label={t('branches.khqrName')} required={!!v.khqr_account}>{(fid) => <Input id={fid} maxLength={25} value={v.khqr_name} onChange={(e) => set('khqr_name')(e.target.value)} />}</Field>
              <Field label={t('branches.khqrCity')}>{(fid) => <Input id={fid} maxLength={15} placeholder="Phnom Penh" value={v.khqr_city} onChange={(e) => set('khqr_city')(e.target.value)} />}</Field>
            </div>
          </Card>
          <ApiErrorAlert error={save.error} className="desktop:col-span-2" />
        </div>
      )}
    </div>
  );
}
