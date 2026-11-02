// Six boxes for a 6-digit code; paste fills all; invalid keeps the digits in red (15c).
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { cx } from './cx';

export function OtpInput({ value, onChange, onComplete, invalid, length = 6, autoFocus = true }: {
  value: string; onChange: (v: string) => void; onComplete?: (v: string) => void; invalid?: boolean; length?: number; autoFocus?: boolean;
}) {
  const { t } = useTranslation('auth');
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const set = (v: string) => {
    const clean = v.replace(/\D/g, '').slice(0, length);
    onChange(clean);
    refs.current[Math.min(clean.length, length - 1)]?.focus();
    if (clean.length === length) onComplete?.(clean);
  };
  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${length}, minmax(0, 1fr))` }}>
      {Array.from({ length }, (_, i) => (
        <input
          key={i}
          ref={(el) => { refs.current[i] = el; }}
          aria-label={t('code.digit', { n: i + 1 })}
          inputMode="numeric"
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          autoFocus={autoFocus && i === 0}
          maxLength={length}
          value={value[i] ?? ''}
          onPaste={(e) => { e.preventDefault(); set(e.clipboardData.getData('text')); }}
          onChange={(e) => {
            const d = e.target.value.replace(/\D/g, '');
            if (d.length > 1) return set(d);
            const chars = value.split('');
            chars[i] = d;
            set(chars.join('').slice(0, i + 1) + (d ? value.slice(i + 1) : ''));
          }}
          onKeyDown={(e) => {
            if (e.key === 'Backspace' && !value[i] && i > 0) {
              onChange(value.slice(0, i - 1));
              refs.current[i - 1]?.focus();
            }
          }}
          className={cx('h-14 rounded-lg border text-center text-[24px] font-semibold outline-none focus:border-2 focus:border-primary-600 focus:shadow-focus',
            invalid ? 'border-danger bg-[#FFF8F7] text-[#A3201A]' : 'border-neutral-300')}
        />
      ))}
    </div>
  );
}
