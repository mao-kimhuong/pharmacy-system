// 11a–11d Stock transfers: list (direction, status), in transit, push without a request; detail: pick FEFO,
// dispatch (controlled: PIN + witness), receive, differences (write off / back to source / accept / reject),
// cancel before dispatch, transfer note PDF with QR.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { InventoryS } from '@/api/types';
import { useUser } from '@/app/auth';
import { branchName, useBranch, useBranchesQuery } from '@/app/branch';
import { QueryState } from '@/app/RouteError';
import { Alert, ApiErrorAlert, BranchTag, Button, Card, DataTable, Dialog, EmptyState, Field, Input, PageHeader, ReasonDialog, Select, SkeletonRows, StatusPill, Tabs, Timeline, Usd, WitnessDialog, hasField, usePdf, useToast } from '@/design';
import { date, dateTime } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';
import { MedicinePicker, medName, type Medicine } from '../shared/MedicinePicker';
import { toneOf, useMedicineNames, usePaging } from '../shared/hooks';
import { ReceiveForm } from './ReceiveForm';

type Tr = InventoryS['TransferOut'];

export default function TransfersPage() {
  const { t, i18n } = useTranslation(['transfer', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const { branchParam, oneBranch, byId } = useBranch();
  const all = useBranchesQuery();
  const paging = usePaging();
  const [tab, setTab] = useState<'all' | 'transit'>('all');
  const [direction, setDirection] = useState('');
  const [push, setPush] = useState(false);
  const [to, setTo] = useState('');
  const [lines, setLines] = useState<{ m: Medicine; qty: string }[]>([]);
  const q = useQuery({ queryKey: ['inventory', 'transfers', branchParam, direction, paging.page], enabled: tab === 'all',
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/transfers', { params: { query: { branch_id: branchParam, direction: (direction || undefined) as never, page: paging.page, size: paging.size } } })) });
  const transit = useQuery({ queryKey: ['inventory', 'in-transit', branchParam], enabled: tab === 'transit', queryFn: () => call(api.inventory.GET('/api/inventory/v1/transfers/in-transit', { params: { query: { branch_id: branchParam } } })) });
  const names = useMedicineNames(transit.data?.map((r) => r.medicine_id) ?? []);
  const create = useMutation({
    mutationFn: () => call(api.inventory.POST('/api/inventory/v1/transfers', { body: { from_branch_id: oneBranch!.id, to_branch_id: to, lines: lines.map((l) => ({ medicine_id: l.m.id, qty_base: Number(l.qty) })) } })),
    onSuccess: (tr) => { void qc.invalidateQueries({ queryKey: ['inventory'] }); nav(`/transfers/${tr.id}`); },
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.transfer')} title={t('tr.title')}
        actions={<>{user.has('transfers.receive') && <Button onClick={() => nav('/transfers/receive')}>{t('tr.scanTitle')}</Button>}{user.has('transfers.dispatch') && <Button variant="primary" onClick={() => setPush(true)}>+ {t('tr.push')}</Button>}</>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: 'all', label: t('tr.title') }, { value: 'transit', label: t('tr.inTransit') }]} />
      {tab === 'all' ? (
        <DataTable toolbar={<Select aria-label={t('tr.direction')} className="w-44" value={direction} onChange={(e) => { setDirection(e.target.value); paging.reset(); }}><option value="">{t('common:label.all')}</option><option value="out">{t('tr.out')}</option><option value="in">{t('tr.in')}</option></Select>}
          rows={q.data?.items} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} onRowClick={(r) => nav(`/transfers/${r.id}`)} empty={<EmptyState title={t('tr.empty')} />}
          paging={{ page: paging.page, size: paging.size, total: q.data?.total ?? 0, onPage: paging.setPage }}
          columns={[
            { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
            { key: 'f', header: t('req.from'), cell: (r) => <BranchTag code={byId(r.from_branch_id)?.code ?? '?'} /> },
            { key: 't', header: t('req.to'), cell: (r) => <BranchTag code={byId(r.to_branch_id)?.code ?? '?'} /> },
            { key: 'l', header: t('common:label.lines'), align: 'right', cell: (r) => r.lines.length },
            { key: 'd', header: t('common:label.date'), cell: (r) => dateTime(r.dispatched_at ?? r.created_at) },
            { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`tr.status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
          ]} />
      ) : (
        <DataTable rows={transit.data} loading={transit.isLoading} error={transit.error} rowKey={(r) => r.transfer_id + r.batch_id} onRowClick={(r) => nav(`/transfers/${r.transfer_id}`)}
          columns={[
            { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
            { key: 'f', header: t('req.from'), cell: (r) => `${byId(r.from_branch_id)?.code ?? '?'} → ${byId(r.to_branch_id)?.code ?? '?'}` },
            { key: 'm', header: t('common:label.medicine'), cell: (r) => names(r.medicine_id) },
            { key: 'l', header: t('common:label.lot'), cell: (r) => `${r.lot_no} · ${date(r.expiry_date)}` },
            { key: 'q', header: t('common:label.qty'), align: 'right', cell: (r) => r.qty_base },
            ...(transit.data?.some((r) => hasField(r, 'cost_per_base')) ? [{ key: 'c', header: t('common:label.cost'), align: 'right' as const, cell: (r: InventoryS['InTransitRow']) => <Usd value={r.cost_per_base} /> }] : []),
            { key: 'd', header: t('common:label.date'), cell: (r) => dateTime(r.dispatched_at) },
          ]} />
      )}
      <Dialog open={push} onClose={() => setPush(false)} title={t('tr.push')} width={640}
        footer={<><Button onClick={() => setPush(false)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!to || !lines.length || lines.some((l) => !Number(l.qty))} loading={create.isPending} onClick={() => create.mutate()}>{t('common:action.save')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('req.to')} required>{(id) => <Select id={id} value={to} onChange={(e) => setTo(e.target.value)}><option value="">—</option>{(all.data ?? []).filter((b) => b.is_active && b.id !== oneBranch?.id).map((b) => <option key={b.id} value={b.id}>{b.code} {branchName(b, i18n.language)}</option>)}</Select>}</Field>
          {lines.map((l, i) => (
            <div key={l.m.id} className="flex items-center gap-2"><span className="flex-1">{medName(l.m)} <span className="text-[12px] text-neutral-500">{l.m.base_unit}</span></span>
              <Input aria-label={`${t('common:label.qty')} ${medName(l.m)}`} className="w-28 text-right" inputMode="numeric" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value.replace(/\D/g, '') } : x)))} />
              <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</Button></div>
          ))}
          <MedicinePicker value={null} clearOnPick filter={(m) => m.kind !== 'hamper'} onChange={(m) => m && setLines([...lines, { m, qty: '' }])} />
          <ApiErrorAlert error={create.error} />
        </div>
      </Dialog>
    </div>
  );
}

export function TransferDetailPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['transfer', 'common', 'nav']);
  const user = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const pdf = usePdf();
  const { byId } = useBranch();
  const all = useBranchesQuery();
  const [dlg, setDlg] = useState<'' | 'cancel' | 'witness' | 'receive'>('');
  const [resolve, setResolve] = useState<{ id: string; kind: string } | null>(null);
  const [resolution, setResolution] = useState<'write_off' | 'return_to_source' | 'accept' | 'reject'>('write_off');
  const [reason, setReason] = useState('');
  const q = useQuery({ queryKey: ['inventory', 'transfer', id], queryFn: () => call(api.inventory.GET('/api/inventory/v1/transfers/{transfer_id}', { params: { path: { transfer_id: id } } })) });
  const tr = q.data;
  const names = useMedicineNames(tr?.lines.map((l) => l.medicine_id) ?? []);
  const refresh = () => qc.invalidateQueries({ queryKey: ['inventory'] });
  const pick = useMutation({ mutationFn: () => call(api.inventory.POST('/api/inventory/v1/transfers/{transfer_id}/pick', { params: { path: { transfer_id: id } }, body: {} })), onSuccess: () => void refresh() });
  const dkey = useRequestKey(`dispatch-${id}`);
  const dispatch = useMutation({
    mutationFn: (tk?: { pin?: string; witness: string }) => call(api.inventory.POST('/api/inventory/v1/transfers/{transfer_id}/dispatch', { params: { path: { transfer_id: id } }, body: { pin_token: tk?.pin ?? null, witness_token: tk?.witness ?? null }, ...withKey(dkey) })),
    onSuccess: () => { toast.success(t('tr.status.dispatched')); void refresh(); },
  });
  const rkey = useRequestKey(`resolve-${resolve?.id}-${resolution}-${reason}`);
  const res = useMutation({
    mutationFn: () => call(api.inventory.POST('/api/inventory/v1/transfers/{transfer_id}/differences/{discrepancy_id}/resolve', { params: { path: { transfer_id: id, discrepancy_id: resolve!.id } }, body: { resolution, reason }, ...withKey(rkey) })),
    onSuccess: () => { setResolve(null); setReason(''); void refresh(); },
  });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  if (!tr) return <SkeletonRows />;
  const mine = new Set(user.isOwner ? (all.data ?? []).map((b) => b.id) : user.branch_ids);
  const atSource = mine.has(tr.from_branch_id);
  const atDest = mine.has(tr.to_branch_id);
  const controlled = tr.lines.some((l) => l.is_controlled);
  const showCost = tr.picks.some((p) => hasField(p, 'cost_per_base'));
  const steps = ['approved', 'picked', 'dispatched', 'received', 'closed'];
  const at = steps.indexOf(tr.status);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.transfer')} / ${t('tr.title')}`} title={tr.number}
        actions={<>
          <Button onClick={() => pdf.open({ type: 'transfer_note', transfer_id: tr.id }, tr.number, `${tr.number}.pdf`)}>{t('tr.note')}</Button>
          {atSource && tr.status === 'approved' && user.has('transfers.dispatch') && <Button variant="primary" loading={pick.isPending} onClick={() => pick.mutate()}>{t('tr.pick')}</Button>}
          {atSource && tr.status === 'picked' && user.has('transfers.dispatch') && <Button variant="primary" loading={dispatch.isPending} onClick={() => (controlled ? setDlg('witness') : dispatch.mutate(undefined))}>{t('tr.dispatch')}</Button>}
          {atDest && tr.status === 'dispatched' && user.has('transfers.receive') && <Button variant="primary" onClick={() => setDlg('receive')}>{t('tr.receive')}</Button>}
          {atSource && ['approved', 'picked'].includes(tr.status) && <Button variant="danger-outline" onClick={() => setDlg('cancel')}>{t('tr.cancel')}</Button>}
        </>}>
        <div className="flex flex-wrap items-center gap-2 text-[13px]"><StatusPill tone={toneOf(tr.status)}>{t(`tr.status.${tr.status}`, { defaultValue: tr.status })}</StatusPill>
          <BranchTag code={byId(tr.from_branch_id)?.code ?? '?'} /> → <BranchTag code={byId(tr.to_branch_id)?.code ?? '?'} /></div>
      </PageHeader>
      <ApiErrorAlert error={pick.error ?? dispatch.error} />
      {controlled && <Alert tone="info">{t('tr.controlled')}</Alert>}
      <div className="grid gap-4 desktop:grid-cols-[2fr_1fr]">
        <div className="flex flex-col gap-4">
          <Card padded={false} title={t('common:label.lines')}>
            <DataTable className="rounded-none border-0" rows={tr.lines} rowKey={(l) => String(l.line_no)} columns={[
              { key: 'm', header: t('common:label.medicine'), cell: (l) => names(l.medicine_id) },
              { key: 'q', header: t('common:label.qty'), align: 'right', cell: (l) => l.qty_base },
            ]} />
          </Card>
          {tr.picks.length > 0 && (
            <Card padded={false} title={t('tr.picks')}>
              <DataTable className="rounded-none border-0" rows={tr.picks} rowKey={(p) => p.id} columns={[
                { key: 'm', header: t('common:label.medicine'), cell: (p) => names(tr.lines.find((l) => l.line_no === p.line_no)?.medicine_id ?? '') },
                { key: 'l', header: t('common:label.lot'), cell: (p) => `${p.lot_no ?? ''} · ${date(p.expiry_date)}` },
                { key: 'q', header: t('common:label.qty'), align: 'right', cell: (p) => p.qty_base },
                { key: 'r', header: t('tr.received'), align: 'right', cell: (p) => p.qty_received ?? '—' },
                { key: 'd', header: t('tr.damaged'), align: 'right', cell: (p) => p.qty_damaged || '—' },
                ...(showCost ? [{ key: 'c', header: t('common:label.cost'), align: 'right' as const, cell: (p: Tr['picks'][number]) => <Usd value={p.cost_per_base} /> }] : []),
              ]} />
            </Card>
          )}
          {tr.discrepancies.length > 0 && (
            <Card padded={false} title={t('tr.differences')}>
              <DataTable className="rounded-none border-0" rows={tr.discrepancies} rowKey={(d) => d.id} columns={[
                { key: 'k', header: t('common:label.type'), cell: (d) => t(`tr.kind.${d.kind}`, { defaultValue: d.kind }) },
                { key: 'q', header: t('common:label.qty'), align: 'right', cell: (d) => d.qty_base },
                { key: 's', header: t('common:label.status'), cell: (d) => (d.resolution ? `${t(`tr.resolution.${d.resolution}`, { defaultValue: d.resolution })} · ${d.reason}` : <StatusPill tone="warning">{d.status}</StatusPill>) },
                { key: 'a', header: '', align: 'right', cell: (d) => d.status === 'open' && user.has('transfers.resolve') && <Button size="sm" variant="primary" onClick={() => { setResolve({ id: d.id, kind: d.kind }); setResolution(d.kind === 'extra' ? 'accept' : 'write_off'); }}>{t('tr.resolve')}</Button> },
              ]} />
            </Card>
          )}
        </div>
        <Card title={t('common:label.status')}>
          <Timeline items={[
            ...steps.map((s, i) => ({ title: t(`tr.status.${s}`), tone: tr.status === 'cancelled' ? ('todo' as const) : i < at ? ('done' as const) : i === at ? ('current' as const) : ('todo' as const),
              meta: s === 'dispatched' ? [dateTime(tr.dispatched_at), tr.dispatch_witness].filter((x) => x && x !== '—').join(' · ') : s === 'received' ? [dateTime(tr.received_at), tr.receive_witness].filter((x) => x && x !== '—').join(' · ') : undefined })),
            ...(tr.status === 'cancelled' ? [{ title: t('tr.status.cancelled'), tone: 'danger' as const, meta: tr.cancel_reason ?? '' }] : []),
          ]} />
        </Card>
      </div>
      <ReasonDialog open={dlg === 'cancel'} onClose={() => setDlg('')} title={t('tr.cancel')} confirmLabel={t('tr.cancel')}
        onConfirm={async (r) => { await call(api.inventory.POST('/api/inventory/v1/transfers/{transfer_id}/cancel', { params: { path: { transfer_id: id } }, body: { reason: r } })); await refresh(); }} />
      <WitnessDialog open={dlg === 'witness'} action="transfers.dispatch" branchId={tr.from_branch_id} onClose={() => setDlg('')}
        onTokens={({ pin, witness }) => { setDlg(''); dispatch.mutate({ pin: pin?.pin_token, witness: witness.pin_token }); }} />
      <Dialog open={dlg === 'receive'} onClose={() => setDlg('')} title={`${t('tr.receive')} · ${tr.number}`} width={720}>
        {dlg === 'receive' && <ReceiveForm tr={tr} onDone={() => setDlg('')} />}
      </Dialog>
      <Dialog open={!!resolve} onClose={() => setResolve(null)} title={t('tr.resolve')} width={460}
        footer={<><Button onClick={() => setResolve(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!reason.trim()} loading={res.isPending} onClick={() => res.mutate()}>{t('tr.resolve')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('common:label.type')}>{(fid) => <Select id={fid} value={resolution} onChange={(e) => setResolution(e.target.value as typeof resolution)}>
            {(resolve?.kind === 'extra' ? (['accept', 'reject'] as const) : (['write_off', 'return_to_source'] as const)).map((r) => <option key={r} value={r}>{t(`tr.resolution.${r}`)}</option>)}
          </Select>}</Field>
          <Field label={t('common:label.reason')} required>{(fid) => <Input id={fid} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <ApiErrorAlert error={res.error} />
        </div>
      </Dialog>
      {pdf.element}
    </div>
  );
}
