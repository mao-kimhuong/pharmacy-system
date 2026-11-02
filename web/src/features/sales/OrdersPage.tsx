// 12c Sale orders: quotes for a customer → confirm (optional FEFO reservation and deposit) → invoice → fulfilled.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, DataTable, Dialog, EmptyState, Field, Input, PageHeader, Select, StatusPill, TextArea, Usd, useToast } from '@/design';
import { date, dateTime } from '@/lib/format';
import { CustomerPicker, type Customer } from '../shared/CustomerPicker';
import { toneOf, useCustomerNames } from '../shared/hooks';
import { LinesEditor, type EditLine } from '../shared/LinesEditor';

const STATUSES = ['quote', 'ordered', 'partly_fulfilled', 'fulfilled', 'closed', 'cancelled', 'expired'];

export default function OrdersPage() {
  const { t } = useTranslation(['sales', 'common', 'nav']);
  const { oneBranch } = useBranch();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState('');
  const [open, setOpen] = useState(false);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [lines, setLines] = useState<EditLine[]>([]);
  const [valid, setValid] = useState('');
  const [note, setNote] = useState('');
  const q = useQuery({
    queryKey: ['sales', 'orders', oneBranch?.id, status],
    enabled: !!oneBranch,
    queryFn: () => call(api.sales.GET('/api/sales/v1/sale-orders', { params: { query: { branch_id: oneBranch!.id, status: status || undefined } } })),
  });
  const names = useCustomerNames(q.data?.map((o) => o.customer_id) ?? []);
  const create = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/sale-orders', { body: {
      branch_id: oneBranch!.id, customer_id: customer!.id, note: note.trim(), valid_until: valid || null,
      lines: lines.filter((l) => l.qty > 0).map((l) => ({ medicine_id: l.medicine.id, pack_unit_id: l.pack_unit_id, qty: l.qty })),
    } })),
    onSuccess: (o) => { toast.success(o.number); setOpen(false); void qc.invalidateQueries({ queryKey: ['sales', 'orders'] }); nav(`/sales/orders/${o.id}`); },
  });
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('orders.title')} actions={<Button variant="primary" onClick={() => setOpen(true)}>+ {t('orders.new')}</Button>} />
      <DataTable
        toolbar={<Field label={t('common:label.status')}>{(id) => <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t('common:label.all')}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}</Select>}</Field>}
        rows={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} rowKey={(o) => o.id} onRowClick={(o) => nav(`/sales/orders/${o.id}`)}
        empty={<EmptyState title={t('orders.empty')} action={<Button variant="primary" onClick={() => setOpen(true)}>{t('orders.new')}</Button>} />}
        columns={[
          { key: 'n', header: t('common:label.number'), cell: (o) => <span className="font-mono text-[12px]">{o.number}</span> },
          { key: 'c', header: t('invoices.customer'), cell: (o) => names(o.customer_id)?.name ?? '…' },
          { key: 'v', header: t('orders.validUntil'), cell: (o) => date(o.valid_until) },
          { key: 't', header: t('common:label.total'), align: 'right', cell: (o) => <Usd value={o.total} strong /> },
          { key: 'd', header: t('orders.deposit'), align: 'right', cell: (o) => (Number(o.deposit_usd) > 0 ? <Usd value={o.deposit_usd} /> : '—') },
          { key: 'cr', header: t('common:label.createdAt'), cell: (o) => dateTime(o.created_at) },
          { key: 's', header: t('common:label.status'), cell: (o) => <StatusPill tone={toneOf(o.status)}>{t(`status.${o.status}`, { defaultValue: o.status })}</StatusPill> },
        ]}
      />
      <Dialog open={open} onClose={() => setOpen(false)} title={t('orders.new')} width={780}
        footer={<><Button onClick={() => setOpen(false)}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!customer || lines.length === 0} loading={create.isPending} onClick={() => create.mutate()}>{t('common:action.save')}</Button></>}>
        <div className="flex flex-col gap-3">
          <div className="grid gap-3 tablet:grid-cols-2">
            <Field label={t('invoices.customer')} required hint={t('orders.customerRequired')}>{(id) => <CustomerPicker id={id} value={customer} onChange={setCustomer} autoFocus />}</Field>
            <Field label={t('orders.validUntil')}>{(id) => <Input id={id} type="date" value={valid} onChange={(e) => setValid(e.target.value)} />}</Field>
          </div>
          <LinesEditor lines={lines} onChange={setLines} />
          <Field label={t('common:label.notes')}>{(id) => <TextArea id={id} rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
          <ApiErrorAlert error={create.error} />
        </div>
      </Dialog>
    </div>
  );
}
