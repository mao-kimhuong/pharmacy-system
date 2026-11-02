// Medicine search (catalog medicines/search): barcode, SKU or name.
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CatalogS } from '@/api/types';
import { Combobox, SafetyBadge } from '@/design';

export type Medicine = CatalogS['SearchHit'];

export const medName = (m: { brand_name: string; strength?: string }) => [m.brand_name, m.strength].filter(Boolean).join(' ');

export function MedicinePicker({ value, onChange, id, placeholder, autoFocus, clearOnPick, invalid, filter }: {
  value: Medicine | null; onChange: (m: Medicine | null) => void; id?: string; placeholder?: string; autoFocus?: boolean; clearOnPick?: boolean; invalid?: boolean;
  filter?: (m: Medicine) => boolean;
}) {
  const { t } = useTranslation('pos');
  return (
    <Combobox<Medicine>
      id={id}
      value={value}
      onChange={onChange}
      autoFocus={autoFocus}
      clearOnPick={clearOnPick}
      invalid={invalid}
      placeholder={placeholder ?? t('scan')}
      minChars={2}
      queryKey={['catalog', 'picker']}
      itemKey={(m) => m.id}
      itemLabel={(m) => `${medName(m)} · ${m.sku}`}
      renderItem={(m) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium">{medName(m)}</span>
          <span className="text-[12px] text-neutral-500">{m.sku}</span>
          {m.is_rx_only && <SafetyBadge kind="rx" />}
          {m.controlled_schedule && <SafetyBadge kind="controlled" />}
          {m.kind === 'hamper' && <SafetyBadge kind="hamper" />}
        </span>
      )}
      search={async (q) => {
        const r = await call(api.catalog.GET('/api/catalog/v1/medicines/search', { params: { query: { q, size: 10 } } }));
        return r.items.filter((m) => m.is_active && (!filter || filter(m)));
      }}
    />
  );
}
