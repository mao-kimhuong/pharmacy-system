// PDFs from the document service (POST /api/documents/v1/render). The service waits up to 5 s for its copy of
// the record and answers DOCUMENT_NOT_READY after that: we try again a few times.
import { api, call } from './client';
import { isApiError } from './errors';
import type { paths } from './gen/documents';

export type RenderBody = paths['/api/documents/v1/render']['post']['requestBody']['content']['application/json'];

export async function renderPdf(body: RenderBody, tries = 3): Promise<Blob> {
  for (let i = 0; ; i++) {
    try {
      return (await call(api.documents.POST('/api/documents/v1/render', { body, parseAs: 'blob' }))) as unknown as Blob;
    } catch (e) {
      if (i + 1 < tries && isApiError(e) && e.code === 'DOCUMENT_NOT_READY') {
        await new Promise((r) => setTimeout(r, 1500));
        continue;
      }
      throw e;
    }
  }
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
