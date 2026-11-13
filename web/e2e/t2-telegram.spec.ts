// T2 Telegram against the stack (its bot has no token: nothing is sent, links cannot be made). Phase 1: the customer's
// Telegram panel and consent, message language and credit terms; branch opening hours and refill days.
import { expect, test } from './fixtures';

test.describe('T2 Telegram', () => {
  test('customer detail shows the Telegram panel; language and credit terms are saved', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('manager');
    await page.goto(`/contacts/customers/${d.customerId}`);
    await expect(page.getByRole('heading', { name: 'Telegram' })).toBeVisible();
    await expect(page.getByText('Not linked')).toBeVisible();
    await expect(page.getByText('The Telegram bot is not set up')).toBeVisible();
    for (const topic of ['Receipts and refunds', 'Refill reminders', 'Balance reminders', 'Orders', 'Medicine names in reminders', 'Promotions']) {
      await expect(page.getByRole('switch', { name: topic })).toBeDisabled(); // not linked: nothing to allow yet
    }
    await expect(page.getByText('never set').first()).toBeVisible();
    await page.getByRole('button', { name: 'Edit' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel('Message language').selectOption('en');
    await dlg.getByLabel('Credit terms (days)').fill('15');
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(dlg).toBeHidden();
    await expect(page.getByText('English')).toBeVisible();
    await expect(page.locator('dd', { hasText: /^15$/ })).toBeVisible();
    const cashier = await as('cashier');
    await cashier.goto(`/contacts/customers/${d.customerId}`);
    await expect(cashier.getByText('Not linked')).toBeVisible(); // contacts.customers may look, not change
  });

  test('branch opening hours and refill reminder days', async ({ as, seed }) => {
    const page = await as('owner');
    await page.goto(`/settings/branches/${seed.branchId}`);
    await page.getByLabel('Telegram refill reminder (days before)').fill('4');
    const mon = page.locator('[data-day="mon"]');
    await mon.getByRole('checkbox', { name: 'Monday' }).check();
    await mon.getByLabel('Monday opens').fill('07:30');
    await mon.getByLabel('Monday closes').fill('20:00');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('Settings saved')).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('Telegram refill reminder (days before)')).toHaveValue('4');
    await expect(page.locator('[data-day="mon"]').getByLabel('Monday opens')).toHaveValue('07:30');
    await expect(page.locator('[data-day="tue"]').getByLabel('Tuesday opens')).toBeDisabled();
  });
});
