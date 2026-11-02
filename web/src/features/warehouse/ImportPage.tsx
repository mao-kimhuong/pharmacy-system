// 9e Import products: template, upload (checked by content on the server), validation rows with errors,
// commit (create missing categories / brands, skip invalid SKUs) with an Idempotency-Key.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api, call, withKey } from '@/api/client';
import { downloadBlob } from '@/api/documents';
import { Alert, ApiErrorAlert, Button, Card, Checkbox, DataTable, PageHeader, StatusPill, UploadBox, useToast } from '@/design';
import { dateTime } from '@/lib/format';
import { toneOf, usePaging } from '../shared/hooks';
import { useRequestKey } from '../pos/hooks';
import { fileBody } from './upload';

export default function ImportPage() {
  const { t } = useTranslation(['warehouse', 'common', 'nav', 'sales']);
  const qc = useQueryClient();
  const toast = useToast();
  const paging = usePaging(50);
  const [id, setId] = useState<string | null>(null);
  const [onlyErrors, setOnlyErrors] = useState(true);
  const [createMissing, setCreateMissing] = useState(true);
  const [skipInvalid, setSkipInvalid] = useState(false);
  const list = useQuery({ queryKey: ['catalog', 'imports'], queryFn: () => call(api.catalog.GET('/api/catalog/v1/imports', { params: { query: { size: 10 } } })) });
  const detail = useQuery({
    queryKey: ['catalog', 'import', id, onlyErrors, paging.page, paging.size],
    enabled: !!id,
    queryFn: () => call(api.catalog.GET('/api/catalog/v1/imports/{import_id}', { params: { path: { import_id: id! }, query: { errors_only: onlyErrors, page: paging.page, size: paging.size } } })),
  });
  const template = useMutation({ mutationFn: async () => downloadBlob((await call(api.catalog.GET('/api/catalog/v1/imports/template.xlsx', { parseAs: 'blob' }))) as unknown as Blob, 'products-template.xlsx') });
  const upload = useMutation({
    mutationFn: (f: File) => call(api.catalog.POST('/api/catalog/v1/imports', fileBody(f))),
    onSuccess: (s) => { setId(s.id); paging.reset(); void qc.invalidateQueries({ queryKey: ['catalog', 'imports'] }); },
  });
  const key = useRequestKey(`${id}-${createMissing}-${skipInvalid}`);
  const commit = useMutation({
    mutationFn: () => call(api.catalog.POST('/api/catalog/v1/imports/{import_id}/commit', { params: { path: { import_id: id! } }, body: { create_missing: createMissing, skip_invalid: skipInvalid }, ...withKey(key) })),
    onSuccess: (s) => { toast.success(t('import.committed', { created: s.created_count, updated: s.updated_count })); void qc.invalidateQueries({ queryKey: ['catalog'] }); },
  });
  const d = detail.data;
  return (
    <div className="flex flex-col gap-4 p-5 tablet:px-7">
      <PageHeader crumb={t('nav:group.warehouse')} title={t('import.title')} actions={<Button loading={template.isPending} onClick={() => template.mutate()}>{t('import.template')}</Button>} />
      <Card><UploadBox accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" busy={upload.isPending} label={t('import.upload')} onFile={(f) => upload.mutate(f)} /></Card>
      <ApiErrorAlert error={upload.error ?? template.error} />
      {d && (
        <Card title={d.file_name} actions={<StatusPill tone={toneOf(d.status)}>{d.status}</StatusPill>}>
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-4 text-[13px]">
              <span>{t('import.rows')}: <b>{d.total_rows}</b></span>
              <span className={d.error_rows ? 'text-danger' : ''}>{t('import.errors')}: <b>{d.error_rows}</b></span>
              {d.new_categories.length > 0 && <span>{t('import.newCats')}: {d.new_categories.join(', ')}</span>}
              {d.new_brands.length > 0 && <span>{t('import.newBrands')}: {d.new_brands.join(', ')}</span>}
            </div>
            <Checkbox label={t('import.onlyErrors')} checked={onlyErrors} onChange={(e) => { setOnlyErrors(e.target.checked); paging.reset(); }} />
            <DataTable rows={d.rows} rowKey={(r) => String(r.row_no)} dense paging={{ page: paging.page, size: paging.size, total: d.rows_total, onPage: paging.setPage }}
              columns={[
                { key: 'r', header: t('import.row'), cell: (r) => r.row_no },
                { key: 's', header: 'SKU', cell: (r) => <span className="font-mono text-[12px]">{r.sku}</span> },
                { key: 'a', header: t('import.action'), cell: (r) => r.action ?? '—' },
                { key: 'e', header: t('import.problems'), cell: (r) => <span className="text-[12px] text-danger">{(r.errors as { field?: string; message?: string }[]).map((e) => `${e.field ?? ''} ${e.message ?? ''}`.trim()).join('; ') || '—'}</span> },
              ]} />
            {d.status !== 'committed' ? (
              <div className="flex flex-wrap items-center gap-4">
                <Checkbox label={t('import.createMissing')} checked={createMissing} onChange={(e) => setCreateMissing(e.target.checked)} />
                <Checkbox label={t('import.skipInvalid')} checked={skipInvalid} onChange={(e) => setSkipInvalid(e.target.checked)} />
                <Button variant="primary" className="ml-auto" loading={commit.isPending} disabled={d.error_rows > 0 && !skipInvalid && !createMissing} onClick={() => commit.mutate()}>{t('import.commit')}</Button>
              </div>
            ) : <Alert tone="success">{t('import.committed', { created: d.created_count, updated: d.updated_count })}</Alert>}
            <ApiErrorAlert error={commit.error} />
          </div>
        </Card>
      )}
      <Card title={t('import.history')} padded={false}>
        <DataTable className="rounded-none border-0" rows={list.data?.items} loading={list.isLoading} error={list.error} rowKey={(s) => s.id} onRowClick={(s) => { setId(s.id); paging.reset(); }}
          columns={[
            { key: 'f', header: t('common:label.file'), cell: (s) => s.file_name },
            { key: 'd', header: t('common:label.date'), cell: (s) => dateTime(s.created_at) },
            { key: 'r', header: t('import.rows'), align: 'right', cell: (s) => s.total_rows },
            { key: 'e', header: t('import.errors'), align: 'right', cell: (s) => s.error_rows },
            { key: 's', header: t('common:label.status'), cell: (s) => <StatusPill tone={toneOf(s.status)}>{s.status}</StatusPill> },
          ]} />
      </Card>
    </div>
  );
}
