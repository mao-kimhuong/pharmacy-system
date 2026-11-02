import {
  forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes,
} from 'react';
import { cx } from './cx';

export const controlClass = (invalid?: boolean, size: 'md' | 'lg' = 'md') =>
  cx(
    'w-full rounded-md border bg-white px-3 text-[14px] text-neutral-900 placeholder:text-neutral-400',
    'focus:border-primary-600 focus:shadow-focus focus:outline-none',
    'disabled:cursor-not-allowed disabled:border-neutral-200 disabled:bg-neutral-100 disabled:text-neutral-400',
    size === 'lg' ? 'h-control-lg rounded-lg text-[16px]' : 'h-control',
    invalid ? 'border-danger' : 'border-neutral-300',
  );

export interface FieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: (id: string, describedBy: string | undefined, invalid: boolean) => ReactNode;
  labelAside?: ReactNode;
}

/** Label + control + hint/error. Errors show on blur and submit (react-hook-form mode onTouched). */
export function Field({ label, hint, error, required, className, children, labelAside }: FieldProps) {
  const id = useId();
  const msgId = `${id}-msg`;
  const invalid = !!error;
  return (
    <div className={cx('flex flex-col gap-1.5', className)}>
      {label && (
        <label htmlFor={id} className="flex items-center justify-between gap-2 text-[13px] font-medium">
          <span>
            {label}
            {required && <span className="text-danger"> *</span>}
          </span>
          {labelAside}
        </label>
      )}
      {children(id, error || hint ? msgId : undefined, invalid)}
      {error ? (
        <span id={msgId} role="alert" className="text-[12px] leading-[18px] text-danger">
          ✕ {error}
        </span>
      ) : hint ? (
        <span id={msgId} className="text-[12px] leading-[18px] text-neutral-500">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & {
  invalid?: boolean;
  fieldSize?: 'md' | 'lg';
  prefix?: ReactNode;
  suffix?: ReactNode;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { invalid, fieldSize = 'md', prefix, suffix, className, ...rest },
  ref,
) {
  if (!prefix && !suffix) {
    return <input ref={ref} aria-invalid={invalid || undefined} className={cx(controlClass(invalid, fieldSize), className)} {...rest} />;
  }
  return (
    <span
      className={cx(
        controlClass(invalid, fieldSize),
        'flex items-center overflow-hidden px-0 focus-within:border-primary-600 focus-within:shadow-focus',
        rest.disabled && 'bg-neutral-100',
        className,
      )}
    >
      {prefix && (
        <span className="flex h-full items-center border-r border-neutral-200 bg-neutral-50 px-2.5 text-[14px] text-neutral-700">{prefix}</span>
      )}
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className="h-full min-w-0 flex-1 bg-transparent px-3 outline-none focus-visible:shadow-none disabled:cursor-not-allowed"
        {...rest}
      />
      {suffix && <span className="flex h-full items-center px-2.5 text-[13px] text-neutral-500">{suffix}</span>}
    </span>
  );
});

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(
  function TextArea({ invalid, className, rows = 3, ...rest }, ref) {
    return (
      <textarea
        ref={ref}
        rows={rows}
        aria-invalid={invalid || undefined}
        className={cx(controlClass(invalid), 'h-auto py-2 leading-[22px]', className)}
        {...rest}
      />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean; fieldSize?: 'md' | 'lg' }>(
  function Select({ invalid, fieldSize, className, children, ...rest }, ref) {
    return (
      <select
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cx(controlClass(invalid, fieldSize), 'appearance-none bg-[length:10px] bg-[right_12px_center] bg-no-repeat pr-8', className)}
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2366706F'/%3E%3C/svg%3E\")",
        }}
        {...rest}
      >
        {children}
      </select>
    );
  },
);

export function Checkbox({ label, className, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode }) {
  return (
    <label className={cx('inline-flex cursor-pointer items-center gap-2 text-[14px]', rest.disabled && 'cursor-not-allowed opacity-60', className)}>
      <input type="checkbox" className="size-4 rounded-sm accent-primary-600" {...rest} />
      {label}
    </label>
  );
}

export function Switch({
  checked, onChange, label, disabled, id,
}: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean; id?: string }) {
  return (
    <label className={cx('inline-flex items-center gap-2 text-[14px]', disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer')}>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx('relative h-5 w-9 rounded-full transition-colors', checked ? 'bg-primary-600' : 'bg-neutral-300')}
      >
        <span className={cx('absolute top-0.5 size-4 rounded-full bg-white shadow transition-all', checked ? 'left-[18px]' : 'left-0.5')} />
      </button>
      {label}
    </label>
  );
}

export function Radio({ label, className, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className={cx('inline-flex cursor-pointer items-center gap-2 text-[14px]', className)}>
      <input type="radio" className="size-4 accent-primary-600" {...rest} />
      {label}
    </label>
  );
}

/** Segmented control (KM/EN toggle, USD/KHR, rows per page). */
export function Segmented<T extends string | number>({
  value, options, onChange, size = 'md', className, ariaLabel,
}: {
  value: T;
  options: { value: T; label: ReactNode; className?: string }[];
  onChange: (v: T) => void;
  size?: 'sm' | 'md';
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={cx('inline-flex overflow-hidden rounded-md border border-neutral-300 bg-white', className)}>
      {options.map((o, i) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            'font-medium',
            size === 'sm' ? 'px-2.5 py-1 text-[13px]' : 'px-2.5 py-[7px] text-[13px]',
            i > 0 && 'border-l border-neutral-300',
            o.value === value ? 'bg-primary-600 text-white' : 'text-neutral-700 hover:bg-neutral-50',
            o.className,
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
