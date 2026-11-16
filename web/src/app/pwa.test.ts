import { describe, expect, it, vi } from 'vitest';

vi.mock('virtual:pwa-register', () => ({ registerSW: vi.fn() }));
const { applyNow } = await import('./pwa');

describe('applyNow', () => {
  it('applies a new version right after a page load', () => {
    expect(applyNow('/', 3_000)).toBe(true);
    expect(applyNow('/profile', 19_000)).toBe(true);
  });
  it('asks once the user has been working', () => {
    expect(applyNow('/profile', 21_000)).toBe(false);
  });
  it('never reloads the till by itself', () => {
    expect(applyNow('/pos', 1_000)).toBe(false);
  });
});
