// F1 POS flows against the stack. Data: e2e/lib/data.ts (medicines, stock, rate 4100, customer limit $5, patient
// allergic to penicillins).
import type { Page } from '@playwright/test';
import { apiLogin } from './lib/api';
import { newRx } from './lib/data';
import { expect, expectAccessible, test } from './fixtures';
import { PIN } from './seed';

async function addByName(page: Page, m: { sku: string }) {
  const box = page.getByRole('textbox', { name: 'Scan or search medicine…' });
  await box.fill(m.sku);
  await page.getByRole('option', { name: new RegExp(m.sku) }).first().click();
}

async function scan(page: Page, barcode: string) {
  const box = page.getByRole('textbox', { name: 'Scan or search medicine…' });
  await box.fill(barcode);
  const found = page.waitForResponse((r) => r.url().includes('/medicines/search'));
  await box.press('Enter');
  await found;
  await expect(page.getByRole('row').nth(1)).toBeVisible();
}

/** Earlier runs leave active prescriptions for the same patient: acknowledge duplicate therapy if it shows. */
async function acknowledgeDuplicates(page: Page) {
  await page.waitForResponse((r) => r.url().includes('/carts/preview'));
  const ack = page.getByRole('button', { name: 'Acknowledge' });
  if (await ack.count()) await ack.first().click();
}

async function pickPatient(page: Page, phone: string) {
  await page.getByLabel('Patient name or phone').fill(phone);
  await page.getByRole('listbox').getByRole('option', { name: new RegExp(phone) }).click();
}

const total = (page: Page) => page.getByTestId('pos-total');

test.describe('F1 POS', () => {
  test('cashier: cash sale in USD + KHR with change and the 80 mm receipt', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    await scan(page, d.meds.para.packs.strip.barcode!); // 1 strip = $1.00
    await scan(page, d.meds.para.packs.strip.barcode!); // 2 strips = $2.00
    await expect(total(page)).toHaveText('$2.00');
    await expect(page.getByTestId('pos-total-khr')).toHaveText('៛8,200');
    await expectAccessible(page);
    await page.keyboard.press('F9');
    await page.getByRole('textbox', { name: 'USD' }).fill('1');
    await page.getByRole('textbox', { name: 'KHR' }).fill('5000');
    // $1 + ៛5,000 (= $1.22) for $2.00: change $0.22 → in riel ៛900 (rounded to 100)
    await expect(page.getByTestId('pos-change')).toContainText('៛');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
    await expect(page.getByTestId('sale-change')).toBeVisible();
    await expect(page.locator('iframe[title=receipt]')).toBeVisible({ timeout: 20_000 });
    await page.keyboard.press('Enter');
    await expect(total(page)).toHaveText('$0.00');
  });

  test('cashier: an Rx-only line blocks payment (RX_REQUIRED / pharmacist hand-off)', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    await addByName(page, d.meds.amox);
    await expect(page.locator('[data-code=RX_REQUIRED]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Hand to pharmacist (suspend)' }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Pay', exact: true })).toBeDisabled();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Clear cart' }).click();
  });

  test('pharmacist: link the Rx, override the allergy with a reason, sell', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const rx = await newRx(owner, seed.branchId, d, d.meds.amox.id, 20);
    const page = await as('pharmacist');
    await page.goto('/pos');
    await addByName(page, d.meds.amox);
    await page.locator('[data-code=RX_REQUIRED]').getByRole('button', { name: 'Link Rx' }).click();
    await pickPatient(page, d.patientPhone);
    await page.getByRole('button', { name: new RegExp(rx.number) }).click();
    await page.getByRole('button', { name: 'Link & continue' }).click();
    // allergy (penicillins) and, after earlier runs, duplicate therapy: override with a reason, acknowledge
    const allergy = page.locator('[data-code=ALLERGY_WARNING]', { hasText: 'Allergy' });
    await expect(allergy).toBeVisible();
    await allergy.getByRole('button', { name: 'Override' }).click();
    await page.getByLabel('Allergy override reason').fill('Confirmed with the doctor by phone: no real allergy');
    await page.getByLabel(/I checked with the patient/).check();
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.locator('[data-code=ALLERGY_WARNING], [data-code=DUPLICATE_THERAPY_WARNING]').filter({ hasNot: page.locator('[aria-hidden]', { hasText: '✓' }) })).toHaveCount(0);
    await page.keyboard.press('F9');
    await page.getByRole('textbox', { name: 'USD' }).fill('2');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
    await page.keyboard.press('Enter');
  });

  test('pharmacist: controlled sale needs the patient ID and the PIN', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const rx = await newRx(owner, seed.branchId, d, d.meds.diaz.id, 10);
    const page = await as('pharmacist');
    await page.goto('/pos');
    await addByName(page, d.meds.diaz);
    await page.locator('[data-code=RX_REQUIRED]').getByRole('button', { name: 'Link Rx' }).click();
    await pickPatient(page, d.patientPhone);
    await page.getByRole('button', { name: new RegExp(rx.number) }).click();
    await page.getByRole('button', { name: 'Link & continue' }).click();
    await acknowledgeDuplicates(page);
    await page.locator('[data-code=VALIDATION_ERROR]').getByRole('button', { name: 'Fix' }).click();
    await page.getByLabel('Patient ID card / passport no.').fill('010245778');
    await page.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByRole('button', { name: 'Pay', exact: true })).toBeDisabled();
    await page.locator('[data-code=PIN_REQUIRED]').getByRole('button', { name: 'Enter PIN' }).click();
    await page.keyboard.type(PIN);
    await expect(page.getByText(/PIN confirmed/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Pay', exact: true })).toBeEnabled();
    await page.keyboard.press('F9');
    await page.getByRole('textbox', { name: 'USD' }).fill('1');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
    await page.keyboard.press('Enter');
  });

  test('cashier: a discount above the cap is approved by the manager\'s witness PIN', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    await scan(page, d.meds.para.packs.box.barcode!);
    await page.keyboard.press('F6');
    await page.getByLabel('Discount %').fill('15');
    await page.getByRole('button', { name: 'Apply' }).click();
    await page.locator('[data-code=DISCOUNT_APPROVAL_REQUIRED]').first().getByRole('button', { name: 'Ask for approval' }).click();
    await page.getByLabel('Choose the witness').selectOption({ label: seed.accounts.manager.name });
    await page.keyboard.type(PIN); // 6 digits submit by themselves
    await expect(page.getByText(`Approved by ${seed.accounts.manager.name}`).first()).toBeVisible();
    await expect(total(page)).toHaveText('$7.65');
    await expect(page.getByRole('button', { name: 'Pay', exact: true })).toBeEnabled();
    await page.keyboard.press('F9');
    await page.getByRole('textbox', { name: 'USD' }).fill('10');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
    await page.keyboard.press('Enter');
  });

  test('cashier: credit over the customer limit is blocked', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    await scan(page, d.meds.para.packs.box.barcode!); // $9.00 > limit $5.00
    await page.keyboard.press('F4');
    await page.getByPlaceholder('Search name or phone').fill(d.customerName.slice(0, 12));
    await page.getByRole('listbox').getByRole('option', { name: new RegExp(d.customerName) }).click();
    await page.getByRole('button', { name: 'Pay later' }).click();
    await expect(page.locator('[data-code=CREDIT_LIMIT_EXCEEDED]')).toBeVisible();
    await expect(page.getByRole('button', { name: /Complete & print/ })).toBeDisabled();
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Clear cart' }).click();
  });

  test('below cost blocks a cashier', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    await addByName(page, d.meds.cheap);
    await expect(page.locator('[data-code=BELOW_COST]')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Pay', exact: true })).toBeDisabled();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Clear cart' }).click();
  });

  test('suspend, then resume from Sale Suspend', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('cashier');
    await page.goto('/pos');
    await scan(page, d.meds.para.packs.strip.barcode!);
    await page.keyboard.press('F8');
    await page.getByLabel('Note (who is it for?)').fill('e2e suspend');
    await page.getByRole('button', { name: /^Suspend/ }).last().click();
    await expect(page.getByText(/Suspended as/)).toBeVisible();
    await expect(total(page)).toHaveText('$0.00');
    await page.goto('/sales/suspended');
    const row = page.getByRole('row', { name: /e2e suspend/ }).first();
    await row.getByRole('button', { name: 'Resume' }).click();
    await expect(page).toHaveURL(/\/pos$/);
    await expect(page.getByText(/^Resumed /)).toBeVisible();
    await expect(total(page)).toHaveText('$1.00');
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Clear cart' }).click();
  });

  test('owner: KHQR paid (fake provider), cancelled with a reason, then the KHQR refunded with the PIN', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('owner');
    await page.goto('/pos');
    await scan(page, d.meds.para.packs.strip.barcode!);
    await page.getByRole('button', { name: 'KHQR' }).click();
    await page.getByRole('button', { name: 'Show QR' }).click();
    await expect(page.getByRole('img', { name: 'KHQR' })).toBeVisible();
    await page.getByRole('button', { name: 'Mark paid (test)' }).click();
    await expect(page.getByRole('button', { name: /Complete & print/ })).toBeEnabled();
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
    const number = (await page.getByText(/^Invoice /).first().innerText()).match(/Invoice (\S+)/)![1];
    await page.keyboard.press('Enter');
    await page.goto('/sales/invoices');
    await page.getByLabel('Invoice number').fill(number);
    await page.getByRole('row', { name: new RegExp(number) }).click();
    await page.getByRole('button', { name: 'Cancel invoice' }).click();
    await page.getByLabel(/Reason/).fill('e2e: wrong item');
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel invoice' }).click();
    await expect(page.getByText('Invoice cancelled')).toBeVisible();
    // the money went to the bank: the invoice offers the refund, made one by one with the PIN
    await expect(page.getByText('1 KHQR refund is due on this invoice.')).toBeVisible();
    await page.getByRole('link', { name: /Refund it in KHQR Refunds/ }).click();
    const row = page.getByRole('row').filter({ hasText: 'Sale cancelled' }).filter({ hasText: number });
    await row.first().getByRole('button', { name: 'Refund' }).click();
    await expect(page.getByRole('dialog')).toContainText('Type your PIN to confirm');
    await page.keyboard.type(PIN); // 6 digits submit by themselves
    await expect(page.getByText(/\$1\.00 refunded\./)).toBeVisible();
    await page.getByRole('tab', { name: 'Refunded' }).click();
    await expect(page.getByRole('row').filter({ hasText: number }).first()).toContainText('Refunded');
  });

  test('manager: partial return of a sale back to stock', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('manager');
    await page.goto('/pos');
    await scan(page, d.meds.para.packs.strip.barcode!);
    await scan(page, d.meds.para.packs.strip.barcode!);
    await expect(total(page)).toHaveText('$2.00');
    await page.keyboard.press('F9');
    await page.getByRole('textbox', { name: 'USD' }).fill('2');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    const number = (await page.getByText(/^Invoice /).first().innerText()).match(/Invoice (\S+)/)![1];
    await page.keyboard.press('Enter');
    await page.goto('/sales/returns');
    await page.getByLabel('Find the invoice').fill(number);
    await page.getByRole('button', { name: 'Search', exact: true }).click();
    await page.getByRole('textbox', { name: /Return qty/ }).first().fill('1');
    await page.getByLabel('Reason').fill('e2e: customer changed mind');
    await page.getByRole('button', { name: 'Record return' }).click();
    await expect(page.getByText(/Return .* recorded/)).toBeVisible();
    await expect(page.getByText('Partly returned')).toBeVisible();
  });
});
