// 14b Roles: list with active user counts, permission checklist per role grouped like the API's catalogue (labels
// come from the API), new role, deactivate / activate. The owner role (all permissions) is locked.
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { Alert, ApiErrorAlert, Button, Card, Checkbox, ConfirmDialog, Dialog, EmptyState, Field, Input, PageHeader, SkeletonRows, StatusPill, cx, useToast } from '@/design';
import { QueryState } from '@/app/RouteError';
import { useRoles } from './UsersPage';

export default function RolesPage() {
  const { t } = useTranslation(['settings', 'common', 'nav', 'sales']);
  const qc = useQueryClient();
  const toast = useToast();
  const roles = useRoles();
  const perms = useQuery({ queryKey: ['auth', 'permissions'], staleTime: 5 * 60_000, queryFn: () => call(api.auth.GET('/api/auth/v1/permissions')) });
  const [sel, setSel] = useState<string>('');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [neu, setNeu] = useState<{ key: string; name: string; description: string } | null>(null);
  const [toggle, setToggle] = useState<boolean>(false);
  const role = roles.data?.find((r) => r.key === sel) ?? roles.data?.[0];
  useEffect(() => { if (role) setChecked(new Set(role.permissions)); }, [role]);
  const groups = useMemo(() => {
    const m = new Map<string, { key: string; label: string }[]>();
    for (const p of perms.data ?? []) m.set(p.group, [...(m.get(p.group) ?? []), p]);
    return [...m.entries()];
  }, [perms.data]);
  const refresh = () => qc.invalidateQueries({ queryKey: ['auth', 'roles'] });
  const save = useMutation({
    mutationFn: () => call(api.auth.PATCH('/api/auth/v1/roles/{key}', { params: { path: { key: role!.key } }, body: { permissions: [...checked].sort() } })),
    onSuccess: () => { toast.success(t('roles.saved')); void refresh(); },
  });
  const create = useMutation({
    mutationFn: () => call(api.auth.POST('/api/auth/v1/roles', { body: { key: neu!.key, name: neu!.name, description: neu!.description, permissions: [] } })),
    onSuccess: (r) => { setNeu(null); setSel(r.key); void refresh(); },
  });
  const locked = !role || role.all_permissions || !role.is_active;
  const dirty = role && !role.all_permissions && (checked.size !== role.permissions.length || role.permissions.some((p) => !checked.has(p)));
  const flip = (k: string, on: boolean) => setChecked((s) => { const n = new Set(s); if (on) n.add(k); else n.delete(k); return n; });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('roles.title')} actions={<Button variant="primary" onClick={() => setNeu({ key: '', name: '', description: '' })}>+ {t('roles.new')}</Button>} />
      {roles.isLoading ? <SkeletonRows /> : roles.error ? <QueryState error={roles.error} onRetry={() => void roles.refetch()} /> : (
        <div className="grid grid-cols-1 gap-4 desktop:grid-cols-[280px_1fr]">
          <Card padded={false} className="self-start">
            <ul className="flex flex-col p-1.5" aria-label={t('roles.title')}>
              {(roles.data ?? []).map((r) => (
                <li key={r.key}>
                  <button type="button" aria-current={r.key === role?.key ? 'true' : undefined} onClick={() => setSel(r.key)}
                    className={cx('flex min-h-11 w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-[14px]', r.key === role?.key ? 'bg-primary-50 font-semibold text-primary-800' : 'hover:bg-neutral-50')}>
                    <span>{r.name}<span className="block text-[12px] font-normal text-neutral-500">{t('roles.users', { count: r.active_users ?? 0 })}</span></span>
                    {!r.is_active && <StatusPill>{t('sales:status.inactive')}</StatusPill>}
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          {role && (
            <Card title={role.name} actions={!role.is_system && !role.all_permissions && (
              <Button size="sm" onClick={() => setToggle(true)}>{role.is_active ? t('common:action.deactivate') : t('common:action.activate')}</Button>
            )}>
              {role.description && <p className="mb-3 text-[13px] text-neutral-600">{role.description}</p>}
              {role.all_permissions ? <Alert tone="info">{t('roles.ownerLocked')}</Alert> : <Alert tone="info" className="mb-3">{t('roles.costHint')}</Alert>}
              {!role.all_permissions && (perms.isLoading ? <SkeletonRows rows={6} /> : groups.length === 0 ? <EmptyState title="—" /> : (
                <div className="flex flex-col gap-4">
                  {groups.map(([g, ps]) => (
                    <fieldset key={g} className="rounded-lg border border-neutral-200 p-3">
                      <legend className="px-1 text-[12px] font-semibold uppercase tracking-wide text-neutral-500">{g}</legend>
                      <div className="grid grid-cols-1 gap-x-4 gap-y-2 tablet:grid-cols-2">
                        {ps.map((p) => <Checkbox key={p.key} label={<span>{p.label} <span className="text-[11px] text-neutral-500">{p.key}</span></span>} disabled={locked} checked={checked.has(p.key)} onChange={(e) => flip(p.key, e.target.checked)} />)}
                      </div>
                    </fieldset>
                  ))}
                  <ApiErrorAlert error={save.error} />
                  <div className="flex justify-end gap-2">
                    <Button disabled={!dirty} onClick={() => setChecked(new Set(role.permissions))}>{t('common:action.reset')}</Button>
                    <Button variant="primary" disabled={!dirty || locked} loading={save.isPending} onClick={() => save.mutate()}>{t('roles.saveMatrix')}</Button>
                  </div>
                </div>
              ))}
            </Card>
          )}
        </div>
      )}
      <Dialog open={!!neu} onClose={() => setNeu(null)} title={t('roles.new')} width={460}
        footer={<><Button onClick={() => setNeu(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!neu?.key || !neu?.name} loading={create.isPending} onClick={() => create.mutate()}>{t('common:action.save')}</Button></>}>
        {neu && <div className="flex flex-col gap-3">
          <Field label={t('common:label.name')} required>{(id) => <Input id={id} autoFocus value={neu.name} onChange={(e) => setNeu({ ...neu, name: e.target.value })} />}</Field>
          <Field label={t('roles.key')} required>{(id) => <Input id={id} value={neu.key} onChange={(e) => setNeu({ ...neu, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} />}</Field>
          <Field label={t('roles.description')}>{(id) => <Input id={id} value={neu.description} onChange={(e) => setNeu({ ...neu, description: e.target.value })} />}</Field>
          <ApiErrorAlert error={create.error} />
        </div>}
      </Dialog>
      <ConfirmDialog open={toggle} onClose={() => setToggle(false)} variant={role?.is_active ? 'danger' : 'primary'}
        title={role?.is_active ? t('common:confirm.deactivateTitle', { name: role?.name }) : `${t('common:action.activate')} · ${role?.name ?? ''}`}
        body={role?.is_active ? t('common:confirm.deactivateBody') : undefined}
        confirmLabel={role?.is_active ? t('common:action.deactivate') : t('common:action.activate')}
        onConfirm={async () => {
          const path = { key: role!.key };
          await (role!.is_active ? call(api.auth.POST('/api/auth/v1/roles/{key}/deactivate', { params: { path } })) : call(api.auth.POST('/api/auth/v1/roles/{key}/activate', { params: { path } })));
          await refresh();
        }} />
    </div>
  );
}
