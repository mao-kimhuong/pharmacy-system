// One finding of the preview (hard stop / requirement / warning / info), in the user's language, with the action
// that resolves it. Messages come from the API in English and Khmer.
import { useTranslation } from 'react-i18next';
import { cx } from '@/design';
import type { Finding } from './hooks';

const TONE = {
  hard_stop: { box: 'bg-danger-bg text-[#7A1610]', icon: 'bg-danger', glyph: '✕' },
  requirement: { box: 'bg-[#ECEAFB] text-[#262A7A]', icon: 'bg-safety-rx', glyph: '℞' },
  warning: { box: 'bg-warning-bg text-[#5C3B00]', icon: 'bg-warning', glyph: '!' },
  info: { box: 'bg-info-bg text-[#173F6E]', icon: 'bg-info', glyph: 'i' },
  ok: { box: 'bg-success-bg text-[#164E2E]', icon: 'bg-success', glyph: '✓' },
} as const;

export interface FindingAction {
  label: string;
  onClick: () => void;
}

export function findingText(f: Finding, lang: string) {
  return lang === 'km' && f.message_km ? f.message_km : f.message_en;
}

export function FindingRow({ f, actions = [], className }: { f: Finding; actions?: FindingAction[]; className?: string }) {
  const { i18n } = useTranslation();
  const tone = f.resolved ? TONE.ok : TONE[f.severity];
  return (
    <div role={f.severity === 'hard_stop' && !f.resolved ? 'alert' : undefined} data-code={f.code}
      className={cx('flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[12px] leading-5 font-medium', tone.box, className)}>
      <span className={cx('flex size-4 flex-none items-center justify-center rounded-full text-[10px] font-bold text-white', tone.icon)} aria-hidden>{tone.glyph}</span>
      <span className="flex-1">{findingText(f, i18n.language)}</span>
      {actions.map((a) => (
        <button key={a.label} type="button" onClick={a.onClick} className="font-semibold whitespace-nowrap underline">{a.label}</button>
      ))}
    </div>
  );
}
