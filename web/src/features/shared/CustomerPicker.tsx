import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CustomersS } from '@/api/types';
import { Combobox } from '@/design';

export type Customer = CustomersS['CustomerOut'];

export function CustomerPicker({ value, onChange, id, invalid, autoFocus }: { value: Customer | null; onChange: (c: Customer | null) => void; id?: string; invalid?: boolean; autoFocus?: boolean }) {
  const { t, i18n } = useTranslation('pos');
  return (
    <Combobox<Customer> id={id} value={value} onChange={onChange} invalid={invalid} autoFocus={autoFocus} placeholder={t('customer.search')} minChars={2}
      queryKey={['customers', 'picker']} itemKey={(c) => c.id}
      itemLabel={(c) => `${i18n.language === 'km' && c.name_km ? c.name_km : c.name} · ${c.phone}`}
      search={async (q) => (await call(api.customers.GET('/api/customers/v1/customers', { params: { query: { q, size: 10 } } }))).items} />
  );
}
