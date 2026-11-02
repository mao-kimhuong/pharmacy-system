// Service worker: precaches the app shell and fonts (vite-plugin-pwa). A new version asks before reloading.
import { registerSW } from 'virtual:pwa-register';

export function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || import.meta.env.DEV) return;
  const update = registerSW({
    onNeedRefresh() {
      window.dispatchEvent(new CustomEvent('pwa:update', { detail: () => update(true) }));
    },
  });
}
