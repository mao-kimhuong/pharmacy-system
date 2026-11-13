// F3 warehouse + stock against the stack.
import path from 'node:path';
import { apiLogin, idem, waitFor } from './lib/api';
import { expect, expectAccessible, test } from './fixtures';
import { loadSeed } from './seed';

const SAMPLES = path.resolve(import.meta.dirname, '../../docs/samples');

test.describe('F3 warehouse + stock', () => {
  // the stock take and the recall use up the shared medicine: later specs sell it again
  test.afterAll(async () => {
    const seed = loadSeed();
    const d = seed.extra.sales!;
    const { http } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const expiry = new Date(Date.now() + 400 * 86_400_000).toISOString().slice(0, 10);
    const r = await http.post('/api/inventory/v1/stock-in', { branch_id: seed.branchId, reason: 'e2e top-up after F3', lines: [
      { medicine_id: d.meds.para.id, pack_unit_id: d.meds.para.packs.tab.id, lot_no: `TOP-${Date.now()}`, expiry_date: expiry, qty: 2000, unit_cost: '0.02' }] }, idem());
    expect(r.status).toBeLessThan(300);
  });

  test('import: the broken file shows its errors, the sample validates and commits', async ({ as }) => {
    const page = await as('owner');
    await page.goto('/imports');
    await page.locator('input[type=file]').setInputFiles(path.join(SAMPLES, 'products-sample-broken.xlsx'));
    await expect(page.getByText(/Rows with errors: [1-9]/)).toBeVisible();
    await page.getByLabel('Create missing categories and brands').uncheck();
    await expect(page.getByRole('button', { name: 'Import', exact: true })).toBeDisabled();
    await page.getByLabel('Create missing categories and brands').check();
    const up = page.waitForResponse((r) => r.url().endsWith('/api/catalog/v1/imports') && r.request().method() === 'POST');
    await page.locator('input[type=file]').setInputFiles(path.join(SAMPLES, 'products-sample.xlsx'));
    await up;
    await expect(page.getByRole('heading', { name: 'products-sample.xlsx' })).toBeVisible();
    await page.getByRole('button', { name: 'Import', exact: true }).click();
    await expect(page.getByText(/Imported: \d+ new, \d+ updated/).first()).toBeVisible();
  });

  test('print shelf labels', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('pharmacist');
    await page.goto('/labels');
    await page.getByPlaceholder('Add medicine').fill(d.meds.para.sku);
    await page.getByRole('listbox').getByRole('option').first().click();
    await page.getByRole('button', { name: 'Make labels' }).click();
    await expect(page.getByRole('dialog').locator('iframe')).toBeVisible({ timeout: 20_000 });
  });

  test('stock on hand and batches; cost hidden for the cashier', async ({ as }) => {
    const page = await as('cashier');
    await page.goto('/stock');
    await expect(page.getByText('Cost columns hidden for your role')).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Value (cost)' })).toHaveCount(0);
    await expectAccessible(page);
  });

  test('stock take of one shelf: blind count, then approve', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const code = `Z${String(Date.now()).slice(-3)}`;
    // one open stock take per branch: cancel what earlier runs left open
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const open = await owner.get<{ id: string; status: string }[]>(`/api/stockcount/v1/counts?branch_id=${seed.branchId}`);
    for (const c of open.data.filter((x) => x.status === 'counting' || x.status === 'review')) await owner.post(`/api/stockcount/v1/counts/${c.id}/cancel`, { reason: 'e2e cleanup' });
    const mgr = await as('manager');
    await mgr.goto('/stock/locations');
    await mgr.getByLabel('Medicine', { exact: true }).fill(d.meds.para.sku);
    await mgr.getByRole('listbox').getByRole('option').first().click();
    await mgr.getByLabel('Location (e.g. A3)').fill(code);
    await mgr.getByRole('button', { name: 'Set location' }).click();
    await expect(mgr.getByRole('row', { name: new RegExp(code) })).toBeVisible();
    await mgr.goto('/stock/counts');
    await mgr.getByRole('button', { name: '+ New stock take' }).click();
    await mgr.getByLabel('Scope').selectOption('location');
    await mgr.getByLabel('Shelf location').fill(code);
    await mgr.getByRole('button', { name: 'Start count' }).click();
    await expect(mgr.getByText('Blind count: enter what you see on the shelf.')).toBeVisible();
    const url = mgr.url();
    // the pharmacist counts on a phone-sized screen
    const ph = await as('pharmacist');
    await ph.setViewportSize({ width: 390, height: 844 });
    await ph.goto(url);
    const lines = ph.getByRole('button', { name: new RegExp(`Paracetamol ${d.suffix}`) });
    await expect(lines.first()).toBeVisible();
    const n = await lines.count();
    const todo = lines.filter({ hasText: 'To count' });
    for (let i = await todo.count(); i > 0; i--) {
      await todo.first().click();
      await ph.getByLabel(/^Counted/).fill('1');
      await ph.getByRole('button', { name: 'Save count' }).click();
      await expect(ph.getByRole('dialog')).toHaveCount(0);
      await expect(todo).toHaveCount(i - 1); // the saved line leaves "To count" before the next click
    }
    // a line worth more than double_count_above_usd (50) needs a second person: the manager counts it too
    await mgr.reload();
    const mgrLines = mgr.getByRole('button', { name: new RegExp(`Paracetamol ${d.suffix}`) });
    await expect(mgrLines).toHaveCount(n); // count() does not wait: let the reloaded list arrive first
    const second = mgrLines.filter({ hasText: 'Second count' });
    for (let i = await second.count(); i > 0; i--) {
      await second.first().click();
      await mgr.getByLabel(/^Counted/).fill('1');
      await mgr.getByRole('button', { name: 'Save count' }).click();
      await expect(mgr.getByRole('dialog')).toHaveCount(0);
      await expect(second).toHaveCount(i - 1); // the saved line leaves the list before the next click
    }
    await ph.reload();
    await ph.getByRole('button', { name: 'Submit for review' }).click();
    await ph.getByRole('dialog').getByRole('button', { name: 'Submit for review' }).click();
    await mgr.reload();
    await expect(mgr.getByRole('columnheader', { name: 'Variance' })).toBeVisible();
    // counting 1 of each batch: on a stack with earlier runs' stock the variance passes owner_approval_above_usd (200)
    const own = await as('owner');
    await own.goto(url);
    await expect(own.getByRole('columnheader', { name: 'Variance', exact: true })).toBeVisible();
    await own.getByRole('button', { name: 'Approve and post' }).click();
    await own.getByRole('dialog').getByRole('button', { name: 'Approve and post' }).click();
    await expect(own.getByText('Approved and posted')).toBeVisible();
  });

  test('recall a lot: the POS refuses it, destroy the stock, close', async ({ as, seed }) => {
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    // a medicine of its own so other tests keep their stock
    const s = String(Date.now()).slice(-6);
    const m = await owner.post<{ id: string; sku: string; pack_units: { id: string }[] }>('/api/catalog/v1/medicines', { sku: `E2ERC${s}`, brand_name: `E2E Recall ${s}`, generic_name: 'Recallamol', base_unit: 'tab', base_price: '0.50' });
    await waitFor(async () => {
      const r = await owner.post<{ code?: string }>('/api/inventory/v1/stock-in', { branch_id: seed.branchId, reason: 'e2e recall', lines: [{ medicine_id: m.data.id, pack_unit_id: m.data.pack_units[0].id, lot_no: `R${s}`, expiry_date: '2030-01-31', qty: 5, unit_cost: '0.10' }] }, idem());
      return r.data.code === 'UNKNOWN_MEDICINE' ? null : r;
    });
    const page = await as('owner');
    await page.goto('/stock/recalls');
    await page.getByRole('button', { name: '+ Start recall' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel(/^Medicine/).fill(m.data.sku);
    await page.getByRole('listbox').getByRole('option').first().click();
    await dlg.getByLabel(/^Lot numbers/).fill(`R${s}`);
    await dlg.getByLabel(/^Reason/).fill('e2e: MoH notice');
    await dlg.getByRole('button', { name: 'Start recall' }).click();
    await expect(page.getByRole('heading', { name: new RegExp(m.data.sku) })).toBeVisible();
    // the POS cannot sell it
    const pos = await as('cashier');
    await pos.goto('/pos');
    await pos.getByRole('textbox', { name: 'Scan or search medicine…' }).fill(m.data.sku);
    await pos.getByRole('option', { name: new RegExp(m.data.sku) }).first().click();
    await expect(pos.locator('[data-code=OUT_OF_STOCK]')).toBeVisible();
    await pos.keyboard.press('Escape');
    await pos.getByRole('button', { name: 'Clear cart' }).click();
    await page.getByRole('button', { name: 'Destroy' }).first().click();
    await expect(page.getByRole('button', { name: 'Destroy' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Close recall' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Close recall' }).click();
    await expect(page.getByText('Closed', { exact: true })).toBeVisible();
  });

  test('re-order list → purchase request', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const page = await as('manager');
    await page.goto('/stock/reorder-settings');
    await page.getByRole('button', { name: '+ Add medicine' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel('Medicine', { exact: true }).fill(d.meds.amox.sku);
    await page.getByRole('listbox').getByRole('option').first().click();
    await dlg.getByLabel('Min').fill('100000');
    await dlg.getByLabel('Max').fill('200000');
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(dlg).toBeHidden(); // leaving the page earlier can cancel the save
    await page.goto('/stock/reorder');
    const ran = page.waitForResponse((r) => r.url().includes('/reorder-lists/run'));
    await page.getByRole('button', { name: 'Run now' }).click();
    await ran; // the run replaces the list shown before it: tick a line of the new one
    const row = page.getByRole('row', { name: new RegExp(d.meds.amox.sku) });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Create purchase request' }).click();
    await expect(page.getByText(/Request .*-PR-/).first()).toBeVisible();
  });

  test('pharmacist releases a returned pack from quarantine', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const inv = await owner.post<{ id: string; lines: { id: string }[] }>('/api/sales/v1/invoices', { branch_id: seed.branchId, lines: [{ medicine_id: d.meds.para.id, pack_unit_id: d.meds.para.packs.tab.id, qty: 1 }], payments: [{ method: 'cash', currency: 'USD', amount: '1.00' }] }, idem());
    expect(inv.status).toBe(201);
    const ret = await owner.post(`/api/sales/v1/invoices/${inv.data.id}/returns`, { lines: [{ invoice_line_id: inv.data.lines[0].id, qty: 1 }], refund_method: 'cash', to: 'quarantine', reason: 'e2e quarantine' }, idem());
    expect(ret.status).toBe(201);
    // release needs inventory.adjust + the pharmacist flag; the default pharmacist role lacks inventory.adjust
    const role = await owner.get<{ key: string; permissions: string[] }[]>('/api/auth/v1/roles');
    const ph = role.data.find((r) => r.key === 'pharmacist')!;
    if (!ph.permissions.includes('inventory.adjust')) await owner.patch('/api/auth/v1/roles/pharmacist', { permissions: [...ph.permissions, 'inventory.adjust'] });
    const page = await as('pharmacist');
    await page.goto('/stock/batches');
    await page.getByLabel('Expiring within').selectOption('');
    const row = page.getByRole('row', { name: new RegExp(d.meds.para.sku) }).filter({ has: page.getByRole('button', { name: 'Release quarantine' }) }).first();
    await row.getByRole('button', { name: 'Release quarantine' }).click();
    await page.getByRole('dialog').getByLabel(/^Reason/).fill('checked: sealed pack');
    await page.getByRole('dialog').getByRole('button', { name: 'Release quarantine' }).click();
    await expect(page.getByText('Released')).toBeVisible();
  });
});
