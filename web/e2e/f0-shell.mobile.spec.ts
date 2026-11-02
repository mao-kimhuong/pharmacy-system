import { expect, freshContext, test, uiLogin } from './fixtures';

test('phone: login in Khmer by default, tab bar and More menu (2d–2f)', async ({ browser, seed }) => {
  const ctx = await freshContext(browser, 'km', { width: 390, height: 844 });
  const page = await ctx.newPage();
  const a = seed.accounts.pharmacist;
  await uiLogin(page, a.phone, a.password);
  const tabs2 = page.getByRole('navigation', { name: 'ម៉ឺនុយ' });
  await expect(tabs2.getByText('ទំព័រដើម')).toBeVisible();
  await tabs2.getByText('ច្រើនទៀត').click();
  await expect(page.getByRole('heading', { name: 'ម៉ឺនុយទាំងអស់' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'km');
  await ctx.close();
});
