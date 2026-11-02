// Data table (Design System §07): sticky header, optional selection with a bulk bar, rows-per-page 20/50/100,
// "1–20 of 186", loading skeleton, server error with retry, empty state.
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Segmented } from './Field';
import { EmptyState, ErrorState, SkeletonRows } from './States';
import { cx } from './cx';

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T, index: number) => ReactNode;
  align?: 'left' | 'right' | 'center';
  width?: string;
  className?: string;
  /** Totals row cell. */
  footer?: ReactNode;
}

export interface Paging {
  page: number;
  size: number;
  total: number;
  onPage: (page: number) => void;
  onSize?: (size: number) => void;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T, index: number) => string;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: ReactNode;
  paging?: Paging;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
  selection?: { selected: Set<string>; onChange: (s: Set<string>) => void; actions?: ReactNode };
  toolbar?: ReactNode;
  className?: string;
  minWidth?: number;
  caption?: string;
  dense?: boolean;
}

export function DataTable<T>({
  columns, rows, rowKey, loading, error, onRetry, empty, paging, onRowClick, rowClassName, selection, toolbar, className, minWidth = 720, caption, dense,
}: DataTableProps<T>) {
  const { t } = useTranslation();
  const keys = rows?.map(rowKey) ?? [];
  const allOn = selection && keys.length > 0 && keys.every((k) => selection.selected.has(k));
  const hasFooter = columns.some((c) => c.footer !== undefined);
  const pad = dense ? 'px-3 py-2' : 'px-3 py-3';
  return (
    <div className={cx('flex min-h-0 flex-col overflow-hidden rounded-xl border border-neutral-200 bg-white', className)}>
      {toolbar && <div className="flex flex-wrap items-center gap-2 border-b border-neutral-200 px-4 py-3">{toolbar}</div>}
      {selection && selection.selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 border-b border-primary-100 bg-primary-50 px-4 py-2 text-[13px]">
          <b className="text-primary-700">{t('table.selected', { count: selection.selected.size })}</b>
          {selection.actions}
          <button type="button" className="ml-auto text-neutral-500" onClick={() => selection.onChange(new Set())}>{t('action.clear')}</button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        {error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : loading && !rows ? (
          <SkeletonRows />
        ) : (
          <table className="w-full border-collapse text-table" style={{ minWidth }}>
            {caption && <caption className="sr-only">{caption}</caption>}
            <thead>
              <tr>
                {selection && (
                  <th className="sticky top-0 z-[1] w-10 border-b border-neutral-200 bg-neutral-50 px-3 py-2.5">
                    <input
                      type="checkbox"
                      aria-label={t('action.select')}
                      className="size-4 accent-primary-600"
                      checked={!!allOn}
                      onChange={() => selection.onChange(allOn ? new Set() : new Set(keys))}
                    />
                  </th>
                )}
                {columns.map((c) => (
                  <th
                    key={c.key}
                    scope="col"
                    className={cx('sticky top-0 z-[1] border-b border-neutral-200 bg-neutral-50 px-3 py-2.5 text-[12px] font-semibold whitespace-nowrap text-neutral-700',
                      c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : 'text-left')}
                    style={c.width ? { width: c.width } : undefined}
                  >
                    {c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows?.map((r, i) => {
                const k = keys[i];
                const on = selection?.selected.has(k);
                return (
                  <tr
                    key={k}
                    onClick={onRowClick ? () => onRowClick(r) : undefined}
                    onKeyDown={onRowClick ? (e) => { if (e.key === 'Enter') onRowClick(r); } : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    className={cx(on ? 'bg-primary-50' : onRowClick && 'cursor-pointer hover:bg-neutral-50', rowClassName?.(r))}
                  >
                    {selection && (
                      <td className={cx('border-b border-neutral-100', pad)} onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          aria-label={t('action.select')}
                          className="size-4 accent-primary-600"
                          checked={!!on}
                          onChange={() => {
                            const s = new Set(selection.selected);
                            if (on) s.delete(k);
                            else s.add(k);
                            selection.onChange(s);
                          }}
                        />
                      </td>
                    )}
                    {columns.map((c) => (
                      <td key={c.key} className={cx('border-b border-neutral-100 align-middle', pad, c.align === 'right' && 'num text-right', c.align === 'center' && 'text-center', c.className)}>
                        {c.cell(r, i)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
            {hasFooter && rows && rows.length > 0 && (
              <tfoot>
                <tr className="bg-neutral-50 font-semibold">
                  {selection && <td />}
                  {columns.map((c) => (
                    <td key={c.key} className={cx('border-t border-neutral-200', pad, c.align === 'right' && 'num text-right')}>{c.footer}</td>
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        )}
        {!error && rows && rows.length === 0 && (empty ?? <EmptyState title={t('table.noRows')} />)}
      </div>
      {paging && !error && <Pager {...paging} />}
    </div>
  );
}

export function Pager({ page, size, total, onPage, onSize }: Paging) {
  const { t } = useTranslation();
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(page * size, total);
  const last = Math.max(1, Math.ceil(total / size));
  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-neutral-100 px-4 py-2.5 text-[13px] text-neutral-700">
      {onSize && (
        <>
          <span>{t('table.rowsPerPage')}</span>
          <Segmented size="sm" value={size} onChange={(v) => onSize(v)} options={[20, 50, 100].map((n) => ({ value: n, label: n }))} />
        </>
      )}
      <span className="ml-auto num">{t('table.range', { from, to, total })}</span>
      <span className="flex gap-1">
        <button type="button" aria-label={t('table.prev')} disabled={page <= 1} onClick={() => onPage(page - 1)}
          className="flex size-8 items-center justify-center rounded-md border border-neutral-300 disabled:border-neutral-200 disabled:text-neutral-300 pointer-coarse:size-11">‹</button>
        <button type="button" aria-label={t('table.nextPage')} disabled={page >= last} onClick={() => onPage(page + 1)}
          className="flex size-8 items-center justify-center rounded-md border border-neutral-300 disabled:border-neutral-200 disabled:text-neutral-300 pointer-coarse:size-11">›</button>
      </span>
    </div>
  );
}
