// 12f Sale return: per line up to sold − returned (in the line's pack unit), opened packs only where the branch
// allows them (OPENED_PACK_RETURN), back to stock or quarantine, cash or credit note (credit sales: credit note).
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import type { SalesS } from '@/api/types';
import { ApiErrorAlert, Button, Checkbox, Dialog, Field, Input, Radio, TextArea, useToast } from '@/design';
import { useRequestKey } from '../pos/hooks';

export function ReturnDialog({ invoice, open, onClose }: { invoice: SalesS['InvoiceOut']; open: boolean; onClose: () => void }) {
  const { t } = useTranslation(['sales', 'common']);
  const toast = useToast();
  const qc = useQueryClient();
  const [qty, setQty] = useState<Record<string, string>>({});
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const [refund, setRefund] = useState<'cash' | 'credit_note'>(Number(invoice.credit_amount) > 0 ? 'credit_note' : 'cash');
  const [to, setTo] = useState<'stock' | 'quarantine'>('stock');
  const [reason, setReason] = useState('');
  useEffect(() => { if (open) { setQty({}); setOpened({}); setReason(''); } }, [open]);
  const body = useMemo<SalesS['ReturnCreate']>(() => ({
    lines: invoice.lines.filter((l) => Number(qty[l.id]) > 0).map((l) => ({ invoice_line_id: l.id, qty: Number(qty[l.id]), opened: !!opened[l.id] })),
    refund_method: refund, to, reason: reason.trim(),
  }), [invoice.lines, qty, opened, refund, to, reason]);
  const key = useRequestKey(JSON.stringify(body));
  const m = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/invoices/{invoice_id}/returns', { params: { path: { invoice_id: invoice.id } }, body, ...withKey(key) })),
    onSuccess: (r) => {
      toast.success(t('returnForm.done', { number: r.number ?? '' }));
      void qc.invalidateQueries({ queryKey: ['sales', 'invoice', invoice.id] });
      void qc.invalidateQueries({ queryKey: ['sales', 'returns', invoice.id] });
      onClose();
    },
  });
  const ok = body.lines.length > 0 && body.reason.length > 0;
  return (
    <Dialog open={open} onClose={onClose} title={`${t('returnForm.title')} · ${invoice.number}`} width={720}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" disabled={!ok} loading={m.isPending} onClick={() => m.mutate()}>{t('returnForm.submit')}</Button></>}>
      <div className="flex flex-col gap-4">
        <table className="w-full border-collapse text-table">
          <thead><tr className="bg-neutral-50 text-left text-[12px] text-neutral-700">
            <th className="px-2 py-2">{t('common:label.medicine')}</th><th className="px-2 py-2 text-right">{t('returnForm.sold')}</th>
            <th className="px-2 py-2 text-right">{t('returnForm.left')}</th><th className="w-28 px-2 py-2">{t('returnForm.qty')}</th><th className="px-2 py-2">{t('returnForm.opened')}</th>
          </tr></thead>
          <tbody>
            {invoice.lines.map((l) => {
              const left = Math.floor((l.qty_base - l.returned_qty_base) / l.qty_in_base);
              return (
                <tr key={l.id} className="border-t border-neutral-100">
                  <td className="px-2 py-2">{l.name} <span className="text-neutral-500">· {l.pack_unit}</span></td>
                  <td className="num px-2 py-2 text-right">{l.qty}</td>
                  <td className="num px-2 py-2 text-right">{left}</td>
                  <td className="px-2 py-2"><Input aria-label={`${t('returnForm.qty')} ${l.name}`} inputMode="numeric" disabled={left <= 0} className="text-right" value={qty[l.id] ?? ''}
                    onChange={(e) => setQty({ ...qty, [l.id]: String(Math.min(left, parseInt(e.target.value.replace(/\D/g, ''), 10) || 0) || '') })} /></td>
                  <td className="px-2 py-2"><Checkbox aria-label={t('returnForm.opened')} checked={!!opened[l.id]} onChange={(e) => setOpened({ ...opened, [l.id]: e.target.checked })} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="grid gap-4 tablet:grid-cols-2">
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0"><legend className="mb-1 text-[13px] font-medium">{t('returnForm.refund')}</legend>
            <Radio name="refund" label={t('returnForm.cash')} checked={refund === 'cash'} onChange={() => setRefund('cash')} disabled={Number(invoice.credit_amount) > 0} />
            <Radio name="refund" label={t('returnForm.creditNote')} checked={refund === 'credit_note'} onChange={() => setRefund('credit_note')} disabled={!invoice.customer_id} />
          </fieldset>
          <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0"><legend className="mb-1 text-[13px] font-medium">{t('returnForm.to')}</legend>
            <Radio name="to" label={t('returnForm.stock')} checked={to === 'stock'} onChange={() => setTo('stock')} />
            <Radio name="to" label={t('returnForm.quarantine')} checked={to === 'quarantine'} onChange={() => setTo('quarantine')} />
          </fieldset>
        </div>
        <Field label={t('returnForm.reason')} required>{(id) => <TextArea id={id} rows={2} maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} />}</Field>
        <ApiErrorAlert error={m.error} />
      </div>
    </Dialog>
  );
}
