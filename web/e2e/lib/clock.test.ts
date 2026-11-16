import { describe, expect, it } from 'vitest';
import { clockSkewProblem } from './clock';

const NOW = Date.parse('2026-11-12T13:00:00Z');
const at = (seconds: number) => new Date(NOW + seconds * 1000).toUTCString();

describe('clockSkewProblem', () => {
  it('accepts clocks within 15 s either way', () => {
    expect(clockSkewProblem(at(0), NOW, 'http://x')).toBeNull();
    expect(clockSkewProblem(at(-15), NOW, 'http://x')).toBeNull();
    expect(clockSkewProblem(at(15), NOW, 'http://x')).toBeNull();
  });

  it('names how far behind the stack is and how to fix it', () => {
    const msg = clockSkewProblem(at(-47), NOW, 'http://localhost:8088');
    expect(msg).toContain('47 s behind');
    expect(msg).toContain('INVALID_MFA_CODE');
    expect(msg).toContain('hwclock -s');
  });

  it('says ahead when the stack is ahead', () => {
    expect(clockSkewProblem(at(90), NOW, 'http://x')).toContain('90 s ahead of');
  });

  it('cannot compare without a Date header', () => {
    expect(clockSkewProblem(null, NOW, 'http://x')).toBeNull();
    expect(clockSkewProblem('not a date', NOW, 'http://x')).toBeNull();
  });
});
