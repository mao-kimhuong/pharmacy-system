// F6 dashboard + reports against the stack (read models are built from events: allow a few seconds).
import { apiLogin, idem } from './lib/api';
import { expect, test } from './fixtures';

test.describe('F6 dashboard + reports', () => {
  test('owner sees profit on the dashboard; a manager without cost does not', async ({ as }) => {
    const owner = await as('owner');
    await owner.goto('/');
    await expect(owner.getByText('Net sales')).toBeVisible();
    await expect(owner.getByText('Gross profit')).toBeVisible();
    const mgr = await as('manager');
    await mgr.goto('/');
    await expect(mgr.getByText('Net sales')).toBeVisible();
    await expect(mgr.getByText('Gross profit')).toHaveCount(0);
  });

  test('a sale made now shows in Sale detail', async ({ as, seed }) => {
    const d = seed.extra.sales!;
    const { http: owner } = await apiLogin(seed.accounts.owner.phone, seed.accounts.owner.password, seed.accounts.owner.totp);
    const inv = await owner.post<{ number: string }>('/api/sales/v1/invoices', { branch_id: seed.branchId, lines: [{ medicine_id: d.meds.para.id, pack_unit_id: d.meds.para.packs.strip.id, qty: 1 }], payments: [{ method: 'cash', currency: 'USD', amount: '1.00' }] }, idem());
    expect(inv.status).toBe(201);
    const page = await as('owner');
    await expect(async () => {
      await page.goto('/reports/sales/detail');
      await expect(page.getByRole('cell', { name: inv.data.number }).first()).toBeVisible({ timeout: 3000 });
    }).toPass({ timeout: 45_000 });
  });

  test('CSV, XLSX and PDF exports download', async ({ as }) => {
    const page = await as('owner');
    await page.goto('/reports/sales/summary');
    await expect(page.getByRole('columnheader').first()).toBeVisible();
    for (const [label, ext] of [['CSV', 'csv'], ['Excel', 'xlsx'], ['PDF', 'pdf']] as const) {
      const dl = page.waitForEvent('download');
      await page.getByRole('button', { name: label, exact: true }).click();
      expect((await dl).suggestedFilename()).toMatch(new RegExp(`\\.${ext}$`));
    }
  });

  test('a cashier gets 403 on the margin report; a manager asking for another branch gets BRANCH_FORBIDDEN', async ({ as, seed }) => {
    const page = await as('cashier');
    await page.goto('/reports/sales/margin-by-item');
    await expect(page.getByRole('heading', { name: "You don't have permission to view this page" })).toBeVisible();
    const { http: mgr } = await apiLogin(seed.accounts.manager.phone, seed.accounts.manager.password, seed.accounts.manager.totp);
    const r = await mgr.get<{ code: string }>('/api/reports/v1/sales/detail?branch_id=00000000-0000-4000-8000-000000000999');
    expect(r.status).toBe(403);
    expect(r.data.code).toBe('BRANCH_FORBIDDEN');
  });
});
