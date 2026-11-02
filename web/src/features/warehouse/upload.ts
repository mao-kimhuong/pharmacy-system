// multipart/form-data bodies for the typed clients (file field "file", plus any extra form fields).
export function fileBody(file: File, fields: Record<string, string> = {}) {
  return {
    body: { file: '', ...fields } as never,
    bodySerializer: () => {
      const fd = new FormData();
      for (const [k, v] of Object.entries(fields)) fd.append(k, v);
      fd.append('file', file);
      return fd;
    },
  };
}
