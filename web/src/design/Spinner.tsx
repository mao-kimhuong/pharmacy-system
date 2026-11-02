import { cx } from './cx';

export function Spinner({ className, light }: { className?: string; light?: boolean }) {
  return (
    <span
      role="status"
      aria-label="loading"
      className={cx(
        'inline-block size-4 animate-spin rounded-full border-2',
        light ? 'border-white/40 border-t-white' : 'border-focus border-t-primary-600',
        className,
      )}
    />
  );
}
