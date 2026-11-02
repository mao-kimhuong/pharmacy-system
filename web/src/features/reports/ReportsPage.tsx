// Reports: the catalog the API allows this user (GET reports/v1/catalog), grouped; one template for every report
// (13a–13p): filters (dates, branch, report extras), totals, table typed by the API's columns, chart for
// day / branch summaries, export CSV / XLSX / PDF, "save view" per device (filters only).
import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, call } from '@/api/client';
import { downloadBlob } from '@/api/documents';
import { exportReport, getReport, type ReportColumn, type ReportQuery } from '@/api/reports';
import { useBranch } from '@/app/branch';
import { QueryState } from '@/app/RouteError';
import { isApiError } from '@/api/errors';
import { Alert, ApiErrorAlert, Button, Card, DataTable, Field, Input, PageHeader, Select, useToast } from '@/design';
import { date, dateTime, firstOfMonth, khr, pct, qty, todayIso, usd } from '@/lib/format';
import { usePaging } from '../shared/hooks';

const GROUP = (key: string) => (/^(sales|returns|payments|commission|rx)/.test(key) ? 'sales' : /^(stock|expiry|movements|shrinkage|counts|modifications|controlled)/.test(key) ? 'stock' : /^(purchases|payables|transfers)/.test(key) ? 'purchase' : /^(receivables|customers)/.test(key) ? 'customers' : 'other');

export default function ReportsPage() {
  const { t } = useTranslation(['reports', 'nav']);
  const q = useQuery({ queryKey: ['reports', 'catalog'], queryFn: () => call(api.reports.GET('/api/reports/v1/catalog')) });
  const groups = useMemo(() => {
    const m = new Map<string, { key: string; title: string }[]>();
    for (const r of q.data ?? []) m.set(GROUP(r.key), [...(m.get(GROUP(r.key)) ?? []), r]);
    return [...m.entries()];
  }, [q.data]);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.reports')} title={t('title')} />
      <div className="grid gap-3 tablet:grid-cols-2 desktop:grid-cols-3">
        {groups.map(([g, items]) => (
          <Card key={g} title={t(`groups.${g}`)}>
            <div className="flex flex-col gap-1">
              {items.map((r) => <Link key={r.key} to={`/reports/${r.key}`} className="rounded-md px-2 py-1.5 text-[14px] no-underline hover:bg-neutral-50">{t(`names.${r.key}`, { defaultValue: r.title })}</Link>)}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function cellText(v: unknown, col: ReportColumn): string {
  if (v === null || v === undefined || v === '') return '—';
  const k = col.kind;
  if (k === 'money' || k === 'usd') return usd(v as string);
  if (k === 'khr') return khr(v as number);
  if (k === 'pct' || k === 'percent') return pct(v as string);
  if (k === 'int' || k === 'qty' || k === 'number') return qty(v as number);
  if (k === 'date') return date(String(v));
  if (k === 'datetime') return dateTime(String(v));
  if (typeof v === 'boolean') return v ? '✓' : '';
  return String(v);
}
const numeric = (k: string) => ['money', 'usd', 'khr', 'pct', 'percent', 'int', 'qty', 'number'].includes(k);

export function ReportView() {
  const params = useParams();
  const key = params['*'] ?? '';
  const { t } = useTranslation(['reports', 'common', 'nav']);
  const toast = useToast();
  const { branchParam } = useBranch();
  const paging = usePaging(50);
  const saved = (() => { try { return JSON.parse(localStorage.getItem(`pharmacy.report.${key}`) ?? 'null') as Partial<ReportQuery> | null; } catch { return null; } })();
  const [from, setFrom] = useState(saved?.date_from ?? firstOfMonth(todayIso()));
  const [to, setTo] = useState(saved?.date_to ?? todayIso());
  const [by, setBy] = useState(saved?.by ?? 'day');
  const [within, setWithin] = useState(String(saved?.within ?? 90));
  const [days, setDays] = useState(String(saved?.days ?? 90));
  const query: ReportQuery = {
    date_from: from, date_to: to, branch_id: branchParam ?? null,
    ...(key === 'sales/summary' || key === 'sales/profit' ? { by } : {}),
    ...(key === 'expiry' ? { within: Number(within) || 90 } : {}),
    ...(key === 'stock/slow-moving' ? { days: Number(days) || 90 } : {}),
    page: paging.page, size: paging.size,
  };
  const q = useQuery({ queryKey: ['reports', key, query], queryFn: () => getReport(key, query) });
  const exp = useMutation({
    mutationFn: async (format: 'csv' | 'xlsx' | 'pdf') => downloadBlob(await exportReport(key, { ...query, page: undefined, size: undefined }, format), `${key.replace('/', '-')}-${from}-${to}.${format}`),
  });
  const d = q.data;
  if (isApiError(q.error) && ['FORBIDDEN', 'BRANCH_FORBIDDEN', 'NOT_FOUND'].includes(q.error.code)) return <QueryState error={q.error} />;
  const colLabel = (c: ReportColumn) => t(`col.${c.key}`, { defaultValue: c.label });
  const chart = d && (by === 'day' || by === 'branch' || by === 'month') && ['sales/summary', 'sales/profit'].includes(key) ? d.rows.map((r) => ({ k: String(r.key ?? r.day ?? r.branch ?? ''), v: Number(r.net ?? r.revenue ?? 0) })) : null;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={`${t('nav:group.reports')} / ${t('title')}`} title={t(`names.${key}`, { defaultValue: d?.title ?? key })}
        actions={<>
          <Button onClick={() => { localStorage.setItem(`pharmacy.report.${key}`, JSON.stringify({ date_from: from, date_to: to, by, within, days })); toast.success(t('savedView')); }}>{t('saveView')}</Button>
          {(['csv', 'xlsx', 'pdf'] as const).map((f) => <Button key={f} loading={exp.isPending && exp.variables === f} onClick={() => exp.mutate(f)}>{t(f)}</Button>)}
        </>}>
        <span className="text-[12px] text-neutral-500">{t('exportLimit')}</span>
      </PageHeader>
      <ApiErrorAlert error={exp.error} />
      {d?.cost_hidden && <Alert tone="info">🔒 {t('costHidden')}</Alert>}
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t('common:label.from')}>{(id) => <Input id={id} type="date" value={from} onChange={(e) => { setFrom(e.target.value); paging.reset(); }} />}</Field>
          <Field label={t('common:label.to')}>{(id) => <Input id={id} type="date" value={to} onChange={(e) => { setTo(e.target.value); paging.reset(); }} />}</Field>
          {(key === 'sales/summary' || key === 'sales/profit') && <Field label={t('by')}>{(id) => <Select id={id} value={by} onChange={(e) => setBy(e.target.value)}>{(key === 'sales/summary' ? ['day', 'branch', 'staff', 'medicine', 'category', 'payment_method'] : ['day', 'branch', 'month']).map((b) => <option key={b} value={b}>{t(`byOpt.${b}`)}</option>)}</Select>}</Field>}
          {key === 'expiry' && <Field label={t('within')}>{(id) => <Input id={id} className="w-28" inputMode="numeric" value={within} onChange={(e) => setWithin(e.target.value.replace(/\D/g, ''))} />}</Field>}
          {key === 'stock/slow-moving' && <Field label={t('days')}>{(id) => <Input id={id} className="w-28" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/\D/g, ''))} />}</Field>}
        </div>
      </Card>
      {d && Object.keys(d.summary ?? {}).length > 0 && (
        <div className="grid gap-3 tablet:grid-cols-3 desktop:grid-cols-5">
          {Object.entries(d.summary).map(([k, v]) => {
            const col = d.columns.find((c) => c.key === k) ?? { key: k, label: k, kind: typeof v === 'number' ? 'int' : /^-?\d+\.\d{2}$/.test(String(v)) ? 'money' : 'text', secret: null };
            return <Card key={k}><div className="text-[12px] text-neutral-500">{colLabel(col)}</div><div className="num text-[22px] font-semibold">{cellText(v, col)}</div></Card>;
          })}
        </div>
      )}
      {chart && chart.length > 0 && (
        <Card>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart}>
                <CartesianGrid stroke="#EEF1F0" vertical={false} />
                <XAxis dataKey="k" tick={{ fontSize: 11, fill: '#66706F' }} />
                <YAxis tick={{ fontSize: 11, fill: '#66706F' }} width={60} />
                <Tooltip formatter={(v) => usd(v as number)} />
                <Bar dataKey="v" fill="#13908A" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}
      <DataTable rows={d?.rows} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(_, i) => String(i)} dense minWidth={Math.max(720, (d?.columns.length ?? 0) * 120)}
        paging={{ page: paging.page, size: paging.size, total: d?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={(d?.columns ?? []).map((c) => ({ key: c.key, header: colLabel(c), align: numeric(c.kind) ? ('right' as const) : undefined, cell: (r: Record<string, unknown>) => cellText(r[c.key], c) }))} />
    </div>
  );
}
