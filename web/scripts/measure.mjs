/**
 * Local performance measures of a production build (docs/verification.md).
 * Usage: npm run build && npm run preview -- --port 5209 --strictPort
 *        node scripts/measure.mjs http://localhost:5209 [runs]
 * Each run uses a fresh Chrome context at 1440 × 900, no throttling.
 */
import { chromium } from '@playwright/test';

const base = process.argv[2] ?? 'http://localhost:5209';
const runs = Number(process.argv[3] ?? 5);
const median = (a) => [...a].sort((x, y) => x - y)[Math.floor(a.length / 2)];
const p95 = (a) => [...a].sort((x, y) => x - y)[Math.min(a.length - 1, Math.ceil(a.length * 0.95) - 1)];
const raf = (page, ms) => page.evaluate((d) => new Promise((resolve) => {
  const gaps = []; let last = performance.now(); const end = last + d;
  const tick = (t) => { gaps.push(t - last); last = t; if (t < end) requestAnimationFrame(tick); else resolve(gaps); };
  requestAnimationFrame(tick);
}), ms);
const frame = (page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(performance.now())))));

const rows = [];
for (let i = 0; i < runs; i++) {
  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? 'chrome' });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'fr-FR' });
  const page = await ctx.newPage();
  const t0 = Date.now();
  await page.goto(`${base}/#/entree`);
  await page.getByRole('button', { name: /Atelier Nova/ }).first().waitFor();
  const usable = Date.now() - t0;
  const entryBytes = await page.evaluate(() => performance.getEntriesByType('resource').reduce((n, r) => n + r.transferSize, 0) + (performance.getEntriesByType('navigation')[0]?.transferSize ?? 0));
  await page.getByRole('button', { name: /Atelier Nova/ }).first().click();
  const t1 = Date.now();
  await page.locator('.kingdom-map').waitFor();
  await frame(page);
  const map = Date.now() - t1;
  const gaps = await raf(page, 500);
  const t2 = Date.now();
  await page.evaluate(() => { location.hash = '#/bibliotheque'; });
  await page.locator('#lib-q').waitFor();
  const lib = Date.now() - t2;
  const t3 = Date.now();
  await page.locator('#lib-q').fill('SemVer');
  await page.locator('.ref-grid .card', { hasText: 'Semantic Versioning' }).first().waitFor();
  await frame(page);
  const filter = Date.now() - t3;
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Performance.enable');
  await cdp.send('HeapProfiler.collectGarbage');
  const heap = (await cdp.send('Performance.getMetrics')).metrics.find((m) => m.name === 'JSHeapUsedSize').value;
  const bytes = await page.evaluate(() => performance.getEntriesByType('resource').reduce((n, r) => n + r.transferSize, 0));
  rows.push({ usable, entryBytes, map, frame95: p95(gaps), lib, filter, heap, bytes });
  await browser.close();
}
const fmt = (k, f) => { const v = rows.map((r) => r[k]); return `${f(median(v))} (${f(Math.min(...v))} – ${f(Math.max(...v))})`; };
const ms = (v) => `${Math.round(v)} ms`, kb = (v) => `${Math.round(v / 1024)} Ko`, mb = (v) => `${(v / 1048576).toFixed(1)} Mo`;
console.log(`| Mesure | Médiane (min – max) sur ${runs} passages |\n| --- | --- |`);
console.log(`| Interface utilisable (bouton Atelier Nova visible) | ${fmt('usable', ms)} |`);
console.log(`| Octets transférés jusqu'à l'entrée | ${fmt('entryBytes', kb)} |`);
console.log(`| Carte du Royaume affichée après chargement du scénario | ${fmt('map', ms)} |`);
console.log(`| Intervalle entre images, 95e centile, carte au repos | ${fmt('frame95', (v) => `${v.toFixed(1)} ms`)} |`);
console.log(`| Ouverture de la Bibliothèque | ${fmt('lib', ms)} |`);
console.log(`| Filtre « SemVer » dans les 395 références | ${fmt('filter', ms)} |`);
console.log(`| Octets transférés en tout | ${fmt('bytes', kb)} |`);
console.log(`| Mémoire JS après nettoyage | ${fmt('heap', mb)} |`);
