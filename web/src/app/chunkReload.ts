// A page's code file could not load (a tab left open across a deploy): reload once to get the current files.
const KEY = 'pharmacy.chunk-reload';

export function reloadOnceForChunk(now: number, store: Pick<Storage, 'getItem' | 'setItem'>, reload: () => void): boolean {
  const last = Number(store.getItem(KEY) ?? 0);
  if (now - last < 30_000) return false; // it failed again right after a reload: show the error instead of looping
  store.setItem(KEY, String(now));
  reload();
  return true;
}

export function watchChunkErrors() {
  window.addEventListener('vite:preloadError', (e) => {
    console.error('Could not load a page file', (e as Event & { payload?: unknown }).payload);
    try {
      if (reloadOnceForChunk(Date.now(), sessionStorage, () => location.reload())) e.preventDefault();
    } catch {
      /* no sessionStorage: the error screen shows */
    }
  });
}
