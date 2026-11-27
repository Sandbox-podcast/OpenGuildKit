import { expect, test, type Page } from '@playwright/test';

/**
 * What the pages ask of the local API, command by command (scripts/serve-sample.mjs builds the project fresh).
 * This file sorts before project.spec.ts, so it reads the sample project as built: the tests change nothing in it.
 */

/** The commands the page sends, in order: `task route closing-survey`, `batch(7)`. */
function recordCommands(page: Page) {
  const sent: string[] = [];
  page.on('request', (request) => {
    if (!request.url().includes('/api/run')) return;
    const body = JSON.parse(request.postData() ?? '{}') as { argv?: string[]; batch?: Record<string, string[]> };
    sent.push(body.argv ? body.argv.join(' ') : `batch(${Object.keys(body.batch ?? {}).length})`);
  });
  return sent;
}
const count = (sent: string[], command: RegExp | string) =>
  sent.filter((c) => (typeof command === 'string' ? c === command : command.test(c))).length;

/** The page hidden for two seconds, then shown again: what coming back to the tab does. */
async function leaveAndReturn(page: Page) {
  const set = (state: string) =>
    page.evaluate((value) => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => value });
      document.dispatchEvent(new Event('visibilitychange'));
    }, state);
  await set('hidden');
  await page.waitForTimeout(1700);
  await set('visible');
}

/** Issue #469: `brains --json` (146 KB, 3 % of it shown) loaded on every screen for a search that was closed. */
test('loads the brains for the search only once it is open and has two letters', async ({ page }) => {
  const sent = recordCommands(page);
  await page.goto('/#/royaume');
  await expect(page.locator('.project-chip')).toContainText('Portail support');
  await expect(page.locator('.todo-list').first()).toBeVisible();
  await page.waitForTimeout(600);
  expect(count(sent, 'brains --json')).toBe(0);

  await page.keyboard.press('Control+k');
  const search = page.getByRole('dialog', { name: 'Rechercher dans le projet' }).getByLabel('Rechercher');
  await search.fill('s');
  await page.waitForTimeout(300);
  expect(count(sent, 'brains --json')).toBe(0);
  await search.fill('security');
  await expect.poll(() => count(sent, 'brains --json')).toBe(1);
  await expect(page.getByRole('dialog', { name: 'Rechercher dans le projet' }).getByText('Cerveau', { exact: true }).first()).toBeVisible();
});

/** Issue #469: a screen that shows brain titles received the review, triggers and sources of every brain. */
test('gives a screen that shows brain titles under 10 KB, and the Guild the whole catalog', async ({ page }) => {
  const sizes: number[] = [];
  page.on('response', async (response) => {
    const body = JSON.parse(response.request().postData() ?? '{}') as { argv?: string[] };
    if (response.url().includes('/api/run') && body.argv?.join(' ') === 'brains --json') sizes.push((await response.body()).length);
  });
  await page.goto('/#/conseil/closing-survey');
  await expect(page.locator('main .board-grid')).toBeVisible();
  await expect.poll(() => sizes.length).toBe(1);
  expect(sizes[0]).toBeLessThan(10_000);

  await page.goto('/#/guilde');
  await expect.poll(() => sizes.length).toBe(2);
  expect(sizes[1]).toBeGreaterThan(50_000);
});

/** Issue #469: coming back to the tab reloaded the catalog (`references --json`, 549 KB decoded) along with the project. */
test('reloads the project, not the catalog, when the person comes back to the tab', async ({ page }) => {
  const sent = recordCommands(page);
  await page.goto('/#/bibliotheque');
  await expect(page.locator('.ref-card').first()).toBeVisible();
  await page.waitForTimeout(600);
  expect(count(sent, 'references --json')).toBe(1);

  sent.length = 0;
  await leaveAndReturn(page);
  await expect.poll(() => count(sent, /^batch\(/)).toBe(1);
  await page.waitForTimeout(600);
  expect(count(sent, /^(references|brains) /)).toBe(0);

  // The button asks for everything, the catalog too.
  sent.length = 0;
  await page.getByRole('button', { name: 'Actualiser les données du projet' }).click();
  await expect.poll(() => count(sent, 'references --json')).toBe(1);
});

/** Issue #467: one `task route` per character typed in the reason of an adjustment, and the grid of brains blinked. */
test('asks for one routing while a reason is typed, and keeps the brains on screen', async ({ page }) => {
  const sent = recordCommands(page);
  await page.goto('/#/conseil/closing-survey');
  const reason = page.getByLabel('Motif de l’ajustement');
  await expect(reason).toBeVisible();
  await expect(page.locator('main .board-grid')).toBeVisible();
  await page.waitForTimeout(800);
  const before = count(sent, /^task route /);

  let removals = 0;
  await page.exposeFunction('gridRemoved', () => {
    removals++;
  });
  await page.evaluate(() => {
    let shown = !!document.querySelector('main .board-grid');
    new MutationObserver(() => {
      const now = !!document.querySelector('main .board-grid');
      if (shown && !now) (window as unknown as { gridRemoved: () => void }).gridRemoved();
      shown = now;
    }).observe(document.querySelector('main')!, { childList: true, subtree: true });
  });
  const text = 'La sécurité doit relire ce flux de mails';
  expect(text).toHaveLength(40);
  await reason.pressSequentially(text, { delay: 40 });
  await page.waitForTimeout(1500);

  expect(count(sent, /^task route /) - before).toBeLessThanOrEqual(2);
  expect(removals).toBe(0);
  await expect(page.locator('main .board-grid')).toBeVisible();
});
