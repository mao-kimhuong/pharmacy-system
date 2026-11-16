// KHQR refunds (sales.khqr_refund: owner, branch manager). Money to give back on KHQR payments — a failed or
// cancelled sale, a return "back to the KHQR", a payment that came after the QR was cancelled, a wrong amount —
// refunded one by one with the PIN (never automatically). ABA PayWay refunds at once; Bakong has no refund API:
// the button records that it was refunded at the bank. The second tab is the daily check (00:40) of yesterday's QRs.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { SalesS } from '@/api/types';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, DataTable, PageHeader, PinDialog, StatusPill, Tabs, useToast, type PillTone } from '@/design';
import { errorText } from '@/i18n/errors';
import { dateTime, khr, usd } from '@/lib/format';

type Refund = SalesS['KhqrRefundOut'];
const TONE: Record<string, PillTone> = { due: 'warning', requested: 'info', refunded: 'success' };
const money = (amount: string, currency: string) => (currency === 'KHR' ? khr(amount) : usd(amount));

export default function KhqrRefundsPage() {
  const { t, i18n } = useTranslation(['sales', 'common', 'nav']);
  const toast = useToast();
  const qc = useQueryClient();
  const { branchParam } = useBranch();
  const [tab, setTab] = useState<'open' | 'done' | 'check'>('open');
  const [pick, setPick] = useState<Refund | null>(null);
  const list = useQuery({
    queryKey: ['sales', 'khqr-refunds', branchParam],
    queryFn: () => call(api.sales.GET('/api/sales/v1/payments/khqr/refunds', { params: { query: { branch_id: branchParam } } })),
  });
  const issues = useQuery({
    queryKey: ['sales', 'khqr-check', branchParam],
    enabled: tab === 'check',
    queryFn: () => call(api.sales.GET('/api/sales/v1/payments/khqr/reconciliation', { params: { query: { branch_id: branchParam } } })),
  });
  const refund = useMutation({
    mutationFn: ({ r, pin }: { r: Refund; pin: string }) => call(api.sales.POST('/api/sales/v1/payments/khqr/refunds/{refund_id}/refund', {
      params: { path: { refund_id: r.id } }, body: { pin_token: pin }, ...withKey(crypto.randomUUID()) })),
    onSuccess: (r) => {
      toast.success(t('khqrRefunds.done', { amount: money(r.amount, r.currency) }));
      void qc.invalidateQueries({ queryKey: ['sales', 'khqr-refunds'] });
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ['sales', 'khqr-refunds'] }),
  });
  const rows = (list.data ?? []).filter((r) => (tab === 'done' ? r.status === 'refunded' : r.status !== 'refunded'));
  const open = (list.data ?? []).filter((r) => r.status !== 'refunded').length;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('nav:item.khqr_refunds')} />
      <p className="m-0 max-w-[70ch] text-[13px] text-neutral-600">{t('khqrRefunds.intro')}</p>
      <Tabs value={tab} onChange={setTab} tabs={[
        { value: 'open', label: t('khqrRefunds.open'), count: open },
        { value: 'done', label: t('khqrRefunds.refunded') },
        { value: 'check', label: t('khqrRefunds.check') },
      ]} />
      <ApiErrorAlert error={refund.error} />
      {tab !== 'check' ? (
        <DataTable rows={rows} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(r) => r.id}
          empty={t('khqrRefunds.none')}
          columns={[
            { key: 'w', header: t('khqrRefunds.when'), cell: (r) => <span className="whitespace-nowrap tabular-nums">{dateTime(r.refunded_at ?? r.created_at)}</span> },
            { key: 'why', header: t('khqrRefunds.why'), cell: (r) => (
              <div className="flex flex-col">
                <span>{t(`khqrRefunds.source.${r.source}`)}</span>
                <span className="text-[12px] text-neutral-500">{r.reason}</span>
              </div>) },
            { key: 'a', header: t('khqrRefunds.amount'), align: 'right', cell: (r) => <span className="num font-semibold">{money(r.amount, r.currency)}</span> },
            { key: 'p', header: t('khqrRefunds.payment'), cell: (r) => (
              <span className="text-[12px] text-neutral-600">{r.payment.provider === 'payway' ? 'ABA PayWay' : r.payment.provider === 'bakong' ? 'Bakong' : t('khqrRefunds.test')}
                {r.payment.bank_ref ? ` · ${r.payment.bank_ref}` : ''}</span>) },
            { key: 's', header: t('common:label.status'), cell: (r) => (
              <div className="flex flex-col gap-0.5">
                <StatusPill tone={TONE[r.status] ?? 'neutral'}>{t(`khqrRefunds.status.${r.status}`)}{r.method === 'by_hand' ? ` · ${t('khqrRefunds.byHand')}` : ''}</StatusPill>
                {r.last_error && r.status !== 'refunded' && <span className="text-[12px] text-danger">{errorText(r.last_error, i18n.language === 'en' ? 'en' : 'km', r.last_error)}</span>}
              </div>) },
            { key: 'x', header: '', align: 'right', cell: (r) => r.status !== 'refunded' && (
              <Button size="sm" variant="primary" loading={refund.isPending && refund.variables?.r.id === r.id} onClick={() => setPick(r)}>
                {r.payment.provider === 'bakong' ? t('khqrRefunds.confirmByHand') : t('khqrRefunds.refund')}
              </Button>) },
          ]} />
      ) : (
        <DataTable rows={issues.data} loading={issues.isLoading} error={issues.error} onRetry={() => void issues.refetch()} rowKey={(r) => r.id}
          empty={t('khqrRefunds.checkNone')}
          columns={[
            { key: 'd', header: t('khqrRefunds.day'), cell: (r) => <span className="tabular-nums">{r.run_date}</span> },
            { key: 'k', header: t('khqrRefunds.issue'), cell: (r) => t(`khqrRefunds.kind.${r.kind}`) },
            { key: 'o', header: t('khqrRefunds.ours'), cell: (r) => <span className="text-[12px]">{String(r.ours.status)} · {String(r.ours.amount)} {String(r.ours.currency)}</span> },
            { key: 't', header: t('khqrRefunds.theirs'), cell: (r) => <span className="text-[12px]">{String(r.theirs.status)}{r.theirs.paid_amount ? ` · ${String(r.theirs.paid_amount)}` : ''}</span> },
          ]} />
      )}
      <PinDialog open={!!pick} action="sales.khqr_refund"
        title={pick ? `${t('khqrRefunds.refund')} · ${money(pick.amount, pick.currency)}` : ''}
        context={pick?.payment.provider === 'bakong' ? t('khqrRefunds.byHandBody') : t('khqrRefunds.pinBody')}
        onClose={() => setPick(null)}
        onToken={(pin) => { const r = pick!; setPick(null); refund.mutate({ r, pin: pin.pin_token }); }} />
    </div>
  );
}
