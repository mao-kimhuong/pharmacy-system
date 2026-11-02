import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx } from './cx';
import { Spinner } from './Spinner';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'danger-outline' | 'ghost' | 'link';
export type ButtonSize = 'sm' | 'md' | 'lg';

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-primary-600 text-white border-primary-600 hover:bg-primary-700 hover:border-primary-700',
  secondary: 'bg-white text-neutral-900 border-neutral-300 hover:bg-neutral-50',
  danger: 'bg-danger text-white border-danger hover:bg-[#9A1D14]',
  'danger-outline': 'bg-white text-danger border-[#E8A39C] hover:bg-danger-bg',
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
        'inline-flex items-center justify-center border font-medium whitespace-nowrap transition-colors select-none',
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
            variant === 'primary' || variant === 'danger' ? 'bg-primary-900/40' : variant === 'danger-outline' ? 'bg-danger-bg' : 'bg-neutral-100 text-neutral-700',
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
    <kbd className={cx('rounded-sm border border-neutral-200 bg-white px-1.5 py-0.5 font-mono text-[11px] text-neutral-700', className)}>
      {children}
    </kbd>
  );
}
