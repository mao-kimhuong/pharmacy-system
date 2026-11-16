// Light / dark theme. "system" follows the device (and changes with it). The choice is kept per browser; the class
// `dark` on <html> switches the colour tokens (src/index.css). Applied before the first render (main.tsx) so the page
// does not flash light.
import { useEffect, useState } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
const KEY = 'pharmacy.theme';
const MODES: ThemeMode[] = ['system', 'light', 'dark'];
const listeners = new Set<(m: ThemeMode) => void>();

function stored(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

const media = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null);

export function resolved(mode: ThemeMode): 'light' | 'dark' {
  return mode === 'system' ? (media()?.matches ? 'dark' : 'light') : mode;
}

export function applyTheme(mode: ThemeMode = stored()): void {
  const dark = resolved(mode) === 'dark';
  document.documentElement.classList.toggle('dark', dark);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0e1514' : '#0e7470');
}

export function setTheme(mode: ThemeMode): void {
  try {
    if (mode === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, mode);
  } catch {
    /* private window: this page only */
  }
  applyTheme(mode);
  listeners.forEach((l) => l(mode));
}

/** Once at start-up: apply the saved choice and follow the device while on "system". */
export function initTheme(): void {
  applyTheme();
  media()?.addEventListener?.('change', () => { if (stored() === 'system') applyTheme('system'); });
}

export function nextMode(mode: ThemeMode): ThemeMode {
  return MODES[(MODES.indexOf(mode) + 1) % MODES.length];
}

export function useTheme(): [ThemeMode, (m: ThemeMode) => void] {
  const [mode, setMode] = useState<ThemeMode>(stored);
  useEffect(() => {
    listeners.add(setMode);
    return () => { listeners.delete(setMode); };
  }, []);
  return [mode, setTheme];
}
