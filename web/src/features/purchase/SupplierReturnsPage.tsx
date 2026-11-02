// 10d Supplier returns: draft (supplier, reason, batches bought from that supplier) → submit as credit (to next
// bills) or refund (owner / branch manager), controlled lines with PIN + witness; cancel a draft; return note PDF.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { isApiError } from '@/api/errors';
import type { PurchasingS } from '@/api/types';
import { branchName, useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, DataTable, Dialog, EmptyState, Field, Input, PageHeader, Radio, ReasonDialog, Select, StatusPill, TextArea, Usd, WitnessDialog, hasField, usePdf, useToast } from '@/design';
import { dateTime } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';
import { BatchSelect } from '../shared/BatchSelect';
import { MedicinePicker, medName, type Medicine } from '../shared/MedicinePicker';
import { SupplierPicker, type Supplier } from '../shared/SupplierPicker';
import { toneOf } from '../shared/hooks';

type Ret = PurchasingS['SupplierReturnOut'];
const REASONS = ['damaged', 'expired', 'recalled', 'wrong_item', 'overstock'] as const;

function NewReturn({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation(['purchase', 'common']);
  const qc = useQueryClient();
  const { oneBranch } = useBranch();
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [reason, setReason] = useState<(typeof REASONS)[number]>('damaged');
  const [note, setNote] = useState('');
  const [lines, setLines] = useState<{ m: Medicine; batch: string; qty: string }[]>([]);
  const m = useMutation({
    mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/supplier-returns', { body: { branch_id: oneBranch!.id, supplier_id: supplier!.id, reason, note, lines: lines.map((l) => ({ medicine_id: l.m.id, batch_id: l.batch, qty_base: Number(l.qty) })) } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['purchasing', 'sreturns'] }); onClose(); },
  });
  return (
    <Dialog open onClose={onClose} title={t('sret.new')} width={760}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!supplier || !lines.length || lines.some((l) => !l.batch || !Number(l.qty))} loading={m.isPending} onClick={() => m.mutate()}>{t('common:action.save')}</Button></>}>
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('common:label.supplier')} required>{(id) => <SupplierPicker id={id} value={supplier} onChange={setSupplier} autoFocus />}</Field>
          <Field label={t('common:label.reason')}>{(id) => <Select id={id} value={reason} onChange={(e) => setReason(e.target.value as typeof reason)}>{REASONS.map((r) => <option key={r} value={r}>{t(`sret.reason.${r}`)}</option>)}</Select>}</Field>
        </div>
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[1.5fr_1.5fr_100px_auto] items-end gap-2">
            <span className="text-[13px] font-medium">{medName(l.m)}</span>
            <Field label={t('sret.batch')}>{(id) => <BatchSelect id={id} branchId={oneBranch!.id} medicineId={l.m.id} supplierId={supplier?.id} value={l.batch} onChange={(b) => setLines(lines.map((x, j) => (j === i ? { ...x, batch: b } : x)))} />}</Field>
            <Field label={t('common:label.qty')}>{(id) => <Input id={id} inputMode="numeric" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: e.target.value.replace(/\D/g, '') } : x)))} />}</Field>
            <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</Button>
          </div>
        ))}
        <MedicinePicker value={null} clearOnPick filter={(x) => x.kind !== 'hamper'} onChange={(x) => x && setLines([...lines, { m: x, batch: '', qty: '' }])} />
        <Field label={t('common:label.notes')}>{(id) => <TextArea id={id} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        <ApiErrorAlert error={m.error} />
      </div>
    </Dialog>
  );
}

function Submit({ ret, onClose }: { ret: Ret; onClose: () => void }) {
  const { t } = useTranslation(['purchase', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const [settle, setSettle] = useState<'credit' | 'refund'>('credit');
  const [method, setMethod] = useState<'cash' | 'bank' | 'ABA' | 'KHQR'>('cash');
  const [ref, setRef] = useState('');
  const [witness, setWitness] = useState(false);
  const body = { settle, refund_method: settle === 'refund' ? method : null, refund_reference: ref };
  const key = useRequestKey(JSON.stringify(body) + ret.id);
  const m = useMutation({
    mutationFn: (tk?: { pin?: string; witness: string }) => call(api.purchasing.POST('/api/purchasing/v1/supplier-returns/{return_id}/submit', { params: { path: { return_id: ret.id } }, body: { ...body, pin_token: tk?.pin ?? null, witness_token: tk?.witness ?? null }, ...withKey(key) })),
    onSuccess: (r) => { toast.success(r.number); void qc.invalidateQueries({ queryKey: ['purchasing'] }); onClose(); },
    onError: (e) => { if (isApiError(e) && (e.code === 'PIN_REQUIRED' || e.code === 'WITNESS_REQUIRED')) setWitness(true); },
  });
  return (
    <>
      <Dialog open={!witness} onClose={onClose} title={`${t('sret.submit')} · ${ret.number}`} width={460}
        footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate(undefined)}>{t('sret.submit')}</Button></>}>
        <div className="flex flex-col gap-3">
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0"><legend className="mb-1 text-[13px] font-medium">{t('sret.settle')}</legend>
            <Radio name="settle" label={t('sret.credit')} checked={settle === 'credit'} onChange={() => setSettle('credit')} />
            <Radio name="settle" label={t('sret.refund')} checked={settle === 'refund'} onChange={() => setSettle('refund')} />
          </fieldset>
          {settle === 'refund' && <div className="grid grid-cols-2 gap-3">
            <Field label={t('sret.refundMethod')}>{(id) => <Select id={id} value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>{(['cash', 'bank', 'ABA', 'KHQR'] as const).map((x) => <option key={x} value={x}>{t(`pay.method.${x}`)}</option>)}</Select>}</Field>
            <Field label={t('pay.reference')}>{(id) => <Input id={id} value={ref} onChange={(e) => setRef(e.target.value)} />}</Field>
          </div>}
          <ApiErrorAlert error={m.error && !(isApiError(m.error) && ['PIN_REQUIRED', 'WITNESS_REQUIRED'].includes(m.error.code)) ? m.error : null} />
        </div>
      </Dialog>
      <WitnessDialog open={witness} action="purchasing.supplier_return" branchId={ret.branch_id} onClose={() => setWitness(false)}
        onTokens={({ pin, witness: w }) => { setWitness(false); m.mutate({ pin: pin?.pin_token, witness: w.pin_token }); }} />
    </>
  );
}

export default function SupplierReturnsPage() {
  const { t, i18n } = useTranslation(['purchase', 'common', 'nav', 'sales']);
  const qc = useQueryClient();
  const pdf = usePdf();
  const { branchParam, byId } = useBranch();
  const [neu, setNeu] = useState(false);
  const [submit, setSubmit] = useState<Ret | null>(null);
  const [cancel, setCancel] = useState<Ret | null>(null);
  const q = useQuery({ queryKey: ['purchasing', 'sreturns', branchParam], queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/supplier-returns', { params: { query: { branch_id: branchParam } } })) });
  const showCost = !!q.data?.some((r) => hasField(r, 'total'));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.purchase')} title={t('sret.title')} actions={<Button variant="primary" onClick={() => setNeu(true)}>+ {t('sret.new')}</Button>} />
      <DataTable rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(r) => r.id} empty={<EmptyState title={t('sret.empty')} />}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (r) => <span className="font-mono text-[12px]">{r.number}</span> },
          { key: 'b', header: t('common:label.branch'), cell: (r) => branchName(byId(r.branch_id), i18n.language) },
          { key: 'r', header: t('common:label.reason'), cell: (r) => t(`sret.reason.${r.reason}`, { defaultValue: r.reason }) },
          { key: 'l', header: t('common:label.lines'), align: 'right', cell: (r) => r.lines.length },
          ...(showCost ? [{ key: 't', header: t('common:label.total'), align: 'right' as const, cell: (r: Ret) => <Usd value={r.total} /> }] : []),
          { key: 'd', header: t('common:label.date'), cell: (r) => dateTime(r.submitted_at ?? r.created_at) },
          { key: 's', header: t('common:label.status'), cell: (r) => <StatusPill tone={toneOf(r.status)}>{t(`sales:status.${r.status}`, { defaultValue: r.status })}</StatusPill> },
          { key: 'a', header: '', align: 'right', cell: (r) => (
            <span className="flex justify-end gap-1">
              <Button size="sm" onClick={() => pdf.open({ type: 'supplier_return', supplier_return_id: r.id, lang: i18n.language as 'km' | 'en' }, r.number, `${r.number}.pdf`)}>{t('sret.pdf')}</Button>
              {r.status === 'draft' && <><Button size="sm" variant="primary" onClick={() => setSubmit(r)}>{t('sret.submit')}</Button><Button size="sm" variant="danger-outline" onClick={() => setCancel(r)}>{t('sret.cancel')}</Button></>}
            </span>
          ) },
        ]} />
      {neu && <NewReturn onClose={() => setNeu(false)} />}
      {submit && <Submit ret={submit} onClose={() => setSubmit(null)} />}
      <ReasonDialog open={!!cancel} onClose={() => setCancel(null)} title={t('sret.cancel')} confirmLabel={t('sret.cancel')}
        onConfirm={async (reason) => { await call(api.purchasing.POST('/api/purchasing/v1/supplier-returns/{return_id}/cancel', { params: { path: { return_id: cancel!.id } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['purchasing'] }); }} />
      {pdf.element}
    </div>
  );
}
