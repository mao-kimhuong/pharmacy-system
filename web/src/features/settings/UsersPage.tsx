// 14a Users: search, role / branch / status filters, create, edit role + branches + pharmacist, deactivate with a
// reason / activate, reset password, reset 2FA, clear PIN. Owner sees every branch; the API refuses the rest.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { AuthS } from '@/api/types';
import { branchName, useBranchesQuery } from '@/app/branch';
import { useUser } from '@/app/auth';
import { ApiErrorAlert, BranchTag, Button, Checkbox, ConfirmDialog, DataTable, Dialog, Field, Input, MenuItem, MultiSelect, PageHeader, PinDialog, Popover, ReasonDialog, Select, StatusPill, Toolbar, useDebounced, useToast } from '@/design';
import { usePaging } from '../shared/hooks';

type User = AuthS['UserOut'];
interface Form { name: string; phone: string; password: string; role: string; branch_ids: string[]; is_pharmacist: boolean; locale: 'km' | 'en' }

export function useRoles() {
  return useQuery({ queryKey: ['auth', 'roles'], staleTime: 60_000, queryFn: () => call(api.auth.GET('/api/auth/v1/roles')) });
}

function UserForm({ initial, onClose }: { initial: User | null; onClose: () => void }) {
  const { t, i18n } = useTranslation(['settings', 'common']);
  const qc = useQueryClient();
  const roles = useRoles();
  const branches = useBranchesQuery();
  const [v, setV] = useState<Form>({
    name: initial?.name ?? '', phone: initial?.phone ?? '', password: '', role: initial?.role ?? '', branch_ids: initial?.branch_ids ?? [],
    is_pharmacist: initial?.is_pharmacist ?? false, locale: (initial?.locale as 'km' | 'en') ?? 'km',
  });
  const owner = v.role === 'owner';
  const m = useMutation({
    mutationFn: () => {
      const common = { name: v.name, phone: v.phone, role: v.role, branch_ids: owner ? [] : v.branch_ids, is_pharmacist: v.is_pharmacist, locale: v.locale };
      return initial
        ? call(api.auth.PATCH('/api/auth/v1/users/{user_id}', { params: { path: { user_id: initial.id } }, body: common }))
        : call(api.auth.POST('/api/auth/v1/users', { body: { ...common, password: v.password } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['auth', 'users'] }); onClose(); },
  });
  const ok = v.name && v.phone && v.role && (initial || v.password) && (owner || v.branch_ids.length > 0);
  return (
    <Dialog open onClose={onClose} title={initial ? t('users.edit') : t('users.new')} width={560}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!ok} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button></>}>
      <div className="grid grid-cols-1 gap-3 tablet:grid-cols-2">
        <Field label={t('common:label.name')} required>{(id) => <Input id={id} autoFocus value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
        <Field label={t('common:label.phone')} required>{(id) => <Input id={id} type="tel" value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />}</Field>
        {!initial && <Field label={t('users.password')} required>{(id) => <Input id={id} type="password" autoComplete="new-password" value={v.password} onChange={(e) => setV({ ...v, password: e.target.value })} />}</Field>}
        <Field label={t('common:label.role')} required>{(id) => (
          <Select id={id} value={v.role} onChange={(e) => setV({ ...v, role: e.target.value })}>
            <option value="">—</option>
            {roles.data?.filter((r) => r.is_active || r.key === v.role).map((r) => <option key={r.key} value={r.key}>{r.name}</option>)}
          </Select>
        )}</Field>
        <Field label={t('common:label.branches')} required={!owner} className="tablet:col-span-2" hint={owner ? t('users.allBranchesOwner') : undefined}>{(id) => (
          <MultiSelect id={id} value={owner ? [] : v.branch_ids} onChange={(ids) => setV({ ...v, branch_ids: ids })}
            options={(branches.data ?? []).filter((b) => b.is_active || v.branch_ids.includes(b.id)).map((b) => ({ value: b.id, label: `${b.code} · ${branchName(b, i18n.language)}` }))} />
        )}</Field>
        <Field label={t('users.language')}>{(id) => <Select id={id} value={v.locale} onChange={(e) => setV({ ...v, locale: e.target.value as 'km' | 'en' })}><option value="km">ខ្មែរ</option><option value="en">English</option></Select>}</Field>
        <div className="flex items-end pb-2"><Checkbox label={t('users.pharmacist')} checked={v.is_pharmacist} onChange={(e) => setV({ ...v, is_pharmacist: e.target.checked })} /></div>
        <ApiErrorAlert error={m.error} className="tablet:col-span-2" />
      </div>
    </Dialog>
  );
}

function ResetPassword({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useTranslation(['settings', 'common']);
  const toast = useToast();
  const [pw, setPw] = useState('');
  const m = useMutation({
    mutationFn: () => call(api.auth.POST('/api/auth/v1/users/{user_id}/reset-password', { params: { path: { user_id: user.id } }, body: { new_password: pw } })),
    onSuccess: () => { toast.success(t('users.done')); onClose(); },
  });
  return (
    <Dialog open onClose={onClose} title={`${t('users.resetPassword')} · ${user.name}`} width={420}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!pw} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button></>}>
      <Field label={t('users.newPassword')} required>{(id) => <Input id={id} type="password" autoComplete="new-password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} />}</Field>
      <ApiErrorAlert error={m.error} className="mt-3" />
    </Dialog>
  );
}

export default function UsersPage() {
  const { t, i18n } = useTranslation(['settings', 'common', 'nav', 'sales']);
  const me = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const paging = usePaging();
  const roles = useRoles();
  const branches = useBranchesQuery();
  const [q, setQ] = useState('');
  const [role, setRole] = useState('');
  const [branch, setBranch] = useState('');
  const [status, setStatus] = useState<'active' | 'inactive' | ''>('active');
  const [form, setForm] = useState<User | 'new' | null>(null);
  const [deact, setDeact] = useState<User | null>(null);
  const [pw, setPw] = useState<User | null>(null);
  const [confirm, setConfirm] = useState<User | null>(null);
  const [reset, setReset] = useState<User | null>(null);
  const [resetError, setResetError] = useState<unknown>(null);
  const dq = useDebounced(q.trim());
  const query = { q: dq || undefined, role: role || undefined, branch_id: branch || undefined, is_active: status === '' ? undefined : status === 'active', page: paging.page, size: paging.size };
  const list = useQuery({ queryKey: ['auth', 'users', query], queryFn: () => call(api.auth.GET('/api/auth/v1/users', { params: { query } })) });
  const refresh = () => qc.invalidateQueries({ queryKey: ['auth', 'users'] });
  const activate = useMutation({
    mutationFn: (id: string) => call(api.auth.POST('/api/auth/v1/users/{user_id}/activate', { params: { path: { user_id: id } } })),
    onSuccess: () => void refresh(),
  });
  const roleName = (k: string) => roles.data?.find((r) => r.key === k)?.name ?? k;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('users.title')} actions={<Button variant="primary" onClick={() => setForm('new')}>+ {t('users.new')}</Button>} />
      <ApiErrorAlert error={resetError} />
      <Toolbar>
        <Input aria-label={t('common:action.search')} placeholder={t('common:action.search')} className="w-60" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />
        <Select aria-label={t('common:label.role')} className="w-44" value={role} onChange={(e) => { setRole(e.target.value); paging.reset(); }}>
          <option value="">{t('common:label.role')}: —</option>
          {roles.data?.map((r) => <option key={r.key} value={r.key}>{r.name}</option>)}
        </Select>
        <Select aria-label={t('common:label.branch')} className="w-44" value={branch} onChange={(e) => { setBranch(e.target.value); paging.reset(); }}>
          <option value="">{t('common:label.allBranches')}</option>
          {branches.data?.map((b) => <option key={b.id} value={b.id}>{b.code} · {branchName(b, i18n.language)}</option>)}
        </Select>
        <Select aria-label={t('common:label.status')} className="w-36" value={status} onChange={(e) => { setStatus(e.target.value as typeof status); paging.reset(); }}>
          <option value="active">{t('sales:status.active')}</option>
          <option value="inactive">{t('sales:status.inactive')}</option>
          <option value="">{t('common:label.status')}: —</option>
        </Select>
      </Toolbar>
      <ApiErrorAlert error={activate.error} />
      <DataTable rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(r) => r.id}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'n', header: t('common:label.name'), cell: (r) => <span className="font-medium">{r.name}{r.is_pharmacist && <span className="ml-2 text-[12px] text-primary-700">℞</span>}</span> },
          { key: 'p', header: t('common:label.phone'), cell: (r) => <span className="tabular-nums">{r.phone}</span> },
          { key: 'r', header: t('common:label.role'), cell: (r) => roleName(r.role) },
          { key: 'b', header: t('common:label.branches'), cell: (r) => (r.role === 'owner' ? t('common:label.allBranches') : <span className="flex flex-wrap gap-1">{r.branch_ids.map((id) => <BranchTag key={id} code={branches.data?.find((b) => b.id === id)?.code ?? '…'} />)}</span>) },
          { key: 'f', header: t('users.twofa'), cell: (r) => (r.totp_enabled ? <StatusPill tone="success">✓</StatusPill> : '—') },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (r) => (
            <span className="flex justify-end gap-1">
              <Button size="sm" onClick={() => setForm(r)}>{t('common:action.edit')}</Button>
              <Popover align="right" width={220} label={t('common:action.more')}
                trigger={({ toggle, props }) => <Button size="sm" aria-label={`${t('common:action.more')} · ${r.name}`} onClick={toggle} {...props}>⋯</Button>}>
                {(close) => <>
                  <MenuItem onClick={() => { close(); setPw(r); }}>{t('users.resetPassword')}</MenuItem>
                  {me.isOwner && r.id !== me.id && r.totp_enabled && <MenuItem onClick={() => { close(); setReset(r); }}>{t('users.reset2fa')}</MenuItem>}
                  <MenuItem onClick={() => { close(); setConfirm(r); }}>{t('users.clearPin')}</MenuItem>
                  {r.id !== me.id && (r.is_active
                    ? <MenuItem danger onClick={() => { close(); setDeact(r); }}>{t('common:action.deactivate')}</MenuItem>
                    : <MenuItem onClick={() => { close(); activate.mutate(r.id); }}>{t('common:action.activate')}</MenuItem>)}
                </>}
              </Popover>
            </span>
          ) },
        ]} />
      {form && <UserForm initial={form === 'new' ? null : form} onClose={() => setForm(null)} />}
      {pw && <ResetPassword user={pw} onClose={() => setPw(null)} />}
      <ConfirmDialog open={!!confirm} onClose={() => setConfirm(null)}
        title={`${t('users.clearPin')} · ${confirm?.name ?? ''}`} body={t('users.clearPinBody')} confirmLabel={t('common:action.confirm')}
        onConfirm={async () => {
          await call(api.auth.DELETE('/api/auth/v1/users/{user_id}/pin', { params: { path: { user_id: confirm!.id } } }));
          toast.success(t('users.done'));
          await refresh();
        }} />
      <PinDialog open={!!reset} action="auth.mfa_reset" title={`${t('users.reset2fa')} · ${reset?.name ?? ''}`} context={t('users.reset2faBody')} onClose={() => setReset(null)}
        onToken={(pin) => {
          const user = reset!;
          setReset(null);
          setResetError(null);
          void call(api.auth.POST('/api/auth/v1/users/{user_id}/2fa/reset', { params: { path: { user_id: user.id } }, body: { pin_token: pin.pin_token } }))
            .then(async () => { toast.success(t('users.done')); await refresh(); })
            .catch(setResetError);
        }} />
      <ReasonDialog open={!!deact} onClose={() => setDeact(null)} title={t('common:confirm.deactivateTitle', { name: deact?.name })} body={t('common:confirm.deactivateBody')} confirmLabel={t('common:action.deactivate')}
        onConfirm={async (reason) => {
          await call(api.auth.POST('/api/auth/v1/users/{user_id}/deactivate', { params: { path: { user_id: deact!.id } }, body: { reason } }));
          await refresh();
        }} />
    </div>
  );
}
