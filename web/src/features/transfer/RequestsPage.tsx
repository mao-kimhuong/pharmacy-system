// 12k Transfer requests: ask another branch for stock (base units); the source approves (→ transfer) or rejects;
// the asker can cancel. Stock at branches you cannot see has no API: only your branches show.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { InventoryS } from '@/api/types';
import { useUser } from '@/app/auth';
import { branchName, useBranch, useBranchesQuery } from '@/app/branch';
import { Alert, ApiErrorAlert, BranchTag, Button, DataTable, Dialog, EmptyState, Field, Input, PageHeader, ReasonDialog, Select, StatusPill } from '@/design';
import { date, dateTime } from '@/lib/format';
import { MedicinePicker, medName, type Medicine } from '../shared/MedicinePicker';
import { toneOf, useMedicineNames } from '../shared/hooks';

type Req = InventoryS['TransferRequestOut'];

export default function TransferRequestsPage() {
  const { t, i18n } = useTranslation(['transfer', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { branchParam, oneBranch, byId } = useBranch();
  const all = useBranchesQuery();
  const [neu, setNeu] = useState(false);
  const [from, setFrom] = useState('');
  const [reason, setReason] = useState('');
  const [needed, setNeeded] = useState('');
  const [lines, setLines] = useState<{ m: Medicine; qty: string }[]>([]);
  const [dlg, setDlg] = useState<{ kind: 'reject' | 'cancel'; r: Req } | null>(null);
  const q = useQuery({ queryKey: ['inventory', 'treqs', branchParam], queryFn: () => call(api.inventory.GET('/api/inventory/v1/transfer-requests', { params: { query: { branch_id: branchParam } } })) });
  const names = useMedicineNames((q.data ?? []).flatMap((r) => r.lines.map((l) => l.medicine_id)));
  const create = useMutation({
    mutationFn: () => call(api.inventory.POST('/api/inventory/v1/transfer-requests', { body: { from_branch_id: from, to_branch_id: oneBranch!.id, reason, needed_by: needed || null, lines: lines.map((l) => ({ medicine_id: l.m.id, qty_base: Number(l.qty) })) } })),
    onSuccess: () => { setNeu(false); setLines([]); void qc.invalidateQueries({ queryKey: ['inventory', 'treqs'] }); },
  });
  const approve = useMutation({
    mutationFn: (id: string) => call(api.inventory.POST('/api/inventory/v1/transfer-requests/{request_id}/approve', { params: { path: { request_id: id } } })),
    onSuccess: (tr) => { void qc.invalidateQueries({ queryKey: ['inventory'] }); nav(`/transfers/${tr.id}`); },
  });
  const mine = new Set(user.isOwner ? (all.data ?? []).map((b) => b.id) : user.branch_ids);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.transfer')} title={t('req.title')} actions={user.has('transfers.request') && <Button variant="primary" onClick={() => setNeu(true)}>+ {t('req.new')}</Button>} />
      <ApiErrorAlert error={approve.error} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} empty={<EmptyState title={t('req.empty')} />}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
          { key: 'f', header: t('req.from'), cell: (r) => <BranchTag code={byId(r.from_branch_id)?.code ?? '?'} /> },
          { key: 't', header: t('req.to'), cell: (r) => <BranchTag code={byId(r.to_branch_id)?.code ?? '?'} /> },
          { key: 'l', header: t('common:label.items'), cell: (r) => <span className="text-[12px]">{r.lines.map((l) => `${names(l.medicine_id)} ×${l.qty_base}`).join(' · ')}</span> },
          { key: 'd', header: t('common:label.date'), cell: (r) => `${dateTime(r.created_at)}${r.needed_by ? ` → ${date(r.needed_by)}` : ''}` },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`tr.status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (r) => r.status === 'requested' && (
            <span className="flex justify-end gap-1">
              {mine.has(r.from_branch_id) && user.has('transfers.approve') && <><Button size="sm" variant="primary" loading={approve.isPending} onClick={() => approve.mutate(r.id)}>{t('req.approve')}</Button><Button size="sm" onClick={() => setDlg({ kind: 'reject', r })}>{t('req.reject')}</Button></>}
              {mine.has(r.to_branch_id) && <Button size="sm" variant="danger-outline" onClick={() => setDlg({ kind: 'cancel', r })}>{t('req.cancel')}</Button>}
            </span>
          ) },
        ]} />
      <Dialog open={neu} onClose={() => setNeu(false)} title={t('req.new')} width={680}
        footer={<><Button onClick={() => setNeu(false)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!from || !lines.length || lines.some((l) => !Number(l.qty))} loading={create.isPending} onClick={() => create.mutate()}>{t('common:action.submit')}</Button></>}>
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('req.from')} required>{(id) => <Select id={id} value={from} onChange={(e) => setFrom(e.target.value)}><option value="">—</option>{(all.data ?? []).filter((b) => b.is_active && b.id !== oneBranch?.id).map((b) => <option key={b.id} value={b.id}>{b.code} {branchName(b, i18n.language)}</option>)}</Select>}</Field>
            <Field label={t('common:label.to')}>{(id) => <Input id={id} disabled value={oneBranch ? `${oneBranch.code} ${branchName(oneBranch, i18n.language)}` : ''} />}</Field>
            <Field label={t('common:label.reason')}>{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
            <Field label={t('purchase:pr.neededBy')}>{(id) => <Input id={id} type="date" value={needed} onChange={(e) => setNeeded(e.target.value)} />}</Field>
          </div>
          {lines.map((l, i) => (
            <div key={l.m.id} className="flex items-center gap-2"><span className="flex-1">{medName(l.m)} <span className="text-[12px] text-neutral-500">{l.m.base_unit}</span></span>
              <Input aria-label={`${t('common:label.qty')} ${medName(l.m)}`} className="w-28 text-right" inputMode="numeric" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value.replace(/\D/g, '') } : x)))} />
              <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</Button></div>
          ))}
          <MedicinePicker value={null} clearOnPick filter={(m) => m.kind !== 'hamper'} onChange={(m) => m && setLines([...lines, { m, qty: '' }])} />
          <Alert tone="info">{t('req.otherStock')}</Alert>
          <ApiErrorAlert error={create.error} />
        </div>
      </Dialog>
      <ReasonDialog open={!!dlg} onClose={() => setDlg(null)} title={dlg?.kind === 'reject' ? t('req.reject') : t('req.cancel')} confirmLabel={dlg?.kind === 'reject' ? t('req.reject') : t('req.cancel')}
        onConfirm={async (reason) => {
          const path = { request_id: dlg!.r.id };
          await (dlg!.kind === 'reject' ? call(api.inventory.POST('/api/inventory/v1/transfer-requests/{request_id}/reject', { params: { path }, body: { reason } })) : call(api.inventory.POST('/api/inventory/v1/transfer-requests/{request_id}/cancel', { params: { path }, body: { reason } })));
          await qc.invalidateQueries({ queryKey: ['inventory', 'treqs'] });
        }} />
    </div>
  );
}
