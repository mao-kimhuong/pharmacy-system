// 10e Receiving goods (phone first): a sent PO's open lines; per line one or more lots with expiry, qty and unit cost
// (cost only with purchase-price permissions; the PO's cost is used otherwise). Expired → BATCH_EXPIRED,
// short expiry flagged; more than ordered needs purchasing.over_receive.
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { useUser } from '@/app/auth';
import { useBranch } from '@/app/branch';
import { Alert, ApiErrorAlert, Button, Card, Checkbox, Field, Input, PageHeader, SafetyBadge, Select, useToast } from '@/design';
import { useRequestKey } from '../pos/hooks';
import { useMedicineNames } from '../shared/hooks';

interface Lot { key: number; po_line_id: string; lot_no: string; expiry_date: string; qty: string; unit_cost: string }

export default function ReceivingPage() {
  const { t } = useTranslation(['purchase', 'common', 'nav']);
  const user = useUser();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const { branchParam } = useBranch();
  const poId = params.get('po') ?? '';
  const [lots, setLots] = useState<Lot[]>([]);
  const [invoiceNo, setInvoiceNo] = useState('');
  const [over, setOver] = useState(false);
  const open = useQuery({
    queryKey: ['purchasing', 'pos', 'receivable', branchParam],
    queryFn: async () => {
      const [a, b] = await Promise.all(['sent', 'partially_received'].map((s) => call(api.purchasing.GET('/api/purchasing/v1/purchase-orders', { params: { query: { branch_id: branchParam, status: s as never, size: 100 } } }))));
      return [...a.items, ...b.items];
    },
  });
  const po = useQuery({ queryKey: ['purchasing', 'po', poId], enabled: !!poId, queryFn: () => call(api.purchasing.GET('/api/purchasing/v1/purchase-orders/{po_id}', { params: { path: { po_id: poId } } })) });
  const names = useMedicineNames(po.data?.lines.map((l) => l.medicine_id) ?? []);
  useEffect(() => {
    if (po.data) setLots(po.data.lines.filter((l) => l.qty_received_base < l.qty_base).map((l, i) => ({ key: i, po_line_id: l.id, lot_no: '', expiry_date: '', qty: String(Math.ceil((l.qty_base - l.qty_received_base) / l.qty_in_base)), unit_cost: l.unit_cost ?? '' })));
  }, [po.data]);
  const body = useMemo(() => ({ supplier_invoice_no: invoiceNo, allow_over: over, lines: lots.filter((l) => Number(l.qty) > 0).map((l) => ({ po_line_id: l.po_line_id, lot_no: l.lot_no, expiry_date: l.expiry_date, qty: Number(l.qty), unit_cost: l.unit_cost || null })) }), [invoiceNo, over, lots]);
  const key = useRequestKey(JSON.stringify(body) + poId);
  const m = useMutation({
    mutationFn: () => call(api.purchasing.POST('/api/purchasing/v1/purchase-orders/{po_id}/receive', { params: { path: { po_id: poId } }, body, ...withKey(key) })),
    onSuccess: (r) => { toast.success(t('receive.done', { number: r.number })); void qc.invalidateQueries({ queryKey: ['purchasing'] }); nav(`/purchase/orders/${poId}`); },
  });
  const set = (k: number, p: Partial<Lot>) => setLots(lots.map((l) => (l.key === k ? { ...l, ...p } : l)));
  const seeCost = user.has('purchasing.order', 'purchasing.pay', 'finance.cost_profit');
  const ok = body.lines.length > 0 && body.lines.every((l) => l.lot_no && l.expiry_date);
  return (
    <div className="flex flex-col gap-3 p-4 tablet:px-7 tablet:py-5">
      <PageHeader crumb={t('nav:group.purchase')} title={t('receive.title')} />
      <Field label={t('receive.pickPo')}>{(id) => (
        <Select id={id} fieldSize="lg" value={poId} onChange={(e) => setParams(e.target.value ? { po: e.target.value } : {})}>
          <option value="">—</option>{open.data?.map((p) => <option key={p.id} value={p.id}>{p.number} · {p.supplier.name}</option>)}
        </Select>
      )}</Field>
      {po.data && (
        <>
          <Field label={t('receive.invoiceNo')}>{(id) => <Input id={id} fieldSize="lg" value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} />}</Field>
          {po.data.lines.filter((l) => lots.some((x) => x.po_line_id === l.id)).map((l) => (
            <Card key={l.id} className="p-0" padded={false}>
              <div className="flex flex-col gap-2 p-3">
                <div className="flex items-start justify-between gap-2"><b>{names(l.medicine_id)}</b><span className="text-[12px] text-neutral-500">{t('receive.open')}: {l.qty_base - l.qty_received_base}</span></div>
                {lots.filter((x) => x.po_line_id === l.id).map((x) => (
                  <div key={x.key} className="grid grid-cols-2 gap-2 tablet:grid-cols-4">
                    <Field label={t('receive.lot')} required>{(id) => <Input id={id} fieldSize="lg" value={x.lot_no} onChange={(e) => set(x.key, { lot_no: e.target.value })} />}</Field>
                    <Field label={t('receive.expiry')} required>{(id) => <Input id={id} fieldSize="lg" type="date" value={x.expiry_date} onChange={(e) => set(x.key, { expiry_date: e.target.value })} />}</Field>
                    <Field label={`${t('common:label.qty')} (×${l.qty_in_base})`}>{(id) => <Input id={id} fieldSize="lg" inputMode="numeric" value={x.qty} onChange={(e) => set(x.key, { qty: e.target.value.replace(/\D/g, '') })} />}</Field>
                    {seeCost && <Field label={t('pr.unitCost')}>{(id) => <Input id={id} fieldSize="lg" inputMode="decimal" value={x.unit_cost} onChange={(e) => set(x.key, { unit_cost: e.target.value.replace(/[^\d.]/g, '') })} />}</Field>}
                  </div>
                ))}
                <Button variant="link" className="self-start" onClick={() => setLots([...lots, { key: Date.now(), po_line_id: l.id, lot_no: '', expiry_date: '', qty: '', unit_cost: l.unit_cost ?? '' }])}>{t('receive.addLot')}</Button>
              </div>
            </Card>
          ))}
          {user.has('purchasing.over_receive') && <Checkbox label={t('receive.allowOver')} checked={over} onChange={(e) => setOver(e.target.checked)} />}
          <Alert tone="info">{t('receive.noPhoto')}</Alert>
          <ApiErrorAlert error={m.error} />
          {m.data?.lines.some((l) => l.short_expiry) && <SafetyBadge kind="near-expiry">{t('receive.short')}</SafetyBadge>}
          <Button variant="primary" size="lg" disabled={!ok} loading={m.isPending} onClick={() => m.mutate()}>{t('receive.submit')}</Button>
        </>
      )}
    </div>
  );
}
