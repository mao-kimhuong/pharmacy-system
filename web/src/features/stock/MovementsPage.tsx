// 18d Inventory movements: signed quantity and the batch balance after; filters by medicine, type, dates.
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useBranch } from '@/app/branch';
import { DataTable, Field, Input, PageHeader, Select } from '@/design';
import { addDays, dateTime, todayIso } from '@/lib/format';
import { MedicinePicker, type Medicine } from '../shared/MedicinePicker';
import { useMedicineNames, usePaging, useStaffNames } from '../shared/hooks';

const TYPES = ['in', 'opening', 'out', 'sale_cancel', 'return', 'adjust_in', 'adjust_out', 'shrinkage', 'count_adjust', 'transfer_out', 'transfer_in', 'supplier_return', 'destroy'];

export default function MovementsPage() {
  const { t } = useTranslation(['stock', 'common', 'nav', 'controlled']);
  const { branchParam } = useBranch();
  const paging = usePaging(50);
  const staff = useStaffNames();
  const [med, setMed] = useState<Medicine | null>(null);
  const [type, setType] = useState('');
  const [from, setFrom] = useState(addDays(todayIso(), -7));
  const [to, setTo] = useState(todayIso());
  const q = useQuery({
    queryKey: ['inventory', 'movements', branchParam, med?.id, type, from, to, paging.page, paging.size],
    queryFn: () => call(api.inventory.GET('/api/inventory/v1/movements', { params: { query: { branch_id: branchParam, medicine_id: med?.id, type: type || undefined, from, to, page: paging.page, size: paging.size } } })),
  });
  const names = useMedicineNames(q.data?.items.map((m) => m.medicine_id) ?? []);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.stock')} title={t('movements.title')} />
      <DataTable
        toolbar={<>
          <Field label={t('common:label.medicine')} className="w-72">{(id) => <MedicinePicker id={id} value={med} onChange={(m) => { setMed(m); paging.reset(); }} />}</Field>
          <Field label={t('movements.type')}>{(id) => <Select id={id} value={type} onChange={(e) => { setType(e.target.value); paging.reset(); }}><option value="">{t('common:label.all')}</option>{TYPES.map((x) => <option key={x} value={x}>{x}</option>)}</Select>}</Field>
          <Field label={t('common:label.from')}>{(id) => <Input id={id} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
          <Field label={t('common:label.to')}>{(id) => <Input id={id} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
        </>}
        rows={q.data?.items} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(m) => m.id} dense
        paging={{ page: paging.page, size: paging.size, total: q.data?.total ?? 0, onPage: paging.setPage, onSize: paging.setSize }}
        columns={[
          { key: 'w', header: t('common:label.date'), cell: (m) => dateTime(m.created_at) },
          { key: 'm', header: t('common:label.medicine'), cell: (m) => names(m.medicine_id) },
          { key: 't', header: t('movements.type'), cell: (m) => <span className="font-mono text-[12px]">{m.type}</span> },
          { key: 'q', header: t('common:label.qty'), align: 'right', cell: (m) => <span className={m.qty_base < 0 ? 'text-pill-danger-fg' : 'text-pill-success-fg'}>{m.qty_base > 0 ? `+${m.qty_base}` : m.qty_base}</span> },
          { key: 'a', header: t('movements.after'), align: 'right', cell: (m) => m.qty_after },
          { key: 'r', header: t('movements.ref'), cell: (m) => <span className="text-[12px] text-neutral-500">{m.ref_type}{m.reason ? ` · ${m.reason}` : ''}</span> },
          { key: 'b', header: t('movements.by'), cell: (m) => staff(m.created_by) },
        ]} />
    </div>
  );
}
