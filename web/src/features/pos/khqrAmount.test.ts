import { describe, expect, it } from 'vitest';
import { rielDue } from './Khqr';

describe('rielDue', () => {
  it('rounds to 100 riel half up, as the invoice total_khr', () => {
    expect(rielDue(2.7, 4100)).toBe(11100); // 11 070 → up (was ceil: same)
    expect(rielDue(2.62, 4100)).toBe(10700); // 10 742 → down (ceil gave 10 800: an overpaying QR)
    expect(rielDue(4.5, 4100)).toBe(18500); // 18 450: half goes up
    expect(rielDue(5.4, 4100)).toBe(22100);
  });
});
