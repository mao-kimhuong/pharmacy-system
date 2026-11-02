import { api, call } from '@/api/client';

export function uploadAttachment(rxId: string, file: File) {
  return call(api.prescription.POST('/api/prescription/v1/prescriptions/{rx_id}/attachments', {
    params: { path: { rx_id: rxId } },
    body: { file: '' },
    bodySerializer: () => { const fd = new FormData(); fd.append('file', file); return fd; },
  }));
}

export function downloadAttachment(rxId: string, attachmentId: string): Promise<Blob> {
  return call(api.prescription.GET('/api/prescription/v1/prescriptions/{rx_id}/attachments/{attachment_id}', {
    params: { path: { rx_id: rxId, attachment_id: attachmentId } }, parseAs: 'blob',
  })) as unknown as Promise<Blob>;
}
