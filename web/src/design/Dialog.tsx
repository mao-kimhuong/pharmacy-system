// Modal dialog and side drawer: portal, focus trap, Esc closes, focus goes back to the opener.
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { cx } from './cx';

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function useFocusTrap(open: boolean, onClose: () => void, ref: React.RefObject<HTMLElement | null>, initialFocus?: string) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = (initialFocus && el?.querySelector<HTMLElement>(initialFocus)) || el?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? el)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !el) return;
      const items = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((x) => x.offsetParent !== null || x === document.activeElement);
      if (items.length === 0) return;
      const [a, z] = [items[0], items[items.length - 1]];
      if (e.shiftKey && document.activeElement === a) {
        e.preventDefault();
        z.focus();
      } else if (!e.shiftKey && document.activeElement === z) {
        e.preventDefault();
        a.focus();
      }
    };
    // The focused control can disappear (a step of the dialog replaced its content): focus would fall to <body>,
    // and Escape / Tab would stop working. Bring it back into the dialog.
    const onFocusOut = () => {
      window.setTimeout(() => {
        if (el && el.isConnected && (document.activeElement === document.body || document.activeElement === null)) {
          (el.querySelector<HTMLElement>(FOCUSABLE) ?? el).focus();
        }
      }, 0);
    };
    el?.addEventListener('keydown', onKey);
    el?.addEventListener('focusout', onFocusOut);
    return () => {
      el?.removeEventListener('keydown', onKey);
      el?.removeEventListener('focusout', onFocusOut);
      opener?.focus?.();
    };
  }, [open, ref, initialFocus]);
}

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: number;
  initialFocus?: string;
  /** Hard-stop dialogs: clicking the backdrop does not close. */
  dismissable?: boolean;
  className?: string;
}

export function Dialog({ open, onClose, title, subtitle, children, footer, width = 480, initialFocus, dismissable = true, className }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { t } = useTranslation();
  useFocusTrap(open, onClose, ref, initialFocus);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/35 p-4" onMouseDown={(e) => dismissable && e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cx('flex max-h-[calc(100vh-32px)] w-full flex-col overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-menu', className)}
        style={{ maxWidth: width }}
      >
        <div className="flex items-start justify-between gap-4 border-b border-neutral-100 px-5 py-4">
          <div className="flex flex-col gap-0.5">
            <h2 id={titleId} className="m-0 text-[16px] leading-6 font-semibold">{title}</h2>
            {subtitle && <div className="text-[13px] text-neutral-500">{subtitle}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label={t('action.close')} className="-m-1 rounded p-1 text-neutral-500 hover:bg-neutral-100">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-5 text-[14px]">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 bg-neutral-50 px-5 py-3.5">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, subtitle, children, footer, width = 420 }: Omit<DialogProps, 'initialFocus' | 'dismissable'>) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { t } = useTranslation();
  useFocusTrap(open, onClose, ref);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end bg-neutral-900/35" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="flex h-full w-full flex-col bg-white shadow-drawer" style={{ maxWidth: width }}>
        <div className="flex items-start justify-between gap-4 border-b border-neutral-100 p-4">
          <div className="flex flex-col">
            <h2 id={titleId} className="m-0 text-[15px] leading-6 font-semibold">{title}</h2>
            {subtitle && <div className="text-[12px] text-neutral-500">{subtitle}</div>}
          </div>
          <button type="button" onClick={onClose} aria-label={t('action.close')} className="-m-1 rounded p-1 text-neutral-500 hover:bg-neutral-100">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 text-[13px]">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-neutral-100 bg-neutral-50 p-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** Bottom sheet on phones (POS lite payment, link Rx). */
export function Sheet({ open, onClose, title, children, footer }: Omit<DialogProps, 'initialFocus' | 'dismissable' | 'width'>) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(open, onClose, ref);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end bg-neutral-900/35" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="flex max-h-[90vh] w-full flex-col rounded-t-2xl bg-white shadow-dialog">
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-neutral-300" aria-hidden />
        <h2 id={titleId} className="m-0 px-4 pt-3 pb-2 text-[17px] font-semibold">{title}</h2>
        <div className="flex-1 overflow-y-auto px-4 pb-4">{children}</div>
        {footer && <div className="border-t border-neutral-100 p-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
