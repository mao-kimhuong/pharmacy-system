// F2: prescriptions and the controlled register against the stack.
import { apiLogin, waitFor } from './lib/api';
import { expect, expectAccessible, test } from './fixtures';
import { PIN } from './seed';

// 1×1 PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');

test.describe('F2 prescriptions + controlled', () => {
  test('pharmacist: patient with an allergy, then an Rx with a photo, activated', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('pharmacist');
    const phone = `0944${String(Date.now()).slice(-5)}`;
    await page.goto('/rx/patients');
    await page.getByRole('button', { name: '+ New patient' }).click();
    const form = page.getByRole('dialog');
    await form.getByLabel('Name (English)').fill(`E2E Rx Patient ${phone}`);
    await form.getByLabel('Phone', { exact: true }).fill(phone);
    await page.getByRole('button', { name: '+ Add allergy' }).click();
    await page.getByPlaceholder('Ingredient or class (e.g. penicillins)').fill('penicillins');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('heading', { name: `E2E Rx Patient ${phone}` })).toBeVisible();
    await expect(page.getByText('penicillins').first()).toBeVisible();
    await expectAccessible(page);
    await page.getByRole('button', { name: '+ New prescription' }).click();
    await page.getByLabel(/^Doctor \*/).fill('Dr E2E');
    await page.getByRole('listbox').getByRole('option').first().click();
    await page.getByPlaceholder('Add medicine').fill(d.meds.amox.sku);
    await page.getByRole('listbox').getByRole('option', { name: new RegExp(d.meds.amox.sku) }).click();
    await page.getByLabel(/^Qty per fill/).fill('21');
    await page.locator('input[type=file]').setInputFiles({ name: 'rx.png', mimeType: 'image/png', buffer: PNG });
    await page.getByRole('button', { name: 'Activate' }).click();
    await expect(page.getByText('Prescription active')).toBeVisible();
    await expect(page.getByText('Active', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Open' }).first().click();
    await expect(page.getByRole('dialog').locator('img')).toBeVisible();
  });

  test('cashier cannot open Prescriptions', async ({ as }) => {
    const page = await as('cashier');
    await page.goto('/rx/patients');
    await expect(page.getByRole('heading', { name: "You don't have permission to view this page" })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Menu' }).getByText('Prescriptions')).toHaveCount(0);
  });

  test('find a patient of another branch by the exact phone', async ({ as, seed }) => {
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const code = `E2F${String(Date.now()).slice(-4)}`;
    const b = await owner.post<{ id: string }>('/api/branch/v1/branches', { code, name_km: code, name_en: `Other ${code}` });
    const phone = `0933${String(Date.now()).slice(-5)}`;
    await waitFor(async () => {
      const r = await owner.post<{ code?: string }>('/api/prescription/v1/patients', { branch_id: b.data.id, name_en: `Other Branch Patient ${code}`, sex: 'male', phone });
      return r.data.code === 'UNKNOWN_BRANCH' ? null : r;
    });
    const page = await as('pharmacist');
    await page.goto('/rx/patients');
    await page.getByRole('button', { name: 'Find in another branch' }).click();
    await page.getByLabel('Exact phone number').fill(phone);
    await page.getByRole('dialog').getByRole('button', { name: 'Search' }).click();
    await page.getByText(new RegExp(`Linked to this branch: Other Branch Patient ${code}`)).click();
    await expect(page.getByRole('heading', { name: `Other Branch Patient ${code}` })).toBeVisible();
    await owner.post(`/api/branch/v1/branches/${b.data.id}/deactivate`, { reason: 'e2e test branch' });
  });

  test('destroy controlled stock: a pharmacist witness is refused, a manager witness works; correction; chain; PDF', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('pharmacist');
    await page.goto('/controlled/register');
    await expect(page.getByText(/Hash chain/)).toBeVisible();
    const dlg = page.getByRole('dialog');
    const fill = async (method: string, reason: string) => {
      await dlg.getByLabel(/^Medicine/).selectOption(d.meds.diaz.id);
      await expect(dlg.getByLabel(/^Batch/).locator('option')).not.toHaveCount(1);
      await dlg.getByLabel(/^Batch/).selectOption({ index: 1 });
      await dlg.getByLabel(/^Quantity \(base unit\)/).fill('1');
      await dlg.getByLabel(/^Destruction method/).fill(method);
      await dlg.getByLabel(/^Reason/).fill(reason);
    };
    const destroy = async (witness: string) => {
      await page.getByRole('button', { name: 'Adjust / destroy' }).click();
      await fill('crushed and mixed with cat litter', 'e2e: broken tablet');
      await page.getByRole('button', { name: 'Continue to PIN + witness' }).click();
      await page.keyboard.type(PIN); // own PIN (auto-submits)
      await page.getByLabel('Choose the witness').selectOption({ label: witness });
      await page.keyboard.type(PIN);
    };
    // the destroy witness list shows managers and owners only: a pharmacist is not offered
    await page.getByRole('button', { name: 'Adjust / destroy' }).click();
    await fill('x', 'check witnesses');
    await page.getByRole('button', { name: 'Continue to PIN + witness' }).click();
    await page.keyboard.type(PIN);
    await expect(page.getByLabel('Choose the witness').locator('option', { hasText: seed.accounts.pharmacist2.name })).toHaveCount(0);
    await page.getByRole('button', { name: 'Back' }).click();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await destroy(seed.accounts.manager.name);
    await expect(page.getByText('Recorded in the register')).toBeVisible();
    // the register builds its entry from inventory's stock.changed event: reload until it is there
    await expect(async () => { await page.reload(); await expect(page.getByRole('row', { name: /Destroyed/ }).first()).toBeVisible({ timeout: 2000 }); }).toPass({ timeout: 30_000 });
    await page.getByRole('row', { name: /Destroyed/ }).first().click();
    await expect(page.getByText('Hash matches')).toBeVisible();
    await page.getByRole('button', { name: 'Correction' }).click();
    await dlg.getByLabel(/Corrected quantity/).fill('1');
    await dlg.getByLabel(/^Reason/).fill('e2e: counted wrong');
    await page.getByRole('button', { name: 'Continue to PIN + witness' }).click();
    await page.keyboard.type(PIN);
    await page.getByLabel('Choose the witness').selectOption({ label: seed.accounts.pharmacist2.name });
    await page.keyboard.type(PIN);
    await expect(page.getByText('Corrects entry')).toBeVisible();
    await page.goto('/controlled/verify');
    await expect(page.getByText('Every chain of this branch is intact.')).toBeVisible();
    await page.goto('/controlled/register');
    await page.getByRole('button', { name: 'Register PDF' }).click();
    await expect(page.getByRole('dialog').locator('iframe')).toBeVisible({ timeout: 20_000 });
  });
});
