// Two-factor login from My profile and the owner's reset, against the stack.
import type { Page } from '@playwright/test';
import { Http, apiLogin, secretFromUri, totpCode } from './lib/api';
import { expect, freshContext, test, uiLogin } from './fixtures';
import { PIN, loadSeed } from './seed';

const PW = 'E2e-TwoFactor-2026!';

async function newUser(owner: Http, role: string, branchId: string) {
  const phone = `0978${String(Date.now()).slice(-5)}`;
  const r = await owner.post<{ id: string; code?: string }>('/api/auth/v1/users', { name: `E2E 2FA ${phone}`, phone, password: PW, role, branch_ids: [branchId], is_pharmacist: false });
  if (r.status >= 300) throw new Error(JSON.stringify(r.data));
  return { id: r.data.id, phone, name: `E2E 2FA ${phone}` };
}

/** Turns 2FA on through the API; returns the key and the backup codes. */
async function turnOn(phone: string) {
  const { http } = await apiLogin(phone, PW);
  const setup = await http.post<{ otpauth_uri: string }>('/api/auth/v1/2fa/setup', {});
  const secret = secretFromUri(setup.data.otpauth_uri);
  const on = await http.post<{ backup_codes: string[] }>('/api/auth/v1/2fa/enable', { code: await totpCode(secret) });
  if (on.status >= 300) throw new Error(JSON.stringify(on.data));
  return { secret, codes: on.data.backup_codes };
}

const digits = (page: Page) => page.getByLabel(/Digit 1|ខ្ទង់ទី 1/);

test.describe('Two-factor login', () => {
  let owner: Http;
  let branchId: string;
  test.beforeAll(async () => {
    const seed = loadSeed();
    branchId = seed.branchId;
    owner = (await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp)).http;
  });

  test('cashier: turn on, log out, log in with a code, turn off', async ({ browser }) => {
    test.setTimeout(240_000); // four one-time codes: each waits for a fresh 30 s step
    const u = await newUser(owner, 'cashier', branchId);
    const ctx = await freshContext(browser);
    const page = await ctx.newPage();
    await uiLogin(page, u.phone, PW);
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await page.goto('/profile');
    await expect(page.getByRole('heading', { name: 'Security' })).toBeVisible();
    await page.getByRole('button', { name: 'Turn on' }).click();
    const dlg = page.getByRole('dialog');
    const qr = dlg.getByRole('img', { name: /QR/ });
    await expect(qr).toBeVisible();
    expect(await qr.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth > 0)).toBe(true); // the QR really draws
    const secret = (await dlg.getByTestId('totp-secret').innerText()).replace(/\s/g, '');
    await digits(page).fill(await totpCode(secret));
    await expect(dlg.getByRole('list', { name: 'Backup codes' }).getByRole('listitem')).toHaveCount(10);
    await dlg.getByRole('button', { name: /saved/i }).click();
    await expect(page.getByText('10 backup codes left')).toBeVisible();

    await page.getByRole('button', { name: new RegExp(u.name) }).click();
    await page.getByRole('menuitem', { name: 'Log out' }).or(page.getByRole('button', { name: 'Log out' })).click();
    await uiLogin(page, u.phone, PW, secret);
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();

    await page.goto('/profile');
    await page.getByRole('button', { name: 'Turn off' }).click();
    const off = page.getByRole('dialog');
    await off.getByLabel(/^Password/).fill('wrong-password');
    await digits(page).fill(await totpCode(secret));
    await off.getByRole('button', { name: 'Turn off' }).click();
    await expect(off.getByText('Wrong password.')).toBeVisible();
    await off.getByLabel(/^Password/).fill(PW);
    await digits(page).fill(await totpCode(secret));
    await off.getByRole('button', { name: 'Turn off' }).click();
    await expect(off).toBeHidden();
    await expect(page.getByRole('button', { name: 'Turn on' })).toBeVisible();
    await ctx.close();
    // no code asked any more
    await apiLogin(u.phone, PW);
  });

  test('a new owner: forced setup, a real QR, a wrong code explained, then the dashboard', async ({ browser }) => {
    test.setTimeout(180_000);
    const u = await newUser(owner, 'owner', branchId);
    const ctx = await freshContext(browser);
    const page = await ctx.newPage();
    await uiLogin(page, u.phone, PW);
    await page.getByRole('button', { name: 'Set up now' }).click();
    const qr = page.getByRole('img', { name: /QR/ });
    await expect(qr).toBeVisible();
    const size = await qr.evaluate((i: HTMLImageElement) => ({ w: i.naturalWidth, h: i.naturalHeight, src: i.src.slice(0, 26) }));
    expect(size.w).toBeGreaterThan(100);
    expect(size.h).toBeGreaterThan(100);
    expect(size.src).toBe('data:image/svg+xml;base64,');
    const secret = (await page.getByTestId('totp-secret').innerText()).replace(/\s/g, '');
    expect(secret.length).toBeGreaterThanOrEqual(16); // also there as text, for typing by hand
    await digits(page).fill('000000');
    await expect(page.getByText('The code is wrong or has expired.')).toBeVisible();
    await digits(page).fill(await totpCode(secret));
    await page.getByRole('button', { name: /saved/i }).click();
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await page.reload(); // the session lives in the refresh cookie set by /2fa/enable
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await ctx.close();
  });

  test('errors in Khmer, and a manager cannot turn it off through the API', async ({ browser }) => {
    test.setTimeout(180_000);
    const u = await newUser(owner, 'cashier', branchId);
    await turnOn(u.phone);
    const m = await newUser(owner, 'branch_manager', branchId);
    const on = await turnOn(m.phone);
    const { http } = await apiLogin(m.phone, PW, on.secret);
    const refused = await http.post<{ code: string }>('/api/auth/v1/me/2fa/disable', { password: PW, backup_code: on.codes[0] });
    expect(refused.status).toBe(403);
    expect(refused.data.code).toBe('MFA_REQUIRED_FOR_ROLE');
    const ctx = await freshContext(browser, 'km');
    const page = await ctx.newPage();
    await page.goto('/');
    await page.getByLabel(/លេខទូរស័ព្ទ/).fill(u.phone);
    await page.getByLabel('ពាក្យសម្ងាត់', { exact: true }).fill(PW);
    await page.getByRole('button', { name: 'ចូល', exact: true }).click();
    await digits(page).fill('000000');
    await expect(page.getByText('លេខកូដមិនត្រឹមត្រូវ ឬផុតកំណត់។').first()).toBeVisible();
    await ctx.close();
  });

  test('owner resets a cashier’s 2FA with the PIN', async ({ as }) => {
    const u = await newUser(owner, 'cashier', branchId);
    await turnOn(u.phone);
    const page = await as('owner');
    await page.goto('/settings/users');
    await page.getByRole('textbox', { name: 'Search' }).fill(u.phone);
    await page.getByRole('button', { name: `More · ${u.name}` }).click();
    await page.getByText('Reset 2FA').click();
    const reset = page.waitForResponse((r) => r.url().endsWith('/2fa/reset'));
    await page.keyboard.type(PIN); // 6 digits submit by themselves
    expect((await reset).status()).toBe(204);
    expect((await apiLogin(u.phone, PW)).res.mfa_required ?? false).toBe(false); // no code asked any more
  });

  test('a manager only sees Reset, and the new key replaces the old one after confirming', async ({ browser }) => {
    const u = await newUser(owner, 'branch_manager', branchId);
    const { secret, codes } = await turnOn(u.phone);
    const ctx = await freshContext(browser);
    const page = await ctx.newPage();
    await uiLogin(page, u.phone, PW, secret);
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await page.goto('/profile');
    await expect(page.getByText('Required for your role')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Turn off' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Reset 2FA' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel(/^Password/).fill(PW);
    await dlg.getByRole('button', { name: 'Use a backup code instead' }).click();
    await dlg.getByLabel(/^Backup code/).fill(codes[0]);
    await dlg.getByRole('button', { name: 'Continue' }).click();
    const fresh = (await dlg.getByTestId('totp-secret').innerText()).replace(/\s/g, '');
    expect(fresh).not.toBe(secret);
    await digits(page).fill(await totpCode(fresh));
    await dlg.getByRole('button', { name: /Confirm/ }).click();
    await expect(dlg.getByRole('list', { name: 'Backup codes' }).getByRole('listitem')).toHaveCount(10);
    await dlg.getByRole('button', { name: 'Done' }).click();
    await ctx.close();
    await apiLogin(u.phone, PW, fresh); // the new key logs in
  });
});

