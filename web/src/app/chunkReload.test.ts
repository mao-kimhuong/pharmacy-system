import { describe, expect, it, vi } from 'vitest';
import { reloadOnceForChunk } from './chunkReload';

const memory = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };

describe('reloadOnceForChunk', () => {
  it('reloads once, then lets the error show', () => {
    const store = memory();
    const reload = vi.fn();
    expect(reloadOnceForChunk(100_000, store, reload)).toBe(true);
    expect(reloadOnceForChunk(105_000, store, reload)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });
  it('may reload again much later', () => {
    const store = memory();
    const reload = vi.fn();
    reloadOnceForChunk(100_000, store, reload);
    expect(reloadOnceForChunk(200_000, store, reload)).toBe(true);
  });
});
