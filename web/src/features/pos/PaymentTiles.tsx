// Payment method tiles: Cash · KHQR · Card / Wallet · Bank transfer · Pay later. Large (≥ 88 px), Khmer label with
// a small English one, the shortcut 1–5 on the tile (digits work when the cursor is not in a number field; Alt+1–5
// anywhere). Selected = a 2 px border AND a check mark (never colour alone). A disabled tile says why under its
// label. Neutral icons only (no bank logos without ABA's official merchant assets).
import { useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cx } from '@/design';

export type TileKey = 'cash' | 'KHQR' | 'card' | 'ABA' | 'credit';
export const TILES: TileKey[] = ['cash', 'KHQR', 'card', 'ABA', 'credit'];

export interface TileState {
  selected: boolean;
  /** why it cannot be used now (shown on the tile), or null */
  disabled: string | null;
}

const path = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' } as const;
const ICONS: Record<TileKey, ReactNode> = {
  cash: <><rect x="3" y="6.5" width="18" height="11" rx="2" {...path} /><circle cx="12" cy="12" r="2.6" {...path} /><path d="M6.5 9.5v5M17.5 9.5v5" {...path} /></>,
  KHQR: <><rect x="4" y="4" width="6" height="6" rx="1" {...path} /><rect x="14" y="4" width="6" height="6" rx="1" {...path} /><rect x="4" y="14" width="6" height="6" rx="1" {...path} /><path d="M14 14h2.5v2.5H14zM18 18h2M14 20h2M20 14v2.5" {...path} /></>,
  card: <><rect x="3" y="5.5" width="18" height="13" rx="2" {...path} /><path d="M3 10h18M7 15h4" {...path} /></>,
  ABA: <><path d="M3.5 9.5 12 4.5l8.5 5" {...path} /><path d="M5 10v7.5M9.5 10v7.5M14.5 10v7.5M19 10v7.5M3.5 19.5h17" {...path} /></>,
  credit: <><circle cx="12" cy="12" r="8" {...path} /><path d="M12 7.5V12l3 2" {...path} /></>,
};

/** The tile a key press picks: "1"–"5" outside text fields, Alt+1–5 anywhere; null for anything else. */
export function tileForKey(e: Pick<KeyboardEvent, 'key' | 'code' | 'altKey' | 'ctrlKey' | 'metaKey'>, inField: boolean): TileKey | null {
  if (e.ctrlKey || e.metaKey) return null;
  const digit = /^Digit([1-5])$/.exec(e.code)?.[1] ?? (/^[1-5]$/.test(e.key) ? e.key : null);
  if (!digit) return null;
  if (inField && !e.altKey) return null; // typing 1–5 into the cash fields stays typing
  return TILES[Number(digit) - 1];
}

function isTypingField(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (el as HTMLElement).isContentEditable;
}

export function PaymentTiles({ state, onPick, active = true }: {
  state: Record<TileKey, TileState>; onPick: (k: TileKey) => void; active?: boolean;
}) {
  const { t } = useTranslation('pos');
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector('[role="dialog"]')) return; // a dialog owns the keys
      const k = tileForKey(e, isTypingField(document.activeElement));
      if (!k || state[k].disabled) return;
      e.preventDefault();
      onPick(k);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, onPick, state]);
  return (
    <div className="grid grid-cols-5 gap-1.5" role="group" aria-label={t('tiles.label')}>
      {TILES.map((k, i) => {
        const s = state[k];
        return (
          <button key={k} type="button" data-tile={k} aria-pressed={s.selected} aria-disabled={!!s.disabled}
            aria-keyshortcuts={`${i + 1} Alt+${i + 1}`}
            onClick={() => !s.disabled && onPick(k)}
            className={cx(
              'relative flex min-h-[88px] flex-col items-center justify-center gap-0.5 rounded-lg px-1 pb-1.5 pt-2 text-center transition-colors',
              s.selected ? 'border-2 border-primary-600 bg-primary-50 text-primary-700' : 'border border-neutral-300 bg-white text-neutral-800 hover:bg-neutral-50',
              s.disabled && 'cursor-not-allowed border-dashed bg-neutral-50 text-neutral-400 hover:bg-neutral-50',
            )}>
            <span className="absolute left-1.5 top-1 font-mono text-[11px] text-neutral-500" aria-hidden>{i + 1}</span>
            {s.selected && (
              <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-primary-600 text-[10px] text-white" aria-hidden>✓</span>
            )}
            <svg viewBox="0 0 24 24" className="size-6" aria-hidden>{ICONS[k]}</svg>
            <span lang="km" className="text-[13px] font-semibold leading-tight">{t(`tiles.${k}.km`)}</span>
            <span lang="en" className="text-[11px] leading-tight text-current opacity-80">{t(`tiles.${k}.en`)}</span>
            {s.disabled && <span className="text-[10px] leading-tight text-neutral-600">{s.disabled}</span>}
          </button>
        );
      })}
    </div>
  );
}
