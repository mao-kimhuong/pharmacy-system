// Shows a private file streamed by a service (image or PDF) from a blob; never a public link.
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { downloadBlob } from '@/api/documents';
import { Button } from './Button';
import { Dialog } from './Dialog';
import { ErrorState, SkeletonRows } from './States';

export function BlobViewer({ load, title, filename, onClose }: { load: (() => Promise<Blob>) | null; title: ReactNode; filename: string; onClose: () => void }) {
  const { t } = useTranslation();
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (!load) return;
    let made: string | null = null;
    let alive = true;
    setBlob(null); setUrl(null); setError(null);
    load().then((b) => { if (!alive) return; made = URL.createObjectURL(b); setBlob(b); setUrl(made); }, (e) => alive && setError(e));
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [load]);
  return (
    <Dialog open={!!load} onClose={onClose} title={title} width={900}
      footer={<><Button onClick={onClose}>{t('action.close')}</Button><Button disabled={!blob} onClick={() => blob && downloadBlob(blob, filename)}>{t('action.download')}</Button></>}>
      {error ? <ErrorState error={error} /> : !url ? <SkeletonRows /> : blob?.type.startsWith('image/') ? (
        <img src={url} alt={filename} className="mx-auto max-h-[70vh] rounded-md" />
      ) : <iframe title={filename} src={url} className="h-[70vh] w-full rounded-md border border-neutral-200" />}
    </Dialog>
  );
}
