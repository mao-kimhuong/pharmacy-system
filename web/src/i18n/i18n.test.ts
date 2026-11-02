import { resources } from './index';

function keys(o: unknown, prefix = ''): string[] {
  if (typeof o !== 'object' || o === null) return [prefix];
  return Object.entries(o).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe('translations', () => {
  it('has the same namespaces in km and en', () => {
    expect(Object.keys(resources.km).sort()).toEqual(Object.keys(resources.en).sort());
  });
  for (const ns of Object.keys(resources.en)) {
    it(`${ns}: every key exists in km and en, none empty`, () => {
      const en = keys(resources.en[ns]).sort();
      const km = keys(resources.km[ns]).sort();
      expect(km).toEqual(en);
      for (const k of en) {
        const get = (o: unknown) => k.split('.').reduce<unknown>((a, p) => (a as Record<string, unknown>)[p], o);
        expect(String(get(resources.en[ns])).trim(), `${ns}.${k} en`).not.toBe('');
        expect(String(get(resources.km[ns])).trim(), `${ns}.${k} km`).not.toBe('');
      }
    });
  }
  it('keeps the same {{placeholders}} in both languages', () => {
    for (const ns of Object.keys(resources.en)) {
      for (const k of keys(resources.en[ns])) {
        const get = (o: unknown) => String(k.split('.').reduce<unknown>((a, p) => (a as Record<string, unknown>)[p], o));
        const ph = (s: string) => (s.match(/\{\{\w+\}\}/g) ?? []).sort();
        expect(ph(get(resources.km[ns])), `${ns}.${k}`).toEqual(ph(get(resources.en[ns])));
      }
    }
  });
});
