// Upload with preview (Design System §10). The server checks the file (JPEG/PNG/PDF ≤ 10 MB, FILE_REJECTED).
import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cx } from './cx';

export function UploadBox({ onFile, accept = 'image/jpeg,image/png,application/pdf', capture, busy, label, className }: {
  onFile: (f: File) => void; accept?: string; capture?: boolean; busy?: boolean; label?: ReactNode; className?: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      role="button"
      tabIndex={0}
      aria-busy={busy || undefined}
      onClick={() => ref.current?.click()}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && ref.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
      className={cx('flex cursor-pointer flex-col gap-1 rounded-lg border-[1.5px] border-dashed p-5 text-center text-[13px] text-neutral-700', over ? 'border-primary-600 bg-primary-50' : 'border-[#9FB5B3] bg-neutral-50', className)}
    >
      <b>{label ?? t('upload.drop')}</b>
      <span className="text-neutral-500">{t('upload.hint')}</span>
      <input ref={ref} type="file" hidden accept={accept} capture={capture ? 'environment' : undefined}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ''; }} />
    </div>
  );
}
