// 10a Purchase requests: anyone with purchasing.request asks; approvers approve / reject, then route approved lines
// to a supplier (one draft PO per branch + a PO group) or fill them by a transfer from another branch.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PurchasingS } from '@/api/types';
import { useUser } from '@/app/auth';
import { branchName, useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, BranchTag, Button, DataTable, Dialog, Drawer, EmptyState, Field, Input, PageHeader, ReasonDialog, Select, StatusPill, useToast } from '@/design';
import { date, dateTime } from '@/lib/format';
import { MedicinePicker, medName, type Medicine } from '../shared/MedicinePicker';
import { SupplierPicker, type Supplier } from '../shared/SupplierPicker';
import { toneOf, useMedicineNames } from '../shared/hooks';

type PR = PurchasingS['PROut'];

function NewRequest({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(['purchase', 'common']);
  const qc = useQueryClient();
  const { oneBranch } = useBranch();
  const [lines, setLines] = useState<{ m: Medicine; qty: string; reason: string }[]>([]);
  const [note, setNote] = useState('');
  const m = useMutation({
    mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/purchase-requests', { body: { branch_id: oneBranch!.id, note, lines: lines.map((l) => ({ medicine_id: l.m.id, qty_base: Number(l.qty), reason: l.reason })) } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['purchasing', 'prs'] }); onClose(); },
  });
  return (
    <Dialog open onClose={onClose} title={t('pr.new')} width={720}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" loading={m.isPending} disabled={!lines.length || lines.some((l) => !Number(l.qty))} onClick={() => m.mutate()}>{t('common:action.submit')}</Button></>}>
      <div className="flex flex-col gap-2">
        {lines.map((l, i) => (
          <div key={l.m.id} className="grid grid-cols-[2fr_120px_1.5fr_auto] items-center gap-2">
            <span className="font-medium">{medName(l.m)} <span className="text-[12px] text-neutral-500">{l.m.base_unit}</span></span>
            <Input aria-label={t('pr.qtyBase')} placeholder={t('pr.qtyBase')} inputMode="numeric" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value.replace(/\D/g, '') } : x)))} />
            <Input aria-label={t('pr.reason')} placeholder={t('pr.reason')} value={l.reason} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, reason: e.target.value } : x)))} />
            <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</Button>
          </div>
        ))}
        <MedicinePicker value={null} clearOnPick filter={(x) => x.kind !== 'hamper'} onChange={(x) => x && setLines([...lines, { m: x, qty: '', reason: '' }])} />
        <Field label={t('common:label.notes')}>{(id) => <Input id={id} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        <ApiErrorAlert error={m.error} />
      </div>
    </Dialog>
  );
}

function Detail({ pr, onClose }: { pr: PR; onClose: () => void }) {
  const { t, i18n } = useTranslation(['purchase', 'common', 'sales']);
  const user = useUser();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const { branches, byId } = useBranch();
  const names = useMedicineNames(pr.lines.map((l) => l.medicine_id));
  const [dlg, setDlg] = useState<'' | 'reject' | 'cancel' | 'po' | 'tr'>('');
  const [sel, setSel] = useState(new Set<string>());
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [po, setPo] = useState<Record<string, { pack: string; qty: string; cost: string }>>({});
  const [source, setSource] = useState('');
  const refresh = () => qc.invalidateQueries({ queryKey: ['purchasing'] });
  const approve = useMutation({ mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/purchase-requests/{request_id}/approve', { params: { path: { request_id: pr.id } } })), onSuccess: () => void refresh() });
  const meds = useQuery({
    queryKey: ['catalog', 'pr-meds', pr.id],
    enabled: dlg === 'po',
    queryFn: () => Promise.all([...new Set(pr.lines.map((l) => l.medicine_id))].map((id) => call(api.catalog.GET('/api/catalog/v1/medicines/{medicine_id}', { params: { path: { medicine_id: id } } })))),
  });
  const toPo = useMutation({
    mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/purchase-requests/to-purchase-orders', { body: { supplier_id: supplier!.id, lines: [...sel].map((id) => ({ request_line_id: id, pack_unit_id: po[id].pack, qty: Number(po[id].qty), unit_cost: po[id].cost })) } })),
    onSuccess: (g) => { toast.success(t('pr.group', { number: g.number })); void refresh(); nav(`/purchase/groups/${g.id}`); },
  });
  const tr = useMutation({
    mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/purchase-requests/{request_id}/fill-by-transfer', { params: { path: { request_id: pr.id } }, body: { source_branch_id: source, line_ids: [...sel] } })),
    onSuccess: () => { setDlg(''); setSel(new Set()); void refresh(); },
  });
  const open = pr.lines.filter((l) => l.status === 'approved' || l.status === 'open');
  const decide = user.has('purchasing.request_approve');
  return (
    <Drawer open onClose={onClose} title={pr.number} subtitle={`${byId(pr.branch_id)?.code ?? ''} · ${dateTime(pr.created_at)}`} width={760}
      footer={<>
        {pr.status === 'submitted' && decide && <><Button onClick={() => setDlg('reject')}>{t('pr.reject')}</Button><Button variant="primary" loading={approve.isPending} onClick={() => approve.mutate()}>{t('pr.approve')}</Button></>}
        {pr.status === 'approved' && sel.size > 0 && <>{user.has('purchasing.order') && <Button variant="primary" onClick={() => setDlg('po')}>{t('pr.toPo')}</Button>}{decide && <Button onClick={() => setDlg('tr')}>{t('pr.byTransfer')}</Button>}</>}
        {['submitted', 'approved'].includes(pr.status) && <Button variant="danger-outline" onClick={() => setDlg('cancel')}>{t('pr.cancel')}</Button>}
      </>}>
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2"><StatusPill tone={toneOf(pr.status)}>{t(`sales:status.${pr.status}`, { defaultValue: pr.status })}</StatusPill>{pr.progress && <span className="text-[12px] text-neutral-500">{pr.progress}</span>}</div>
        {pr.status === 'approved' && <Alert tone="info">{t('pr.routeHint')}</Alert>}
        <ApiErrorAlert error={approve.error} />
        <DataTable rows={pr.lines} rowKey={(l) => l.id} minWidth={600} dense
          selection={pr.status === 'approved' ? { selected: sel, onChange: (s) => setSel(new Set([...s].filter((id) => open.some((l) => l.id === id)))) } : undefined}
          columns={[
            { key: 'm', header: t('common:label.medicine'), cell: (l) => names(l.medicine_id) },
            { key: 'q', header: t('pr.qtyBase'), align: 'right', cell: (l) => l.qty_base },
            { key: 'f', header: t('pr.fulfilled'), align: 'right', cell: (l) => l.fulfilled_base },
            { key: 'n', header: t('pr.neededBy'), cell: (l) => date(l.needed_by) },
            { key: 's', header: t('common:label.status'), cell: (l) => <span className="text-[12px]">{l.status}{l.po_number ? ` · ${l.po_number}` : ''}{l.transfer_number ? ` · ${l.transfer_number}` : ''}</span> },
          ]} />
      </div>
      <ReasonDialog open={dlg === 'reject' || dlg === 'cancel'} onClose={() => setDlg('')} title={dlg === 'reject' ? t('pr.reject') : t('pr.cancel')} confirmLabel={dlg === 'reject' ? t('pr.reject') : t('pr.cancel')}
        onConfirm={async (reason) => {
          const path = { request_id: pr.id };
          await (dlg === 'reject' ? call(api.purchasing.POST('/api/purchasing/v1/purchase-requests/{request_id}/reject', { params: { path }, body: { reason } })) : call(api.purchasing.POST('/api/purchasing/v1/purchase-requests/{request_id}/cancel', { params: { path }, body: { reason } })));
          await refresh();
        }} />
      <Dialog open={dlg === 'po'} onClose={() => setDlg('')} title={t('pr.toPo')} width={760}
        footer={<><Button onClick={() => setDlg('')}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!supplier || [...sel].some((id) => !po[id]?.pack || !Number(po[id]?.qty) || !po[id]?.cost)} loading={toPo.isPending} onClick={() => toPo.mutate()}>{t('pr.toPo')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('common:label.supplier')} required>{(id) => <SupplierPicker id={id} value={supplier} onChange={setSupplier} autoFocus />}</Field>
          {pr.lines.filter((l) => sel.has(l.id)).map((l) => {
            const m = meds.data?.find((x) => x.id === l.medicine_id);
            const v = po[l.id] ?? { pack: '', qty: '', cost: '' };
            const set = (p: Partial<typeof v>) => setPo({ ...po, [l.id]: { ...v, ...p } });
            return (
              <div key={l.id} className="grid grid-cols-[2fr_1fr_100px_120px] items-end gap-2">
                <span className="text-[13px]">{names(l.medicine_id)} <span className="text-neutral-500">({l.qty_base})</span></span>
                <Field label={t('common:label.unit')}>{(id) => <Select id={id} value={v.pack} onChange={(e) => set({ pack: e.target.value })}><option value="">—</option>{m?.pack_units.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.qty_in_base})</option>)}</Select>}</Field>
                <Field label={t('common:label.qty')}>{(id) => <Input id={id} inputMode="numeric" value={v.qty} onChange={(e) => set({ qty: e.target.value.replace(/\D/g, '') })} />}</Field>
                <Field label={t('pr.unitCost')}>{(id) => <Input id={id} inputMode="decimal" value={v.cost} onChange={(e) => set({ cost: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>
              </div>
            );
          })}
          <ApiErrorAlert error={toPo.error} />
        </div>
      </Dialog>
      <Dialog open={dlg === 'tr'} onClose={() => setDlg('')} title={t('pr.byTransfer')} width={460}
        footer={<><Button onClick={() => setDlg('')}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!source} loading={tr.isPending} onClick={() => tr.mutate()}>{t('pr.byTransfer')}</Button></>}>
        <Field label={t('pr.sourceBranch')}>{(id) => <Select id={id} value={source} onChange={(e) => setSource(e.target.value)}><option value="">—</option>{branches.filter((b) => b.id !== pr.branch_id).map((b) => <option key={b.id} value={b.id}>{b.code} {branchName(b, i18n.language)}</option>)}</Select>}</Field>
        <ApiErrorAlert error={tr.error} />
      </Dialog>
    </Drawer>
  );
}

export default function RequestsPage() {
  const { t } = useTranslation(['purchase', 'common', 'nav', 'sales']);
  const { branchParam, byId } = useBranch();
  const [status, setStatus] = useState('');
  const [neu, setNeu] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const q = useQuery({ queryKey: ['purchasing', 'prs', branchParam, status], queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/purchase-requests', { params: { query: { branch_id: branchParam, status: status || undefined } } })) });
  const pr = q.data?.find((x) => x.id === sel);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.purchase')} title={t('pr.title')} actions={<Button variant="primary" onClick={() => setNeu(true)}>+ {t('pr.new')}</Button>} />
      <DataTable
        toolbar={<Select aria-label={t('common:label.status')} className="w-48" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t('common:label.all')}</option>{['submitted', 'approved', 'rejected', 'cancelled', 'fulfilled'].map((s) => <option key={s} value={s}>{t(`sales:status.${s}`, { defaultValue: s })}</option>)}</Select>}
        rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} onRowClick={(r) => setSel(r.id)} empty={<EmptyState title={t('pr.empty')} />}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
          { key: 'b', header: t('common:label.branch'), cell: (r) => <BranchTag code={byId(r.branch_id)?.code ?? '?'} /> },
          { key: 'l', header: t('common:label.lines'), align: 'right', cell: (r) => r.lines.length },
          { key: 'p', header: t('pr.progress'), cell: (r) => r.progress ?? '—' },
          { key: 'd', header: t('common:label.date'), cell: (r) => dateTime(r.created_at) },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`sales:status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
        ]} />
      {neu && <NewRequest onClose={() => setNeu(false)} />}
      {pr && <Detail pr={pr} onClose={() => setSel(null)} />}
    </div>
  );
}
