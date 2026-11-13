// T2 Telegram against the stack (its bot has no token: nothing is sent, links cannot be made). Phase 1: the customer's
// Telegram panel and consent, message language and credit terms; branch opening hours and refill days. Phase 2: My
// profile's Telegram card; a discount asked on Telegram from the till (the tap's last step – notification → sales
// /internal/v1/discount-approvals/{id}/decide – is run inside the stack, as notification would).
import { execFileSync } from 'node:child_process';
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

function decideInsideStack(approvalId: string, branchId: string, decision: 'approve' | 'reject') {
  const project = process.env.E2E_COMPOSE_PROJECT ?? 'pharmacy';
  const body = JSON.stringify({ decision, actor: { user_id: '00000000-0000-4000-8000-00000000e2e1', name: 'E2E Manager (Telegram)', role: 'branch_manager', branch_ids: [branchId], permissions: ['sales.discount'] } });
  const code = 'import os,sys,httpx;r=httpx.post(f"http://localhost:8000/internal/v1/discount-approvals/{sys.argv[1]}/decide",content=sys.argv[2],headers={"X-Service-Token":os.environ["SERVICE_TOKEN"],"Content-Type":"application/json"});print(r.status_code);sys.exit(r.status_code!=200)';
  return execFileSync('docker', ['compose', '-p', project, 'exec', '-T', 'sales', 'python', '-c', code, approvalId, body], { stdio: 'pipe' }).toString().trim();
}

async function scan(page: Page, barcode: string) {
  const box = page.getByRole('textbox', { name: 'Scan or search medicine…' });
  await box.fill(barcode);
  const found = page.waitForResponse((r) => r.url().includes('/medicines/search'));
  await box.press('Enter');
  await found;
  await expect(page.getByRole('row').nth(1)).toBeVisible();
}

test.describe('T2 Telegram', () => {
  test('my profile shows the Telegram card', async ({ as }) => {
    const page = await as('manager');
    await page.goto('/profile');
    await expect(page.locator('#telegram')).toBeVisible();
    await expect(page.getByText('Not linked', { exact: true })).toBeVisible();
    await expect(page.getByText('approve requests with the buttons')).toBeVisible(); // managers may approve on Telegram
    await expect(page.getByText('The Telegram bot is not set up on this server.')).toBeVisible();
  });

  test('a discount above the cap approved on Telegram completes the sale', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    await scan(page, d.meds.para.packs.box.barcode!);
    await page.keyboard.press('F6');
    await page.getByLabel('Discount %').fill('15');
    await page.getByRole('button', { name: 'Apply' }).click();
    await page.locator('[data-code=DISCOUNT_APPROVAL_REQUIRED]').first().getByRole('button', { name: 'Ask for approval' }).click();
    const asked = page.waitForResponse((r) => r.url().endsWith('/carts/discount-approvals') && r.request().method() === 'POST');
    await page.getByTestId('ask-telegram').getByRole('button', { name: 'Ask on Telegram' }).click();
    const approval = await (await asked).json() as { id: string };
    await expect(page.getByText('Waiting for a manager on Telegram')).toBeVisible();
    expect(decideInsideStack(approval.id, seed.branchId, 'approve')).toBe('200');
    await expect(page.getByText('Approved on Telegram').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('button', { name: 'Pay', exact: true })).toBeEnabled();
    await page.keyboard.press('F9');
    await page.getByRole('textbox', { name: 'USD' }).fill('10');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
    await page.keyboard.press('Enter');
  });

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
