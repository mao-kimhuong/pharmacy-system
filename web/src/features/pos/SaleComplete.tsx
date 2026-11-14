// 3c: sale complete. The 80 mm receipt from the API next to the change to give; Enter starts the next sale.
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { renderPdf } from '@/api/documents';
import type { SalesS } from '@/api/types';
import { Button, ErrorState, SkeletonRows, usePdf } from '@/design';
import { khr, usd } from '@/lib/format';

export function SaleComplete({ invoice, onNew }: { invoice: SalesS['InvoiceOut']; onNew: () => void }) {
  const { t } = useTranslation('pos');
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const pdf = usePdf();
  useEffect(() => {
    let made: string | null = null;
    let alive = true;
    setError(null);
    renderPdf({ type: 'receipt_80mm', invoice_id: invoice.id }).then((b) => {
      if (!alive) return;
      made = URL.createObjectURL(b);
      setUrl(made);
    }, (e) => alive && setError(e));
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [invoice.id, attempt]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Enter' && !document.querySelector('[role=dialog]')) { e.preventDefault(); onNew(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onNew]);
  const changeUsd = Number(invoice.change_given_usd);
  const changeKhr = invoice.change_given_khr;
  const hasRx = invoice.lines.some((l) => l.rx_item_id);
  return (
    <div className="absolute inset-0 z-40 flex items-center justify-center gap-6 bg-scrim/45 p-6" role="dialog" aria-modal="true" aria-label={t('complete.title')}>
      <div className="flex h-full max-h-[680px] w-[340px] flex-col overflow-hidden rounded-lg bg-surface shadow-dialog">
        {error ? <ErrorState error={error} onRetry={() => setAttempt((a) => a + 1)} /> : url ? <iframe ref={frame} title="receipt" src={url} className="h-full w-full" /> : <SkeletonRows rows={8} />}
      </div>
      <div className="flex w-[360px] flex-col gap-4 rounded-2xl bg-surface p-6 shadow-dialog">
        <div className="flex items-center gap-2.5"><span className="flex size-8 items-center justify-center rounded-full bg-success text-white" aria-hidden>✓</span><b className="text-[18px]">{t('complete.title')}</b></div>
        <div className="text-[13px] text-neutral-700">{t('complete.invoice', { number: invoice.number })} · {usd(invoice.total)}{invoice.total_khr != null ? ` · ${khr(invoice.total_khr)}` : ''}</div>
        <div className="flex flex-col gap-1 rounded-lg bg-success-bg p-4">
          <span className="text-[13px] font-semibold text-pill-success-fg">{changeUsd > 0 || changeKhr > 0 ? t('complete.giveChange') : t('complete.noChange')}</span>
          <span className="num text-[34px] leading-10 font-bold text-success-fg" data-testid="sale-change">
            {[changeUsd > 0 ? usd(changeUsd) : null, changeKhr > 0 ? khr(changeKhr) : null].filter(Boolean).join(' + ') || usd(0)}
          </span>
          {Number(invoice.change_usd) > 0 && <span className="num text-[12px] text-pill-success-fg">= {usd(invoice.change_usd)}</span>}
        </div>
        <Button variant="primary" size="lg" kbd="Enter" onClick={onNew} autoFocus>{t('actions.newSale')}</Button>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!url} onClick={() => frame.current?.contentWindow?.print()}>{t('actions.reprint')}</Button>
          <Button onClick={() => pdf.open({ type: 'invoice_a4', invoice_id: invoice.id }, t('actions.a4'), `${invoice.number}.pdf`)}>{t('actions.a4')}</Button>
          {hasRx && <Button onClick={() => pdf.open({ type: 'dispensing_label', invoice_id: invoice.id }, t('actions.label'), `${invoice.number}-labels.pdf`)}>{t('actions.label')}</Button>}
        </div>
      </div>
      {pdf.element}
    </div>
  );
}
