// Dashboard (5a–5d): today vs yesterday and the same weekday last week (profit only when the API sends it), last
// 30 days, today by branch (all branches), top medicines, low stock, near expiry, top debtors, approvals waiting.
// Sales by hour has no API: not shown.
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getReport } from '@/api/reports';
import { useUser } from '@/app/auth';
import { ALL, useBranch } from '@/app/branch';
import { useBellCounts } from '@/app/shell/Header';
import { Card, ErrorState, KpiTile, PageHeader, SkeletonTiles, hasField } from '@/design';
import { addDays, date, khr, pct, todayIso, usd } from '@/lib/format';
import HomePage from '../home/HomePage';

const RAMP = ['#0E7470', '#5FB3AC', '#B7DAD6', '#13908A', '#7CC6BF'];

function delta(now: string | null | undefined, then: string | null | undefined) {
  const a = Number(now ?? 0);
  const b = Number(then ?? 0);
  if (!b) return { value: a ? '+∞' : '0%', tone: 'flat' as const };
  const d = ((a - b) / b) * 100;
  return { value: `${d > 0 ? '+' : ''}${d.toFixed(0)}%`, tone: d > 0.5 ? ('up' as const) : d < -0.5 ? ('down' as const) : ('flat' as const) };
}

function Dashboard() {
  const { t } = useTranslation(['reports', 'nav']);
  const user = useUser();
  const { branchParam, current, byId } = useBranch();
  const q = useBellCounts();
  const today = todayIso();
  const series = useQuery({ queryKey: ['reports', 'dash-30', branchParam], enabled: user.has('reports.sales'),
    queryFn: () => getReport('sales/summary', { date_from: addDays(today, -29), date_to: today, branch_id: branchParam ?? null, by: 'day', size: 100 }) });
  const byBranch = useQuery({ queryKey: ['reports', 'dash-branch'], enabled: user.has('reports.sales') && current === ALL,
    queryFn: () => getReport('sales/summary', { date_from: today, date_to: today, by: 'branch', size: 50 }) });
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data;
  const showProfit = !!d && hasField(d.today, 'gross_profit');
  const vs = (k: 'net_sales' | 'invoices' | 'average_basket' | 'gross_profit') => d ? [
    { ...delta(String(d.today[k] ?? ''), String(d.yesterday[k] ?? '')), label: t('dash.vsYesterday') },
    { ...delta(String(d.today[k] ?? ''), String(d.same_day_last_week[k] ?? '')), label: t('dash.vsLastWeek') },
  ] : [];
  const p = d?.pending_approvals;
  const pending = p ? [
    { n: p.shrinkages, label: t('dash.shrinkages'), to: '/shrinkage' }, { n: p.stock_takes, label: t('dash.stockTakes'), to: '/stock/counts' },
    { n: p.transfer_requests, label: t('dash.transferRequests'), to: '/transfers/requests' }, { n: p.purchase_requests, label: t('dash.purchaseRequests'), to: '/purchase/requests' },
    { n: d?.open_controlled_discrepancies ?? 0, label: t('dash.discrepancies'), to: '/controlled/discrepancies' },
  ].filter((x) => x.n > 0) : [];
  const line = (series.data?.rows ?? []).map((r) => ({ k: String(r.key ?? '').slice(5), v: Number(r.net ?? 0) }));
  const pie = (byBranch.data?.rows ?? []).map((r) => ({ name: String(r.key ?? ''), value: Number(r.net ?? 0) })).filter((x) => x.value > 0);
  return (
    <div className="flex flex-col gap-4 p-4 tablet:px-7 tablet:py-5">
      <PageHeader crumb={`${t('dash.today')} · ${date(today)}`} title={t('dash.title')} />
      {!d ? <SkeletonTiles count={4} /> : (
        <div className="grid gap-3 tablet:grid-cols-2 desktop:grid-cols-4">
          <KpiTile label={t('dash.netSales')} scope={current === ALL ? 'ALL' : byId(current)?.code} value={usd(d.today.net_sales)} sub={khr(d.today.net_sales_khr)} deltas={vs('net_sales')} />
          <KpiTile label={t('dash.invoices')} value={d.today.invoices} sub={`${t('dash.returns')} ${usd(d.today.returns)}`} deltas={vs('invoices')} />
          <KpiTile label={t('dash.basket')} value={usd(d.today.average_basket)} deltas={vs('average_basket')} />
          {showProfit && <KpiTile label={t('dash.profit')} value={usd(d.today.gross_profit)} sub={pct(d.today.margin_pct)} deltas={vs('gross_profit')} />}
        </div>
      )}
      <div className="grid gap-4 desktop:grid-cols-[2fr_1fr]">
        {user.has('reports.sales') && (
          <Card title={t('dash.last30')}>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={line}><CartesianGrid stroke="#EEF1F0" vertical={false} /><XAxis dataKey="k" tick={{ fontSize: 11, fill: '#66706F' }} /><YAxis tick={{ fontSize: 11, fill: '#66706F' }} width={56} />
                  <Tooltip formatter={(v) => usd(v as number)} /><Line dataKey="v" stroke="#13908A" strokeWidth={2} dot={false} /></LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        )}
        <Card title={t('dash.approvals')}>
          {pending.length === 0 ? <span className="text-neutral-500">{t('dash.nothing')}</span> : (
            <div className="flex flex-col gap-2">{pending.map((x) => <Link key={x.to} to={x.to} className="flex items-center justify-between rounded-lg border border-[#F0D48E] bg-[#FFFBF0] px-3 py-2.5 no-underline"><span className="text-neutral-900">{x.label}</span><b className="text-pill-warning-fg">{x.n}</b></Link>)}</div>
          )}
        </Card>
      </div>
      <div className="grid gap-4 tablet:grid-cols-2 desktop:grid-cols-3">
        {current === ALL && pie.length > 0 && (
          <Card title={t('dash.byBranch')}>
            <div className="flex items-center gap-4">
              <div className="size-32 flex-none"><ResponsiveContainer><PieChart><Pie data={pie} dataKey="value" innerRadius={36} outerRadius={60}>{pie.map((_, i) => <Cell key={i} fill={RAMP[i % RAMP.length]} />)}</Pie></PieChart></ResponsiveContainer></div>
              <div className="flex flex-col gap-1.5 text-[13px]">{pie.map((x, i) => <span key={x.name} className="flex items-center gap-2"><span className="size-2.5 rounded-sm" style={{ background: RAMP[i % RAMP.length] }} />{x.name}<b className="ml-auto pl-3">{usd(x.value)}</b></span>)}</div>
            </div>
          </Card>
        )}
        {d && (
          <Card title={t('dash.topMeds')}>
            <div className="h-48"><ResponsiveContainer><BarChart data={d.top_medicines.map((m) => ({ k: m.sku ?? m.name ?? '', v: Number(m.net) }))} layout="vertical"><XAxis type="number" hide /><YAxis type="category" dataKey="k" width={110} tick={{ fontSize: 11 }} /><Tooltip formatter={(v) => usd(v as number)} /><Bar dataKey="v" fill="#13908A" /></BarChart></ResponsiveContainer></div>
          </Card>
        )}
        {d && (
          <Card title={t('dash.lowStock')}>
            <div className="flex flex-col gap-1 text-[13px]">{d.low_stock.length === 0 ? <span className="text-neutral-500">—</span> : d.low_stock.slice(0, 8).map((x, i) => <span key={i} className="flex justify-between"><span>{x.name ?? x.sku}</span><b>{x.on_hand} / {x.reorder_point}</b></span>)}</div>
          </Card>
        )}
        {d && (
          <Card title={t('dash.nearExpiry', { count: d.near_expiry.count })}>
            <div className="flex flex-col gap-1 text-[13px]">{d.near_expiry.soonest.slice(0, 8).map((x, i) => <span key={i} className="flex justify-between"><span>{x.sku} · {x.lot_no}</span><b className={x.days_left < 30 ? 'text-pill-danger-fg' : 'text-pill-warning-fg'}>{x.days_left}d</b></span>)}</div>
          </Card>
        )}
        {d && d.top_debtors.length > 0 && (
          <Card title={t('dash.debtors')}>
            <div className="flex flex-col gap-1 text-[13px]">{d.top_debtors.map((x, i) => <span key={i} className="flex justify-between"><span>{x.customer}</span><b>{usd(x.owes)}</b></span>)}</div>
          </Card>
        )}
      </div>
      <span className="text-[12px] text-neutral-500">{t('dash.noHourly')}</span>
    </div>
  );
}

export default function DashboardOrHome() {
  const user = useUser();
  return user.has('dashboard.view') ? <Dashboard /> : <HomePage />;
}
