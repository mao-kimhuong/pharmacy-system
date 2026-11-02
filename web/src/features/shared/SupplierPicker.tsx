import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { PurchasingS } from '@/api/types';
import { Combobox } from '@/design';

export type Supplier = PurchasingS['SupplierOut'];

export function SupplierPicker({ value, onChange, id, autoFocus }: { value: Supplier | null; onChange: (s: Supplier | null) => void; id?: string; autoFocus?: boolean }) {
  const { i18n } = useTranslation();
  return (
    <Combobox<Supplier> id={id} value={value} onChange={onChange} autoFocus={autoFocus} minChars={1} queryKey={['purchasing', 'supplier-picker']} itemKey={(s) => s.id}
      itemLabel={(s) => `${i18n.language === 'km' && s.name_km ? s.name_km : s.name} · ${s.code}`}
      search={async (q) => (await call(api.purchasing.GET('/api/purchasing/v1/suppliers', { params: { query: { q, size: 10 } } }))).items} />
  );
}
