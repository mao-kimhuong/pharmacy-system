// Every report shares one query and one response shape (columns, rows, summary, cost_hidden), so one helper
// calls any of them by its catalog path. Formats: json (screen), csv, xlsx, pdf (files).
import { api, call } from './client';
import type { paths } from './gen/reports';

export type ReportPath = keyof paths & `/api/reports/v1/${string}`;
type Detail = paths['/api/reports/v1/sales/detail']['get'];
export type ReportQuery = NonNullable<Detail['parameters']['query']>;
export interface ReportColumn { key: string; label: string; kind: string; secret: string | null }
export interface ReportData {
  report: string;
  title: string;
  total: number;
  page: number;
  size: number;
  columns: ReportColumn[];
  rows: Record<string, unknown>[];
  summary: Record<string, unknown>;
  cost_hidden: boolean;
}

/** key: the catalog key, e.g. "sales/detail". */
export function getReport(key: string, query: ReportQuery): Promise<ReportData> {
  const path = `/api/reports/v1/${key}`;
  // all report paths take the same parameters as sales/detail
  return call(api.reports.GET(path as '/api/reports/v1/sales/detail', { params: { query: { ...query, format: 'json' } } })) as unknown as Promise<ReportData>;
}

export async function exportReport(key: string, query: ReportQuery, format: 'csv' | 'xlsx' | 'pdf'): Promise<Blob> {
  const path = `/api/reports/v1/${key}`;
  return (await call(api.reports.GET(path as '/api/reports/v1/sales/detail', { params: { query: { ...query, format } }, parseAs: 'blob' }))) as unknown as Blob;
}
