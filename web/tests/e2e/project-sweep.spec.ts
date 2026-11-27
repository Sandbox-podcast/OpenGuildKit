import { expect, test, type Page } from '@playwright/test';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

/**
 * Every route of the project interface, in RPG and Pro, on desktop and on a phone: the place renders
 * without an error, has one main heading, names every control, does not scroll sideways, lets the keyboard reach
 * what scrolls, names its table headers, keeps 24 px targets and lets a link's name hold its visible words.
 * axe-core runs too when it is installed (or AXE_CORE_PATH names its axe.min.js): a serious or critical violation fails.
 */
function axeSource(): string | null {
  try { return readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf-8'); } catch { /* not installed */ }
  const path = process.env.AXE_CORE_PATH;
  return path && existsSync(path) ? readFileSync(path, 'utf-8') : null;
}
const AXE = axeSource();
const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];
const ROUTES = [
  '/royaume', '/blueprint', '/blueprint/regles', '/blueprint/detection', '/blueprint/json',
  '/guilde', '/guilde/security', '/conseil', '/conseil/request-export', '/conseil/dark-theme', '/conseil/status-labels',
  '/quetes', '/quetes/request-status', '/bibliotheque', '/bibliotheque/patterns', '/bibliotheque/packs', '/bibliotheque/secteurs',
  '/bibliotheque/ref/owasp-asvs', '/forge', '/forge/request-history', '/forge/livrables', '/forge/outils', '/forge/storybook',
  '/tour', '/tour/alertes', '/tour/blocages', '/observatoire', '/documentation', '/documentation/partages', '/documentation/decisions',
  '/chroniques', '/intendance', '/intendance/catalogue', '/intendance/interface', '/arsenal',
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
    const focusable = 'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';
    const short = (el: Element) => el.outerHTML.slice(0, 100);
    const scrollers = [...document.querySelectorAll('main *')].filter((el) => {
      const style = getComputedStyle(el);
      const sideways = /auto|scroll/.test(style.overflowX) && el.scrollWidth > el.clientWidth + 1;
      const down = /auto|scroll/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 1;
      return (sideways || down) && (el as HTMLElement).tabIndex < 0 && !el.querySelector(focusable);
    }).map(short);
    const SECTION_ROLES = ['region', 'alert', 'alertdialog', 'application', 'banner', 'complementary', 'contentinfo', 'dialog', 'document', 'feed', 'log', 'main', 'marquee', 'navigation', 'none', 'note', 'presentation', 'search', 'status', 'tabpanel'];
    const targets = [...document.querySelectorAll('main .target-link, main .map-house')].filter((el) => {
      const box = el.getBoundingClientRect();
      return box.width > 0 && (box.width < 24 || box.height < 24);
    }).map(short);
    // The words a link or a button shows, without what is hidden from assistive technologies or only for them.
    const shownWords = (el: Element) => {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const words: string[] = [];
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const parent = node.parentElement;
        if (!parent || parent.closest('[aria-hidden="true"], .sr-only') || !parent.getClientRects().length) continue;
        words.push(node.textContent ?? '');
      }
      return words.join(' ').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    };
    const labelled = [...document.querySelectorAll('a[aria-label], button[aria-label]')].filter((el) => {
      const shown = shownWords(el);
      const name = (el.getAttribute('aria-label') ?? '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
      return shown.length > 2 && !name.includes(shown);
    }).map(short);
    // English left by the CLI must be marked lang="en": a text with two English words or more, outside a marked
    // passage, a command (code) and what a person or the agent wrote themselves (data-own), is flagged.
    const ENGLISH = /\b(the|and|with|this|that|is|are|of|to|for|when|which|from|must|should|needs|each|every|its|their|your|not|has|have|will|can|only|into|than|then|before|after)\b/gi;
    const english: string[] = [];
    const texts = document.createTreeWalker(document.querySelector('main') ?? document.body, NodeFilter.SHOW_TEXT);
    for (let node = texts.nextNode(); node; node = texts.nextNode()) {
      const parent = node.parentElement;
      if (!parent || parent.closest('[lang]:not(html), [data-own], code, kbd, script, style, [aria-hidden="true"]') || !parent.getClientRects().length) continue;
      const words = new Set((node.textContent?.match(ENGLISH) ?? []).map((w) => w.toLowerCase()));
      if (words.size >= 2) english.push(node.textContent!.trim().slice(0, 90));
    }
    return {
      english: [...new Set(english)],
      scrollers,
      emptyHeaders: [...document.querySelectorAll('main th')].filter((th) => !th.textContent?.trim() && !th.getAttribute('aria-label')).map(short),
      roles: [...document.querySelectorAll('main section[role]')].filter((el) => !SECTION_ROLES.includes(el.getAttribute('role') ?? '')).map(short),
      targets,
      labelled,
      demo: document.querySelectorAll('a[href*="demo=1"]').length,
      // In the Pro style the page speaks the glossary: a task is a tâche, never a quête.
      quest: [...new Set(document.body.innerText.match(/\bqu[êe]tes?\b/gi) ?? [])],
      h1: document.querySelectorAll('main h1').length,
      unnamed,
      duplicateIds: [...new Set(ids)],
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      broken: document.body.innerText.match(/n’a pas pu s’afficher|La commande a échoué|n’a pas renvoyé de JSON|Lien introuvable/g) ?? [],
    };
  });
}

/**
 * The violations of the page's security policy, as the browser reports them: a style it refuses (the policy has no
 * 'unsafe-inline'), a script, an image. A page that sets a style attribute or adds a style element fails here.
 */
async function watchPolicy(page: Page) {
  const violations: string[] = [];
  await page.exposeFunction('reportPolicyViolation', (violation: string) => violations.push(violation));
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      (window as unknown as { reportPolicyViolation: (v: string) => void }).reportPolicyViolation(`${e.effectiveDirective} ${e.blockedURI || 'inline'} (${e.sourceFile}:${e.lineNumber})`);
    });
  });
  return violations;
}

/** Waits until the place is drawn and no request is in flight for a moment: the audit then sees the full screen. */
async function settle(page: Page, inflight: () => number) {
  await expect(page.locator('main h1')).toBeVisible();
  await expect(page.getByText(/^Chargement|Lecture d|Ouverture de la salle/)).toHaveCount(0, { timeout: 15_000 });
  let quiet = 0;
  for (let i = 0; i < 200 && quiet < 3; i++) { await page.waitForTimeout(50); quiet = inflight() === 0 ? quiet + 1 : 0; }
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

/** axe-core on the page as it is: the serious and critical violations, by rule, with their first elements. */
async function axe(page: Page) {
  if (!AXE) return [];
  await page.evaluate(AXE);
  return page.evaluate(async (tags) => {
    const result = await (window as unknown as { axe: { run: (d: Document, o: unknown) => Promise<{ violations: { id: string; impact: string; nodes: { target: string[] }[] }[] }> } }).axe.run(document, { runOnly: { type: 'tag', values: tags } });
    return result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
  }, AXE_TAGS);
}

const VARIANTS = [
  ['bureau RPG', { width: 1440, height: 900 }, 'explorer'], ['bureau Pro', { width: 1440, height: 900 }, 'focus'],
  ['mobile RPG', { width: 375, height: 812 }, 'explorer'], ['mobile Pro', { width: 375, height: 812 }, 'focus'],
] as const;

for (const [label, viewport, mode] of VARIANTS) {
  test(`every route renders cleanly (${label})`, async ({ page }) => {
    test.setTimeout(360_000);
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    const violations = await watchPolicy(page);
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
      if (mode === 'focus' && a.quest.length) problems.push(`${route}: the Pro style says ${a.quest.join(', ')}`);
      if (a.demo) problems.push(`${route}: links the demo, which the product page does not ship`);
      if (a.unnamed.length) problems.push(`${route}: unnamed ${a.unnamed.join(' | ')}`);
      if (a.duplicateIds.length) problems.push(`${route}: duplicate ids ${a.duplicateIds.join(', ')}`);
      if (a.overflow > 1) problems.push(`${route}: scrolls sideways by ${a.overflow}px`);
      if (a.broken.length) problems.push(`${route}: ${a.broken.join(', ')}`);
      if (a.scrollers.length) problems.push(`${route}: scrolls without keyboard access ${a.scrollers.join(' | ')}`);
      if (a.emptyHeaders.length) problems.push(`${route}: empty table header ${a.emptyHeaders.join(' | ')}`);
      if (a.roles.length) problems.push(`${route}: role not allowed on a section ${a.roles.join(' | ')}`);
      if (a.targets.length) problems.push(`${route}: target under 24 px ${a.targets.join(' | ')}`);
      if (a.english.length) problems.push(`${route}: English without lang="en" ${a.english.join(' | ')}`);
      if (a.labelled.length) problems.push(`${route}: name without its visible words ${a.labelled.join(' | ')}`);
      for (const violation of await axe(page)) problems.push(`${route}: axe ${violation}`);
    }
    expect(problems, problems.join('\n')).toEqual([]);
    expect(violations, violations.join('\n')).toEqual([]);
    expect(errors, errors.join('\n')).toEqual([]);
  });
}

test('the Arsenal shows a header scene that exists, in RPG', async ({ page }) => {
  // Twelve scenes are drawn for thirteen places: a place without its own shows another, never a missing image.
  const failed: string[] = [];
  page.on('response', (r) => { if (r.request().resourceType() === 'image' && r.status() >= 400) failed.push(`${r.status()} ${r.url()}`); });
  await page.addInitScript(() => { localStorage.setItem('ogk-ui:prefs', JSON.stringify({ mode: 'explorer', motion: 'reduced' })); });
  await page.goto('/#/arsenal');
  await expect(page.getByRole('heading', { level: 1, name: 'Arsenal' })).toBeVisible();
  const scene = page.locator('.place-heading-art img');
  await expect(scene).toHaveCount(1);
  await expect.poll(() => scene.evaluate((img: HTMLImageElement) => (img.complete ? img.naturalWidth : 0))).toBeGreaterThan(0);
  expect(failed).toEqual([]);
});
