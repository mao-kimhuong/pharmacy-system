// Promotion editor: all 6 types through the UI with the preview price, edit, deactivate, errors next to their
// field in EN and KM, and the manager's branch rule. Each type has its own medicine so saved rules cannot compete.
import type { Page } from '@playwright/test';
import { Http, apiLogin, waitFor } from './lib/api';
import { expect, test } from './fixtures';
import { loadSeed } from './seed';

interface Med { id: string; sku: string; pack: string }
const s = String(Date.now()).slice(-6);
let owner: Http;
const meds: Record<string, Med> = {};
let groupName = '';
let customerName = '';
const codes: string[] = [];

async function med(key: string, price: string) {
  const sku = `PRM${key.toUpperCase()}${s}`;
  const r = await owner.post<{ id: string; pack_units: { id: string }[] }>('/api/catalog/v1/medicines', { sku, brand_name: `Promo ${key} ${s}`, generic_name: 'Testamol', strength: '1 mg', base_unit: 'tab', base_price: price, pack_units: [] });
  if (r.status >= 300) throw new Error(JSON.stringify(r.data));
  meds[key] = { id: r.data.id, sku, pack: r.data.pack_units[0].id };
}

test.beforeAll(async () => {
  const seed = loadSeed();
  const a = seed.accounts.owner;
  owner = (await apiLogin(a.phone, a.password, a.totp)).http;
  for (const k of ['pct', 'amt', 'bxy', 'bun', 'bun2', 'tier', 'grp', 'edit']) await med(k, '1.00');
  groupName = `Clinic ${s}`;
  const g = await owner.post<{ id: string }>('/api/customers/v1/customer-groups', { name_en: groupName });
  customerName = `Promo Customer ${s}`;
  const c = await owner.post<{ id: string }>('/api/customers/v1/customers', { phone: `0977${s.slice(-5)}`, name: customerName, group_id: g.data.id });
  if (c.status >= 300) throw new Error(JSON.stringify(c.data));
  // sales learns about the medicines and the customer over RabbitMQ
  await waitFor(async () => {
    const r = await owner.post<{ lines?: unknown[] }>('/api/sales/v1/carts/preview', { branch_id: seed.branchId, customer_id: c.data.id, lines: Object.values(meds).map((m) => ({ medicine_id: m.id, pack_unit_id: m.pack, qty: 1 })) });
    return r.status === 200 ? r : null;
  }, 60);
});

test.afterAll(async () => {
  const list = await owner.get<{ id: string; code: string; is_active: boolean }[]>('/api/catalog/v1/promotions');
  for (const p of list.data) if (codes.includes(p.code) && p.is_active) await owner.post(`/api/catalog/v1/promotions/${p.id}/deactivate`, {});
});

async function open(page: Page, code: string, name: string) {
  await page.goto('/sales/promotions');
  await page.getByRole('button', { name: '+ New promotion' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel(/^Code/).fill(code);
  await dlg.getByLabel(/^Name \(EN\)|^Name.*English/).fill(name);
  codes.push(code);
  return dlg;
}

async function pick(page: Page, input: ReturnType<Page['locator']>, sku: string) {
  await input.fill(sku);
  await page.getByRole('option', { name: new RegExp(sku) }).first().click();
}

const targetBox = (dlg: ReturnType<Page['getByRole']>) => dlg.locator('input[role=combobox]').first();
const sampleBox = (dlg: ReturnType<Page['getByRole']>) => dlg.locator('input[role=combobox]').last();

async function previewTotal(page: Page, dlg: ReturnType<Page['getByRole']>, lines: [Med, number][]) {
  for (const [m, qty] of lines) {
    await pick(page, sampleBox(dlg), m.sku);
    await dlg.getByRole('row', { name: new RegExp(m.sku) }).getByRole('textbox', { name: 'Quantity' }).fill(String(qty));
  }
  await dlg.getByRole('button', { name: 'Preview', exact: true }).click();
  return dlg.getByTestId('promo-preview');
}

async function saveOk(page: Page, dlg: ReturnType<Page['getByRole']>, name: string) {
  await dlg.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dlg).toBeHidden();
  await expect(page.getByRole('row', { name: new RegExp(name) })).toBeVisible();
}

test.describe('Promotion editor', () => {
  test('% off with date window, days, limits and stackable: preview, save, reopen with the same values', async ({ as }) => {
    const page = await as('owner');
    const name = `Pct ${s}`;
    const dlg = await open(page, `PCT${s}`, name);
    await dlg.getByLabel(/^Discount/).fill('10');
    await pick(page, targetBox(dlg), meds.pct.sku);
    const from = dlg.locator('input[type=datetime-local]').first();
    await from.fill('2026-01-01T09:30');
    await expect(from).toHaveValue('2026-01-01T09:30'); // Phnom Penh time stays as typed
    await dlg.getByRole('button', { name: 'Stackable' }).click();
    await dlg.getByLabel('Max uses in total').fill('100');
    await dlg.getByLabel('Max uses per customer').fill('5');
    await expect(await previewTotal(page, dlg, [[meds.pct, 10]])).toContainText('$9.00');
    await saveOk(page, dlg, name);
    await page.getByRole('row', { name: new RegExp(name) }).click();
    await expect(from).toHaveValue('2026-01-01T09:30');
    await expect(dlg.getByText(`Promo pct ${s}`).first()).toBeVisible(); // the name, not an id
    await expect(dlg.getByLabel('Max uses in total')).toHaveValue('100');
    await expect(dlg.getByRole('button', { name: 'Stackable' })).toHaveAttribute('aria-pressed', 'true');
  });

  test('amount off, buy X get Y and quantity tiers', async ({ as }) => {
    const page = await as('owner');
    let dlg = await open(page, `AMT${s}`, `Amt ${s}`);
    await dlg.getByRole('button', { name: 'USD off' }).click();
    await dlg.getByLabel(/^USD off per unit/).fill('0.50');
    await pick(page, targetBox(dlg), meds.amt.sku);
    await expect(await previewTotal(page, dlg, [[meds.amt, 10]])).toContainText('$5.00');
    await saveOk(page, dlg, `Amt ${s}`);

    dlg = await open(page, `BXY${s}`, `Bxy ${s}`);
    await dlg.getByRole('button', { name: 'Buy X get Y' }).click();
    await dlg.getByLabel(/^Buy/).fill('2');
    await dlg.getByLabel(/^Get free/).fill('1');
    await pick(page, targetBox(dlg), meds.bxy.sku);
    await expect(await previewTotal(page, dlg, [[meds.bxy, 3]])).toContainText('$2.00');
    await saveOk(page, dlg, `Bxy ${s}`);

    dlg = await open(page, `TIER${s}`, `Tier ${s}`);
    await dlg.getByRole('button', { name: 'Quantity tiers', exact: true }).click();
    await dlg.getByRole('button', { name: '+ Add tier' }).click();
    await dlg.getByLabel('Minimum quantity').fill('10');
    await dlg.getByLabel('Percent off').fill('20');
    await pick(page, targetBox(dlg), meds.tier.sku);
    await expect(await previewTotal(page, dlg, [[meds.tier, 10]])).toContainText('$8.00');
    await saveOk(page, dlg, `Tier ${s}`);
  });

  test('bundle price: the items are chosen in the editor', async ({ as }) => {
    const page = await as('owner');
    const dlg = await open(page, `BUN${s}`, `Bundle ${s}`);
    await dlg.getByRole('button', { name: 'Bundle price', exact: true }).click();
    await dlg.getByLabel(/^Bundle price/).fill('1.50');
    await pick(page, targetBox(dlg), meds.bun.sku);
    await pick(page, targetBox(dlg), meds.bun2.sku);
    await expect(await previewTotal(page, dlg, [[meds.bun, 1], [meds.bun2, 1]])).toContainText('$1.50');
    await saveOk(page, dlg, `Bundle ${s}`);
  });

  test('customer-group price: applies for a customer of the group', async ({ as }) => {
    const page = await as('owner');
    const dlg = await open(page, `GRP${s}`, `Group ${s}`);
    await dlg.getByRole('button', { name: 'Group price', exact: true }).click();
    await dlg.getByLabel(/^Group price/).fill('0.40');
    await pick(page, targetBox(dlg), meds.grp.sku);
    await dlg.getByLabel(/^Customer groups/).fill(groupName);
    await page.getByRole('listbox').getByRole('option', { name: groupName }).click();
    await dlg.getByLabel('Customer (optional)').fill(customerName);
    await page.getByRole('option', { name: new RegExp(customerName) }).click();
    await expect(await previewTotal(page, dlg, [[meds.grp, 10]])).toContainText('$4.00');
    await saveOk(page, dlg, `Group ${s}`);
  });

  test('edit one, deactivate one', async ({ as }) => {
    const page = await as('owner');
    const dlg = await open(page, `EDT${s}`, `Before ${s}`);
    await dlg.getByLabel(/^Discount/).fill('5');
    await pick(page, targetBox(dlg), meds.edit.sku);
    await saveOk(page, dlg, `Before ${s}`);
    await page.getByRole('row', { name: new RegExp(`Before ${s}`) }).click();
    await dlg.getByLabel(/^Name \(EN\)|^Name.*English/).fill(`After ${s}`);
    await dlg.getByLabel(/^Discount/).fill('15');
    await saveOk(page, dlg, `After ${s}`);
    const row = page.getByRole('row', { name: new RegExp(`After ${s}`) });
    await row.getByRole('button', { name: 'Deactivate' }).click();
    await expect(row.getByText('Inactive')).toBeVisible();
    await expect(row.getByRole('button', { name: 'Activate' })).toBeVisible();
  });

  test('errors show next to their field, in English and Khmer; nothing fails silently', async ({ as }) => {
    const page = await as('owner');
    const dlg = await open(page, '', '');
    await dlg.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dlg.getByText('This field is required.')).toHaveCount(2);
    await dlg.getByLabel(/^Code/).fill(`ERR${s}`);
    await dlg.getByLabel(/^Name \(EN\)|^Name.*English/).fill('Errors');
    await dlg.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dlg.getByText('Enter a percentage above 0, up to 100.')).toBeVisible();
    await dlg.getByLabel(/^Discount/).fill('10');
    await dlg.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dlg.getByText('Choose the medicines, categories or brands it applies to.')).toBeVisible();
    await dlg.getByRole('button', { name: 'Bundle price', exact: true }).click();
    await dlg.getByLabel(/^Bundle price/).fill('1');
    await dlg.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dlg.getByText('A bundle needs at least two units.')).toBeVisible();
    await dlg.getByRole('button', { name: 'Group price', exact: true }).click();
    await pick(page, targetBox(dlg), meds.edit.sku);
    await dlg.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dlg.getByText('Choose at least one customer group.')).toBeVisible();
    await dlg.getByRole('button', { name: 'Cancel' }).click();
    // a code that is already used: on the Code field
    const dup = await open(page, `PCT${s}`, 'Dup');
    await dup.getByLabel(/^Discount/).fill('5');
    await pick(page, targetBox(dup), meds.edit.sku);
    await dup.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dup.getByText('This code is already used.')).toBeVisible();
    await dup.getByRole('button', { name: 'Cancel' }).click();
    // Khmer
    await page.evaluate(() => localStorage.setItem('pharmacy.lang', 'km'));
    await page.goto('/sales/promotions');
    await page.getByRole('button', { name: '+ ប្រូម៉ូសិនថ្មី' }).click();
    const km = page.getByRole('dialog');
    await km.getByRole('button', { name: 'រក្សាទុក', exact: true }).click();
    await expect(km.getByText('ត្រូវបំពេញវាលនេះ។')).toHaveCount(2);
    await page.evaluate(() => localStorage.setItem('pharmacy.lang', 'en'));
  });

  test('a manager works inside their own branches', async ({ as, seed }) => {
    const page = await as('manager');
    const dlg = await open(page, `MGR${s}`, `Manager ${s}`);
    await dlg.getByLabel(/^Discount/).fill('5');
    await pick(page, targetBox(dlg), meds.edit.sku);
    const remove = dlg.getByRole('button', { name: new RegExp(`Remove ${seed.branchCode}`) });
    await expect(remove).toBeVisible(); // their branches come filled in
    await remove.click();
    await dlg.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dlg.getByText('Choose your branches: only the owner can use all branches.')).toBeVisible();
    await dlg.getByLabel(/^Branches/).fill(seed.branchCode);
    await page.getByRole('listbox').getByRole('option', { name: new RegExp(seed.branchCode) }).click();
    await saveOk(page, dlg, `Manager ${s}`);
  });
});

