import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx } from './cx';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'danger-outline' | 'ghost' | 'link';
export type ButtonSize = 'sm' | 'md' | 'lg';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-primary-600 text-white border-primary-600 hover:bg-primary-deep hover:border-primary-deep',
  secondary: 'bg-surface text-neutral-900 border-neutral-300 hover:bg-neutral-50',
  danger: 'bg-danger text-white border-danger hover:bg-danger-strong',
  'danger-outline': 'bg-surface text-danger border-danger-bd hover:bg-danger-bg',
  ghost: 'bg-transparent text-neutral-700 border-transparent hover:bg-neutral-100',
  link: 'bg-transparent text-primary-600 border-transparent hover:text-primary-700 px-0',
};
const SIZE: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-[13px] rounded-md gap-1.5',
  md: 'h-control px-3.5 text-[14px] rounded-md gap-2',
  lg: 'h-12 px-5 text-[16px] rounded-lg gap-2.5 font-semibold',
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  kbd?: string;
  icon?: ReactNode;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, kbd, icon, block, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      aria-keyshortcuts={kbd && kbd !== 'Enter' && kbd !== 'Esc' ? kbd : kbd === 'Esc' ? 'Escape' : kbd}
      className={cx(
        'inline-flex items-center justify-center border font-medium whitespace-nowrap transition-colors select-none pointer-coarse:min-h-11',
        'disabled:cursor-not-allowed disabled:opacity-45',
        VARIANT[variant],
        SIZE[size],
        block && 'w-full',
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner className="size-3.5" light={variant === 'primary' || variant === 'danger'} /> : icon}
      {children}
      {kbd && (
        <kbd
          aria-hidden
          className={cx(
            'rounded-sm px-1.5 py-0.5 font-mono text-[11px] font-normal',
            variant === 'primary' || variant === 'danger' ? 'bg-primary-deep/40' : variant === 'danger-outline' ? 'bg-danger-bg' : 'bg-neutral-100 text-neutral-700',
          )}
        >
          {kbd}
        </kbd>
      )}
    </button>
  );
});

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cx('rounded-sm border border-neutral-200 bg-surface px-1.5 py-0.5 font-mono text-[11px] text-neutral-700', className)}>
      {children}
    </kbd>
  );
}
