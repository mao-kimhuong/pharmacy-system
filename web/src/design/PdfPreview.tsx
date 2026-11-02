// Print preview (17a–17i): the API's PDF in an iframe, then print() or download. The PDF comes from our own
// document service as a same-origin blob (Chrome does not show PDFs inside sandboxed iframes).
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { downloadBlob, renderPdf, type RenderBody } from '@/api/documents';
import { Button } from './Button';
import { Dialog } from './Dialog';
import { ErrorState, SkeletonRows } from './States';

export function PdfPreview({ open, onClose, body, title, filename }: { open: boolean; onClose: () => void; body: RenderBody | null; title: ReactNode; filename: string }) {
  const { t } = useTranslation();
  const [blob, setBlob] = useState<Blob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const key = body ? JSON.stringify(body) : '';
  useEffect(() => {
    if (!open || !body) return;
    let alive = true;
    let made: string | null = null;
    setBlob(null);
    setUrl(null);
    setError(null);
    renderPdf(body).then(
      (b) => {
        if (!alive) return;
        made = URL.createObjectURL(b);
        setBlob(b);
        setUrl(made);
      },
      (e) => alive && setError(e),
    );
    return () => {
      alive = false;
      if (made) URL.revokeObjectURL(made);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key, attempt]);
  return (
    <Dialog open={open} onClose={onClose} title={title} width={900}
      footer={<>
        <Button onClick={onClose}>{t('action.close')}</Button>
        <Button disabled={!blob} onClick={() => blob && downloadBlob(blob, filename)}>{t('action.download')}</Button>
        <Button variant="primary" disabled={!url} onClick={() => frame.current?.contentWindow?.print()}>{t('action.print')}</Button>
      </>}>
      {error ? <ErrorState error={error} onRetry={() => setAttempt((a) => a + 1)} /> : url ? (
        <iframe ref={frame} title={filename} src={url} className="h-[70vh] w-full rounded-md border border-neutral-200 bg-neutral-100" />
      ) : <SkeletonRows rows={6} />}
    </Dialog>
  );
}

/** Opens the preview for a render body. */
export function usePdf() {
  const [state, setState] = useState<{ body: RenderBody; title: ReactNode; filename: string } | null>(null);
  return {
    open: (body: RenderBody, title: ReactNode, filename: string) => setState({ body, title, filename }),
    element: <PdfPreview open={!!state} onClose={() => setState(null)} body={state?.body ?? null} title={state?.title} filename={state?.filename ?? 'document.pdf'} />,
  };
}
