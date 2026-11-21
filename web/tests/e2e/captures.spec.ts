/**
 * Regenerates the screenshot series of docs/verification.md (docs/captures-apres for RPG,
 * docs/captures-pro for Pro). Skipped unless CAPTURES=1:  CAPTURES=1 npm run e2e -- captures
 * Fixed clock, Paris time zone, reduced motion, fresh browser context and the Atelier Nova scenario.
 */
import { expect, test, type Page } from '@playwright/test';

test.skip(!process.env.CAPTURES, 'Captures de la documentation : lancer avec CAPTURES=1');
test.use({ timezoneId: 'Europe/Paris', locale: 'fr-FR', reducedMotion: 'reduce' });

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };
const SERIES: { name: string; hash: string; size: typeof DESKTOP }[] = [
  { name: '01-entree', hash: '#/entree', size: DESKTOP },
  { name: '01-entree-mobile', hash: '#/entree', size: MOBILE },
  { name: '02-royaume', hash: '#/royaume', size: DESKTOP },
  { name: '02-royaume-mobile', hash: '#/royaume', size: MOBILE },
  { name: '03-conseil', hash: '#/conseil/cns-export', size: DESKTOP },
  { name: '04-bibliotheque', hash: '#/bibliotheque?famille=securite-et-cyber&q=owasp', size: DESKTOP },
  { name: '05-quete-bloquee', hash: '#/quetes/qst-billing-relances', size: DESKTOP },
  { name: '05-quetes-mobile', hash: '#/quetes', size: MOBILE },
  { name: '06-forge', hash: '#/forge/livrables/dlv-audit-code', size: DESKTOP },
  { name: '07-preuve-a-reevaluer', hash: '#/tour/preuves?preuve=prv-ds1', size: DESKTOP },
  { name: '07-preuve-a-reevaluer-mobile', hash: '#/tour/preuves?preuve=prv-ds1', size: MOBILE },
  { name: '08-chroniques', hash: '#/chroniques', size: DESKTOP },
  { name: '09-controles', hash: '#/tour/controles', size: DESKTOP },
  { name: '09-controles-mobile', hash: '#/tour/controles', size: MOBILE },
  { name: '10-guilde', hash: '#/guilde', size: DESKTOP },
];

async function setStyle(page: Page, style: 'RPG' | 'Pro') {
  await page.setViewportSize(DESKTOP);
  await page.getByRole('button', { name: style, exact: true }).first().click();
  await expect(page.locator('.app')).toHaveClass(style === 'Pro' ? /mode-focus/ : /mode-explorer/);
}

test('séries de captures RPG et Pro', async ({ page }) => {
  test.setTimeout(240_000);
  await page.clock.setFixedTime(new Date('2026-11-20T14:00:00+01:00'));
  await page.goto('/#/entree');
  await page.getByRole('button', { name: /Atelier Nova/ }).first().click();
  await expect(page).toHaveURL(/#\/royaume/);
  await expect(page.locator('.toast')).toHaveCount(0, { timeout: 10_000 });
  for (const [style, dir] of [['RPG', 'captures-apres'], ['Pro', 'captures-pro']] as const) {
    await setStyle(page, style);
    for (const { name, hash, size } of SERIES) {
      await page.setViewportSize(size);
      await page.evaluate((h) => { location.hash = h; }, hash);
      await page.waitForTimeout(700);
      await page.screenshot({ path: `docs/${dir}/${name}.png` });
    }
  }
});
