// F4 purchase + transfer against the stack.
import { apiLogin, idem, waitFor } from './lib/api';
import { expect, test } from './fixtures';

test.describe('F4 purchase + transfer', () => {
  test('manager: purchase request → PO group → send; pharmacist receives 2 lots on a phone; pay to 0, overpay refused; supplier return as credit', async ({ as, seed }) => {
    test.setTimeout(240_000);
    const d = seed.extra.sales!;
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const s = String(Date.now()).slice(-6);
    const sup = await owner.post<{ id: string; name: string }>('/api/purchasing/v1/suppliers', { code: `S${s}`, name: `E2E Supplier ${s}`, payment_terms_days: 30 });
    expect(sup.status).toBeLessThan(300);
    const mgr = await as('manager');
    await mgr.goto('/purchase/requests');
    await mgr.getByRole('button', { name: '+ New request' }).click();
    const dlg = mgr.getByRole('dialog');
    await dlg.getByPlaceholder('Scan or search medicine…').fill(d.meds.para.sku);
    await mgr.getByRole('listbox').getByRole('option').first().click();
    await dlg.getByPlaceholder('Qty (base unit)').fill('200');
    const created = mgr.waitForResponse((r) => r.url().endsWith('/purchase-requests') && r.request().method() === 'POST');
    await dlg.getByRole('button', { name: 'Submit' }).click();
    const { number } = (await (await created).json()) as { number: string };
    await mgr.getByRole('row').filter({ hasText: number }).click(); // other tests leave requests too
    await mgr.getByRole('button', { name: 'Approve', exact: true }).click();
    await expect(mgr.getByText('Approve first, then route the lines')).toBeVisible();
    await mgr.getByRole('dialog').getByRole('row').nth(1).getByRole('checkbox').check();
    await mgr.getByRole('button', { name: 'Order from a supplier' }).click();
    const po = mgr.getByRole('dialog').last();
    await po.getByLabel(/^Supplier/).fill(`E2E Supplier ${s}`);
    await mgr.getByRole('listbox').getByRole('option').first().click();
    await po.getByLabel('Unit', { exact: true }).selectOption({ label: 'box (100)' });
    await po.getByLabel('Quantity', { exact: true }).fill('2');
    await po.getByLabel('Unit cost (USD)').fill('3.50');
    await po.getByRole('button', { name: 'Order from a supplier' }).click();
    await expect(mgr.getByRole('heading', { name: /-PG-/ })).toBeVisible();
    await mgr.getByRole('row').nth(1).click();
    await mgr.getByRole('button', { name: 'Mark as sent' }).click();
    await mgr.getByRole('dialog').getByRole('button', { name: 'Mark as sent' }).click();
    await expect(mgr.getByText('Sent', { exact: true })).toBeVisible();
    const poUrl = mgr.url();
    const poId = poUrl.split('/').pop()!;
    // pharmacist receives on a phone: 1 box lot A, 1 box lot B
    const ph = await as('pharmacist');
    await ph.setViewportSize({ width: 390, height: 844 });
    await ph.goto(`/purchase/receiving?po=${poId}`);
    await ph.getByRole('button', { name: '+ Another lot' }).click();
    const lots = ph.getByLabel(/^Lot/);
    await lots.nth(0).fill(`A${s}`);
    await lots.nth(1).fill(`B${s}`);
    await ph.getByLabel(/^Expiry/).nth(0).fill('2029-06-30');
    await ph.getByLabel(/^Expiry/).nth(1).fill('2030-06-30');
    await ph.getByLabel(/^Quantity/).nth(0).fill('1');
    await ph.getByLabel(/^Quantity/).nth(1).fill('1');
    await ph.getByRole('button', { name: 'Receive', exact: true }).click();
    await expect(ph.getByText(/Received as .*-GRN-/)).toBeVisible();
    // pay to 0, then overpaying is refused
    await mgr.goto('/purchase/payments');
    await mgr.getByRole('button', { name: '+ New payment' }).click();
    const pay = mgr.getByRole('dialog');
    await pay.getByLabel(/^Supplier/).fill(`E2E Supplier ${s}`);
    await mgr.getByRole('listbox').getByRole('option').first().click();
    await pay.getByLabel(/^Amount/).fill('7.00');
    await pay.getByRole('button', { name: 'New payment' }).click();
    await expect(mgr.getByText(/Payment .* posted/)).toBeVisible();
    await mgr.getByRole('button', { name: '+ New payment' }).click();
    await pay.getByLabel(/^Supplier/).fill(`E2E Supplier ${s}`);
    await mgr.getByRole('listbox').getByRole('option').first().click();
    await pay.getByLabel(/^Amount/).fill('1.00');
    await pay.getByRole('button', { name: 'New payment' }).click();
    await expect(pay.getByText('Payment is more than the supplier balance.')).toBeVisible();
    await pay.getByRole('button', { name: 'Cancel' }).click();
    // supplier return as credit
    await mgr.goto('/purchase/returns');
    await mgr.getByRole('button', { name: '+ New supplier return' }).click();
    const ret = mgr.getByRole('dialog');
    await ret.getByLabel(/^Supplier/).fill(`E2E Supplier ${s}`);
    await mgr.getByRole('listbox').getByRole('option').first().click();
    await ret.getByPlaceholder('Scan or search medicine…').fill(d.meds.para.sku);
    await mgr.getByRole('listbox').getByRole('option').first().click();
    await ret.getByLabel(/^Batch from this supplier/).selectOption({ index: 1 });
    await ret.getByLabel(/^Quantity/).fill('10');
    await ret.getByRole('button', { name: 'Save' }).click();
    await mgr.getByRole('row').filter({ hasText: 'Draft' }).first().getByRole('button', { name: 'Submit' }).click();
    await mgr.getByRole('dialog').getByRole('button', { name: 'Submit' }).click();
    await expect(mgr.getByRole('row').filter({ hasText: /Credited/i }).first()).toBeVisible();
  });

  test('owner: push a transfer, pick FEFO, dispatch, receive 1 short, write the difference off', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const code = `E2T${String(Date.now()).slice(-4)}`;
    const b = await owner.post<{ id: string }>('/api/branch/v1/branches', { code, name_km: code, name_en: `Branch ${code}` });
    await waitFor(async () => { const r = await owner.get<{ id: string }[]>('/api/branch/v1/branches'); return r.data.some((x) => x.id === b.data.id); });
    const page = await as('owner');
    await page.goto('/transfers');
    await page.getByRole('button', { name: '+ Send stock (no request)' }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel(/^To/).selectOption(b.data.id);
    await dlg.getByPlaceholder('Scan or search medicine…').fill(d.meds.para.sku);
    await page.getByRole('listbox').getByRole('option').first().click();
    await dlg.getByRole('textbox', { name: /^Quantity/ }).fill('5');
    await expect(async () => {
      await dlg.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByRole('button', { name: 'Pick FEFO' })).toBeVisible({ timeout: 3000 });
    }).toPass({ timeout: 30_000 });
    await page.getByRole('button', { name: 'Pick FEFO' }).click();
    await page.getByRole('button', { name: 'Dispatch' }).click();
    await expect(page.getByRole('button', { name: 'Receive' })).toBeVisible();
    await page.getByRole('button', { name: 'Receive' }).click();
    await page.getByRole('dialog').getByLabel('Received').first().fill('0'); // FEFO may split over batches: the first pick arrives short
    await page.getByRole('dialog').getByRole('button', { name: 'Receive' }).click();
    await expect(page.getByText('Short')).toBeVisible();
    await page.getByRole('button', { name: 'Resolve' }).click();
    await page.getByRole('dialog').getByLabel(/^Reason/).fill('e2e: lost in transit');
    await page.getByRole('dialog').getByRole('button', { name: 'Resolve' }).click();
    await expect(page.getByText(/Write off · e2e: lost in transit/)).toBeVisible();
    await page.getByRole('button', { name: 'Transfer note PDF' }).click();
    await expect(page.getByRole('dialog').locator('iframe')).toBeVisible({ timeout: 20_000 });
    await owner.post(`/api/branch/v1/branches/${b.data.id}/deactivate`, { reason: 'e2e' });
  });

  test('shrinkage above the limit waits; another person approves', async ({ as, seed }) => {
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const s = String(Date.now()).slice(-6);
    const m = await owner.post<{ id: string; sku: string; pack_units: { id: string }[] }>('/api/catalog/v1/medicines', { sku: `E2EEXP${s}`, brand_name: `E2E Pricey ${s}`, generic_name: 'Priceymol', base_unit: 'vial', base_price: '20.00' });
    await waitFor(async () => {
      const r = await owner.post<{ code?: string }>('/api/inventory/v1/stock-in', { branch_id: seed.branchId, reason: 'e2e shrinkage', lines: [{ medicine_id: m.data.id, pack_unit_id: m.data.pack_units[0].id, lot_no: `X${s}`, expiry_date: '2030-01-31', qty: 20, unit_cost: '10.00' }] }, idem());
      return r.data.code === 'UNKNOWN_MEDICINE' ? null : r;
    });
    const ph = await as('pharmacist');
    await ph.goto('/shrinkage');
    await ph.getByRole('button', { name: '+ Record shrinkage' }).click();
    const dlg = ph.getByRole('dialog');
    await dlg.getByPlaceholder('Scan or search medicine…').fill(m.data.sku);
    await ph.getByRole('listbox').getByRole('option').first().click();
    await dlg.getByLabel(/^Batch/).selectOption({ index: 1 });
    await dlg.getByLabel(/^Quantity/).fill('6');
    await dlg.getByRole('button', { name: 'Save' }).click();
    await expect(ph.getByRole('row').filter({ hasText: 'Pending approval' }).first()).toBeVisible();
    const mgr = await as('manager');
    await mgr.goto('/shrinkage');
    const row = mgr.getByRole('row').filter({ hasText: m.data.sku.slice(0, 3) }).filter({ hasText: 'Pending approval' }).first();
    await row.getByRole('button', { name: 'Approve' }).click();
    await expect(mgr.getByRole('row').filter({ hasText: 'Posted' }).first()).toBeVisible();
  });
});
