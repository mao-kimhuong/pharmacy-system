// 14d Commission rules: list (active first), new rule (% of net or USD per base unit; scope everything / medicine /
// category / brand; optional staff override and branch; dates), deactivate with confirmation. Rules are never edited.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { SalesS } from '@/api/types';
import { useUser } from '@/app/auth';
import { branchName, useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, BranchTag, Button, ConfirmDialog, DataTable, Dialog, Field, Input, PageHeader, Select, StatusPill, Usd } from '@/design';
import { date, todayIso } from '@/lib/format';
import { MedicinePicker, type Medicine as PickedMedicine } from '../shared/MedicinePicker';
import { useMedicineNames, useStaffNames } from '../shared/hooks';

type Rule = SalesS['RuleOut'];
type Scope = Rule['scope'];
type Medicine = PickedMedicine;
interface Form { name: string; kind: Rule['kind']; value: string; scope: Scope; target_id: string; medicine: Medicine | null; staff_id: string; branch_id: string; starts_on: string; ends_on: string }

function useLookups() {
  const cats = useQuery({ queryKey: ['catalog', 'categories'], staleTime: 5 * 60_000, queryFn: () => call(api.catalog.GET('/api/catalog/v1/categories')) });
  const brands = useQuery({ queryKey: ['catalog', 'brands'], staleTime: 5 * 60_000, queryFn: () => call(api.catalog.GET('/api/catalog/v1/brands')) });
  return { cats: cats.data ?? [], brands: brands.data ?? [] };
}

function RuleForm({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation(['settings', 'common']);
  const user = useUser();
  const qc = useQueryClient();
  const { branches, oneBranch } = useBranch();
  const { cats, brands } = useLookups();
  const users = useQuery({ queryKey: ['auth', 'users', 'all'], enabled: user.has('settings.users'), staleTime: 5 * 60_000, queryFn: () => call(api.auth.GET('/api/auth/v1/users', { params: { query: { size: 200, is_active: true } } })) });
  const [v, setV] = useState<Form>({ name: '', kind: 'percent', value: '', scope: 'all', target_id: '', medicine: null, staff_id: '', branch_id: user.isOwner ? '' : oneBranch?.id ?? '', starts_on: todayIso(), ends_on: '' });
  const target = v.scope === 'medicine' ? v.medicine?.id : v.target_id;
  const m = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/commission/rules', { body: {
      name: v.name, kind: v.kind, value: v.value, scope: v.scope, target_id: v.scope === 'all' ? null : target ?? null,
      staff_id: v.staff_id || null, branch_id: v.branch_id || null, starts_on: v.starts_on, ends_on: v.ends_on || null,
    } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['sales', 'commission', 'rules'] }); onClose(); },
  });
  const ok = v.name && Number(v.value) > 0 && v.starts_on && (v.scope === 'all' || target) && (user.isOwner || v.branch_id);
  const nm = (x: { name_en: string; name_km: string }) => (i18n.language === 'km' && x.name_km ? x.name_km : x.name_en);
  return (
    <Dialog open onClose={onClose} title={t('commission.new')} width={600}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!ok} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button></>}>
      <div className="grid grid-cols-1 gap-3 tablet:grid-cols-2">
        <Field label={t('common:label.name')} required className="tablet:col-span-2">{(id) => <Input id={id} autoFocus value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <Field label={t('commission.kind')} required>{(id) => (
          <Select id={id} value={v.kind} onChange={(e) => setV({ ...v, kind: e.target.value as Rule['kind'] })}>
            <option value="percent">{t('commission.percent')}</option><option value="per_unit">{t('commission.per_unit')}</option>
          </Select>
        )}</Field>
        <Field label={t('commission.value')} required>{(id) => <Input id={id} inputMode="decimal" prefix={v.kind === 'per_unit' ? '$' : undefined} suffix={v.kind === 'percent' ? '%' : undefined} value={v.value} onChange={(e) => setV({ ...v, value: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
        <Field label={t('commission.scope')} required>{(id) => (
          <Select id={id} value={v.scope} onChange={(e) => setV({ ...v, scope: e.target.value as Scope, target_id: '', medicine: null })}>
            {(['all', 'medicine', 'category', 'brand'] as const).map((s) => <option key={s} value={s}>{t(`commission.scopes.${s}`)}</option>)}
          </Select>
        )}</Field>
        {v.scope === 'medicine' && <Field label={t('commission.scopes.medicine')} required>{(id) => <MedicinePicker id={id} value={v.medicine} onChange={(x) => setV({ ...v, medicine: x })} />}</Field>}
        {v.scope === 'category' && <Field label={t('commission.scopes.category')} required>{(id) => <Select id={id} value={v.target_id} onChange={(e) => setV({ ...v, target_id: e.target.value })}><option value="">—</option>{cats.filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{nm(c)}</option>)}</Select>}</Field>}
        {v.scope === 'brand' && <Field label={t('commission.scopes.brand')} required>{(id) => <Select id={id} value={v.target_id} onChange={(e) => setV({ ...v, target_id: e.target.value })}><option value="">—</option>{brands.filter((c) => c.is_active).map((c) => <option key={c.id} value={c.id}>{nm(c)}</option>)}</Select>}</Field>}
        {v.scope === 'all' && <div />}
        {users.data && <Field label={t('commission.staff')}>{(id) => <Select id={id} value={v.staff_id} onChange={(e) => setV({ ...v, staff_id: e.target.value })}><option value="">—</option>{users.data.items.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select>}</Field>}
        <Field label={t('commission.branch')} required={!user.isOwner}>{(id) => (
          <Select id={id} value={v.branch_id} onChange={(e) => setV({ ...v, branch_id: e.target.value })}>
            {user.isOwner ? <option value="">{t('common:label.allBranches')}</option> : <option value="">—</option>}
            {branches.map((b) => <option key={b.id} value={b.id}>{b.code} · {branchName(b, i18n.language)}</option>)}
          </Select>
        )}</Field>
        <Field label={t('commission.starts')} required>{(id) => <Input id={id} type="date" value={v.starts_on} onChange={(e) => setV({ ...v, starts_on: e.target.value })} />}</Field>
        <Field label={t('commission.ends')}>{(id) => <Input id={id} type="date" min={v.starts_on} value={v.ends_on} onChange={(e) => setV({ ...v, ends_on: e.target.value })} />}</Field>
        <ApiErrorAlert error={m.error} className="tablet:col-span-2" />
      </div>
    </Dialog>
  );
}

export default function CommissionRulesPage() {
  const { t, i18n } = useTranslation(['settings', 'common', 'nav', 'sales']);
  const qc = useQueryClient();
  const { byId } = useBranch();
  const staff = useStaffNames();
  const { cats, brands } = useLookups();
  const [neu, setNeu] = useState(false);
  const [deact, setDeact] = useState<Rule | null>(null);
  const q = useQuery({ queryKey: ['sales', 'commission', 'rules'], queryFn: () => call(api.sales.GET('/api/sales/v1/commission/rules')) });
  const rows = [...(q.data ?? [])].sort((a, b) => Number(b.is_active) - Number(a.is_active));
  const med = useMedicineNames(rows.filter((r) => r.scope === 'medicine' && r.target_id).map((r) => r.target_id!));
  const nm = (x?: { name_en: string; name_km: string }) => (x ? (i18n.language === 'km' && x.name_km ? x.name_km : x.name_en) : '…');
  const target = (r: Rule) => {
    if (r.scope === 'all' || !r.target_id) return t('commission.scopes.all');
    if (r.scope === 'medicine') return med(r.target_id);
    return nm((r.scope === 'category' ? cats : brands).find((x) => x.id === r.target_id));
  };
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('commission.title')} actions={<Button variant="primary" onClick={() => setNeu(true)}>+ {t('commission.new')}</Button>} />
      <Alert tone="info">{t('commission.noEdit')}</Alert>
      <DataTable rows={rows} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id}
        columns={[
          { key: 'n', header: t('common:label.name'), cell: (r) => <span className="font-medium">{r.name}</span> },
          { key: 'v', header: t('commission.value'), align: 'right', cell: (r) => (r.kind === 'percent' ? `${r.value}%` : <><Usd value={r.value} /> / {t('common:label.unit')}</>) },
          { key: 's', header: t('commission.scope'), cell: (r) => <span>{t(`commission.scopes.${r.scope}`)}{r.scope !== 'all' && <span className="block text-[12px] text-neutral-500">{target(r)}</span>}</span> },
          { key: 'st', header: t('commission.staff'), cell: (r) => (r.staff_id ? staff(r.staff_id) : '—') },
          { key: 'b', header: t('common:label.branch'), cell: (r) => (r.branch_id ? <BranchTag code={byId(r.branch_id)?.code ?? '…'} /> : t('common:label.allBranches')) },
          { key: 'd', header: t('common:label.date'), cell: (r) => <span className="whitespace-nowrap tabular-nums">{date(r.starts_on)} – {r.ends_on ? date(r.ends_on) : '…'}</span> },
          { key: 'a', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
          { key: 'x', header: '', align: 'right', cell: (r) => r.is_active && <Button size="sm" onClick={() => setDeact(r)}>{t('common:action.deactivate')}</Button> },
        ]} />
      {neu && <RuleForm onClose={() => setNeu(false)} />}
      <ConfirmDialog open={!!deact} onClose={() => setDeact(null)} variant="danger" title={t('common:confirm.deactivateTitle', { name: deact?.name })} body={t('commission.noEdit')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async () => {
          await call(api.sales.POST('/api/sales/v1/commission/rules/{rule_id}/deactivate', { params: { path: { rule_id: deact!.id } } }));
          await qc.invalidateQueries({ queryKey: ['sales', 'commission', 'rules'] });
        }} />
    </div>
  );
}
