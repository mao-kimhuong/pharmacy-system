// F4 customer: search by name or phone; balance and credit left come from the API (absent without permission).
import { forwardRef, useImperativeHandle, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import type { CustomersS } from '@/api/types';
import { Combobox, Kbd, cx } from '@/design';
import { initials, usd } from '@/lib/format';
import type { CartCustomer } from './cart';

export interface CustomerBoxHandle {
  focus: () => void;
}

export const CustomerBox = forwardRef<CustomerBoxHandle, { customer: CartCustomer | null; onChange: (c: CartCustomer | null) => void; dark?: boolean }>(
  function CustomerBox({ customer, onChange, dark }, ref) {
    const { t, i18n } = useTranslation('pos');
    const [editing, setEditing] = useState(false);
    const wrap = useRef<HTMLDivElement>(null);
    useImperativeHandle(ref, () => ({ focus: () => { setEditing(true); setTimeout(() => wrap.current?.querySelector('input')?.focus(), 0); } }));
    const q = useQuery({
      queryKey: ['customers', 'customer', customer?.id],
      enabled: !!customer,
      queryFn: () => call(api.customers.GET('/api/customers/v1/customers/{customer_id}', { params: { path: { customer_id: customer!.id } } })),
    });
    const c = q.data;
    return (
      <div ref={wrap} className={cx('flex flex-col gap-2 border-b px-4 py-3.5', dark ? 'border-posdark-line' : 'border-neutral-100')}>
        <div className="flex items-center justify-between text-[12px] font-semibold text-neutral-500 uppercase"><span>{t('customer.label')}</span><Kbd>F4</Kbd></div>
        {editing || !customer ? (
          editing ? (
            <Combobox<CustomersS['CustomerOut']>
              value={null}
              autoFocus
              placeholder={t('customer.search')}
              onChange={(v) => { if (v) onChange({ id: v.id, name: i18n.language === 'km' && v.name_km ? v.name_km : v.name, phone: v.phone }); setEditing(false); }}
              queryKey={['customers', 'search']}
              itemKey={(v) => v.id}
              itemLabel={(v) => `${v.name} · ${v.phone}`}
              search={async (s) => (await call(api.customers.GET('/api/customers/v1/customers', { params: { query: { q: s, size: 8 } } }))).items}
            />
          ) : (
            <button type="button" onClick={() => setEditing(true)} className="flex items-center gap-2.5 text-left">
              <span className="flex size-9 items-center justify-center rounded-full bg-neutral-100 text-[13px] font-semibold text-neutral-700">—</span>
              <span className="text-[14px] text-neutral-700">{t('customer.walkIn')}</span>
            </button>
          )
        ) : (
          <div className="flex items-center gap-2.5">
            <span className="flex size-9 items-center justify-center rounded-full bg-neutral-100 text-[13px] font-semibold text-neutral-700">{initials(customer.name)}</span>
            <div className="flex min-w-0 flex-1 flex-col">
              <b className="truncate text-[14px]">{customer.name}</b>
              <span className="text-[12px] text-neutral-500">
                {customer.phone}
                {c?.balance !== undefined && c.balance !== null && ` · ${t('customer.balance', { amount: usd(c.balance) })}`}
                {c?.available_credit !== undefined && c.available_credit !== null && ` · ${t('customer.available', { amount: usd(c.available_credit) })}`}
              </span>
            </div>
            <button type="button" aria-label={t('customer.remove')} className="text-neutral-500" onClick={() => onChange(null)}>✕</button>
          </div>
        )}
      </div>
    );
  },
);
