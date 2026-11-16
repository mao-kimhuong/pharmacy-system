// Toasts: bottom-right, at most 3; success 4 s, failure stays until dismissed.
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export type ToastKind = 'success' | 'error' | 'info';
interface ToastItem {
  id: number;
  kind: ToastKind;
  text: ReactNode;
  action?: { label: ReactNode; onClick: () => void };
}
interface ToastApi {
  show: (t: Omit<ToastItem, 'id'>) => void;
  success: (text: ReactNode, action?: ToastItem['action']) => void;
  error: (text: ReactNode, action?: ToastItem['action']) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const { t } = useTranslation();
  const remove = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const show = useCallback(
    (item: Omit<ToastItem, 'id'>) => {
      const id = ++seq.current;
      setItems((xs) => [...xs, { ...item, id }].slice(-3));
      if (item.kind !== 'error') setTimeout(() => remove(id), 4000);
    },
    [remove],
  );
  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (text, action) => show({ kind: 'success', text, action }),
      error: (text, action) => show({ kind: 'error', text, action }),
    }),
    [show],
  );
  return (
    <Ctx.Provider value={api}>
      {children}
      <div aria-live="polite" className="no-print pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[380px] max-w-[calc(100vw-32px)] flex-col gap-2">
        {items.map((x) => (
          <div key={x.id} role={x.kind === 'error' ? 'alert' : 'status'} className="pointer-events-auto flex items-center gap-3 rounded-lg bg-inverse px-3.5 py-3 text-[13px] text-white shadow-toast">
            <span className={x.kind === 'error' ? 'font-bold text-[#FF8A7E]' : x.kind === 'info' ? 'font-bold text-[#F3C24B]' : 'font-bold text-posdark-accent-soft'} aria-hidden>
              {x.kind === 'error' ? '✕' : x.kind === 'info' ? 'i' : '✓'}
            </span>
            <span className="flex-1">{x.text}</span>
            {x.action && (
              <button type="button" className="font-semibold text-posdark-accent-soft" onClick={() => { x.action!.onClick(); remove(x.id); }}>
                {x.action.label}
              </button>
            )}
            <button type="button" aria-label={t('action.dismiss')} className="text-white/60 hover:text-white" onClick={() => remove(x.id)}>✕</button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const c = useContext(Ctx);
  if (!c) throw new Error('useToast outside ToastProvider');
  return c;
}
