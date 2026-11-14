// Multi-select with chips (Design System "Branches · multi-select").
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cx } from './cx';

export interface Option {
  value: string;
  label: string;
}

export function MultiSelect({ value, onChange, options, placeholder, id }: { value: string[]; onChange: (v: string[]) => void; options: Option[]; placeholder?: string; id?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);
  const byValue = new Map(options.map((o) => [o.value, o]));
  const shown = options.filter((o) => !q || o.label.toLowerCase().includes(q.toLowerCase()));
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <div ref={ref} className="relative">
      <div className="flex min-h-control flex-wrap items-center gap-1 rounded-md border border-neutral-300 bg-surface px-1.5 py-1 text-[13px] focus-within:border-primary-600 focus-within:shadow-focus">
        {value.map((v) => (
          <span key={v} className="inline-flex items-center gap-1.5 rounded-sm bg-primary-100 py-0.5 pr-1.5 pl-2 font-medium text-primary-700">
            {byValue.get(v)?.label ?? v}
            <button type="button" aria-label={`${t('action.remove')} ${byValue.get(v)?.label ?? v}`} onClick={() => toggle(v)}>×</button>
          </span>
        ))}
        <input id={id} className="min-w-[80px] flex-1 px-1 outline-none focus-visible:shadow-none" placeholder={value.length ? '' : placeholder ?? `${t('action.add')}…`} value={q}
          onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false); if (e.key === 'Backspace' && !q && value.length) onChange(value.slice(0, -1)); }} />
      </div>
      {open && shown.length > 0 && (
        <div role="listbox" aria-multiselectable className="absolute z-30 mt-1 flex max-h-60 w-full flex-col overflow-y-auto rounded-lg border border-neutral-200 bg-surface p-1 shadow-menu">
          {shown.map((o) => (
            <label key={o.value} role="option" aria-selected={value.includes(o.value)} className={cx('flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px] hover:bg-neutral-50', value.includes(o.value) && 'bg-primary-50')}>
              <input type="checkbox" className="accent-primary-600" checked={value.includes(o.value)} onChange={() => toggle(o.value)} />{o.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
