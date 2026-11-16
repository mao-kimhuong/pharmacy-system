// Playwright global setup: makes sure the e2e accounts exist on the stack (through the public API, like
// scripts/smoke.py) and writes them to e2e/.auth/seed.json. Safe to repeat: existing accounts are reused.
//
// Owner: E2E_OWNER_PHONE / E2E_OWNER_PASSWORD (+ E2E_OWNER_TOTP, the base32 secret, if 2FA is on). Without them
// the first owner is created with `docker compose -p $E2E_COMPOSE_PROJECT exec auth ... create-owner` (only works
// on a stack that has no owner yet, e.g. a throwaway stack).
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { BASE, Http, apiLogin, secretFromUri, totpCode, waitFor } from './lib/api';
import { checkServerClock } from './lib/clock';
import { ensureSalesData, type SalesData } from './lib/data';

export const SEED_FILE = path.resolve(import.meta.dirname, '.auth/seed.json');
export const PIN = '482915';
export const PASSWORD = 'E2e-Passw0rd-2026';

export type Role = 'owner' | 'manager' | 'pharmacist' | 'pharmacist2' | 'cashier';
export interface Account { id?: string; name: string; phone: string; password: string; totp?: string; role: string }
export interface Seed { branchId: string; branchCode: string; accounts: Record<Role, Account>; extra: { sales?: SalesData } & Record<string, unknown> }

const rand = (n: number) => Array.from({ length: n }, () => Math.floor(Math.random() * 10)).join('');

export function loadSeed(): Seed {
  return JSON.parse(fs.readFileSync(SEED_FILE, 'utf8')) as Seed;
}
export function saveSeed(s: Seed) {
  fs.mkdirSync(path.dirname(SEED_FILE), { recursive: true });
  fs.writeFileSync(SEED_FILE, JSON.stringify(s, null, 2));
}

async function enable2fa(http: Http): Promise<string> {
  const setup = await http.post<{ otpauth_uri: string }>('/api/auth/v1/2fa/setup');
  if (setup.status !== 200) throw new Error(`2fa setup: ${JSON.stringify(setup.data)}`);
  const secret = secretFromUri(setup.data.otpauth_uri);
  const en = await http.post<{ access_token: string }>('/api/auth/v1/2fa/enable', { code: await totpCode(secret) });
  if (en.status !== 200) throw new Error(`2fa enable: ${JSON.stringify(en.data)}`);
  http.token = en.data.access_token;
  return secret;
}

/** Logs in; turns 2FA on the first time for roles that must have it. */
async function login(a: Account): Promise<Http> {
  const { http, res } = await apiLogin(a.phone, a.password, a.totp);
  if (res.mfa_setup_required) a.totp = await enable2fa(http);
  return http;
}

function ownerFromEnvOrCreate(): Account {
  if (process.env.E2E_OWNER_PHONE && process.env.E2E_OWNER_PASSWORD) {
    return { name: 'Owner', phone: process.env.E2E_OWNER_PHONE, password: process.env.E2E_OWNER_PASSWORD, totp: process.env.E2E_OWNER_TOTP, role: 'owner' };
  }
  const project = process.env.E2E_COMPOSE_PROJECT ?? 'pharmacy';
  const phone = `0979${rand(5)}`;
  const args = ['compose', '-p', project, 'exec', '-T', '-e', `OWNER_PASSWORD=${PASSWORD}`, 'auth', 'python', '-m', 'auth_service.cli', 'create-owner', '--name', 'E2E Owner', '--phone', phone];
  try {
    execFileSync('docker', args, { stdio: 'pipe' });
  } catch (e) {
    const msg = e instanceof Error && 'stderr' in e ? String((e as { stderr: Buffer }).stderr) : String(e);
    throw new Error(`Could not create the e2e owner (${msg.trim()}). On a stack that already has an owner, set E2E_OWNER_PHONE, E2E_OWNER_PASSWORD and E2E_OWNER_TOTP.`, { cause: e });
  }
  return { name: 'E2E Owner', phone, password: PASSWORD, role: 'owner' };
}

export default async function seed() {
  await checkServerClock(BASE); // a drifted Docker clock fails every 2FA login: say so before any test runs
  let s: Seed | null = null;
  try {
    s = loadSeed();
  } catch {
    /* first run */
  }
  const owner = s?.accounts.owner ?? ownerFromEnvOrCreate();
  const oh = await login(owner);

  let branchId = s?.branchId;
  let branchCode = s?.branchCode;
  if (!branchId) {
    branchCode = `E2E${rand(4)}`;
    const b = await oh.post<{ id: string }>('/api/branch/v1/branches', { code: branchCode, name_km: `សាខា ${branchCode}`, name_en: `Branch ${branchCode}` });
    if (b.status !== 201 && b.status !== 200) throw new Error(`branch: ${JSON.stringify(b.data)}`);
    branchId = b.data.id;
  }

  const wanted: Record<Exclude<Role, 'owner'>, { name: string; role: string; is_pharmacist: boolean }> = {
    manager: { name: 'E2E Manager', role: 'branch_manager', is_pharmacist: false },
    pharmacist: { name: 'E2E Pharmacist', role: 'pharmacist', is_pharmacist: true },
    pharmacist2: { name: 'E2E Pharmacist Two', role: 'pharmacist', is_pharmacist: true },
    cashier: { name: 'E2E Cashier', role: 'cashier', is_pharmacist: false },
  };
  const accounts = { owner } as Record<Role, Account>;
  for (const [key, w] of Object.entries(wanted) as [Exclude<Role, 'owner'>, (typeof wanted)['manager']][]) {
    let a = s?.accounts[key];
    if (!a) {
      const phone = `0978${rand(5)}`;
      // auth learns about the new branch over RabbitMQ: retry while it is UNKNOWN_BRANCH
      const created = await waitFor(async () => {
        const r = await oh.post<{ id: string; code?: string }>('/api/auth/v1/users', { ...w, phone, password: PASSWORD, branch_ids: [branchId] });
        if (r.data.code === 'UNKNOWN_BRANCH') return null;
        if (r.status >= 300) throw new Error(`user ${key}: ${JSON.stringify(r.data)}`);
        return r.data;
      });
      a = { id: created.id, name: w.name, phone, password: PASSWORD, role: w.role };
    }
    const h = await login(a);
    const me = await h.get<{ has_pin: boolean; id: string }>('/api/auth/v1/me');
    a.id = me.data.id;
    if (!me.data.has_pin) {
      const r = await h.put('/api/auth/v1/me/pin', { password: a.password, pin: PIN });
      if (r.status >= 300) throw new Error(`pin ${key}: ${JSON.stringify(r.data)}`);
    }
    accounts[key] = a;
  }
  const ome = await oh.get<{ id: string; has_pin: boolean }>('/api/auth/v1/me');
  owner.id = ome.data.id;
  if (!ome.data.has_pin) await oh.put('/api/auth/v1/me/pin', { password: owner.password, pin: PIN });

  // the e2e stack uses every module (the owner turns these on in Settings → Feature switches)
  const feats = await oh.get<{ key: string; enabled: boolean }[]>('/api/branch/v1/features');
  for (const f of feats.data.filter((x) => !x.enabled && x.key !== 'ai')) await oh.put(`/api/branch/v1/features/${f.key}`, { enabled: true });
  const extra = s?.extra ?? {};
  saveSeed({ branchId: branchId!, branchCode: branchCode!, accounts, extra });
  extra.sales = await ensureSalesData(oh, branchId!, extra.sales);
  saveSeed({ branchId: branchId!, branchCode: branchCode!, accounts, extra });
}
