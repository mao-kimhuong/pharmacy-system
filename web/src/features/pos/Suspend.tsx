// 3m: suspend with a note (no stock reserved). Also the pharmacist hand-off (3e).
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { ApiErrorAlert, Button, Dialog, Field, Input } from '@/design';
import { toLinesIn, type CartState } from './cart';

export function SuspendDialog({ open, cart, branchId, onClose, onDone, defaultNote = '' }: {
  open: boolean; cart: CartState; branchId: string; onClose: () => void; onDone: (number: string) => void; defaultNote?: string;
}) {
  const { t } = useTranslation(['pos', 'common']);
  const [note, setNote] = useState(defaultNote);
  const m = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/carts/suspend', { body: {
      branch_id: branchId, customer_id: cart.customer?.id ?? null, note: note.trim(),
      lines: toLinesIn(cart.lines).map((l) => ({ ...l, batch_id: null, override_reason: null })),
    } })),
    onSuccess: (c) => { onDone(c.number); setNote(''); },
  });
  return (
    <Dialog open={open} onClose={onClose} title={t('suspend.title')} width={440}
      footer={<><Button onClick={onClose}>{t('common:action.cancel')}</Button><Button variant="primary" kbd="Enter" loading={m.isPending} onClick={() => m.mutate()}>{t('actions.suspend')}</Button></>}>
      <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <span className="text-[13px] text-neutral-700">{t('suspend.hint')}</span>
        <Field label={t('suspend.note')}>{(id) => <Input id={id} autoFocus maxLength={255} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
        <ApiErrorAlert error={m.error} />
      </form>
    </Dialog>
  );
}
