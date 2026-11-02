// Approvals (phone tab, bell): what is waiting, from the dashboard counts, each opening its own list.
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useBellCounts } from '@/app/shell/Header';
import { EmptyState, PageHeader, SkeletonRows } from '@/design';

export default function ApprovalsPage() {
  const { t } = useTranslation(['reports']);
  const q = useBellCounts();
  const d = q.data;
  const items = d ? [
    { n: d.pending_approvals.shrinkages, label: t('dash.shrinkages'), to: '/shrinkage' },
    { n: d.pending_approvals.stock_takes, label: t('dash.stockTakes'), to: '/stock/counts' },
    { n: d.pending_approvals.transfer_requests, label: t('dash.transferRequests'), to: '/transfers/requests' },
    { n: d.pending_approvals.purchase_requests, label: t('dash.purchaseRequests'), to: '/purchase/requests' },
    { n: d.open_controlled_discrepancies, label: t('dash.discrepancies'), to: '/controlled/discrepancies' },
  ].filter((x) => x.n > 0) : [];
  return (
    <div className="flex flex-col gap-3 p-4 tablet:px-7">
      <PageHeader title={t('dash.approvals')} />
      {!d ? <SkeletonRows /> : items.length === 0 ? <EmptyState title={t('dash.nothing')} /> : items.map((x) => (
        <Link key={x.to} to={x.to} className="flex min-h-touch items-center justify-between rounded-xl border border-[#F0D48E] bg-[#FFFBF0] px-4 py-3 no-underline">
          <span className="text-neutral-900">{x.label}</span><b className="text-[18px] text-pill-warning-fg">{x.n}</b>
        </Link>
      ))}
    </div>
  );
}
