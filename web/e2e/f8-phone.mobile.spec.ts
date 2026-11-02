// F8 on a phone (360 px, Khmer, touch): no sideways scrolling, every control at least 44 px high, Khmer text not cut
// off, axe clean.
import type { Page } from '@playwright/test';
import { expect, expectAccessible, freshContext, test, uiLogin } from './fixtures';

const ROUTES = ['/', '/more', '/pos', '/sales/invoices', '/rx/patients', '/rx/prescriptions', '/stock', '/stock/counts', '/purchase/receiving', '/transfers', '/profile'];

/** Visible controls lower than 44 px (inline text links excepted). */
function smallTargets(page: Page) {
  return page.evaluate(() => {
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('button, a[href], input:not([type=hidden]), select, [role=button], [role=tab], [role=menuitem], [role=switch]'))) {
      const r = el.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1 || el.closest('[aria-hidden=true]')) continue; // sr-only skip link
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden') continue;
      // checkboxes and radios count with their label
      const box = (el instanceof HTMLInputElement && (el.type === 'checkbox' || el.type === 'radio') && el.closest('label')) || el;
      const h = box.getBoundingClientRect().height;
      const inlineLink = el.tagName === 'A' && style.display === 'inline';
      if (h < 43.5 && !inlineLink) out.push(`${el.tagName.toLowerCase()} "${(el.getAttribute('aria-label') ?? el.textContent ?? '').trim().slice(0, 30)}" ${Math.round(h)}px`);
    }
    return out;
  });
}

/** Elements whose Khmer text is cut off (ellipsis or clipped). */
function cutKhmer(page: Page) {
  return page.evaluate(() => {
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      if (el.children.length || !/[ក-៿]/.test(el.textContent ?? '')) continue;
      if (el.closest('.sr-only')) continue; // visually hidden on purpose (skip link, table captions)
      const s = getComputedStyle(el);
      const clips = s.textOverflow === 'ellipsis' || s.overflow === 'hidden' || s.overflowX === 'hidden';
      if (clips && el.scrollWidth > el.clientWidth + 1) out.push(`${el.tagName.toLowerCase()}.${el.className.toString().split(' ').slice(0, 4).join('.')} ${(el.textContent ?? '').trim().slice(0, 40)}`);
    }
    return out;
  });
}

test('phone in Khmer: no sideways scroll, 44 px targets, Khmer not cut, axe clean', async ({ browser, seed }) => {
  test.setTimeout(240_000);
  const ctx = await freshContext(browser, 'km', { width: 360, height: 780 });
  const page = await ctx.newPage();
  const a = seed.accounts.pharmacist;
  await uiLogin(page, a.phone, a.password);
  await expect(page.getByRole('navigation', { name: 'ម៉ឺនុយ' })).toBeVisible();
  await page.evaluate((id) => localStorage.setItem('pharmacy.branch', id), seed.branchId);
  const problems: string[] = [];
  for (const path of ROUTES) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('[aria-busy=true]')).toHaveCount(0, { timeout: 15_000 });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (over > 1) problems.push(`${path}: page is ${over}px wider than the screen`);
    for (const s of await smallTargets(page)) problems.push(`${path}: ${s}`);
    for (const s of await cutKhmer(page)) problems.push(`${path}: cut "${s}"`);
    await expectAccessible(page);
  }
  expect(problems).toEqual([]);
  await ctx.close();
});
