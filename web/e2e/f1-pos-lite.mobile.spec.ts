import { expect, freshContext, test, uiLogin } from './fixtures';

test('POS lite (phone): scan by code, pay cash in a sheet (4a/4b)', async ({ browser, seed }) => {
  const d = seed.extra.sales!;
  const ctx = await freshContext(browser, 'en', { width: 390, height: 844 });
  const page = await ctx.newPage();
  const a = seed.accounts.cashier;
  await uiLogin(page, a.phone, a.password);
  await expect(page.getByRole('navigation', { name: 'Menu' })).toBeVisible();
  await page.goto('/pos');
  const box = page.getByRole('textbox', { name: 'Scan or search medicine…' });
  await box.fill(d.meds.para.packs.strip.barcode!);
  await box.press('Enter');
  await expect(page.getByTestId('pos-total').first()).toHaveText('$1.00');
  await page.getByRole('button', { name: /^Pay \$1\.00/ }).click();
  await page.getByRole('textbox', { name: 'USD' }).fill('1');
  await page.getByRole('button', { name: /Complete & print/ }).click();
  await expect(page.getByText('Sale complete')).toBeVisible();
  await ctx.close();
});
