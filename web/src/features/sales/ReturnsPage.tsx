// Sale Return (menu): find the invoice by number, then the return form on its detail page (12f).
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { ApiErrorAlert, Button, Card, EmptyState, Field, Input, PageHeader } from '@/design';

export default function ReturnsPage() {
  const { t } = useTranslation(['sales', 'common', 'nav']);
  const nav = useNavigate();
  const [number, setNumber] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [none, setNone] = useState(false);
  const find = async () => {
    setBusy(true); setError(null); setNone(false);
    try {
      const r = await call(api.sales.GET('/api/sales/v1/invoices', { params: { query: { number: number.trim(), size: 1 } } }));
      if (r.items[0]) nav(`/sales/invoices/${r.items[0].id}?return=1`);
      else setNone(true);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('returns.title')} />
      <Card>
        <form className="flex max-w-[520px] flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void find(); }}>
          <span className="text-[13px] text-neutral-700">{t('returnForm.hint')}</span>
          <Field label={t('returnForm.find')}>{(id) => <Input id={id} autoFocus placeholder="PP1-INV-2026-000123" value={number} onChange={(e) => setNumber(e.target.value)} />}</Field>
          <ApiErrorAlert error={error} />
          {none && <EmptyState title={t('common:table.noMatch')} />}
          <div><Button type="submit" variant="primary" loading={busy} disabled={!number.trim()}>{t('common:action.search')}</Button></div>
        </form>
      </Card>
    </div>
  );
}
