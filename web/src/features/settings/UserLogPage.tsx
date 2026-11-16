// 14c User Log: filter by date, staff, branch, action, record type; a row opens the change as a before / after
// table (only the changed keys are stored, see pharmacy_shared.audit.changes).
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { AuthS } from '@/api/types';
import { branchName, useBranchesQuery } from '@/app/branch';
import { BranchTag, DataTable, DefinitionList, Drawer, Input, PageHeader, Select, Toolbar, useDebounced } from '@/design';
import { addDays, dateTime, todayIso } from '@/lib/format';
import { usePaging } from '../shared/hooks';

type Entry = AuthS['AuditOut'];

const changedKeys = (r: Entry) => Object.keys({ ...r.before, ...r.after }).filter((k) => JSON.stringify(r.before?.[k]) !== JSON.stringify(r.after?.[k]));
const show = (v: unknown) => (v === undefined ? '—' : v === null ? '∅' : typeof v === 'object' ? JSON.stringify(v) : String(v));

export function Diff({ before, after }: { before: Record<string, unknown>; after: Record<string, unknown> }) {
  const { t } = useTranslation('settings');
  const all = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].sort();
  // Some services store whole records: show only what changed (all keys when nothing differs, e.g. a creation).
  const changed = all.filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]));
  const keys = changed.length ? changed : all;
  if (!keys.length) return <p className="text-[13px] text-neutral-500">—</p>;
  return (
    <table className="w-full table-fixed border-collapse text-[13px]">
      <caption className="sr-only">{t('log.changes')}</caption>
      <thead><tr className="text-left text-[12px] text-neutral-500"><th className="w-1/3 py-1.5 pr-2 font-medium">{t('log.field')}</th><th className="py-1.5 pr-2 font-medium">{t('log.before')}</th><th className="py-1.5 font-medium">{t('log.after')}</th></tr></thead>
      <tbody>
        {keys.map((k) => (
          <tr key={k} className="border-t border-neutral-100 align-top">
            <td className="break-words py-1.5 pr-2 font-mono text-[12px]">{k}</td>
            <td className="break-words py-1.5 pr-2 text-danger">{show(before?.[k])}</td>
            <td className="break-words py-1.5 text-success">{show(after?.[k])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function UserLogPage() {
  const { t, i18n } = useTranslation(['settings', 'common', 'nav']);
  const paging = usePaging(50);
  const branches = useBranchesQuery();
  const users = useQuery({ queryKey: ['auth', 'users', 'all'], staleTime: 5 * 60_000, queryFn: () => call(api.auth.GET('/api/auth/v1/users', { params: { query: { size: 100 } } })) });
  const [from, setFrom] = useState(addDays(todayIso(), -7));
  const [to, setTo] = useState(todayIso());
  const [actor, setActor] = useState('');
  const [branch, setBranch] = useState('');
  const [action, setAction] = useState('');
  const [entity, setEntity] = useState('');
  const [open, setOpen] = useState<Entry | null>(null);
  const da = useDebounced(action.trim());
  const de = useDebounced(entity.trim());
  // The API takes timestamps (to is exclusive): whole days in Phnom Penh time.
  const query = { from: from ? `${from}T00:00:00+07:00` : undefined, to: to ? `${addDays(to, 1)}T00:00:00+07:00` : undefined, actor_id: actor || undefined, branch_id: branch || undefined, action: da || undefined, entity_type: de || undefined, page: paging.page, size: paging.size };
  const q = useQuery({ queryKey: ['auth', 'audit', query], queryFn: () => call(api.auth.GET('/api/auth/v1/audit-logs', { params: { query } })) });
  const name = (id: string | null) => (id ? users.data?.items.find((u) => u.id === id)?.name ?? '…' + id.slice(-6) : t('log.system'));
  const code = (id: string | null) => (id ? branches.data?.find((b) => b.id === id)?.code : undefined);
  const reset = (f: () => void) => { f(); paging.reset(); };
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('log.title')} />
      <Toolbar>
        <Input aria-label={t('common:label.from')} type="date" className="w-40" value={from} onChange={(e) => reset(() => setFrom(e.target.value))} />
        <Input aria-label={t('common:label.to')} type="date" className="w-40" value={to} onChange={(e) => reset(() => setTo(e.target.value))} />
        <Select aria-label={t('log.who')} className="w-44" value={actor} onChange={(e) => reset(() => setActor(e.target.value))}>
          <option value="">{t('log.who')}: —</option>
          {users.data?.items.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </Select>
        <Select aria-label={t('common:label.branch')} className="w-44" value={branch} onChange={(e) => reset(() => setBranch(e.target.value))}>
          <option value="">{t('common:label.allBranches')}</option>
          {branches.data?.map((b) => <option key={b.id} value={b.id}>{b.code} · {branchName(b, i18n.language)}</option>)}
        </Select>
        <Input aria-label={t('log.action')} placeholder={t('log.action')} className="w-44" value={action} onChange={(e) => reset(() => setAction(e.target.value))} />
        <Input aria-label={t('log.what')} placeholder={t('log.what')} className="w-40" value={entity} onChange={(e) => reset(() => setEntity(e.target.value))} />
      </Toolbar>
      <DataTable rows={q.data?.items} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} onRowClick={setOpen} dense
        paging={{ page: paging.page, size: paging.size, total: q.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'w', header: t('log.when'), cell: (r) => <span className="whitespace-nowrap tabular-nums">{dateTime(r.occurred_at)}</span> },
          { key: 'u', header: t('log.who'), cell: (r) => <span>{name(r.actor_id)}{r.actor_role && <span className="ml-1 text-[12px] text-neutral-500">({r.actor_role})</span>}</span> },
          { key: 'b', header: t('common:label.branch'), cell: (r) => (code(r.branch_id) ? <BranchTag code={code(r.branch_id)!} /> : '—') },
          { key: 'a', header: t('log.action'), cell: (r) => <span className="font-mono text-[12px]">{r.action}</span> },
          { key: 'e', header: t('log.what'), cell: (r) => <span className="text-[12px]">{r.entity_type}</span> },
          { key: 'c', header: t('log.changes'), cell: (r) => <span className="text-[12px] text-neutral-500">{changedKeys(r).slice(0, 3).join(', ') || '—'}</span> },
        ]} />
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.action ?? ''} subtitle={open ? dateTime(open.occurred_at) : undefined} width={560}>
        {open && <div className="flex flex-col gap-4">
          <DefinitionList cols={2} items={[
            { label: t('log.who'), value: name(open.actor_id) },
            { label: t('common:label.role'), value: open.actor_role ?? '—' },
            { label: t('log.service'), value: open.service },
            { label: t('common:label.branch'), value: code(open.branch_id) ?? '—' },
            { label: t('log.what'), value: open.entity_type },
            { label: 'ID', value: <span className="break-all font-mono text-[12px]">{open.entity_id ?? '—'}</span> },
            { label: 'IP', value: open.ip ?? '—' },
          ]} />
          <Diff before={open.before} after={open.after} />
        </div>}
      </Drawer>
    </div>
  );
}
