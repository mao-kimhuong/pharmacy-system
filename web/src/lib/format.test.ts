import { addDays, date, dateTime, daysUntil, khmerDigits, khr, roundRiel, todayIso, usd, usdToKhr } from './format';

describe('money', () => {
  it('formats USD with 2 decimals and a real minus sign', () => {
    expect(usd('1234.5')).toBe('$1,234.50');
    expect(usd(-3)).toBe('−$3.00');
    expect(usd(null)).toBe('—');
  });
  it('formats KHR in whole riel', () => {
    expect(khr(41000)).toBe('៛41,000');
    expect(khr('17000')).toBe('៛17,000');
  });
  it('rounds riel to 100 half up, like the API', () => {
    expect(roundRiel(16_949)).toBe(16_900);
    expect(roundRiel(16_950)).toBe(17_000);
    expect(roundRiel(-150)).toBe(-200);
    expect(usdToKhr('4.15', 4100)).toBe(17_000);
    expect(usdToKhr('0.29', 4100)).toBe(1_200);
  });
});

describe('dates in Asia/Phnom_Penh', () => {
  it('shows DD/MM/YYYY of the Phnom Penh day', () => {
    // 2026-10-31 18:30 UTC is already 01/11 in Phnom Penh (UTC+7).
    expect(date('2026-10-31T18:30:00Z')).toBe('01/11/2026');
    expect(dateTime('2026-10-31T07:35:00Z')).toBe('31/10/2026 14:35');
    expect(date('2026-03-12')).toBe('12/03/2026');
  });
  it('knows today in Phnom Penh', () => {
    expect(todayIso(new Date('2026-10-31T18:30:00Z'))).toBe('2026-11-01');
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(daysUntil('2026-11-10', '2026-11-01')).toBe(9);
  });
  it('writes Khmer digits for counts', () => {
    expect(khmerDigits('1–8 of 428')).toBe('១–៨ of ៤២៨');
  });
});
