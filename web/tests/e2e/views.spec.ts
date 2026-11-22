/**
 * Visual captures (brief §12.2) and interface-level checks of sensitive rules (brief §12.1):
 * permissions shown in the interface, keyboard access, reload, invalid import, mode switch.
 */
import { expect, test, type Page } from '@playwright/test';

const shot = (page: Page, name: string, fullPage = false) => page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage });
const go = async (page: Page, hash: string) => { await page.evaluate((h) => { location.hash = h; }, hash); await page.waitForTimeout(300); };
async function loadNova(page: Page) {
  await page.goto('/#/entree');
  await page.getByRole('button', { name: 'Charger Atelier Nova' }).click();
  await expect(page).toHaveURL(/#\/royaume/);
}
async function actAs(page: Page, name: string) {
  await go(page, '#/intendance/demo');
  await page.locator('li', { hasText: name }).getByRole('button', { name: /Agir comme|Acteur courant/ }).click();
}
async function hideGuide(page: Page) {
  const close = page.getByRole('button', { name: 'Masquer le parcours' });
  if (await close.isVisible()) await close.click();
}

test('captures : Royaume, Bibliothèque, Tour de guet, Guilde', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await loadNova(page);
  await hideGuide(page);
  await page.waitForTimeout(400);
  await shot(page, '01-royaume-grand-ecran');

  await page.setViewportSize({ width: 1366, height: 768 });
  await page.getByRole('button', { name: /Territoire Atlas CRM/ }).click();
  await expect(page.locator('.selection-panel')).toContainText('Export des données clients');
  await page.locator('.map-panel').scrollIntoViewIfNeeded();
  await shot(page, '01b-royaume-portable-territoire');

  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, '#/bibliotheque/?famille=securite-et-cyber&nature=referentiel&q=owasp');
  await expect(page.locator('.ref-grid .card')).not.toHaveCount(0);
  await page.locator('.library-layout').scrollIntoViewIfNeeded();
  await shot(page, '04-bibliotheque-filtres');
  await page.locator('.ref-grid .card', { hasText: 'OWASP Application Security Verification Standard' }).click();
  await expect(page.getByRole('link', { name: /asvs|OWASP Application Security/i }).first()).toBeVisible();
  await shot(page, '04b-bibliotheque-fiche');

  await go(page, '#/tour/controles');
  await expect(page.getByText('À réévaluer').first()).toBeVisible();
  await expect(page.getByText('Échoué').first()).toBeVisible();
  await page.locator('.tabs').first().scrollIntoViewIfNeeded();
  await shot(page, '06-tour-de-guet-controles');
  await go(page, '#/tour/revues');
  await expect(page.locator('.card', { hasText: 'clôture' })).toBeVisible();
  await shot(page, '06b-tour-de-guet-revues');

  await go(page, '#/guilde');
  await shot(page, '10-guilde');
  await go(page, '#/guilde/exp-org-nova-security');
  await shot(page, '10b-guilde-fiche');
});

test('bibliothèque : 395 fiches chargées, recherche par sigle et sources ouvrables', async ({ page }) => {
  await loadNova(page);
  await go(page, '#/bibliotheque');
  await expect(page.getByText('395', { exact: true }).first()).toBeVisible();
  for (const term of ['RGPD', 'SemVer', 'ASVS', 'ISO 27001', 'WCAG', 'Diataxis', 'MCP', 'A2A', 'camelCase', 'PEP 8']) {
    await page.locator('#lib-q').fill(term);
    await expect(page.locator('.ref-grid .card').first(), term).toBeVisible();
  }
  await page.locator('#lib-q').fill('Conventional Commits');
  await page.locator('.ref-grid .card').first().click();
  await expect(page.locator('.panel a[target=_blank]').first()).toBeVisible();
  const hrefs = await page.locator('.panel a[target=_blank]').evaluateAll((as) => as.map((a) => (a as HTMLAnchorElement).href));
  expect(hrefs.length).toBeGreaterThan(0);
  hrefs.forEach((h) => expect(h).toMatch(/^https?:\/\//));
});

test('permissions dans l’interface : lecteur et agent IA', async ({ page }) => {
  await loadNova(page);
  await actAs(page, 'Léa Fontaine');
  await go(page, '#/blueprint/structure?version=3&regle=rul-iso');
  const edit = page.getByRole('button', { name: 'Modifier' }).first();
  await expect(edit).toBeDisabled();
  await expect(page.locator('.why').filter({ hasText: 'Lecteur' }).first()).toBeVisible();
  await page.keyboard.press('Control+K');
  await expect(page.getByRole('option', { name: /Créer une quête/ })).toBeDisabled();
  await page.keyboard.press('Escape');

  await go(page, '#/tour/preuves?preuve=prv-ds1');
  const proof = page.getByRole('region', { name: 'Lecture de la preuve' });
  await expect(proof.getByText('Preuve simulée')).toBeVisible();
  await expect(proof.getByText('À réévaluer', { exact: true })).toBeVisible();
  await expect(proof.getByText(/Cette preuve ne débloque pas la version en vigueur/)).toBeVisible();

  await go(page, '#/intendance/demo');
  await page.getByLabel('Ou agir comme un agent IA').selectOption({ label: 'Gardien (agent IA)' });
  await go(page, '#/tour/revues');
  const approve = page.locator('.card', { hasText: 'clôture' }).getByRole('button', { name: 'Approuver' });
  await expect(approve).toBeDisabled();
  await expect(page.locator('.why').filter({ hasText: /humain/ }).first()).toBeVisible();
});

test('les liens directs sont limités à l’organisation active', async ({ page }) => {
  await loadNova(page);
  await go(page, '#/entree');
  await page.getByLabel(/Nom de l.organisation/).fill('Atelier QA');
  await page.getByRole('button', { name: 'Commencer le questionnaire' }).click();
  await page.getByLabel('Activité', { exact: true }).selectOption({ label: 'Éditeur SaaS B2B' });
  await page.getByLabel('Produit principal', { exact: true }).fill('QA Desk');
  await page.getByRole('button', { name: /Conclusion/ }).click();
  await page.getByRole('button', { name: 'Publier le premier Blueprint' }).click();
  await expect(page).toHaveURL(/#\/royaume$/);
  await expect(page.locator('#org-pick option:checked')).toHaveText('Atelier QA');

  for (const query of ['preuve=prv-ds1', 'resultat=res-ds1']) {
    await go(page, `#/tour/preuves?${query}`);
    await expect(page.getByText('Preuve introuvable dans cette organisation.')).toBeVisible();
    await expect(page.getByText('Preuve simulée')).toHaveCount(0);
  }

  await go(page, '#/blueprint/impacts?projet=prj-export');
  await expect(page.getByText('Projet indisponible dans cette organisation.')).toBeVisible();
  await expect(page.getByLabel('Projet', { exact: true }).last()).toHaveValue('');

  await go(page, '#/chroniques/trace?kind=quest&id=qst-audit');
  await expect(page.getByText('Objet introuvable dans cette organisation', { exact: false })).toBeVisible();
  await expect(page.getByText(/Journal d.audit des connexions/)).toHaveCount(0);

  await go(page, '#/conseil?nouveau=1&signal=sig-helio');
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Titre', { exact: true })).toHaveValue('');
  await expect(dialog.getByLabel('Contexte', { exact: true })).toHaveValue('');
});

test('quêtes : déplacer une quête bloquée vers « Terminée » est refusé avec sa cause', async ({ page }) => {
  await loadNova(page);
  await go(page, '#/quetes');
  const blocked = page.getByRole('region', { name: /^Bloquée/ });
  const done = page.getByRole('region', { name: /^Terminée/ });
  const card = blocked.locator('.quest-card', { hasText: 'Relances automatiques' });
  // Expose both columns before dragging, as a user scrolling the board would.
  await blocked.evaluate((column) => column.scrollIntoView({ block: 'nearest', inline: 'start' }));
  await card.dragTo(done, { sourcePosition: { x: 12, y: 12 }, targetPosition: { x: 12, y: 34 } });
  await expect(page.locator('.toast').filter({ hasText: /Impossible depuis l’état « Bloquée »/ })).toBeVisible();
  await expect(card).toBeVisible();
  await card.focus();
  await page.keyboard.press('Alt+ArrowRight');
  await expect(page.locator('.toast').filter({ hasText: 'Déplacement impossible' })).toBeVisible();
});

test('clavier, palette, styles RPG et Pro et rechargement', async ({ page }) => {
  await loadNova(page);
  await page.keyboard.press('Tab');
  await expect(page.locator('.skip-link')).toBeFocused();
  await page.keyboard.press('Control+K');
  await page.locator('#palette-q').fill('RGPD');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/bibliotheque\/ref\/reglement-general/);
  await page.keyboard.press('g');
  await page.keyboard.press('q');
  await expect(page).toHaveURL(/#\/quetes/);
  await go(page, '#/quetes?vue=liste&projet=prj-billing');
  await page.getByRole('button', { name: 'Pro', exact: true }).click();
  await expect(page.locator('.app')).toHaveClass(/mode-focus/);
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(244, 247, 245)');
  await expect(page.getByRole('heading', { name: 'Tâches', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/vue=liste&projet=prj-billing/);
  await expect(page.getByText('Relances automatiques')).toBeVisible();
  await page.getByRole('button', { name: 'RPG', exact: true }).click();
  await expect(page).toHaveURL(/vue=liste&projet=prj-billing/);
  await go(page, '#/quetes/qst-audit');
  await Promise.all([
    page.waitForEvent('domcontentloaded'),
    page.getByRole('button', { name: 'Pro', exact: true }).evaluate((button: HTMLButtonElement) => {
      button.click();
      location.reload();
    }),
  ]);
  await expect(page).toHaveURL(/#\/quetes\/qst-audit$/);
  await expect(page.locator('.app')).toHaveClass(/mode-focus/);
  const quest = page.getByRole('region', { name: 'Journal d’audit des connexions', exact: true });
  await expect(quest.getByRole('heading', { name: 'Journal d’audit des connexions', exact: true })).toBeVisible();
  await expect(quest.getByText('Terminée', { exact: true })).toBeVisible();
  await go(page, '#/quetes/inexistante');
  await expect(page.getByText('Quête introuvable')).toBeVisible();
});

test('navigation : URL invalide, recherche clavier et brouillon', async ({ page }) => {
  await loadNova(page);
  await page.goto('/#/projets/%E0');
  await page.reload();
  await expect(page.getByText('Lien introuvable')).toBeVisible();

  await go(page, '#/bibliotheque');
  const search = page.locator('#lib-q');
  await search.pressSequentially('RGPD');
  await expect(search).toBeFocused();
  await expect(search).toHaveValue('RGPD');

  const special = "R&D d'équipe? 25%";
  await go(page, `#/bibliotheque?q=${encodeURIComponent(special)}`);
  await expect(search).toHaveValue(special);

  const edit = '#/forge/livrables/dlv-audit-code?onglet=editer';
  await go(page, edit);
  const content = page.getByLabel(/Contenu structuré/);
  await content.fill('Brouillon QA');
  await page.getByRole('button', { name: 'Pro', exact: true }).click();
  await expect(content).toHaveValue('Brouillon QA');
  await expect(page).toHaveURL(edit);
  await page.getByRole('button', { name: 'RPG', exact: true }).click();
  page.once('dialog', (dialog) => dialog.accept());
  await go(page, `${edit}&retour=1`);
  await expect(content).toHaveValue('Brouillon QA');
  page.once('dialog', (dialog) => dialog.dismiss());
  await go(page, '#/royaume');
  await expect(page).toHaveURL(/onglet=editer&retour=1$/);
  await expect(content).toHaveValue('Brouillon QA');
});

test('import invalide refusé sans altérer les données', async ({ page }) => {
  await loadNova(page);
  await go(page, '#/intendance/donnees');
  const before = await page.evaluate(() => localStorage.getItem('open-guild-kit.demo'));
  await page.locator('#backup-in').setInputFiles({ name: 'faux.json', mimeType: 'application/json', buffer: Buffer.from('{"format":"ogk-sauvegarde/1","state":{"schema":4}}') });
  await expect(page.getByText('Import refusé, rien n’a été modifié')).toBeVisible();
  const after = await page.evaluate(() => localStorage.getItem('open-guild-kit.demo'));
  expect(after).toBe(before);
});

test('mobile et réduction des mouvements', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await loadNova(page);
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced');
  await hideGuide(page);
  await shot(page, '07-mobile-royaume');
  await page.getByRole('button', { name: 'Ouvrir la navigation' }).click();
  await shot(page, '07b-mobile-navigation');
  await page.getByRole('navigation', { name: 'Lieux du royaume' }).getByRole('link', { name: /Quêtes/ }).click();
  await expect(page).toHaveURL(/#\/quetes/);
  const appearance = page.getByRole('switch', { name: 'Mode Pro' });
  await appearance.click();
  await expect(appearance).toBeChecked();
  await expect(page.getByRole('heading', { name: 'Tâches', exact: true })).toBeVisible();
  await appearance.click();
  await expect(appearance).not.toBeChecked();
  await expect(page).toHaveURL(/#\/quetes/);
  await page.waitForTimeout(300);
  await shot(page, '07c-mobile-quetes');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  await go(page, '#/tour/controles');
  await expect(page.getByRole('heading', { name: 'Tableau des contrôles' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);

  await go(page, '#/tour/preuves?preuve=prv-ds1');
  const stale = page.getByText(/Cette preuve ne débloque pas la version en vigueur/);
  await expect(stale).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);

  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, '#/conseil/cns-ds');
  await page.getByRole('button', { name: 'Demander les avis' }).click();
  await expect(page.locator('.council-room')).toContainText('4/4 avis', { timeout: 15_000 });
  await shot(page, '08-mouvement-reduit-conseil');
});
