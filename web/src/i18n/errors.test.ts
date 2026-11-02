import designed from '@design/error-messages.json';
import { ERROR_TEXTS, errorText } from './errors';

// Every code any endpoint can answer with, as listed in the generated OpenAPI types.
const gen = import.meta.glob<string>('../api/gen/*.ts', { query: '?raw', import: 'default', eager: true });
const codes = new Set<string>();
for (const src of Object.values(gen)) {
  for (const m of src.matchAll(/code\?: ((?:"[A-Z_]+"(?: \| )?)+)/g)) for (const c of m[1].matchAll(/"([A-Z_]+)"/g)) codes.add(c[1]);
}

describe('error messages', () => {
  it('found the API error codes', () => {
    expect(codes.size).toBeGreaterThan(50);
  });
  it('has English and Khmer text for every ErrorOut code', () => {
    const missing = [...codes].filter((c) => !ERROR_TEXTS[c]?.en || !ERROR_TEXTS[c]?.km);
    expect(missing).toEqual([]);
  });
  it('uses the designed text for the 13 designed codes', () => {
    for (const [code, v] of Object.entries(designed.messages)) {
      expect(errorText(code, 'en')).toBe(v.en);
      expect(errorText(code, 'km')).toBe(v.km);
    }
  });
  it('falls back to the API message for an unknown code', () => {
    expect(errorText('SOMETHING_NEW', 'en', 'From the API')).toBe('From the API');
  });
});
