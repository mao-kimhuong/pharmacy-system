// The cart (3a–3o, left): one row per line with unit, qty stepper, price, discount, total from the preview; the
// line's findings below it with their actions.
import { useTranslation } from 'react-i18next';
import { SafetyBadge, cx } from '@/design';
import { date, usd } from '@/lib/format';
import type { CartLine } from './cart';
import { FindingRow, type FindingAction } from './Findings';
import type { Finding, Preview } from './hooks';

export interface LineHandlers {
  qty: (key: string, qty: number) => void;
  unit: (key: string, packUnitId: string) => void;
  select: (index: number) => void;
  actionsFor: (line: CartLine, f: Finding) => FindingAction[];
}

export function CartTable({ lines, preview, selected, h, dark }: { lines: CartLine[]; preview?: Preview; selected: number; h: LineHandlers; dark?: boolean }) {
  const { t, i18n } = useTranslation('pos');
  const grid = 'grid grid-cols-[36px_minmax(0,1fr)_108px_104px_78px_74px_92px] items-center';
  if (lines.length === 0) {
    return <div className="flex flex-1 items-center justify-center p-8 text-center text-[14px] text-neutral-500">{t('empty')}</div>;
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col" role="table" aria-label={t('title')}>
      <div role="row" className={cx(grid, 'border-b text-[12px] font-semibold', dark ? 'border-posdark-line bg-posdark-raised text-posdark-text-muted' : 'border-neutral-200 bg-neutral-50 text-neutral-700')}>
        <div role="columnheader" className="px-2.5 py-2">#</div>
        <div role="columnheader" className="px-2.5 py-2">{t('cols.medicine')}</div>
        <div role="columnheader" className="px-2.5 py-2">{t('cols.unit')}</div>
        <div role="columnheader" className="px-2.5 py-2">{t('cols.qty')}</div>
        <div role="columnheader" className="px-2.5 py-2 text-right">{t('cols.price')}</div>
        <div role="columnheader" className="px-2.5 py-2 text-right">{t('cols.disc')}</div>
        <div role="columnheader" className="px-2.5 py-2 text-right">{t('cols.total')}</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {lines.map((l, i) => {
          const p = preview?.lines.find((x) => x.line_no === i + 1);
          const top = preview ? [...preview.hard_stops, ...preview.requirements, ...preview.warnings].filter((f) => f.line_no === i + 1) : [];
          const findings = [...(p?.hard_stops ?? []), ...(p?.requirements ?? []), ...(p?.warnings ?? []), ...top].filter((f) => f.code !== 'NEAR_EXPIRY');
          const blocking = findings.some((f) => !f.resolved && (f.severity === 'hard_stop' || f.severity === 'warning'));
          const need = findings.some((f) => !f.resolved && f.severity === 'requirement');
          const disc = p ? Number(p.promo_discount) + Number(p.manual_discount) : 0;
          const name = i18n.language === 'km' && l.medicine.name_km ? l.medicine.name_km : l.medicine.name;
          const near = (p?.warnings ?? []).some((f) => f.code === 'NEAR_EXPIRY');
          return (
            <div key={l.key} role="row" aria-selected={i === selected} onClick={() => h.select(i)}
              className={cx('flex flex-col border-b border-l-[3px]', dark ? 'border-b-posdark-line' : 'border-b-neutral-100',
                blocking ? 'border-l-danger bg-[#FFF8F7]' : need ? 'border-l-safety-rx bg-[#FBFBFF]' : i === selected ? 'border-l-primary-600 bg-primary-50' : 'border-l-transparent',
                dark && !blocking && !need && i !== selected && 'bg-transparent')}>
              <div className={cx(grid, 'text-[13px]')}>
                <div role="cell" className="px-2.5 py-2.5 text-neutral-500">{i + 1}</div>
                <div role="cell" className="flex min-w-0 flex-col gap-1 px-2.5 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[14px] font-semibold">{name}</span>
                    {l.medicine.controlled && <SafetyBadge kind="controlled" />}
                    {l.medicine.is_rx_only && !l.rx && <SafetyBadge kind="rx" />}
                    {l.rx && <SafetyBadge kind="rx">{l.rx.number}</SafetyBadge>}
                    {l.medicine.is_hamper && <SafetyBadge kind="hamper" />}
                    {near && <SafetyBadge kind="near-expiry" />}
                    {p?.promotions.map((pr) => <SafetyBadge key={pr.id} kind="promotion">{i18n.language === 'km' && pr.name_km ? pr.name_km : pr.name_en} · −{usd(pr.discount)}</SafetyBadge>)}
                  </div>
                  {p && p.batches.length > 0 && (
                    <div className="flex flex-wrap gap-x-2 text-[12px] text-neutral-500">
                      {p.batches.map((b) => <span key={b.lot_no + b.expiry_date}><span className="font-mono text-[11px]">{b.lot_no}</span> · {t('line.exp', { date: date(b.expiry_date) })} · {b.qty_base}</span>)}
                      {!l.batch_id && <span className="text-primary-600">FEFO</span>}
                    </div>
                  )}
                </div>
                <div role="cell" className="px-2.5" onClick={(e) => e.stopPropagation()}>
                  <select aria-label={t('cols.unit')} value={l.pack_unit_id} onChange={(e) => h.unit(l.key, e.target.value)}
                    className="h-[30px] w-full rounded-md border border-neutral-300 bg-white px-2 text-[13px] text-neutral-900">
                    {l.medicine.pack_units.filter((u) => u.is_active || u.id === l.pack_unit_id).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                  </select>
                </div>
                <div role="cell" className="px-2.5" onClick={(e) => e.stopPropagation()}>
                  <span className={cx('flex h-[30px] items-center overflow-hidden rounded-md border bg-white text-[13px] text-neutral-900', findings.some((f) => f.code === 'OUT_OF_STOCK' || f.code === 'RX_QUANTITY_EXCEEDED') ? 'border-danger' : 'border-neutral-300')}>
                    <button type="button" aria-label="−" className="w-[26px] text-neutral-500" onClick={() => h.qty(l.key, l.qty - 1)}>−</button>
                    <input aria-label={t('cols.qty')} inputMode="numeric" value={l.qty} onChange={(e) => { const n = parseInt(e.target.value.replace(/\D/g, ''), 10); if (n > 0) h.qty(l.key, n); }}
                      className="w-full min-w-0 flex-1 text-center font-semibold outline-none focus-visible:shadow-none" />
                    <button type="button" aria-label="+" className="w-[26px] text-neutral-500" onClick={() => h.qty(l.key, l.qty + 1)}>+</button>
                  </span>
                </div>
                <div role="cell" className="num px-2.5 text-right">{p ? usd(p.unit_price) : '…'}</div>
                <div role="cell" className={cx('num px-2.5 text-right', disc > 0 ? (Number(p?.promo_discount) > 0 ? 'font-semibold text-safety-promotion' : 'font-semibold text-pill-danger-fg') : 'text-neutral-500')}>{disc > 0 ? `−${usd(disc).slice(1)}` : '—'}</div>
                <div role="cell" className="num px-2.5 text-right text-[14px] font-semibold">{p ? usd(p.net) : '…'}</div>
              </div>
              {findings.length > 0 && (
                <div className="flex flex-col gap-1 pr-2.5 pb-2 pl-[43px]">
                  {findings.map((f, j) => <FindingRow key={f.code + j} f={f} actions={f.resolved ? [] : h.actionsFor(l, f)} />)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
