// POS payment tiles + the payment modal (KHQR, Card / Wallet via PayWay). The e2e stack runs the fake provider:
// no PayWay page, the owner's test buttons pay or decline the attempt. Screenshots in Khmer and English go to
// e2e/screenshots/ (git-ignored).
import type { Page } from '@playwright/test';
import { expect, test } from './fixtures';

const shot = (name: string) => `e2e/screenshots/${name}.png`;

async function cartToPay(page: Page, barcode: string, times = 1) {
  await page.goto('/pos');
  const box = page.getByRole('textbox', { name: 'Scan or search medicine…' });
  for (let i = 0; i < times; i++) {
    await box.fill(barcode);
    const found = page.waitForResponse((r) => r.url().includes('/medicines/search'));
    await box.press('Enter');
    await found;
  }
  await expect(page.getByRole('row').nth(1)).toBeVisible();
  await expect(page.getByRole('button', { name: /^Pay/ }).first()).toBeEnabled();
  await page.keyboard.press('F9');
  await expect(page.locator('[data-tile="cash"]')).toBeVisible();
}

const tile = (page: Page, k: string) => page.locator(`[data-tile="${k}"]`);

test.describe('POS payment tiles', () => {
  test('five tiles with KM + EN labels; Pay later needs a customer; shortcuts 1–5 and Alt+1–5', async ({ as, seed }) => {
    const page = await as('cashier');
    await cartToPay(page, seed.extra.sales!.meds.para.packs.strip.barcode!);
    for (const [k, km, en] of [['cash', 'សាច់ប្រាក់', 'Cash'], ['KHQR', 'KHQR', 'KHQR'], ['card', 'កាត / កាបូប', 'Card / Wallet'],
      ['ABA', 'ផ្ទេរធនាគារ', 'Bank transfer'], ['credit', 'បង់ពេលក្រោយ', 'Pay later']] as const) {
      await expect(tile(page, k)).toContainText(km);
      await expect(tile(page, k)).toContainText(en);
    }
    await expect(tile(page, 'cash')).toHaveAttribute('aria-pressed', 'true'); // selected: border + ✓
    await expect(tile(page, 'credit')).toHaveAttribute('aria-disabled', 'true');
    await expect(tile(page, 'credit')).toContainText('Choose a customer first');
    const usd = page.getByRole('textbox', { name: 'USD' });
    await usd.focus();
    await page.keyboard.press('2'); // in the cash field: a digit is a digit
    await expect(usd).toHaveValue('2');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.keyboard.press('Alt+2'); // Alt+2 anywhere: KHQR
    await expect(page.getByRole('dialog', { name: 'KHQR' })).toBeVisible();
    await page.keyboard.press('Escape'); // nothing started yet: closes without asking
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByTestId('pay-remaining').click(); // out of the field
    await page.keyboard.press('4');
    await expect(page.getByRole('dialog', { name: 'Bank transfer' })).toBeVisible();
    await page.keyboard.press('Escape');
    await page.keyboard.press('5'); // disabled: nothing opens
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  test('bank transfer with its reference completes the sale', async ({ as, seed }) => {
    const page = await as('cashier');
    await cartToPay(page, seed.extra.sales!.meds.para.packs.strip.barcode!);
    await tile(page, 'ABA').click();
    const dlg = page.getByRole('dialog', { name: 'Bank transfer' });
    await expect(dlg.getByRole('button', { name: 'Add payment' })).toBeDisabled(); // the reference is required
    await dlg.getByLabel(/Transfer reference/).fill('TT-2026-0042');
    await dlg.getByRole('button', { name: 'Add payment' }).click();
    await expect(page.getByText('Bank transfer · TT-2026-0042')).toBeVisible();
    await expect(tile(page, 'ABA')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('pay-remaining')).toHaveText('Fully covered');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
  });

  test('split payment: bank transfer, then KHQR for the rest', async ({ as, seed }) => {
    const page = await as('owner');
    await cartToPay(page, seed.extra.sales!.meds.para.packs.strip.barcode!, 2);
    await tile(page, 'ABA').click();
    const ref = page.getByRole('dialog', { name: 'Bank transfer' });
    await ref.getByLabel(/Amount/).fill('1.00');
    await ref.getByLabel(/Transfer reference/).fill('TT-1');
    await ref.getByRole('button', { name: 'Add payment' }).click();
    await expect(page.getByTestId('pay-remaining')).toHaveText('Remaining $1.00');
    await tile(page, 'KHQR').click();
    const modal = page.getByRole('dialog', { name: 'KHQR' });
    await expect(modal.getByTestId('modal-amount')).toHaveText('$1.00');
    await modal.getByRole('button', { name: 'Show QR' }).click();
    await expect(modal.getByRole('img', { name: 'KHQR' })).toBeVisible();
    await expect(modal.getByTestId('modal-state')).toHaveText('Waiting for payment');
    await expect(modal.getByTestId('modal-countdown')).toBeVisible();
    await modal.getByRole('button', { name: 'Mark paid (test)' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0); // closes by itself once paid
    await expect(page.getByTestId('pay-remaining')).toHaveText('Fully covered');
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();
  });

  test('card / wallet modal: declined → paid; closing asks and cancels', async ({ as, seed }) => {
    const page = await as('owner');
    await cartToPay(page, seed.extra.sales!.meds.para.packs.strip.barcode!);
    await tile(page, 'card').click();
    let modal = page.getByRole('dialog', { name: 'ABA PayWay checkout' });
    await modal.getByRole('button', { name: 'Open PayWay' }).click();
    await expect(modal.getByTestId('modal-state')).toHaveText('Waiting for payment');
    await modal.getByRole('button', { name: 'Decline (test)' }).click();
    await expect(modal.getByTestId('modal-state')).toHaveText('Declined');
    await expect(modal.getByRole('alert')).toContainText('The payment was declined');
    await expect(modal.getByRole('button', { name: 'Choose another method' })).toBeVisible();
    await page.screenshot({ path: shot('payway-declined-en') });
    await modal.getByRole('button', { name: 'Mark paid (test)' }).click(); // the customer tries again and pays
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByText('Card / Wallet (PayWay)')).toBeVisible();
    await page.getByRole('button', { name: /Complete & print/ }).click();
    await expect(page.getByText('Sale complete')).toBeVisible();

    await cartToPay(page, seed.extra.sales!.meds.para.packs.strip.barcode!);
    await tile(page, 'card').click();
    modal = page.getByRole('dialog', { name: 'ABA PayWay checkout' });
    await modal.getByRole('button', { name: 'Open PayWay' }).click();
    await expect(modal.getByTestId('modal-state')).toHaveText('Waiting for payment');
    const cancelled = page.waitForResponse((r) => r.url().includes('/cancel') && r.request().method() === 'POST');
    await page.keyboard.press('Escape'); // while waiting: asks first
    const confirm = page.getByRole('dialog', { name: 'Cancel this payment?' });
    await confirm.getByRole('button', { name: 'Cancel payment' }).click();
    expect((await cancelled).status()).toBe(200);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByText('Card / Wallet (PayWay)')).toHaveCount(0);
  });

  test('screenshots of the tiles and the modals in Khmer and English', async ({ as, seed }) => {
    const page = await as('owner');
    for (const lang of ['en', 'km'] as const) {
      await cartToPay(page, seed.extra.sales!.meds.para.packs.strip.barcode!);
      if (lang === 'km') await page.getByRole('radio', { name: 'ខ្មែរ' }).first().click();
      else await page.getByRole('radio', { name: 'EN' }).first().click();
      await expect(tile(page, 'cash')).toBeVisible();
      await page.screenshot({ path: shot(`tiles-${lang}`) });
      await tile(page, 'KHQR').click();
      await page.getByRole('dialog').getByRole('button', { name: lang === 'km' ? 'បង្ហាញ QR' : 'Show QR' }).click();
      await expect(page.getByRole('dialog').getByRole('img', { name: 'KHQR' })).toBeVisible();
      await page.screenshot({ path: shot(`khqr-${lang}`) });
      await page.keyboard.press('Escape');
      await page.getByRole('dialog').last().getByRole('button', { name: lang === 'km' ? 'លុបចោលការបង់' : 'Cancel payment' }).click();
      await tile(page, 'card').click();
      await page.getByRole('dialog').getByRole('button', { name: lang === 'km' ? 'បើក PayWay' : 'Open PayWay' }).click();
      await expect(page.getByTestId('modal-state')).toBeVisible();
      await page.screenshot({ path: shot(`payway-${lang}`) });
      await page.keyboard.press('Escape');
      await page.getByRole('dialog').last().getByRole('button', { name: lang === 'km' ? 'លុបចោលការបង់' : 'Cancel payment' }).click();
    }
    await page.getByRole('radio', { name: 'EN' }).first().click();
  });
});
