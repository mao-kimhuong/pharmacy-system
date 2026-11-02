// 9a Medicines: search, filters (category, Rx only, controlled, inactive), Excel export, new medicine.
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { downloadBlob } from '@/api/documents';
import { useUser } from '@/app/auth';
import { ApiErrorAlert, Button, Checkbox, DataTable, Input, PageHeader, SafetyBadge, Select, StatusPill, useDebounced } from '@/design';
import { usd } from '@/lib/format';
import { usePaging } from '../shared/hooks';

export default function ProductsPage() {
  const { t, i18n } = useTranslation(['warehouse', 'common', 'nav', 'sales']);
  const user = useUser();
  const nav = useNavigate();
  const paging = usePaging();
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [rx, setRx] = useState(false);
  const [ctl, setCtl] = useState(false);
  const [inactive, setInactive] = useState(false);
  const dq = useDebounced(q.trim());
  const cats = useQuery({ queryKey: ['catalog', 'categories'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/categories')) });
  const list = useQuery({
    queryKey: ['catalog', 'medicines', dq, cat, rx, ctl, inactive, paging.page, paging.size],
    queryFn: () => call(api.catalog.GET('/api/catalog/v1/medicines', { params: { query: { q: dq || undefined, category_id: cat || undefined, is_rx_only: rx || undefined, controlled: ctl || undefined, include_inactive: inactive, page: paging.page, size: paging.size } } })),
  });
  const exp = useMutation({
    mutationFn: async () => downloadBlob((await call(api.catalog.GET('/api/catalog/v1/medicines/export.xlsx', { params: { query: { include_inactive: inactive } }, parseAs: 'blob' }))) as unknown as Blob, 'medicines.xlsx'),
  });
  const km = i18n.language === 'km';
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.warehouse')} title={t('products.title')}
        actions={<><Button loading={exp.isPending} onClick={() => exp.mutate()}>{t('products.export')}</Button>{user.has('products.manage') && <Button variant="primary" onClick={() => nav('/products/new')}>+ {t('products.new')}</Button>}</>} />
      <ApiErrorAlert error={exp.error} />
      <DataTable
        toolbar={<>
          <Input aria-label={t('common:action.search')} placeholder={`⌕ ${t('common:action.search')}`} className="w-72" value={q} onChange={(e) => { setQ(e.target.value); paging.reset(); }} />
          <Select aria-label={t('common:label.category')} className="w-48" value={cat} onChange={(e) => { setCat(e.target.value); paging.reset(); }}><option value="">{t('common:label.category')}: {t('common:label.all')}</option>{cats.data?.map((c) => <option key={c.id} value={c.id}>{km && c.name_km ? c.name_km : c.name_en}</option>)}</Select>
          <Checkbox label={t('products.filterRx')} checked={rx} onChange={(e) => setRx(e.target.checked)} />
          <Checkbox label={t('products.filterControlled')} checked={ctl} onChange={(e) => setCtl(e.target.checked)} />
          <Checkbox label={t('products.showInactive')} checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
        </>}
        rows={list.data?.items} loading={list.isLoading} error={list.error} onRetry={() => void list.refetch()} rowKey={(m) => m.id} onRowClick={(m) => nav(`/products/${m.id}`)}
        paging={{ page: paging.page, size: paging.size, total: list.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'sku', header: t('products.sku'), cell: (m) => <span className="font-mono text-[12px]">{m.sku}</span> },
          { key: 'n', header: t('common:label.medicine'), cell: (m) => (
            <span className="flex flex-col gap-0.5">
              <span className="flex flex-wrap items-center gap-1.5 font-medium">{m.brand_name} {m.strength}{m.is_rx_only && <SafetyBadge kind="rx" />}{m.controlled_schedule && <SafetyBadge kind="controlled" />}{m.kind === 'hamper' && <SafetyBadge kind="hamper" />}</span>
              <span className="text-[12px] text-neutral-500">{m.generic_name}{m.name_km ? ` · ${m.name_km}` : ''}</span>
            </span>
          ) },
          { key: 'c', header: t('common:label.category'), cell: (m) => (m.category ? (km && m.category.name_km ? m.category.name_km : m.category.name_en) : '—') },
          { key: 'p', header: t('packs.title'), cell: (m) => <span className="text-[12px]">{m.pack_units.filter((p) => p.is_active).map((p) => `${p.name} ${usd(p.sell_price)}`).join(' · ')}</span> },
          { key: 's', header: t('common:label.status'), cell: (m) => <StatusPill tone={m.is_active ? 'success' : 'neutral'}>{m.is_active ? t('sales:status.active') : t('sales:status.inactive')}</StatusPill> },
        ]} />
    </div>
  );
}
