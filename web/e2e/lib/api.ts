// Minimal API client for the seed and checks (Node fetch, same public API as the app, through Traefik).
import fs from 'node:fs';
import path from 'node:path';
import { TOTP } from 'otpauth';

export const BASE = process.env.BASE_URL ?? 'http://localhost';

export class Http {
  constructor(public token: string | null = null) {}
  async req<T = unknown>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<{ status: number; data: T }> {
    const res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data: unknown = text;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      /* not JSON */
    }
    return { status: res.status, data: data as T };
  }
  get<T = unknown>(p: string) { return this.req<T>('GET', p); }
  post<T = unknown>(p: string, b?: unknown, h?: Record<string, string>) { return this.req<T>('POST', p, b ?? {}, h); }
  put<T = unknown>(p: string, b?: unknown) { return this.req<T>('PUT', p, b ?? {}); }
  patch<T = unknown>(p: string, b?: unknown) { return this.req<T>('PATCH', p, b ?? {}); }
}

export const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() });

// One TOTP step per user and 30 s window (the API refuses a replayed step): wait for a fresh step.
// The used steps are kept in a file: the seed and the tests run in different processes.
const STEPS_FILE = path.resolve(import.meta.dirname, '../.auth/totp-steps.json');
function readSteps(): Record<string, number> {
  try {
    return JSON.parse(fs.readFileSync(STEPS_FILE, 'utf8')) as Record<string, number>;
  } catch {
    return {};
  }
}
export async function totpCode(secret: string): Promise<string> {
  const totp = new TOTP({ secret, digits: 6, period: 30, algorithm: 'SHA1' });
  for (;;) {
    const step = Math.floor(Date.now() / 30_000);
    const used = readSteps();
    // stay clear of the last 2 s of a window (the request might land in the next one)
    if ((used[secret] ?? -1) < step && Date.now() % 30_000 < 28_000) {
      used[secret] = step;
      fs.mkdirSync(path.dirname(STEPS_FILE), { recursive: true });
      fs.writeFileSync(STEPS_FILE, JSON.stringify(used));
      return totp.generate();
    }
    await new Promise((r) => setTimeout(r, (step + 1) * 30_000 - Date.now() + 300));
  }
}

export function secretFromUri(uri: string): string {
  return new URL(uri).searchParams.get('secret')!;
}

export async function waitFor<T>(fn: () => Promise<T | null | undefined>, tries = 40, ms = 500): Promise<T> {
  for (let i = 0; i < tries; i++) {
    const v = await fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, ms));
  }
  throw new Error('waitFor: gave up');
}

interface TokenResponse { access_token?: string | null; mfa_required?: boolean; mfa_token?: string | null; mfa_setup_required?: boolean; code?: string }

/** Logs in through the API (password, then TOTP when the account has it). */
export async function apiLogin(phone: string, password: string, totpSecret?: string): Promise<{ http: Http; res: TokenResponse }> {
  const h = new Http();
  const r = await h.post<TokenResponse>('/api/auth/v1/login', { phone, password });
  if (r.status !== 200) throw new Error(`login ${phone}: ${r.status} ${JSON.stringify(r.data)}`);
  let res = r.data;
  if (res.mfa_required) {
    if (!totpSecret) throw new Error(`login ${phone}: 2FA code needed`);
    const r2 = await h.post<TokenResponse>('/api/auth/v1/login/2fa', { mfa_token: res.mfa_token, code: await totpCode(totpSecret) });
    if (r2.status !== 200) throw new Error(`2fa ${phone}: ${r2.status} ${JSON.stringify(r2.data)}`);
    res = r2.data;
  }
  h.token = res.access_token ?? null;
  return { http: h, res };
}
