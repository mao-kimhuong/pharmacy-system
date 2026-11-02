// Lines of medicine + pack unit + quantity (templates, quotes, purchase orders, transfer requests…).
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Input, Select } from '@/design';
import { MedicinePicker, medName, type Medicine } from './MedicinePicker';

export interface EditLine {
  key: string;
  medicine: Pick<Medicine, 'id' | 'sku' | 'brand_name' | 'strength' | 'pack_units' | 'base_unit'>;
  pack_unit_id: string;
  qty: number;
  extra?: Record<string, string>;
}

let n = 0;
export function lineFrom(m: Medicine, packUnitId?: string): EditLine {
  const active = m.pack_units.filter((p) => p.is_active);
  return { key: `e${++n}`, medicine: m, pack_unit_id: packUnitId ?? (active.find((p) => p.is_base) ?? active[0]).id, qty: 1 };
}

export function LinesEditor({ lines, onChange, extraColumns = [], filter, unitLabel }: {
  lines: EditLine[];
  onChange: (l: EditLine[]) => void;
  extraColumns?: { key: string; header: ReactNode; width?: string; render: (l: EditLine, set: (v: string) => void) => ReactNode }[];
  filter?: (m: Medicine) => boolean;
  unitLabel?: string;
}) {
  const { t } = useTranslation(['common', 'pos']);
  const set = (key: string, patch: Partial<EditLine>) => onChange(lines.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto rounded-lg border border-neutral-200">
        <table className="w-full min-w-[640px] border-collapse text-table">
          <thead>
            <tr className="bg-neutral-50 text-left text-[12px] font-semibold text-neutral-700">
              <th className="px-3 py-2">{t('label.medicine')}</th>
              <th className="w-36 px-3 py-2">{unitLabel ?? t('label.unit')}</th>
              <th className="w-28 px-3 py-2 text-right">{t('label.qty')}</th>
              {extraColumns.map((c) => <th key={c.key} className="px-3 py-2" style={{ width: c.width }}>{c.header}</th>)}
              <th className="w-10" />
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.key} className="border-t border-neutral-100">
                <td className="px-3 py-2"><span className="font-medium">{medName(l.medicine)}</span> <span className="text-[12px] text-neutral-500">{l.medicine.sku}</span></td>
                <td className="px-3 py-2">
                  <Select aria-label={t('label.unit')} value={l.pack_unit_id} onChange={(e) => set(l.key, { pack_unit_id: e.target.value })}>
                    {l.medicine.pack_units.filter((p) => p.is_active || p.id === l.pack_unit_id).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.qty_in_base})</option>)}
                  </Select>
                </td>
                <td className="px-3 py-2"><Input aria-label={t('label.qty')} inputMode="numeric" className="text-right" value={l.qty || ''} onChange={(e) => set(l.key, { qty: parseInt(e.target.value.replace(/\D/g, ''), 10) || 0 })} /></td>
                {extraColumns.map((c) => <td key={c.key} className="px-3 py-2">{c.render(l, (v) => set(l.key, { extra: { ...l.extra, [c.key]: v } }))}</td>)}
                <td className="px-2 py-2 text-center"><button type="button" aria-label={t('action.remove')} className="text-neutral-500 hover:text-danger" onClick={() => onChange(lines.filter((x) => x.key !== l.key))}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <MedicinePicker value={null} clearOnPick filter={filter} placeholder={t('pos:scan')} onChange={(m) => m && onChange([...lines, lineFrom(m)])} />
    </div>
  );
}
