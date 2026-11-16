// F7 user management + settings against the stack.
import { apiLogin } from './lib/api';
import { expect, freshContext, test, uiLogin } from './fixtures';

const PW = 'E2e-Cashier-2026!';

test.describe('F7 users and settings', () => {
  test('owner creates a cashier who sees only sales menus; a role change shows in the User Log', async ({ as, seed, browser }) => {
    const phone = `0976${String(Date.now()).slice(-5)}`;
    const name = `E2E Cashier ${phone}`;
    const owner = await as('owner');
    await owner.goto('/settings/users');
    await owner.getByRole('button', { name: '+ New user' }).click();
    const dlg = owner.getByRole('dialog');
    await dlg.getByLabel(/^Name/).fill(name);
    await dlg.getByLabel(/^Phone/).fill(phone);
    await dlg.getByLabel(/^Password/).fill(PW);
    await dlg.getByLabel(/^Role/).selectOption('cashier');
    await dlg.getByLabel(/^Branches/).fill(seed.branchCode);
    await owner.getByRole('listbox').getByRole('option', { name: new RegExp(seed.branchCode) }).click();
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(dlg).toBeHidden();
    await owner.getByRole('textbox', { name: 'Search' }).fill(phone);
    await expect(owner.getByRole('row', { name: new RegExp(name) })).toBeVisible();

    const ctx = await freshContext(browser);
    const cp = await ctx.newPage();
    await uiLogin(cp, phone, PW);
    const menu = cp.getByRole('navigation', { name: 'Menu' });
    await expect(menu).toBeVisible();
    // the cashier role's default grants (auth permissions.py): POS, no user management, settings = own profile only
    await menu.getByRole('button', { name: 'POS' }).click();
    await expect(menu.getByRole('link', { name: 'POS', exact: true })).toBeVisible();
    for (const g of ['User Management', 'Prescriptions', 'Controlled drugs']) await expect(menu.getByRole('button', { name: g })).toHaveCount(0);
    await menu.getByRole('button', { name: 'Settings' }).click();
    for (const hidden of ['Branches', 'Feature switches', 'Exchange rate', 'Telegram']) await expect(menu.getByRole('link', { name: hidden, exact: true })).toHaveCount(0);
    await expect(menu.getByRole('link', { name: 'My profile' })).toBeVisible();
    await cp.goto('/settings/users');
    await expect(cp.getByRole('heading', { name: "You don't have permission to view this page" })).toBeVisible();
    await ctx.close();

    await owner.getByRole('row', { name: new RegExp(name) }).getByRole('button', { name: 'Edit' }).click();
    await owner.getByRole('dialog').getByLabel(/^Role/).selectOption('pharmacist');
    await owner.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
    await expect(owner.getByRole('dialog')).toBeHidden();

    await owner.goto('/settings/user-log');
    await owner.getByRole('textbox', { name: 'Action' }).fill('user.updated');
    await owner.getByRole('row').filter({ hasText: 'user.updated' }).filter({ hasText: 'role' }).first().click();
    const drawer = owner.getByRole('dialog');
    const row = drawer.getByRole('row').filter({ hasText: /^role/ });
    await expect(row).toContainText('cashier');
    await expect(row).toContainText('pharmacist');

    // clean up: deactivate with a reason
    await owner.goto('/settings/users');
    await owner.getByRole('textbox', { name: 'Search' }).fill(phone);
    await owner.getByRole('row', { name: new RegExp(name) }).getByRole('button', { name: /^More/ }).click();
    await owner.getByRole('menuitem', { name: 'Deactivate' }).click();
    await owner.getByRole('dialog').getByLabel(/Reason/).fill('e2e: test account');
    await owner.getByRole('dialog').getByRole('button', { name: 'Deactivate' }).click();
    await expect(owner.getByRole('dialog')).toBeHidden();
  });

  test('roles: the owner role is locked; permission groups come from the API', async ({ as }) => {
    const page = await as('owner');
    await page.goto('/settings/roles');
    await page.getByRole('button', { name: /^Owner/ }).click();
    await expect(page.getByText('Owner role is locked')).toBeVisible();
    await page.getByRole('button', { name: /^Cashier/ }).click();
    await expect(page.getByRole('checkbox').first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Save permissions' })).toBeDisabled();
  });

  test('manager sets the exchange rate and sees it in the history', async ({ as, seed }) => {
    const page = await as('manager');
    await page.goto('/settings/exchange-rate');
    await page.getByLabel(/New rate/).fill('4105');
    await page.getByRole('button', { name: 'Set rate' }).click();
    await expect(page.getByText('Rate saved')).toBeVisible();
    const first = page.getByRole('row').nth(1);
    await expect(first).toContainText('៛4,105');
    // put the rate back for the other specs
    const { http } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    expect((await http.put(`/api/sales/v1/exchange-rates/${seed.branchId}`, { khr_per_usd: 4100 })).status).toBe(200);
  });

  test('branch settings: receipt footer saved', async ({ as, seed }) => {
    const page = await as('owner');
    await page.goto(`/settings/branches/${seed.branchId}`);
    const footer = `E2E thank you ${Date.now()}`;
    await page.getByLabel('Receipt footer').fill(footer);
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Settings saved')).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('Receipt footer')).toHaveValue(footer);
  });

  test('a device signed out from another one must sign in again', async ({ seed, browser }) => {
    const a = seed.accounts.cashier;
    const one = await freshContext(browser);
    // a user agent of its own, to find this device in the list
    const ua = `E2E-Device-${Date.now()}`;
    const two = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'en-GB', timezoneId: 'Asia/Phnom_Penh', userAgent: ua });
    await two.addInitScript(() => localStorage.setItem('pharmacy.lang', 'en'));
    const p1 = await one.newPage();
    const p2 = await two.newPage();
    await uiLogin(p2, a.phone, a.password, a.totp);
    await expect(p2.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await uiLogin(p1, a.phone, a.password, a.totp);
    await expect(p1.getByRole('navigation', { name: 'Menu' })).toBeVisible();
    await p1.goto('/profile');
    await p1.getByRole('row').filter({ hasText: ua }).getByRole('button', { name: 'Sign out' }).click();
    await p1.getByRole('dialog').getByRole('button', { name: 'Sign out' }).click();
    await expect(p1.getByRole('dialog')).toBeHidden();
    await p2.reload();
    await expect(p2.getByLabel('Phone number')).toBeVisible({ timeout: 15_000 });
    await one.close();
    await two.close();
  });

  test('new backup codes need the password and a code', async ({ as }) => {
    const page = await as('owner');
    await page.goto('/profile');
    await page.getByRole('button', { name: 'New backup codes' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel(/Password/).fill('not-the-password');
    await expect(dlg.getByRole('button', { name: 'Continue' })).toBeDisabled(); // no code yet
    await dlg.getByLabel('Digit 1').fill('000000');
    await dlg.getByRole('button', { name: 'Continue' }).click();
    await expect(dlg.getByText('Wrong password.')).toBeVisible();
  });
  test('telegram: a branch chat is saved; without a bot token the test says so', async ({ as, seed }) => {
    const page = await as('owner');
    await page.goto('/settings/telegram');
    const card = page.locator('div').filter({ hasText: new RegExp(`^${seed.branchCode} · `) }).first();
    await card.getByLabel('Chat ID').fill(`-100${String(Date.now()).slice(-10)}`); // new each run: the same id leaves Save disabled
    await card.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Settings saved')).toBeVisible();
    await card.getByRole('button', { name: 'Send test' }).click();
    await expect(page.getByRole('alert').filter({ hasText: /Telegram/ }).first()).toBeVisible();
  });

  test('a branch manager cannot open roles or feature switches', async ({ as }) => {
    const page = await as('manager');
    for (const path of ['/settings/roles', '/settings/features']) {
      await page.goto(path);
      await expect(page.getByRole('heading', { name: "You don't have permission to view this page" })).toBeVisible();
    }
  });
});
