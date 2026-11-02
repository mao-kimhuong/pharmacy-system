// 9f Print labels: pack units with copies, layout (shelf 50×30, barcode 40×25, A4 sheet) → label PDF.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Card, Field, Input, PageHeader, Select, usePdf } from '@/design';
import { usd } from '@/lib/format';
import { MedicinePicker, medName } from '../shared/MedicinePicker';

type Layout = 'shelf_50x30' | 'barcode_40x25' | 'a4_sheet';
interface Item { key: number; name: string; packs: { id: string; name: string; sell_price: string; is_active: boolean }[]; pack_unit_id: string; copies: string }

export default function LabelsPage() {
  const { t } = useTranslation(['warehouse', 'common', 'nav']);
  const pdf = usePdf();
  const [layout, setLayout] = useState<Layout>('shelf_50x30');
  const [items, setItems] = useState<Item[]>([]);
  const set = (k: number, p: Partial<Item>) => setItems(items.map((i) => (i.key === k ? { ...i, ...p } : i)));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.warehouse')} title={t('labels.title')}
        actions={<Button variant="primary" disabled={!items.length} onClick={() => pdf.open({ type: 'label', layout, items: items.map((i) => ({ pack_unit_id: i.pack_unit_id, copies: Number(i.copies) || 1 })) }, t('labels.title'), `labels-${layout}.pdf`)}>{t('labels.print')}</Button>} />
      <Card>
        <div className="flex flex-col gap-3">
          <Field label={t('labels.layout')} className="w-72">{(id) => <Select id={id} value={layout} onChange={(e) => setLayout(e.target.value as Layout)}>{(['shelf_50x30', 'barcode_40x25', 'a4_sheet'] as const).map((l) => <option key={l} value={l}>{t(`labels.layouts.${l}`)}</option>)}</Select>}</Field>
          {items.map((i) => (
            <div key={i.key} className="flex flex-wrap items-end gap-2">
              <span className="min-w-60 flex-1 font-medium">{i.name}</span>
              <Field label={t('packs.name')}>{(id) => <Select id={id} value={i.pack_unit_id} onChange={(e) => set(i.key, { pack_unit_id: e.target.value })}>{i.packs.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name} · {usd(p.sell_price)}</option>)}</Select>}</Field>
              <Field label={t('labels.copies')}>{(id) => <Input id={id} className="w-20 text-right" inputMode="numeric" value={i.copies} onChange={(e) => set(i.key, { copies: e.target.value.replace(/\D/g, '') })} />}</Field>
              <Button variant="ghost" aria-label={t('common:action.remove')} onClick={() => setItems(items.filter((x) => x.key !== i.key))}>✕</Button>
            </div>
          ))}
          <MedicinePicker value={null} clearOnPick placeholder={t('labels.add')} onChange={(m) => m && setItems([...items, { key: Date.now(), name: medName(m), packs: m.pack_units, pack_unit_id: (m.pack_units.find((p) => p.is_active && !p.is_base) ?? m.pack_units[0]).id, copies: '1' }])} />
        </div>
      </Card>
      {pdf.element}
    </div>
  );
}
