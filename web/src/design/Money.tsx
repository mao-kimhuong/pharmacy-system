import { khr, qty, usd } from '@/lib/format';
import { cx } from './cx';

export function Usd({ value, className, strong }: { value: string | number | null | undefined; className?: string; strong?: boolean }) {
  return <span className={cx('num whitespace-nowrap', strong && 'font-semibold', className)}>{usd(value)}</span>;
}

export function Khr({ value, className }: { value: string | number | null | undefined; className?: string }) {
  return <span className={cx('num whitespace-nowrap', className)}>{khr(value)}</span>;
}

export function Qty({ value, unit, className }: { value: string | number | null | undefined; unit?: string; className?: string }) {
  return (
    <span className={cx('num whitespace-nowrap', className)}>
      {qty(value)}
      {unit && <span className="ml-1 text-[12px] font-normal text-neutral-500">{unit}</span>}
    </span>
  );
}

/** Shows a cost-type value only when the API sent the field (absent = hidden for the role, never computed). */
export function hasField<T extends object>(row: T | undefined | null, key: string): boolean {
  return !!row && Object.prototype.hasOwnProperty.call(row, key);
}
