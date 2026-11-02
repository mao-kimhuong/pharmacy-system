// F8 accessibility: axe (WCAG 2 A/AA, no serious or critical findings) on every page without a parameter, as the
// owner, in English and Khmer; POS keyboard paths put the focus back in the scan box.
import { readFileSync } from 'node:fs';
import { expect, expectAccessible, test } from './fixtures';

/** Every registered path without a parameter (app/pages.tsx), minus the dev-only design page. */
export function staticRoutes(): string[] {
  const src = readFileSync(new URL('../src/app/pages.tsx', import.meta.url), 'utf8');
  const paths = [...src.matchAll(/path: '([^']+)'/g)].map((m) => m[1]);
  return [...new Set(paths)].filter((p) => !p.includes(':') && !p.includes('*') && !p.startsWith('/dev'));
}

async function settle(page: import('@playwright/test').Page) {
  await page.waitForLoadState('networkidle');
  // skeletons appear after a short delay: wait until none is busy
  await expect(page.locator('[aria-busy=true]')).toHaveCount(0, { timeout: 15_000 });
}

test.describe('F8 accessibility', () => {
  for (const path of staticRoutes()) {
    test(`axe ${path}`, async ({ as }) => {
      const page = await as('owner');
      await page.goto(path);
      await settle(page);
      await expectAccessible(page);
    });
  }

  test('axe in Khmer on the main screens', async ({ as }) => {
    const page = await as('owner');
    await page.goto('/');
    await page.getByRole('radio', { name: 'ខ្មែរ' }).click();
    try {
      for (const path of ['/', '/pos', '/sales/invoices', '/stock', '/products', '/reports', '/settings/users']) {
        await page.goto(path);
        await settle(page);
        await expect(page.locator('html')).toHaveAttribute('lang', 'km');
        await expectAccessible(page);
      }
    } finally {
      await page.getByRole('radio', { name: 'EN' }).first().click();
    }
  });

  test('POS keyboard: after F4, F8, F9 and Esc the focus goes back to the scan box', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    const scanBox = page.getByLabel('Scan or search medicine…');
    await expect(scanBox).toBeFocused();
    await scanBox.fill(d.meds.para.packs.strip.barcode!);
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: '+' })).toBeVisible();
    await page.keyboard.press('F4'); // customer search
    await expect(scanBox).not.toBeFocused();
    await page.keyboard.press('Escape');
    await expect(scanBox).toBeFocused();
    await page.keyboard.press('F8'); // suspend dialog
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(scanBox).toBeFocused();
    await expect(page.getByRole('button', { name: 'Pay', exact: true })).toBeEnabled();
    await page.keyboard.press('F9');
    await expect(page.getByRole('textbox', { name: 'USD' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(scanBox).toBeFocused();
    await page.keyboard.press('Escape');
    await page.getByRole('dialog').getByRole('button', { name: 'Clear cart' }).click();
    await expect(scanBox).toBeFocused();
  });
});
