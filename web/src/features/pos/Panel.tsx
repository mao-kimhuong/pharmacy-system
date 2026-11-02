// Right panel: totals (USD + KHR from the preview), actions (summary mode) or tender (payment mode).
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Kbd, Segmented, cx } from '@/design';
import { khr, usd } from '@/lib/format';
import { quickKhr, quickUsd, rielIsValid, type ChangeIn, type PaymentIn, type Tender } from './cart';
import { FindingRow, type FindingAction } from './Findings';
import type { Finding, Preview } from './hooks';

export function Totals({ preview, dark }: { preview?: Preview; dark?: boolean }) {
  const { t } = useTranslation('pos');
  const promo = preview ? preview.lines.reduce((a, l) => a + Number(l.promo_discount), 0) : 0;
  const manual = preview ? preview.lines.reduce((a, l) => a + Number(l.manual_discount), 0) : 0;
  return (
    <div className={cx('flex flex-col gap-1.5 border-b px-4 py-3.5 text-[14px]', dark ? 'border-posdark-line' : 'border-neutral-100')}>
      <div className="flex justify-between text-neutral-700"><span>{t('totals.subtotal')}</span><span className="num">{usd(preview?.subtotal ?? 0)}</span></div>
      {promo > 0 && <div className="flex justify-between text-safety-promotion"><span>{t('totals.promo')}</span><span className="num">−{usd(promo).slice(1)}</span></div>}
      {manual > 0 && <div className="flex justify-between text-pill-danger-fg"><span>{t('totals.discount')}</span><span className="num">−{usd(manual).slice(1)}</span></div>}
      <div className="mt-1.5 flex items-baseline justify-between">
        <span className="text-[16px] font-semibold">{t('totals.total')}</span>
        <span className="num text-[52px] leading-[60px] font-bold tracking-tight" data-testid="pos-total">{usd(preview?.total ?? 0)}</span>
      </div>
      <div className={cx('num text-right text-[22px] font-semibold', dark ? 'text-posdark-accent-soft' : 'text-primary-700')} data-testid="pos-total-khr">{preview?.total_khr != null ? khr(preview.total_khr) : '—'}</div>
    </div>
  );
}

export function CartFindings({ findings, actionsFor }: { findings: Finding[]; actionsFor: (f: Finding) => FindingAction[] }) {
  if (findings.length === 0) return null;
  return <div className="flex flex-col gap-1">{findings.map((f, i) => <FindingRow key={f.code + i} f={f} actions={f.resolved ? [] : actionsFor(f)} />)}</div>;
}

export function SummaryActions({ onDiscount, onSuspend, onCredit, onKhqr, onPay, onCancel, canPay, canSuspend, blockMsg, extra }: {
  onDiscount: () => void; onSuspend: () => void; onCredit: () => void; onKhqr: () => void; onPay: () => void; onCancel: () => void;
  canPay: boolean; canSuspend: boolean; blockMsg?: ReactNode; extra?: ReactNode;
}) {
  const { t } = useTranslation('pos');
  return (
    <div className="flex flex-1 flex-col gap-2 px-4 py-3.5">
      {extra}
      <div className="grid grid-cols-2 gap-2">
        <Button size="lg" className="text-[14px] font-medium" kbd="F6" onClick={onDiscount}>{t('actions.discount')}</Button>
        <Button size="lg" className="text-[14px] font-medium" kbd="F8" onClick={onSuspend} disabled={!canSuspend}>{t('actions.suspend')}</Button>
        <Button size="lg" className="text-[14px] font-medium" onClick={onCredit} disabled={!canPay}>{t('actions.credit')}</Button>
        <Button size="lg" className="text-[14px] font-medium" onClick={onKhqr} disabled={!canPay}>{t('actions.khqr')}</Button>
      </div>
      {blockMsg && <div className="rounded-md bg-danger-bg px-3 py-2 text-[13px] font-medium text-[#7A1610]" role="alert">{blockMsg}</div>}
      <Button variant="primary" size="lg" className="mt-auto h-14 text-[17px]" kbd="F9" disabled={!canPay} onClick={onPay}>{t('actions.pay')}</Button>
      <Button variant="danger-outline" size="lg" kbd="Esc" onClick={onCancel}>{t('actions.cancel')}</Button>
    </div>
  );
}

const METHODS: PaymentIn['method'][] = ['cash', 'card', 'ABA', 'KHQR', 'credit'];

export function PaymentView({ preview, tender, setTender, changeIn, setChangeIn, rate, onMethod, onComplete, onBack, completing, canComplete, error }: {
  preview?: Preview; tender: Tender; setTender: (t: Tender) => void; changeIn: ChangeIn; setChangeIn: (c: ChangeIn) => void; rate: number | null;
  onMethod: (m: PaymentIn['method']) => void; onComplete: () => void; onBack: () => void; completing: boolean; canComplete: boolean; error?: ReactNode;
}) {
  const { t } = useTranslation('pos');
  const total = Number(preview?.total ?? 0);
  const pay = preview?.payment;
  const due = Math.max(0, total - Number(pay?.paid ?? 0) - Number(pay?.credit ?? 0));
  const khrOk = rielIsValid(tender.cashKhr);
  return (
    <div className="flex flex-1 flex-col gap-2.5 px-4 py-3.5">
      <div className="grid grid-cols-5 gap-1.5" role="group" aria-label={t('pay.lines')}>
        {METHODS.map((m) => (
          <button key={m} type="button" onClick={() => onMethod(m)}
            className={cx('h-9 rounded-md border text-[13px]', m === 'cash' ? 'border-primary-600 bg-primary-50 font-semibold text-primary-700' : 'border-neutral-300 bg-white')}>
            {t(`pay.method.${m}`)}
          </button>
        ))}
      </div>
      {tender.others.length > 0 && (
        <div className="flex flex-col gap-1 text-[13px]">
          {tender.others.map((p, i) => (
            <div key={i} className="flex items-center justify-between rounded-md bg-neutral-50 px-2.5 py-1.5">
              <span>{t(`pay.method.${p.method}`)}</span>
              <span className="flex items-center gap-2"><span className="num font-semibold">{p.currency === 'KHR' ? khr(p.amount) : usd(p.amount)}</span>
                <button type="button" aria-label={t('actions.remove')} className="text-neutral-500" onClick={() => setTender({ ...tender, others: tender.others.filter((_, j) => j !== i) })}>✕</button></span>
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-semibold text-neutral-700">{t('pay.tendered')}</span>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex h-11 items-center overflow-hidden rounded-md border border-neutral-300 bg-white text-[18px] focus-within:border-2 focus-within:border-primary-600 focus-within:shadow-focus">
            <span className="px-2.5 text-[14px] text-neutral-500">$</span>
            <input aria-label={t('pay.usd')} inputMode="decimal" className="num w-full min-w-0 pr-2.5 text-right font-semibold outline-none focus-visible:shadow-none" value={tender.cashUsd}
              onChange={(e) => setTender({ ...tender, cashUsd: e.target.value.replace(/[^\d.]/g, '') })} autoFocus />
          </label>
          <label className={cx('flex h-11 items-center overflow-hidden rounded-md border bg-white text-[18px] focus-within:border-2 focus-within:border-primary-600 focus-within:shadow-focus', khrOk ? 'border-neutral-300' : 'border-danger')}>
            <span className="px-2.5 text-[14px] text-neutral-500">៛</span>
            <input aria-label={t('pay.khr')} inputMode="numeric" disabled={!rate} className="num w-full min-w-0 pr-2.5 text-right font-semibold outline-none focus-visible:shadow-none" value={tender.cashKhr}
              onChange={(e) => setTender({ ...tender, cashKhr: e.target.value.replace(/\D/g, '') })}
              onBlur={() => { const n = Number(tender.cashKhr); if (n > 0 && n % 100) setTender({ ...tender, cashKhr: String(Math.round(n / 100) * 100) }); }} />
          </label>
        </div>
        {!khrOk && <span className="text-[12px] text-danger">{t('pay.riel100')}</span>}
        <div className="flex flex-wrap gap-1.5">
          {quickUsd(due).map((v) => <button key={`u${v}`} type="button" onClick={() => setTender({ ...tender, cashUsd: v.toFixed(2), cashKhr: '' })} className="num rounded-sm border border-neutral-200 bg-neutral-50 px-2 py-1 text-[12px]">{usd(v)}</button>)}
          {rate ? quickKhr(due, rate).map((v) => <button key={`k${v}`} type="button" onClick={() => setTender({ ...tender, cashKhr: String(v), cashUsd: '' })} className="num rounded-sm border border-neutral-200 bg-neutral-50 px-2 py-1 text-[12px]">{khr(v)}</button>) : null}
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 text-[12px] text-neutral-700">
        <span>{t('pay.changeIn')}</span>
        <Segmented size="sm" value={changeIn} onChange={setChangeIn} options={[{ value: 'USD_KHR', label: t('pay.changeUsdKhr') }, { value: 'USD', label: 'USD' }, { value: 'KHR', label: 'KHR' }]} />
      </div>
      {pay && (
        <div className={cx('flex flex-col gap-0.5 rounded-lg border px-3 py-2.5', due > 0.004 ? 'border-[#F0D48E] bg-warning-bg' : 'border-[#BFE2CC] bg-success-bg')} aria-live="polite">
          {due > 0.004 ? (
            <div className="flex items-baseline justify-between"><span className="text-[13px] font-semibold text-[#7A4F00]">{t('pay.due')}</span><span className="num text-[22px] font-bold text-[#5C3B00]">{usd(due)}</span></div>
          ) : (
            <>
              <div className="flex items-baseline justify-between">
                <span className="text-[13px] font-semibold text-pill-success-fg">{t('pay.change')}</span>
                <span className="num text-[26px] font-bold text-[#164E2E]" data-testid="pos-change">
                  {[Number(pay.change_given_usd) > 0 ? usd(pay.change_given_usd) : null, pay.change_given_khr > 0 ? khr(pay.change_given_khr) : null].filter(Boolean).join(' + ') || usd(0)}
                </span>
              </div>
              <div className="flex justify-between text-[12px] text-pill-success-fg"><span>{Number(pay.credit) > 0 ? `${t('pay.credit')} ${usd(pay.credit)}` : ''}</span><span className="num">= {usd(pay.change_usd)}</span></div>
            </>
          )}
        </div>
      )}
      {error}
      <Button variant="primary" size="lg" className="mt-auto h-[52px]" kbd="Enter" disabled={!canComplete || !khrOk} loading={completing} onClick={onComplete}>{t('actions.complete')}</Button>
      <Button size="lg" kbd="Esc" onClick={onBack}>{t('actions.back')}</Button>
    </div>
  );
}

export function KeyHints({ dark }: { dark?: boolean }) {
  const { t } = useTranslation('pos');
  const keys: [string, string][] = [['F2', 'search'], ['F4', 'customer'], ['F6', 'discount'], ['F7', 'rx'], ['F8', 'suspend'], ['F9', 'pay'], ['Esc', 'cancel']];
  return (
    <div className={cx('flex h-10 flex-none items-center gap-4 overflow-hidden text-[12px]', dark ? 'text-posdark-text-muted' : 'text-neutral-700')}>
      {keys.map(([k, l]) => <span key={k} className="flex items-center gap-1.5 whitespace-nowrap"><Kbd>{k}</Kbd>{t(`keys.${l}`)}</span>)}
    </div>
  );
}
