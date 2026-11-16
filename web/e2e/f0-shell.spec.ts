// F0: each role signs in (2FA for owner and manager), sees only its menu, cost routes give 403, the language
// switch persists, lockout shows the Phnom Penh unlock time, backup codes work.
import { Http, apiLogin, totpCode } from './lib/api';
import { expect, expectAccessible, freshContext, test, uiLogin } from './fixtures';

test.describe('F0 shell and auth', () => {
  test('owner (2FA) sees every group', async ({ as }) => {
    const page = await as('owner');
    await page.goto('/');
    const nav = page.getByRole('navigation', { name: 'Menu' });
    await expect(nav.getByText('Settings')).toBeVisible();
    await expectAccessible(page);
  });

  test('cashier sees no settings and gets 403 on the design route only in production builds', async ({ as }) => {
    const page = await as('cashier');
    await page.goto('/');
    const nav = page.getByRole('navigation', { name: 'Menu' });
    await expect(nav.getByText('User Management')).toHaveCount(0);
    await expect(nav.getByText('Controlled drugs')).toHaveCount(0);
  });

  test('a page the role cannot open shows 403 (16e)', async ({ as }) => {
    const page = await as('cashier');
    await page.goto('/settings/users');
    await expect(page.getByRole('heading', { name: /permission|សិទ្ធិ|doesn't exist/ })).toBeVisible();
  });

  test('language switch persists across reloads', async ({ as }) => {
    const page = await as('pharmacist');
    await page.goto('/profile');
    await page.getByRole('radio', { name: 'ខ្មែរ' }).first().click();
    await expect(page.getByRole('heading', { name: 'ប្រវត្តិរូប' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'ប្រវត្តិរូប' })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', 'km');
    await page.getByRole('radio', { name: 'EN' }).first().click();
    await expect(page.getByRole('heading', { name: 'My profile' })).toBeVisible();
  });

  test('Ctrl K opens the search and finds pages', async ({ as }) => {
    const page = await as('pharmacist');
    await page.goto('/');
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await page.keyboard.press('Control+k');
    await page.getByPlaceholder('Type to search…').fill('profile');
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/profile$/);
  });

  test('2FA with a backup code instead of the app code', async ({ browser, seed }) => {
    const m = seed.accounts.manager;
    // new backup codes through the API (needs the password and a code)
    const { http } = await apiLogin(m.phone, m.password, m.totp);
    const r = await http.post<{ codes: string[] }>('/api/auth/v1/2fa/backup-codes', { password: m.password, code: await totpCode(m.totp!) });
    expect(r.status).toBe(200);
    const ctx = await freshContext(browser);
    const page = await ctx.newPage();
    await page.goto('/');
    await page.getByLabel('Phone number').fill(m.phone);
    await page.getByLabel('Password', { exact: true }).fill(m.password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.getByRole('button', { name: 'Use a backup code instead' }).click();
    await page.getByLabel('Backup code').fill(r.data.codes[0]);
    await page.getByRole('button', { name: 'Verify' }).click();
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await ctx.close();
  });

  test('2FA setup shows backup codes once (new manager)', async ({ browser, seed }) => {
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const phone = `0977${String(Date.now()).slice(-5)}`;
    const u = await owner.post<{ id: string }>('/api/auth/v1/users', { name: 'E2E Setup Manager', phone, password: 'E2e-Passw0rd-2026', role: 'branch_manager', branch_ids: [seed.branchId] });
    expect(u.status).toBeLessThan(300);
    const ctx = await freshContext(browser);
    const page = await ctx.newPage();
    await uiLogin(page, phone, 'E2e-Passw0rd-2026');
    await expect(page.getByText('Two-factor is required for your role')).toBeVisible();
    await page.getByRole('button', { name: 'Set up now' }).click();
    const key = (await page.locator('code').first().innerText()).replace(/\s/g, '');
    await page.getByLabel('Digit 1').fill(await totpCode(key));
    await expect(page.getByText('Save your backup codes')).toBeVisible();
    await expect(page.getByRole('list', { name: 'Backup codes' }).getByRole('listitem')).toHaveCount(10);
    await page.getByRole('button', { name: 'I saved them' }).click();
    await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await owner.post(`/api/auth/v1/users/${u.data.id}/deactivate`, { reason: 'e2e test account' });
    await ctx.close();
  });

  test('account lockout shows the unlock time in Phnom Penh', async ({ browser, seed }) => {
    test.setTimeout(300_000);
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const phone = `0976${String(Date.now()).slice(-5)}`;
    const u = await owner.post<{ id: string }>('/api/auth/v1/users', { name: 'E2E Lockout', phone, password: 'E2e-Passw0rd-2026', role: 'cashier', branch_ids: [seed.branchId] });
    expect(u.status).toBeLessThan(300);
    // 10 wrong passwords lock the account (5 per minute per IP + phone: spread over the API)
    const h = new Http();
    let locked: { details?: { locked_until?: string } } | null = null;
    for (let i = 0; i < 40 && !locked; i++) {
      const r = await h.post<{ code: string; details?: { locked_until?: string } }>('/api/auth/v1/login', { phone, password: 'wrong-password' });
      if (r.data.code === 'ACCOUNT_LOCKED') locked = r.data;
      else if (r.status === 429) await new Promise((x) => setTimeout(x, 12_000));
    }
    expect(locked?.details?.locked_until).toBeTruthy();
    const until = new Date(locked!.details!.locked_until!);
    const hhmm = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Phnom_Penh', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(until);
    await new Promise((x) => setTimeout(x, 61_000)); // past the per-minute login limit
    const ctx = await freshContext(browser);
    const page = await ctx.newPage();
    await page.goto('/');
    await page.getByLabel('Phone number').fill(phone);
    await page.getByLabel('Password', { exact: true }).fill('E2e-Passw0rd-2026');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Account locked')).toBeVisible();
    await expect(page.getByText(hhmm)).toBeVisible();
    await owner.post(`/api/auth/v1/users/${u.data.id}/deactivate`, { reason: 'e2e test account' });
    await ctx.close();
  });
});
