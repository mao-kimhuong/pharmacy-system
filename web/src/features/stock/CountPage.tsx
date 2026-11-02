// A stock take. While counting: the blind counter view (8h; phones too) — scan or pick a line, enter the count;
// lines that need a second person show it (8i). In review: expected vs counted, variance (value with cost),
// recount selected lines, approve (PIN when a controlled line differs; owner above the limit), cancel.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { isApiError } from '@/api/errors';
import type { StockcountS } from '@/api/types';
import { useUser } from '@/app/auth';
import { QueryState } from '@/app/RouteError';
import { Alert, ApiErrorAlert, Button, ConfirmDialog, DataTable, Dialog, Field, Input, PageHeader, PinDialog, ReasonDialog, SafetyBadge, Scanner, Sheet, SkeletonRows, StatusPill, Usd, cx, hasField, useToast } from '@/design';
import { date } from '@/lib/format';
import { toneOf } from '../shared/hooks';
import { useRequestKey } from '../pos/hooks';

type Line = StockcountS['CounterLine'];

function CounterView({ count }: { count: StockcountS['CounterView'] }) {
  const { t, i18n } = useTranslation(['stock', 'common']);
  const qc = useQueryClient();
  const toast = useToast();
  const [code, setCode] = useState('');
  const [found, setFound] = useState<Line[] | null>(null);
  const [line, setLine] = useState<Line | null>(null);
  const [qty, setQty] = useState('');
  const [camera, setCamera] = useState(false);
  const [submit, setSubmit] = useState(false);
  const lookup = useMutation({
    mutationFn: (barcode: string) => call(api.stockcount.GET('/api/stockcount/v1/counts/{count_id}/lookup', { params: { path: { count_id: count.id }, query: { barcode } } })),
    onSuccess: (r) => { setFound(r); if (r.length === 1) { setLine(r[0]); setQty(''); } },
  });
  const entry = useMutation({
    mutationFn: () => call(api.stockcount.POST('/api/stockcount/v1/counts/{count_id}/entries', { params: { path: { count_id: count.id } }, body: { line_id: line!.id, qty: Number(qty) } })),
    onSuccess: (l) => { toast.success(`${l.name} · ${qty}`); setLine(null); setFound(null); setCode(''); void qc.invalidateQueries({ queryKey: ['stockcount', 'count', count.id] }); },
  });
  const name = (l: Line) => (i18n.language === 'km' && l.name_km ? l.name_km : l.name);
  const lines = found ?? count.lines;
  return (
    <div className="flex flex-col gap-3">
      <Alert tone="info">{t('counts.blind')}</Alert>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (code.trim()) lookup.mutate(code.trim()); }}>
        <Input aria-label={t('counts.scan')} placeholder={t('counts.scan')} value={code} onChange={(e) => setCode(e.target.value)} fieldSize="lg" autoFocus />
        <Button type="button" size="lg" variant="primary" aria-label={t('common:action.scan')} onClick={() => setCamera(true)}>▦</Button>
        {found && <Button size="lg" onClick={() => { setFound(null); setCode(''); }}>{t('common:action.clear')}</Button>}
      </form>
      <ApiErrorAlert error={lookup.error} />
      <div className="flex flex-col gap-2">
        {lines.map((l) => (
          <button key={l.id} type="button" onClick={() => { setLine(l); setQty(l.my_count != null ? String(l.my_count) : ''); }}
            className={cx('flex min-h-touch items-center justify-between gap-2 rounded-xl border bg-white p-3 text-left', l.status === 'agreed' ? 'border-success' : l.status === 'needs_second' || l.status === 'recount' ? 'border-warning' : 'border-neutral-200')}>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="flex flex-wrap items-center gap-1.5 font-semibold">{name(l)}{l.is_controlled && <SafetyBadge kind="controlled" />}</span>
              <span className="text-[12px] text-neutral-500"><span className="font-mono">{l.lot_no}</span> · {date(l.expiry_date)}{l.location ? ` · ${l.location}` : ''}</span>
              {l.needs_double && <span className="text-[12px] text-pill-warning-fg">{t('counts.doubleHint')}</span>}
            </span>
            <span className="flex flex-none flex-col items-end gap-1">
              <StatusPill tone={l.status === 'agreed' ? 'success' : l.status === 'pending' ? 'neutral' : 'warning'}>{t(`counts.lineStatus.${l.status}`, { defaultValue: l.status })}</StatusPill>
              {l.my_count != null && <span className="text-[12px] text-neutral-700">{t('counts.myCount')}: <b>{l.my_count}</b></span>}
            </span>
          </button>
        ))}
      </div>
      <Button variant="primary" size="lg" onClick={() => setSubmit(true)}>{t('counts.submit')}</Button>
      <Dialog open={!!line} onClose={() => setLine(null)} title={line ? name(line) : ''} subtitle={line ? `${line.lot_no} · ${date(line.expiry_date)} · ${line.base_unit}` : undefined} width={380}
        footer={<><Button onClick={() => setLine(null)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={qty === ''} loading={entry.isPending} onClick={() => entry.mutate()}>{t('counts.save')}</Button></>}>
        <form onSubmit={(e) => { e.preventDefault(); if (qty !== '') entry.mutate(); }} className="flex flex-col gap-3">
          <Field label={`${t('counts.counted')} (${line?.base_unit ?? ''})`}>{(id) => <Input id={id} inputMode="numeric" fieldSize="lg" autoFocus className="text-right text-[20px]" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ''))} />}</Field>
          <ApiErrorAlert error={entry.error} />
        </form>
      </Dialog>
      <Sheet open={camera} onClose={() => setCamera(false)} title={t('counts.scan')}>
        {camera && <Scanner onClose={() => setCamera(false)} onCode={(c) => { setCamera(false); setCode(c); lookup.mutate(c); }} />}
      </Sheet>
      <ConfirmDialog open={submit} onClose={() => setSubmit(false)} title={t('counts.submit')} confirmLabel={t('counts.submit')}
        onConfirm={async () => { await call(api.stockcount.POST('/api/stockcount/v1/counts/{count_id}/submit', { params: { path: { count_id: count.id } } })); await qc.invalidateQueries({ queryKey: ['stockcount'] }); }} />
    </div>
  );
}

function ReviewView({ countId }: { countId: string }) {
  const { t, i18n } = useTranslation(['stock', 'common']);
  const user = useUser();
  const qc = useQueryClient();
  const toast = useToast();
  const [sel, setSel] = useState(new Set<string>());
  const [dlg, setDlg] = useState<'' | 'recount' | 'approve' | 'pin' | 'cancel'>('');
  const q = useQuery({ queryKey: ['stockcount', 'review', countId], queryFn: () => call(api.stockcount.GET('/api/stockcount/v1/counts/{count_id}/review', { params: { path: { count_id: countId } } })) });
  const key = useRequestKey(`approve-${countId}`);
  const approve = useMutation({
    mutationFn: (pin?: string) => call(api.stockcount.POST('/api/stockcount/v1/counts/{count_id}/approve', { params: { path: { count_id: countId } }, body: { pin_token: pin ?? null }, ...withKey(key) })),
    onSuccess: () => { toast.success(t('counts.approved')); void qc.invalidateQueries({ queryKey: ['stockcount'] }); },
    onError: (e) => { if (isApiError(e) && e.code === 'PIN_REQUIRED') setDlg('pin'); },
  });
  const r = q.data;
  if (!r) return q.error ? <QueryState error={q.error} /> : <SkeletonRows />;
  const showCost = r.lines.some((l) => hasField(l, 'variance_value'));
  const needsPin = r.lines.some((l) => l.is_controlled && (l.variance ?? 0) !== 0);
  const review = r.status === 'review';
  return (
    <div className="flex flex-col gap-3">
      {review && <span className="text-[12px] text-neutral-500">{t('counts.ownerNote')}</span>}
      <DataTable rows={r.lines} rowKey={(l) => l.id} minWidth={900} dense
        selection={review ? { selected: sel, onChange: setSel, actions: <Button size="sm" variant="link" onClick={() => setDlg('recount')}>{t('counts.recount')}</Button> } : undefined}
        rowClassName={(l) => ((l.variance ?? 0) !== 0 ? 'bg-[#FFFBF0]' : undefined)}
        columns={[
          { key: 'n', header: t('common:label.medicine'), cell: (l) => <span className="flex flex-wrap items-center gap-1.5">{i18n.language === 'km' && l.name_km ? l.name_km : l.name}{l.is_controlled && <SafetyBadge kind="controlled" />}</span> },
          { key: 'l', header: t('common:label.lot'), cell: (l) => <span className="font-mono text-[12px]">{l.lot_no}</span> },
          { key: 's', header: t('counts.snapshot'), align: 'right', cell: (l) => l.snapshot_qty },
          { key: 'e', header: t('counts.expected'), align: 'right', cell: (l) => l.expected_qty ?? '—' },
          { key: 'c', header: t('counts.counted'), align: 'right', cell: (l) => <b>{l.counted_qty ?? '—'}</b> },
          { key: 'v', header: t('counts.variance'), align: 'right', cell: (l) => <span className={(l.variance ?? 0) < 0 ? 'font-semibold text-pill-danger-fg' : (l.variance ?? 0) > 0 ? 'font-semibold text-pill-success-fg' : ''}>{l.variance ?? '—'}</span> },
          ...(showCost ? [{ key: 'vv', header: t('counts.varianceValue'), align: 'right' as const, cell: (l: typeof r.lines[number]) => <Usd value={l.variance_value} /> }] : []),
          { key: 'st', header: t('common:label.status'), cell: (l) => <StatusPill tone={l.status === 'agreed' ? 'success' : 'warning'}>{t(`counts.lineStatus.${l.status}`, { defaultValue: l.status })}</StatusPill> },
        ]} />
      <ApiErrorAlert error={approve.error && !(isApiError(approve.error) && approve.error.code === 'PIN_REQUIRED') ? approve.error : null} />
      {review && (
        <div className="flex flex-wrap gap-2">
          {user.has('stockcount.approve') && <Button variant="primary" loading={approve.isPending} onClick={() => (needsPin ? setDlg('pin') : setDlg('approve'))}>{t('counts.approve')}</Button>}
          <Button variant="danger-outline" onClick={() => setDlg('cancel')}>{t('counts.cancel')}</Button>
        </div>
      )}
      <ReasonDialog open={dlg === 'recount'} onClose={() => setDlg('')} title={t('counts.recount')} confirmLabel={t('counts.recount')} variant="primary"
        onConfirm={async (reason) => { await call(api.stockcount.POST('/api/stockcount/v1/counts/{count_id}/recount', { params: { path: { count_id: countId } }, body: { reason, line_ids: [...sel] } })); setSel(new Set()); await qc.invalidateQueries({ queryKey: ['stockcount'] }); }} />
      <ConfirmDialog open={dlg === 'approve'} onClose={() => setDlg('')} title={t('counts.approve')} body={t('counts.approveBody')} confirmLabel={t('counts.approve')} onConfirm={() => approve.mutateAsync(undefined)} />
      <PinDialog open={dlg === 'pin'} action="stockcount.approve" title={t('counts.approve')} context={t('counts.approveBody')} onClose={() => setDlg('')} onToken={(tk) => { setDlg(''); approve.mutate(tk.pin_token); }} />
      <ReasonDialog open={dlg === 'cancel'} onClose={() => setDlg('')} title={t('counts.cancel')} confirmLabel={t('counts.cancel')}
        onConfirm={async (reason) => { await call(api.stockcount.POST('/api/stockcount/v1/counts/{count_id}/cancel', { params: { path: { count_id: countId } }, body: { reason } })); await qc.invalidateQueries({ queryKey: ['stockcount'] }); }} />
    </div>
  );
}

export default function CountPage() {
  const { id = '' } = useParams();
  const { t } = useTranslation(['stock', 'common', 'nav', 'sales']);
  const q = useQuery({ queryKey: ['stockcount', 'count', id], queryFn: () => call(api.stockcount.GET('/api/stockcount/v1/counts/{count_id}', { params: { path: { count_id: id } } })) });
  if (q.error) return <QueryState error={q.error} onRetry={() => void q.refetch()} />;
  const c = q.data;
  if (!c) return <SkeletonRows />;
  return (
    <div className="flex flex-col gap-4 p-4 tablet:px-7 tablet:py-5">
      <PageHeader crumb={`${t('nav:group.stock')} / ${t('counts.title')}`} title={c.number}>
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <StatusPill tone={toneOf(c.status)}>{t(`sales:status.${c.status}`, { defaultValue: c.status })}</StatusPill>
          <span>{t(`counts.scopes.${c.scope}`, { defaultValue: c.scope })}{c.location ? ` · ${c.location}` : ''}</span>
        </div>
      </PageHeader>
      {c.status === 'counting' ? <CounterView count={c} /> : <ReviewView countId={c.id} />}
    </div>
  );
}
