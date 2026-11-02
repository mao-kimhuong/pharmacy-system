// Display helpers. Amounts always come from the API (strings for NUMERIC); these only format them.
export const TIMEZONE = 'Asia/Phnom_Penh';

export type Lang = 'km' | 'en';

const KHMER_DIGITS = ['០', '១', '២', '៣', '៤', '៥', '៦', '៧', '៨', '៩'];
/** Khmer digits for counts in running text (design: "១–៨ នៃ ៤២៨"). Money and tables keep Latin digits. */
export function khmerDigits(s: string | number): string {
  return String(s).replace(/[0-9]/g, (d) => KHMER_DIGITS[Number(d)]);
}

function toNumber(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** USD: "$1,234.50"; negative "−$3.00". */
export function usd(v: string | number | null | undefined): string {
  const n = toNumber(v);
  if (n === null) return '—';
  const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? '−' : ''}$${s}`;
}

/** KHR as the API gives it (whole riel): "៛41,000". */
export function khr(v: string | number | null | undefined): string {
  const n = toNumber(v);
  if (n === null) return '—';
  const s = Math.abs(Math.round(n)).toLocaleString('en-US');
  return `${n < 0 ? '−' : ''}៛${s}`;
}

/** Rounds riel to whole hundreds, half up (what the API does for KHR totals and cash). */
export function roundRiel(v: number): number {
  return Math.sign(v) * Math.floor(Math.abs(v) / 100 + 0.5) * 100;
}

/** Converts a USD amount to KHR at a rate (riel per USD), rounded to 100 riel. Display only. */
export function usdToKhr(amount: string | number, rate: number): number {
  return roundRiel((toNumber(amount) ?? 0) * rate);
}

export function qty(v: string | number | null | undefined, digits = 0): string {
  const n = toNumber(v);
  if (n === null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: Math.max(digits, 3), minimumFractionDigits: digits });
}

export function pct(v: string | number | null | undefined, digits = 1): string {
  const n = toNumber(v);
  if (n === null) return '—';
  return `${n.toFixed(digits)}%`;
}

const parts = (d: Date, opts: Intl.DateTimeFormatOptions) =>
  Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', { timeZone: TIMEZONE, ...opts }).formatToParts(d).map((p) => [p.type, p.value]),
  );

function asDate(v: string | Date): Date {
  if (v instanceof Date) return v;
  // A plain date (YYYY-MM-DD) is a calendar day, not an instant: keep it as that day.
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return new Date(`${v}T12:00:00+07:00`);
  return new Date(v);
}

/** DD/MM/YYYY in Phnom Penh. */
export function date(v: string | Date | null | undefined): string {
  if (!v) return '—';
  const p = parts(asDate(v), { day: '2-digit', month: '2-digit', year: 'numeric' });
  return `${p.day}/${p.month}/${p.year}`;
}

/** DD/MM/YYYY HH:mm in Phnom Penh. */
export function dateTime(v: string | Date | null | undefined): string {
  if (!v) return '—';
  const p = parts(asDate(v), {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  });
  return `${p.day}/${p.month}/${p.year} ${p.hour}:${p.minute}`;
}

export function time(v: string | Date | null | undefined): string {
  if (!v) return '—';
  const p = parts(asDate(v), { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  return `${p.hour}:${p.minute}`;
}

/** Today's date (YYYY-MM-DD) in Phnom Penh. */
export function todayIso(now: Date = new Date()): string {
  const p = parts(now, { day: '2-digit', month: '2-digit', year: 'numeric' });
  return `${p.year}-${p.month}-${p.day}`;
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function firstOfMonth(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

/** Whole days from today (Phnom Penh) to a date; negative when past. */
export function daysUntil(iso: string, today = todayIso()): number {
  return Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
}

export function initials(name: string): string {
  const w = name.trim().split(/\s+/);
  return ((w[0]?.[0] ?? '') + (w.length > 1 ? w[w.length - 1][0] : '')).toUpperCase();
}
