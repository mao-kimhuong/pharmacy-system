// 9g / 18e Initialize opening stock: branch locks, template, upload (validated), lines with errors / short
// expiry (cost only when sent), commit → branch locked; owner unlocks with a reason.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { downloadBlob } from '@/api/documents';
import { useUser } from '@/app/auth';
import { branchName, useBranch } from '@/app/branch';
import { ApiErrorAlert, BranchTag, Button, Card, ConfirmDialog, DataTable, PageHeader, ReasonDialog, SafetyBadge, StatusPill, UploadBox, Usd, hasField } from '@/design';
import { date, dateTime } from '@/lib/format';
import { useRequestKey } from '../pos/hooks';
import { fileBody } from './upload';

export default function InitializePage() {
  const { t, i18n } = useTranslation(['warehouse', 'common', 'nav']);
  const user = useUser();
  const qc = useQueryClient();
  const { oneBranch, byId } = useBranch();
  const [id, setId] = useState<string | null>(null);
  const [commitOpen, setCommitOpen] = useState(false);
  const [unlock, setUnlock] = useState<string | null>(null);
  const locks = useQuery({ queryKey: ['inventory', 'locks'], queryFn: () => call(api.inventory.GET('/api/inventory/v1/initialize-locks')) });
  const uploads = useQuery({ queryKey: ['inventory', 'openings'], queryFn: () => call(api.inventory.GET('/api/inventory/v1/opening-balances', { params: { query: { size: 20 } } })) });
  const detail = useQuery({ queryKey: ['inventory', 'opening', id], enabled: !!id, queryFn: () => call(api.inventory.GET('/api/inventory/v1/opening-balances/{opening_id}', { params: { path: { opening_id: id! } } })) });
  const template = useMutation({ mutationFn: async () => downloadBlob((await call(api.inventory.GET('/api/inventory/v1/opening-balances/template.xlsx', { parseAs: 'blob' }))) as unknown as Blob, 'opening-stock-template.xlsx') });
  const upload = useMutation({
    mutationFn: (f: File) => call(api.inventory.POST('/api/inventory/v1/opening-balances/upload', fileBody(f, { branch_id: oneBranch!.id }))),
    onSuccess: (o) => { setId(o.id); void qc.invalidateQueries({ queryKey: ['inventory', 'openings'] }); },
  });
  const key = useRequestKey(`opening-${id}`);
  const d = detail.data;
  const refresh = () => qc.invalidateQueries({ queryKey: ['inventory'] });
  const showCost = !!d?.lines.some((l) => hasField(l, 'cost_per_base'));
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.settings')} title={t('init.title')} actions={<Button loading={template.isPending} onClick={() => template.mutate()}>{t('init.template')}</Button>} />
      <Card title={t('init.locks')} padded={false}>
        <DataTable className="rounded-none border-0" rows={locks.data} loading={locks.isLoading} error={locks.error} rowKey={(l) => l.branch_id} columns={[
          { key: 'b', header: t('common:label.branch'), cell: (l) => <span className="flex items-center gap-1.5"><BranchTag code={byId(l.branch_id)?.code ?? '?'} />{branchName(byId(l.branch_id), i18n.language)}</span> },
          { key: 's', header: t('common:label.status'), cell: (l) => <StatusPill tone={l.locked ? 'warning' : 'success'}>{l.locked ? t('init.locked') : t('init.open')}</StatusPill> },
          { key: 'w', header: t('common:label.date'), cell: (l) => dateTime(l.locked ? l.locked_at : l.unlocked_at) },
          { key: 'r', header: t('common:label.reason'), cell: (l) => l.unlock_reason ?? '—' },
          { key: 'a', header: '', align: 'right', cell: (l) => l.locked && user.isOwner && <Button size="sm" onClick={() => setUnlock(l.branch_id)}>{t('init.unlock')}</Button> },
        ]} />
      </Card>
      <Card><UploadBox accept=".xlsx" busy={upload.isPending} label={`${t('init.upload')} · ${oneBranch?.code ?? ''}`} onFile={(f) => upload.mutate(f)} /></Card>
      <ApiErrorAlert error={upload.error ?? template.error} />
      {d && (
        <Card title={d.file_name || d.source} actions={<StatusPill tone={d.status === 'committed' ? 'success' : d.status === 'has_errors' ? 'danger' : 'primary'}>{t(`init.status.${d.status}`)}</StatusPill>}>
          <div className="flex flex-col gap-3">
            <span className="text-[13px]">{t('init.lines')}: <b>{d.total_lines}</b> · {t('init.errors')}: <b className={d.error_lines ? 'text-danger' : ''}>{d.error_lines}</b></span>
            <DataTable rows={d.lines} rowKey={(l) => String(l.line_no)} dense columns={[
              { key: 'n', header: '#', cell: (l) => l.line_no },
              { key: 'm', header: 'SKU', cell: (l) => String((l.data as Record<string, unknown>).sku ?? '—') },
              { key: 'l', header: t('common:label.lot'), cell: (l) => l.lot_no },
              { key: 'e', header: t('common:label.expiry'), cell: (l) => <span className="flex items-center gap-1">{date(l.expiry_date)}{l.short_expiry && <SafetyBadge kind="near-expiry">{t('init.short')}</SafetyBadge>}</span> },
              { key: 'q', header: t('common:label.qty'), align: 'right', cell: (l) => l.qty ?? '—' },
              ...(showCost ? [{ key: 'c', header: t('common:label.cost'), align: 'right' as const, cell: (l: typeof d.lines[number]) => <Usd value={l.unit_cost} /> }] : []),
              { key: 'x', header: t('import.problems'), cell: (l) => <span className="text-[12px] text-danger">{(l.errors as { message?: string; field?: string }[]).map((e) => `${e.field ?? ''} ${e.message ?? ''}`.trim()).join('; ') || '—'}</span> },
            ]} />
            {d.status === 'validated' && <Button variant="primary" className="self-end" onClick={() => setCommitOpen(true)}>{t('init.commit')}</Button>}
          </div>
        </Card>
      )}
      <Card title={t('init.history')} padded={false}>
        <DataTable className="rounded-none border-0" rows={uploads.data?.items} loading={uploads.isLoading} error={uploads.error} rowKey={(o) => o.id} onRowClick={(o) => setId(o.id)} columns={[
          { key: 'b', header: t('common:label.branch'), cell: (o) => <BranchTag code={byId(o.branch_id)?.code ?? '?'} /> },
          { key: 'f', header: t('common:label.file'), cell: (o) => o.file_name || o.source },
          { key: 'd', header: t('common:label.date'), cell: (o) => dateTime(o.created_at) },
          { key: 's', header: t('common:label.status'), cell: (o) => t(`init.status.${o.status}`) },
        ]} />
      </Card>
      <ConfirmDialog open={commitOpen} onClose={() => setCommitOpen(false)} title={t('init.commit')} body={t('init.commitBody')} confirmLabel={t('init.commit')}
        onConfirm={async () => { await call(api.inventory.POST('/api/inventory/v1/opening-balances/{opening_id}/commit', { params: { path: { opening_id: id! } }, ...withKey(key) })); await refresh(); }} />
      <ReasonDialog open={!!unlock} onClose={() => setUnlock(null)} title={t('init.unlock')} body={t('init.unlockBody')} confirmLabel={t('init.unlock')}
        onConfirm={async (reason) => { await call(api.inventory.POST('/api/inventory/v1/initialize-locks/{branch_id}/unlock', { params: { path: { branch_id: unlock! } }, body: { reason } })); await refresh(); }} />
    </div>
  );
}
