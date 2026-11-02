// Barcode / search box (always focused, F2). Enter on a barcode adds that pack at once; otherwise pick a hit.
import { forwardRef, useImperativeHandle, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Kbd, SafetyBadge, Spinner, cx } from '@/design';
import { usd } from '@/lib/format';
import { searchMedicines, toCartMedicine } from './hooks';
import type { CartMedicine } from './cart';
import type { CatalogS } from '@/api/types';

export interface ScanBoxHandle {
  focus: () => void;
}

export const ScanBox = forwardRef<ScanBoxHandle, { onAdd: (m: CartMedicine, packUnitId?: string) => void; dark?: boolean; onError?: (q: string) => void }>(
  function ScanBox({ onAdd, dark, onError }, ref) {
    const { t, i18n } = useTranslation('pos');
    const input = useRef<HTMLInputElement>(null);
    const [q, setQ] = useState('');
    const [hits, setHits] = useState<CatalogS['SearchHit'][] | null>(null);
    const [active, setActive] = useState(0);
    const [busy, setBusy] = useState(false);
    useImperativeHandle(ref, () => ({ focus: () => input.current?.focus() }));
    const pick = (h: CatalogS['SearchHit'], pack?: string | null) => {
      onAdd(toCartMedicine(h), pack ?? h.matched_pack_unit_id ?? undefined);
      setHits(null);
      input.current?.focus();
    };
    const search = async (text: string, enter: boolean) => {
      if (text.trim().length < 2) return setHits(null);
      setBusy(true);
      try {
        const r = await searchMedicines(text.trim());
        const barcode = r.find((h) => h.matched_pack_unit_id);
        if (enter && barcode) return pick(barcode, barcode.matched_pack_unit_id);
        if (enter && r.length === 1) return pick(r[0]);
        if (enter) setQ(text); // several or none: show the list for this text
        setHits(r);
        setActive(0);
        if (enter && r.length === 0) onError?.(text);
      } finally {
        setBusy(false);
      }
    };
    return (
      <div className="relative">
        <div className={cx('flex h-[52px] items-center gap-3 rounded-lg border-2 border-primary-600 px-3.5 shadow-focus', dark ? 'bg-posdark-raised text-posdark-text' : 'bg-white')}>
          <span className="flex h-5 items-stretch gap-px" aria-hidden>{[2, 1, 3, 1, 2, 1].map((w, i) => <span key={i} style={{ width: w }} className={dark ? 'bg-posdark-text' : 'bg-neutral-900'} />)}</span>
          <input
            ref={input}
            autoFocus
            aria-label={t('scan')}
            placeholder={t('scan')}
            className="h-full flex-1 bg-transparent text-[16px] outline-none focus-visible:shadow-none"
            value={q}
            onChange={(e) => { setQ(e.target.value); if (e.target.value.length >= 3) void search(e.target.value, false); else setHits(null); }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                if (hits && hits[active] && !/^\d{6,}$/.test(q.trim())) { setQ(''); pick(hits[active]); return; }
                // A scanner sends the next code at once: free the box now, then look this one up.
                const text = q;
                setQ('');
                setHits(null);
                void search(text, true);
              }
              else if (e.key === 'ArrowDown' && hits) { e.preventDefault(); e.stopPropagation(); setActive((a) => Math.min(a + 1, hits.length - 1)); }
              else if (e.key === 'ArrowUp' && hits) { e.preventDefault(); e.stopPropagation(); setActive((a) => Math.max(a - 1, 0)); }
              else if (e.key === 'Escape' && hits) { e.stopPropagation(); setHits(null); }
            }}
          />
          {busy ? <Spinner /> : <Kbd>F2</Kbd>}
        </div>
        {hits && (
          <div role="listbox" aria-label={t('scan')} className="absolute z-30 mt-1 flex max-h-80 w-full flex-col overflow-y-auto rounded-lg border border-neutral-200 bg-white p-1 shadow-menu">
            {hits.length === 0 && <div className="px-3 py-2.5 text-[13px] text-neutral-500">{t('noMatch', { q })}</div>}
            {hits.map((h, i) => (
              <div key={h.id} role="option" aria-selected={i === active} onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); setQ(''); pick(h); }}
                className={cx('flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-[14px]', i === active && 'bg-primary-50')}>
                <span className="flex min-w-0 flex-col">
                  <span className="flex flex-wrap items-center gap-1.5 font-medium">
                    {[h.brand_name, h.strength].filter(Boolean).join(' ')}
                    {h.is_rx_only && <SafetyBadge kind="rx" />}
                    {h.controlled_schedule && <SafetyBadge kind="controlled" />}
                    {h.kind === 'hamper' && <SafetyBadge kind="hamper" />}
                  </span>
                  <span className="text-[12px] text-neutral-500">{h.sku} · {h.generic_name}{i18n.language === 'km' && h.name_km ? ` · ${h.name_km}` : ''}</span>
                </span>
                <span className="flex flex-none flex-col items-end text-[12px] text-neutral-500">
                  {h.pack_units.filter((p) => p.is_active).slice(0, 3).map((p) => <span key={p.id} className="num">{p.name} {usd(p.sell_price)}</span>)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  },
);
