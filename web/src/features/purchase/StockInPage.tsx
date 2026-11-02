// 10f Quick stock-in (no PO): lines with lot, expiry, qty, unit cost; optional supplier; reason. Same expiry rules
// as receiving.
import { useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, Card, Field, Input, PageHeader, SafetyBadge, useToast } from '@/design';
import { useRequestKey } from '../pos/hooks';
import { LinesEditor, type EditLine } from '../shared/LinesEditor';
import { SupplierPicker, type Supplier } from '../shared/SupplierPicker';

export default function StockInPage() {
  const { t } = useTranslation(['purchase', 'common', 'nav']);
  const toast = useToast();
  const { oneBranch } = useBranch();
  const [lines, setLines] = useState<EditLine[]>([]);
  const [supplier, setSupplier] = useState<Supplier | null>(null);
  const [reason, setReason] = useState('');
  const body = useMemo(() => ({ branch_id: oneBranch?.id ?? '', reason, supplier_id: supplier?.id ?? null,
    lines: lines.map((l) => ({ medicine_id: l.medicine.id, pack_unit_id: l.pack_unit_id, qty: l.qty, lot_no: l.extra?.lot ?? '', expiry_date: l.extra?.expiry ?? '', unit_cost: l.extra?.cost ?? '0' })) }), [oneBranch, reason, supplier, lines]);
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({ mutationFn: () => call(api.inventory.POST('/api/inventory/v1/stock-in', { body, ...withKey(key) })), onSuccess: () => { toast.success(t('stockIn.done')); setLines([]); } });
  const ok = reason.trim() && lines.length && lines.every((l) => l.qty > 0 && l.extra?.lot && l.extra?.expiry);
  return (
    <div className="flex flex-col gap-3 p-4 tablet:px-7 tablet:py-5">
      <PageHeader crumb={t('nav:group.purchase')} title={t('stockIn.title')} />
      <Card>
        <div className="grid gap-3 tablet:grid-cols-2">
          <Field label={t('stockIn.reason')} required>{(id) => <Input id={id} fieldSize="lg" value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
          <Field label={t('common:label.supplier')}>{(id) => <SupplierPicker id={id} value={supplier} onChange={setSupplier} />}</Field>
        </div>
      </Card>
      <Card><LinesEditor lines={lines} onChange={setLines} filter={(x) => x.kind !== 'hamper'} extraColumns={[
        { key: 'lot', header: t('receive.lot'), width: '120px', render: (l, set) => <Input aria-label={t('receive.lot')} value={l.extra?.lot ?? ''} onChange={(e) => set(e.target.value)} /> },
        { key: 'expiry', header: t('receive.expiry'), width: '150px', render: (l, set) => <Input aria-label={t('receive.expiry')} type="date" value={l.extra?.expiry ?? ''} onChange={(e) => set(e.target.value)} /> },
        { key: 'cost', header: t('pr.unitCost'), width: '110px', render: (l, set) => <Input aria-label={t('pr.unitCost')} inputMode="decimal" value={l.extra?.cost ?? ''} onChange={(e) => set(e.target.value.replace(/[^\d.]/g, ''))} /> },
      ]} /></Card>
      <ApiErrorAlert error={m.error} />
      {m.data?.lines.some((l) => l.short_expiry) && <SafetyBadge kind="near-expiry">{t('receive.short')}</SafetyBadge>}
      <Button variant="primary" size="lg" disabled={!ok} loading={m.isPending} onClick={() => m.mutate()}>{t('stockIn.submit')}</Button>
    </div>
  );
}
