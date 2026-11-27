// Service worker: precaches the app shell and fonts (vite-plugin-pwa). A cached app must not outlive a deploy: right
// after a page load (nothing typed yet) a new version applies by itself; later, or at the till (POS shows the banner
// too), the banner asks, so a reload never drops a cart or a half-filled form.
import { registerSW } from 'virtual:pwa-register';

const FRESH_MS = 20_000;
const CHECK_EVERY_MS = 60 * 60 * 1000;
let pending: (() => void) | null = null;

/** The waiting update, for a banner that mounts after the event (the login page has none). */
export const pendingUpdate = () => pending;

export function applyNow(path: string, msSinceLoad: number): boolean {
  return msSinceLoad < FRESH_MS && !path.startsWith('/pos');
}

export function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || import.meta.env.DEV) return;
  const update = registerSW({
    onNeedRefresh() {
      const apply = () => void update(true);
      if (applyNow(location.pathname, performance.now())) return apply();
      pending = apply;
      window.dispatchEvent(new CustomEvent('pwa:update', { detail: apply }));
    },
    onRegisteredSW(_url, registration) {
      if (registration) setInterval(() => void registration.update(), CHECK_EVERY_MS);
    },
  });
}
