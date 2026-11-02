// 12a Sale templates: a regular customer's usual items. Load re-prices them into the POS.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { api, call } from '@/api/client';
import { useBranch } from '@/app/branch';
import { ApiErrorAlert, Button, Card, Dialog, EmptyState, Field, Input, PageHeader, SkeletonRows, StatusPill, useToast } from '@/design';
import { LinesEditor, type EditLine } from '../shared/LinesEditor';
import { customerRef, linesOf } from './toPos';

export default function TemplatesPage() {
  const { t } = useTranslation(['sales', 'common', 'nav']);
  const { oneBranch } = useBranch();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [lines, setLines] = useState<EditLine[]>([]);
  const q = useQuery({
    queryKey: ['sales', 'templates', oneBranch?.id],
    enabled: !!oneBranch,
    queryFn: () => call(api.sales.GET('/api/sales/v1/sale-templates', { params: { query: { branch_id: oneBranch!.id } } })),
  });
  const create = useMutation({
    mutationFn: () => call(api.sales.POST('/api/sales/v1/sale-templates', { body: { name: name.trim(), branch_id: oneBranch!.id, lines: lines.filter((l) => l.qty > 0).map((l) => ({ medicine_id: l.medicine.id, pack_unit_id: l.pack_unit_id, qty: l.qty })) } })),
    onSuccess: () => { toast.success(t('templates.saved')); setOpen(false); setName(''); setLines([]); void qc.invalidateQueries({ queryKey: ['sales', 'templates'] }); },
  });
  const load = useMutation({
    mutationFn: (id: string) => call(api.sales.POST('/api/sales/v1/sale-templates/{template_id}/load', { params: { path: { template_id: id } } })),
    onSuccess: async (r) => nav('/pos', { state: { load: { lines: linesOf(r.lines), customer: await customerRef(r.customer_id) } } }),
  });
  const deactivate = useMutation({
    mutationFn: (id: string) => call(api.sales.PATCH('/api/sales/v1/sale-templates/{template_id}', { params: { path: { template_id: id } }, body: { is_active: false } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['sales', 'templates'] }),
  });
  const rows = (q.data ?? []).filter((x) => x.is_active);
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.sales')} title={t('templates.title')} actions={<Button variant="primary" onClick={() => setOpen(true)}>+ {t('templates.new')}</Button>} />
      <ApiErrorAlert error={load.error ?? deactivate.error} />
      {q.isLoading ? <SkeletonRows /> : rows.length === 0 ? (
        <Card><EmptyState title={t('templates.empty')} body={t('templates.emptyBody')} action={<Button variant="primary" onClick={() => setOpen(true)}>{t('templates.new')}</Button>} /></Card>
      ) : (
        <div className="grid gap-3 tablet:grid-cols-2 desktop:grid-cols-3">
          {rows.map((tp) => (
            <Card key={tp.id} title={tp.name} actions={<StatusPill tone="primary">{t('templates.lines')} {tp.lines.length}</StatusPill>}>
              <div className="flex flex-col gap-3">
                {tp.note && <span className="text-[13px] text-neutral-700">{tp.note}</span>}
                <div className="flex gap-2">
                  <Button variant="primary" loading={load.isPending && load.variables === tp.id} onClick={() => load.mutate(tp.id)}>{t('templates.load')}</Button>
                  <Button onClick={() => deactivate.mutate(tp.id)}>{t('templates.deactivate')}</Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} title={t('templates.new')} width={760}
        footer={<><Button onClick={() => setOpen(false)}>{t('common:action.cancel')}</Button><Button variant="primary" loading={create.isPending} disabled={!name.trim() || lines.length === 0} onClick={() => create.mutate()}>{t('common:action.save')}</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label={t('templates.name')} required>{(id) => <Input id={id} autoFocus value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <LinesEditor lines={lines} onChange={setLines} />
          <ApiErrorAlert error={create.error} />
        </div>
      </Dialog>
    </div>
  );
}
