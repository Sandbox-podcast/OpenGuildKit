// Measures the project interface served by `openguildkit ui`: first screen, then each place.
//   node scripts/measure-project.mjs 'http://ogk-….localhost:7311/?key=…' [runs]   (the address `openguildkit ui` printed)
// For each place: time until its content shows, API requests, and bytes downloaded (cold, then warm).
import { chromium } from '@playwright/test';

// The printed address carries the key that opens the session: the first page of each run goes through it.
if (!process.argv[2]) { console.error('Give the address openguildkit ui printed: it carries the key and the host name of the run.'); process.exit(1); }
const printed = new URL(process.argv[2]);
const base = printed.origin;
const opening = `${base}/${printed.search}`;
const runs = Number(process.argv[3] ?? 3);
const PLACES = [
  ['/quetes', '.kanban'], ['/conseil/request-export', '.review-card'], ['/forge/request-history', 'table.data'],
  ['/bibliotheque', '.ref-card'], ['/guilde', '.brain-card'], ['/tour/alertes', 'table.data'], ['/observatoire', '.card'],
  ['/documentation', '.panel'], ['/chroniques', '.chronicle-item'], ['/intendance', '.card'], ['/blueprint', '.list-editor'],
];
/** Changes the route in the page and counts frames until the place's content is there (Playwright's own polling is too coarse). */
const until = (page, route, selector) => page.evaluate(async ([r, s]) => {
  const t0 = performance.now();
  if (r) window.location.hash = `#${r}`;
  while (!document.querySelector(`main ${s}`)) await new Promise((resolve) => requestAnimationFrame(resolve));
  return Math.round(performance.now() - t0);
}, [route, selector]);
const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL === 'chromium' ? undefined : 'chrome' });
const first = []; const places = new Map();
for (let run = 0; run < runs; run++) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  let api = 0; let bytes = 0;
  page.on('request', (r) => { if (r.url().includes('/api/')) api++; });
  page.on('response', async (r) => { try { bytes += (await r.body()).length; } catch { /* redirects */ } });
  const t0 = Date.now();
  await page.goto(`${opening}#/royaume`);
  await page.locator('.todo-list').first().waitFor();
  const shownFirst = Math.round(await page.evaluate(() => performance.getEntriesByType('navigation')[0] ? performance.now() : 0)) || Date.now() - t0;
  await page.waitForTimeout(200); // let the requests the place started finish, to count them
  first.push({ ms: shownFirst, api, kb: Math.round(bytes / 1024) });
  for (const [route, selector] of PLACES) {
    api = 0; bytes = 0;
    const shown = await until(page, route, selector);
    await page.waitForTimeout(200); // let the requests the place started finish, to count them
    const entry = places.get(route) ?? [];
    entry.push({ ms: shown, api, kb: Math.round(bytes / 1024) });
    places.set(route, entry);
  }
  await context.close();
}
await browser.close();
const pick = (list) => ({ ms: median(list.map((x) => x.ms)), api: median(list.map((x) => x.api)), kb: median(list.map((x) => x.kb)) });
const f = pick(first);
console.log(`Premier écran (Royaume) : ${f.ms} ms, ${f.api} requête(s) d'API, ${f.kb} Ko`);
for (const [route, list] of places) { const p = pick(list); console.log(`${route.padEnd(26)} ${String(p.ms).padStart(5)} ms  ${p.api} API  ${p.kb} Ko`); }
console.log(`Médiane de ${runs} exécution(s), navigateur neuf à chaque fois.`);
