// Searchable select (Design System "Supplier · searchable"): type, ↑↓ to move, Enter to pick.
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { controlClass } from './Field';
import { Spinner } from './Spinner';
import { cx } from './cx';

export interface ComboboxProps<T> {
  value: T | null;
  onChange: (v: T | null) => void;
  search: (q: string) => Promise<T[]>;
  queryKey: unknown[];
  itemKey: (v: T) => string;
  itemLabel: (v: T) => string;
  renderItem?: (v: T) => ReactNode;
  placeholder?: string;
  minChars?: number;
  id?: string;
  invalid?: boolean;
  disabled?: boolean;
  size?: 'md' | 'lg';
  autoFocus?: boolean;
  clearOnPick?: boolean;
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function Combobox<T>({
  value, onChange, search, queryKey, itemKey, itemLabel, renderItem, placeholder, minChars = 1, id, invalid, disabled, size = 'md', autoFocus, clearOnPick,
}: ComboboxProps<T>) {
  const { t } = useTranslation('shell');
  const [text, setText] = useState(value ? itemLabel(value) : '');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDebounced(text.trim());
  const listId = useId();
  const listShown = open && q.length >= minChars;
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setText(value ? itemLabel(value) : '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value && itemKey(value)]);
  const res = useQuery({
    queryKey: [...queryKey, q],
    enabled: open && q.length >= minChars,
    queryFn: () => search(q),
    staleTime: 30_000,
  });
  const items = res.data ?? [];
  const pick = (v: T) => {
    onChange(v);
    setOpen(false);
    if (clearOnPick) setText('');
  };
  useEffect(() => {
    const onDoc = (e: MouseEvent) => !wrap.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);
  return (
    <div ref={wrap} className="relative">
      <div className="relative">
        <input
          id={id}
          role="combobox"
          aria-expanded={listShown}
          aria-controls={listShown ? listId : undefined}
          aria-autocomplete="list"
          autoComplete="off"
          autoFocus={autoFocus}
          disabled={disabled}
          className={cx(controlClass(invalid, size), 'pr-8')}
          placeholder={placeholder}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setActive(0);
            if (!e.target.value && value) onChange(null);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { setOpen(true); setActive((a) => Math.min(a + 1, items.length - 1)); e.preventDefault(); }
            else if (e.key === 'ArrowUp') { setActive((a) => Math.max(a - 1, 0)); e.preventDefault(); }
            else if (e.key === 'Enter' && open && items[active]) { pick(items[active]); e.preventDefault(); }
            else if (e.key === 'Escape') setOpen(false);
          }}
        />
        <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-neutral-500">{res.isFetching ? <Spinner className="size-3.5" /> : '▾'}</span>
      </div>
      {listShown && (
        <div id={listId} role="listbox" className="absolute z-30 mt-1 flex max-h-72 w-full flex-col overflow-y-auto rounded-lg border border-neutral-200 bg-white p-1 shadow-menu">
          {items.map((it, i) => (
            <div
              key={itemKey(it)}
              role="option"
              aria-selected={i === active}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); pick(it); }}
              className={cx('cursor-pointer rounded-sm px-2.5 py-2 text-[14px]', i === active && 'bg-primary-50')}
            >
              {renderItem ? renderItem(it) : itemLabel(it)}
            </div>
          ))}
          {res.isSuccess && items.length === 0 && <div className="px-2.5 py-2 text-[13px] text-neutral-500">{t('palette.none')}</div>}
          {items.length > 0 && <div className="border-t border-neutral-100 px-2.5 py-2 text-[12px] text-neutral-500">{t('palette.hint')}</div>}
        </div>
      )}
    </div>
  );
}
