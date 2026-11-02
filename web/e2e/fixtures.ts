// Per-role signed-in browser contexts, created once per worker (logins are rate limited and 2FA codes are
// single-use per 30 s). Each test opens fresh pages in its role's context; the app refreshes the access token from
// the httpOnly cookie on load.
import { test as base, expect, type Browser, type BrowserContext, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { totpCode } from './lib/api';
import { loadSeed, type Role, type Seed } from './seed';

export async function uiLogin(page: Page, phone: string, password: string, totp?: string) {
  await page.goto('/');
  await page.getByLabel(/Phone number|លេខទូរស័ព្ទ/).fill(phone);
  await page.getByLabel(/^(Password|ពាក្យសម្ងាត់)$/).fill(password);
  await page.getByRole('button', { name: /^(Sign in|ចូល)$/ }).click();
  if (totp) {
    await page.getByLabel(/Digit 1|ខ្ទង់ទី 1/).waitFor();
    await page.getByLabel(/Digit 1|ខ្ទង់ទី 1/).fill(await totpCode(totp));
  }
}

/** A fresh context (not signed in) in the given language; the app's default on a new device is Khmer. */
export async function freshContext(browser: Browser, lang: 'en' | 'km' = 'en', viewport = { width: 1366, height: 768 }) {
  const ctx = await browser.newContext({ viewport, locale: 'en-GB', timezoneId: 'Asia/Phnom_Penh' });
  await ctx.addInitScript((l) => { if (!localStorage.getItem('pharmacy.lang')) localStorage.setItem('pharmacy.lang', l); }, lang);
  return ctx;
}

async function contextFor(browser: Browser, seed: Seed, role: Role, lang: 'en' | 'km'): Promise<BrowserContext> {
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'en-GB', timezoneId: 'Asia/Phnom_Penh' });
  await ctx.addInitScript((l) => { if (!localStorage.getItem('pharmacy.lang')) localStorage.setItem('pharmacy.lang', l); }, lang);
  const page = await ctx.newPage();
  const a = seed.accounts[role];
  await uiLogin(page, a.phone, a.password, a.totp);
  await expect(page.getByRole('navigation', { name: /Menu|ម៉ឺនុយ/ })).toBeVisible();
  // choose the e2e branch in the switcher (stored per device)
  await page.evaluate((id) => localStorage.setItem('pharmacy.branch', id), seed.branchId);
  await page.close();
  return ctx;
}

type Fixtures = { seed: Seed; as: (role: Role) => Promise<Page> };
type WorkerFixtures = { contexts: Map<Role, BrowserContext>; workerSeed: Seed };

export const test = base.extend<Fixtures, WorkerFixtures>({
  workerSeed: [async ({}, use) => use(loadSeed()), { scope: 'worker' }],
  contexts: [async ({}, use) => {
    const m = new Map<Role, BrowserContext>();
    await use(m);
    for (const c of m.values()) await c.close();
  }, { scope: 'worker' }],
  seed: async ({ workerSeed }, use) => use(workerSeed),
  as: async ({ browser, contexts, workerSeed }, use) => {
    const pages: Page[] = [];
    await use(async (role) => {
      let ctx = contexts.get(role);
      if (!ctx) {
        ctx = await contextFor(browser, workerSeed, role, 'en');
        contexts.set(role, ctx);
      }
      const p = await ctx.newPage();
      pages.push(p);
      return p;
    });
    for (const p of pages) await p.close();
  },
});
export { expect };

/** axe on the current page: no serious or critical violations. */
export async function expectAccessible(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  const bad = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(', ')}`)).toEqual([]);
}
