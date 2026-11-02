// F5 contacts against the stack.
import { apiLogin, idem } from './lib/api';
import { expect, test } from './fixtures';

test.describe('F5 contacts', () => {
  test('manager sets a credit limit; a cashier cannot', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const mgr = await as('manager');
    await mgr.goto(`/contacts/customers/${d.customerId}`);
    await mgr.getByRole('button', { name: 'Edit' }).click();
    await expect(mgr.getByRole('dialog').getByLabel('Credit limit')).toBeEnabled();
    await mgr.getByRole('dialog').getByLabel('Credit limit').fill('5.00');
    await mgr.getByRole('dialog').getByRole('button', { name: 'Save' }).click();
    const cash = await as('cashier');
    await cash.goto(`/contacts/customers/${d.customerId}`);
    await cash.getByRole('button', { name: 'Edit' }).click();
    await expect(cash.getByRole('dialog').getByLabel('Credit limit')).toBeDisabled();
    await expect(cash.getByText('Only users allowed to set credit limits can change it.')).toBeVisible();
  });

  test('a credit sale, then a payment oldest-first, cancelled with a reason; statement PDF in km and en', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const inv = await owner.post<{ number: string }>('/api/sales/v1/invoices', { branch_id: seed.branchId, customer_id: d.customerId, lines: [{ medicine_id: d.meds.para.id, pack_unit_id: d.meds.para.packs.strip.id, qty: 1 }], payments: [{ method: 'credit', currency: 'USD', amount: '1.00' }] }, idem());
    expect(inv.status).toBe(201);
    const page = await as('manager');
    await page.goto(`/contacts/customers/${d.customerId}`);
    await expect(page.getByRole('row', { name: new RegExp(inv.data.number) })).toBeVisible();
    await page.goto('/contacts/customer-payments');
    await page.getByRole('button', { name: '+ Record payment' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel(/^Customer/).fill(d.customerName.slice(0, 12));
    await page.getByRole('listbox').getByRole('option', { name: new RegExp(d.customerName) }).click();
    await dlg.getByLabel(/^Amount/).fill('1.00');
    await dlg.getByRole('button', { name: 'Record payment' }).click();
    await expect(page.getByText(/Payment .* recorded/)).toBeVisible();
    await page.getByRole('row').filter({ hasText: d.customerName }).filter({ hasText: 'Posted' }).first().getByRole('button', { name: 'Cancel payment' }).click();
    await page.getByRole('dialog').getByLabel(/Reason/).fill('e2e: wrong customer');
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel payment' }).click();
    await expect(page.getByRole('row').filter({ hasText: d.customerName }).filter({ hasText: 'Cancelled' }).first()).toBeVisible();
    for (const lang of ['ខ្មែរ', 'EN']) {
      await page.goto(`/contacts/customers/${d.customerId}`);
      await page.getByRole('radio', { name: lang }).first().click();
      await page.getByRole('button', { name: /Statement PDF|របាយការណ៍ PDF/ }).click();
      await expect(page.getByRole('dialog').locator('iframe')).toBeVisible({ timeout: 20_000 });
      await page.keyboard.press('Escape');
    }
  });

  test('deactivate a customer with a reason', async ({ as }) => {
    const page = await as('manager');
    const phone = `0911${String(Date.now()).slice(-5)}`;
    await page.goto('/contacts/customers');
    await page.getByRole('button', { name: '+ New customer' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel(/^Name \*/).fill(`E2E Deact ${phone}`);
    await dlg.getByLabel(/^Phone/).fill(phone);
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('heading', { name: `E2E Deact ${phone}` })).toBeVisible();
    await page.getByRole('button', { name: 'Deactivate' }).click();
    await page.getByRole('dialog').getByLabel(/Reason/).fill('e2e: moved away');
    await page.getByRole('dialog').getByRole('button', { name: 'Deactivate' }).click();
    await expect(page.getByRole('button', { name: 'Activate', exact: true })).toBeVisible();
  });

  test('supplier detail shows the balance the API reports', async ({ as, seed }) => {
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const sup = await owner.get<{ items: { id: string }[] }>('/api/purchasing/v1/suppliers?size=1');
    const id = sup.data.items[0].id;
    const bal = await owner.get<{ owed: string }>(`/api/purchasing/v1/suppliers/${id}/balance`);
    const page = await as('owner');
    await page.goto(`/contacts/suppliers/${id}`);
    const owed = `$${Number(bal.data.owed).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
    await expect(page.getByText('Owed').locator('..').getByText(owed)).toBeVisible();
  });
});
