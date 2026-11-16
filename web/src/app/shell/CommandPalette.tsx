// Ctrl K: medicines, invoices, customers, patients (each only with its permission and when its screen exists)
// and the pages of the menu.
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { cx, useDebounced } from '@/design';
import { useUser } from '../auth';
import { useCanOpen, useNav } from './useNav';

interface Hit {
  id: string;
  section: string;
  label: string;
  meta?: string;
  to: string;
}

export function CommandPalette({ open, onClose, initial = '' }: { open: boolean; onClose: () => void; initial?: string }) {
  const { t, i18n } = useTranslation(['shell', 'nav']);
  const navTo = useNavigate();
  const user = useUser();
  const canOpen = useCanOpen();
  const groups = useNav();
  const [text, setText] = useState('');
  const [active, setActive] = useState(0);
  const q = useDebounced(text.trim(), 200);
  useEffect(() => {
    if (open) {
      setText(initial);
      setActive(0);
    }
  }, [open, initial]);

  const meds = useQuery({
    queryKey: ['palette', 'medicines', q],
    enabled: open && q.length >= 2 && user.has('products.view') && canOpen('/products'),
    queryFn: () => call(api.catalog.GET('/api/catalog/v1/medicines/search', { params: { query: { q, size: 5 } } })),
  });
  const invoices = useQuery({
    queryKey: ['palette', 'invoices', q],
    enabled: open && q.length >= 3 && /\d/.test(q) && user.has('sales.view') && canOpen('/sales/invoices'),
    queryFn: () => call(api.sales.GET('/api/sales/v1/invoices', { params: { query: { number: q, size: 5 } } })),
  });
  const customers = useQuery({
    queryKey: ['palette', 'customers', q],
    enabled: open && q.length >= 2 && user.has('contacts.customers') && canOpen('/contacts/customers'),
    queryFn: () => call(api.customers.GET('/api/customers/v1/customers', { params: { query: { q, size: 5 } } })),
  });
  const patients = useQuery({
    queryKey: ['palette', 'patients', q],
    enabled: open && q.length >= 2 && user.has('patients.view') && canOpen('/rx/patients'),
    queryFn: () => call(api.prescription.GET('/api/prescription/v1/patients', { params: { query: { q, size: 5 } } })),
  });

  const hits = useMemo<Hit[]>(() => {
    const out: Hit[] = [];
    const km = i18n.language === 'km';
    for (const m of meds.data?.items ?? [])
      out.push({ id: `m${m.id}`, section: t('palette.medicines'), label: `${m.brand_name} ${m.strength}`.trim(), meta: m.sku, to: `/products/${m.id}` });
    for (const inv of invoices.data?.items ?? [])
      out.push({ id: `i${inv.id}`, section: t('palette.invoices'), label: inv.number ?? inv.id.slice(0, 8), meta: inv.status, to: `/sales/invoices/${inv.id}` });
    for (const c of customers.data?.items ?? [])
      out.push({ id: `c${c.id}`, section: t('palette.customers'), label: km && c.name_km ? c.name_km : c.name, meta: c.phone, to: `/contacts/customers/${c.id}` });
    for (const p of patients.data?.items ?? [])
      out.push({ id: `p${p.id}`, section: t('palette.patients'), label: km && p.name_km ? p.name_km : p.name_en, meta: p.phone, to: `/rx/patients/${p.id}` });
    const needle = text.trim().toLowerCase();
    for (const g of groups) for (const it of g.items) {
      const label = `${t(`nav:group.${g.key}`)} › ${t(`nav:item.${it.key}`)}`;
      if (!needle || label.toLowerCase().includes(needle) || it.key.includes(needle))
        out.push({ id: `pg${it.path}`, section: t('palette.pages'), label, to: it.path });
    }
    return out.slice(0, 40);
  }, [meds.data, invoices.data, customers.data, patients.data, groups, text, t, i18n.language]);

  if (!open) return null;
  const go = (h: Hit) => {
    onClose();
    navTo(h.to);
  };
  let lastSection = '';
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-scrim/35 p-4 pt-[12vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={t('search')} className="w-full max-w-[560px] overflow-hidden rounded-2xl border border-neutral-200 bg-surface shadow-menu">
        <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-3.5 text-[15px]">
          <span aria-hidden>⌕</span>
          <input
            autoFocus
            role="combobox"
            aria-expanded
            aria-controls="palette-list"
            className="flex-1 outline-none"
            placeholder={t('palette.placeholder')}
            value={text}
            onChange={(e) => { setText(e.target.value); setActive(0); }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose();
              else if (e.key === 'ArrowDown') { setActive((a) => Math.min(a + 1, hits.length - 1)); e.preventDefault(); }
              else if (e.key === 'ArrowUp') { setActive((a) => Math.max(a - 1, 0)); e.preventDefault(); }
              else if (e.key === 'Enter' && hits[active]) go(hits[active]);
            }}
          />
        </div>
        <div id="palette-list" role="listbox" className="flex max-h-[50vh] flex-col overflow-y-auto p-1.5 text-[13px]">
          {hits.length === 0 && <div className="px-2.5 py-3 text-neutral-500">{t('palette.none')}</div>}
          {hits.map((h, i) => {
            const head = h.section !== lastSection;
            lastSection = h.section;
            return (
              <div key={h.id}>
                {head && <div className="px-2.5 py-1.5 text-[11px] font-semibold text-neutral-500 uppercase">{h.section}</div>}
                <div role="option" aria-selected={i === active} onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); go(h); }}
                  className={cx('flex cursor-pointer justify-between gap-3 rounded-md px-2.5 py-2', i === active && 'bg-primary-50')}>
                  <span>{h.label}</span>
                  <span className="text-neutral-500">{h.meta ?? '↵'}</span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="border-t border-neutral-100 px-4 py-2 text-[12px] text-neutral-500">{t('palette.hint')}</div>
      </div>
    </div>,
    document.body,
  );
}
