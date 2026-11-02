// KM is the default; the choice is kept per device. <html lang> follows it (fonts + Khmer line heights).
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import type { Lang } from '@/lib/format';

const en = import.meta.glob<{ default: Record<string, unknown> }>('./en/*.json', { eager: true });
const km = import.meta.glob<{ default: Record<string, unknown> }>('./km/*.json', { eager: true });

const load = (files: typeof en) =>
  Object.fromEntries(Object.entries(files).map(([p, m]) => [p.replace(/^.*\/(.*)\.json$/, '$1'), m.default]));

export const resources = { en: load(en), km: load(km) };
export const namespaces = Object.keys(resources.en);

const STORAGE_KEY = 'pharmacy.lang';

export function storedLang(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'en' ? 'en' : 'km';
  } catch {
    return 'km';
  }
}

export function setLang(lang: Lang) {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* private mode */
  }
  void i18n.changeLanguage(lang);
}

i18n.on('languageChanged', (lng) => {
  if (typeof document !== 'undefined') document.documentElement.lang = lng;
});

void i18n.use(initReactI18next).init({
  resources,
  lng: storedLang(),
  fallbackLng: false,
  ns: namespaces,
  defaultNS: 'common',
  interpolation: { escapeValue: false },
  returnNull: false,
});
if (typeof document !== 'undefined') document.documentElement.lang = i18n.language;

export default i18n;
