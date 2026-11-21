import { expect, test, type Page } from '@playwright/test';

/**
 * Every route of the project interface, in RPG and Pro, on desktop and on a phone: the place renders
 * without an error, has one main heading, names every control and does not scroll sideways.
 */
const ROUTES = [
  '/royaume', '/blueprint', '/blueprint/regles', '/blueprint/detection', '/blueprint/json',
  '/guilde', '/guilde/security', '/conseil', '/conseil/request-export', '/conseil/dark-theme', '/conseil/status-labels',
  '/quetes', '/quetes/request-status', '/bibliotheque', '/bibliotheque/patterns', '/bibliotheque/packs', '/bibliotheque/secteurs',
  '/bibliotheque/ref/owasp-asvs', '/forge', '/forge/request-history', '/forge/livrables', '/forge/outils', '/forge/storybook',
  '/tour', '/tour/alertes', '/tour/blocages', '/observatoire', '/documentation', '/documentation/partages', '/documentation/decisions',
  '/chroniques', '/intendance', '/intendance/catalogue', '/intendance/interface',
];

async function audit(page: Page) {
  return page.evaluate(() => {
    const name = (el: Element) => {
      const h = el as HTMLElement;
      const labelled = h.getAttribute('aria-labelledby')?.split(' ').map((id) => document.getElementById(id)?.textContent ?? '').join(' ');
      const labels = (h as HTMLInputElement).labels ? Array.from((h as HTMLInputElement).labels!).map((l) => l.textContent ?? '').join(' ') : '';
      return (h.getAttribute('aria-label') ?? labelled ?? labels ?? h.title ?? '').trim() || (h.getAttribute('title') ?? '').trim() || labels.trim() || (el.tagName === 'BUTTON' || el.tagName === 'A' ? (h.textContent ?? '').trim() : '');
    };
    const visible = (el: Element) => (el as HTMLElement).offsetParent !== null || (el as HTMLElement).getClientRects().length > 0;
    const unnamed = [...document.querySelectorAll('main input:not([type=hidden]), main select, main textarea, main button, main a[href]')]
      .filter((el) => visible(el) && !name(el)).map((el) => el.outerHTML.slice(0, 120));
    const ids = [...document.querySelectorAll('[id]')].map((el) => el.id).filter((id, i, all) => id && all.indexOf(id) !== i);
    return {
      h1: document.querySelectorAll('main h1').length,
      unnamed,
      duplicateIds: [...new Set(ids)],
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      broken: document.body.innerText.match(/n’a pas pu s’afficher|La commande a échoué|n’a pas renvoyé de JSON|Lien introuvable/g) ?? [],
    };
  });
}

/** Waits until the place is drawn and no request is in flight for a moment: the audit then sees the full screen. */
async function settle(page: Page, inflight: () => number) {
  await expect(page.locator('main h1')).toBeVisible();
  await expect(page.getByText(/^Chargement|Lecture d|Ouverture de la salle/)).toHaveCount(0, { timeout: 15_000 });
  let quiet = 0;
  for (let i = 0; i < 200 && quiet < 3; i++) { await page.waitForTimeout(50); quiet = inflight() === 0 ? quiet + 1 : 0; }
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

for (const [label, viewport, mode] of [['bureau RPG', { width: 1440, height: 900 }, 'explorer'], ['mobile Pro', { width: 390, height: 844 }, 'focus']] as const) {
  test(`every route renders cleanly (${label})`, async ({ page }) => {
    test.setTimeout(240_000);
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    let inflight = 0;
    page.on('request', () => { inflight++; });
    page.on('requestfinished', () => { inflight--; });
    page.on('requestfailed', () => { inflight--; });
    await page.setViewportSize(viewport);
    await page.addInitScript((m) => { localStorage.setItem('ogk-ui:prefs', JSON.stringify({ mode: m, motion: 'reduced' })); }, mode);
    if (mode === 'focus') {
      // Exercise a long interpreter path regardless of where Python is installed for this run.
      await page.route('**/api/run', async (route) => {
        if (route.request().postDataJSON()?.argv?.[0] !== 'preview') return route.continue();
        const response = await route.fetch();
        const body = await response.json();
        body.json.checks.push(`"/opt/${'environment'.repeat(12)}/bin/python" -c "print('ok')"`);
        await route.fulfill({ response, json: body });
      });
    }
    const problems: string[] = [];
    for (const route of ROUTES) {
      await page.goto(`/#${route}`);
      await settle(page, () => inflight);
      const a = await audit(page);
      if (a.h1 !== 1) problems.push(`${route}: ${a.h1} h1`);
      if (a.unnamed.length) problems.push(`${route}: unnamed ${a.unnamed.join(' | ')}`);
      if (a.duplicateIds.length) problems.push(`${route}: duplicate ids ${a.duplicateIds.join(', ')}`);
      if (a.overflow > 1) problems.push(`${route}: scrolls sideways by ${a.overflow}px`);
      if (a.broken.length) problems.push(`${route}: ${a.broken.join(', ')}`);
    }
    expect(problems, problems.join('\n')).toEqual([]);
    expect(errors, errors.join('\n')).toEqual([]);
  });
}
