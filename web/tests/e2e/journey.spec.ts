/**
 * Main journey played through the real interface (brief §10, steps 1 to 20), with the
 * screenshots saved in Playwright's test output directory.
 */
import { expect, test, type Page } from '@playwright/test';

const shot = (page: Page, name: string) => page.screenshot({ path: test.info().outputPath(`${name}.png`) });
const dialog = (page: Page) => page.locator('dialog[open]');
const go = async (page: Page, hash: string) => { await page.evaluate((h) => { location.hash = h; }, hash); await page.waitForTimeout(250); };
const button = (page: Page, name: string | RegExp) => page.getByRole('button', { name }).filter({ visible: true }).first();
async function actAs(page: Page, name: string) {
  await go(page, '#/intendance/demo');
  await page.locator('li', { hasText: name }).getByRole('button', { name: /Agir comme|Acteur courant/ }).click();
  await expect(page.locator('.identity')).toContainText(name.split(' ')[0]);
}
const stateOf = (page: Page) => page.evaluate(() => JSON.parse(localStorage.getItem('open-guild-kit.demo')!).state);
/** A person's decision: the demo shows the terminal command, then simulates its entry. */
async function decideAtTerminal(page: Page, approve: ReturnType<Page['getByRole']>) {
  await approve.click();
  await expect(dialog(page)).toContainText('dans son propre terminal');
  await dialog(page).getByRole('button', { name: 'Simuler la commande' }).click();
}

test('parcours principal : de l’inconnue du Blueprint au réexamen', async ({ page }) => {
  await page.goto('/#/entree');
  await button(page, 'Charger Atelier Nova').click();
  await expect(page).toHaveURL(/#\/royaume/);
  await expect(page.locator('.kingdom-map')).toBeVisible();

  // 3–4. Resolve the unknown in the v3 draft, arbitrate the competing rules, publish, adopt.
  await go(page, '#/blueprint/assistant');
  await page.getByPlaceholder('Renseigner la valeur…').fill('7 jours');
  await button(page, 'Résoudre').click();
  await page.getByLabel('Motif de l’arbitrage').fill('GitHub flow est déjà pratiqué par toutes les équipes.');
  await button(page, 'Arbitrer').click();
  await button(page, 'Soumettre en revue').click();
  await dialog(page).getByRole('button', { name: 'Soumettre en revue' }).click();
  await button(page, 'Publier la version').click();
  await go(page, '#/blueprint/impacts?projet=prj-export');
  await page.getByLabel('Version envisagée').selectOption('3');
  await expect(page.getByText('inconnue résolue', { exact: true })).toBeVisible();
  await button(page, 'Adopter la v3 pour ce projet').click();
  await dialog(page).getByLabel('Motif').fill('Durée de disponibilité fixée à 7 jours.');
  await dialog(page).getByRole('button', { name: 'Adopter la version' }).click();
  await expect(page.getByText('suit désormais la v3')).toBeVisible();

  // 5. Validate the suggested references.
  await go(page, '#/bibliotheque/applicabilite');
  for (let i = 0; i < 3; i++) await button(page, 'Valider').click();

  // 7–9. Council: contributions, disagreement, arbitration, distinct approver.
  await go(page, '#/conseil/cns-export');
  await expect(page.getByRole('link', { name: /Lire l'avis de/ })).toHaveCount(0);
  await button(page, 'Demander les avis').click();
  await expect(page.locator('.council-room')).toContainText('6/6 avis', { timeout: 20_000 });
  await go(page, '#/conseil/cns-export?onglet=options');
  await page.getByLabel('Nouvelle annotation').fill('Produit et Engineering divergent : rapidité contre grands volumes.');
  for (const name of ['Stratège', 'Bâtisseur', 'Magistrat']) await page.locator('.choice', { hasText: name }).first().click();
  await button(page, 'Annoter le désaccord').click();
  await expect(page.getByText('Produit et Engineering divergent')).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, '03-conseil-options-desaccords');
  await page.getByRole('link', { name: /Lire l'avis de Stratège/ }).press('Enter');
  await expect(page).toHaveURL(/onglet=contributions&avis=exp-org-nova-product/);
  await expect(page.getByRole('article', { name: 'Contribution de Stratège' })).toBeFocused();
  await page.evaluate(() => document.querySelector('.council-room')?.scrollIntoView());
  await shot(page, '02-conseil-salle');
  await button(page, 'Passer à l’arbitrage').click();
  await go(page, '#/conseil/cns-export?onglet=arbitrage');
  await page.getByLabel('Option retenue').selectOption('opt-b');
  await page.getByLabel('Justification').fill('Couvre les grands comptes ; la durée de disponibilité est fixée à 7 jours.');
  await button(page, 'Enregistrer la décision').click();
  await button(page, 'Soumettre à approbation').click();
  await dialog(page).getByLabel('Approbateur·rice').selectOption('u-ines');
  await dialog(page).getByRole('button', { name: 'Soumettre à approbation' }).click();
  await expect(button(page, 'Approuver la décision')).toBeDisabled();
  await expect(page.locator('.why').filter({ hasText: /assignée|Séparation/ }).first()).toBeVisible();
  await actAs(page, 'Inès Morel');
  await go(page, '#/conseil/cns-export?onglet=arbitrage');
  await decideAtTerminal(page, button(page, 'Approuver la décision'));
  await expect(page.getByText(/openguildkit task decide/)).toHaveCount(0);
  await expect(page.locator('.panel', { hasText: 'Décisions de la session' }).getByText('Approuvée').first()).toBeVisible();
  await actAs(page, 'Yanis Belkacem');

  // 10. Idempotent conversion into a quest.
  await go(page, '#/conseil/cns-export?onglet=arbitrage');
  await page.getByRole('link', { name: 'Traitement asynchrone' }).first().click();
  await button(page, 'Créer les quêtes').click();
  await expect(button(page, 'Créer les quêtes')).toBeDisabled();
  await page.locator('.panel', { hasText: 'Quêtes issues de la décision' }).getByRole('link', { name: /Export asynchrone/ }).click();
  await button(page, 'Démarrer').click();

  // 11. The forge prepares the expected deliverables.
  await button(page, /Préparer les livrables attendus/).click();
  await expect(page.getByRole('button', { name: /Préparer les livrables attendus/ })).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator('.panel', { hasText: 'Livrables' }).locator('li')).toHaveCount(6, { timeout: 30_000 });
  const questUrl = page.url();

  // 12. The first verification reveals the isolation defect.
  const iso = page.locator('.card', { hasText: 'CTL-ISO' });
  await iso.getByRole('button', { name: 'Lancer' }).click();
  await expect(iso.getByText('Échoué')).toBeVisible({ timeout: 20_000 });

  // 13–14. The finding gets the correction, which produces a new version.
  await go(page, '#/tour/constats');
  await page.getByRole('link', { name: /Défaut d’isolation entre clients dans l’export/ }).click();
  await page.getByLabel('Ou rattacher à une quête existante').selectOption({ label: 'Export asynchrone des données clients' });
  await button(page, 'Rattacher').click();
  await button(page, 'Proposer un correctif (simulation)').click();
  await page.waitForTimeout(4500);
  await page.goto(questUrl);
  await expect(iso.getByText('À réévaluer')).toBeVisible({ timeout: 15_000 });

  // 15. New executions, new results and evidence.
  await iso.getByRole('button', { name: 'Relancer' }).click();
  await page.locator('.card', { hasText: 'CTL-PERM' }).getByRole('button', { name: 'Lancer' }).click();
  await page.locator('.card', { hasText: 'CTL-TST' }).getByRole('button', { name: 'Lancer' }).click();
  await expect(iso.getByText('Réussi')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('.card', { hasText: 'CTL-TST' }).getByText('Réussi')).toBeVisible({ timeout: 20_000 });

  // 16. Criteria, tasks, reviews by a distinct approver.
  for (const box of await page.locator('.panel', { hasText: 'Critères d’acceptation' }).getByRole('checkbox').all()) await box.check();
  for (let i = 0; i < 6; i++) {
    const start = page.locator('.task-row').getByRole('button', { name: 'Démarrer' }).first();
    if (await start.count()) await start.click();
    const finish = page.locator('.task-row').getByRole('button', { name: 'Terminer' }).first();
    if (await finish.count()) await finish.click();
  }
  await button(page, 'Soumettre les brouillons en revue').click();
  await actAs(page, 'Inès Morel');
  await go(page, '#/tour/revues');
  const pending = page.locator('.panel', { hasText: 'Revues humaines en attente' }).getByRole('button', { name: 'Approuver', disabled: false });
  while (await pending.count()) await decideAtTerminal(page, pending.first());
  await actAs(page, 'Yanis Belkacem');
  await page.goto(questUrl);
  await button(page, 'Mettre en revue').click();
  await page.getByLabel('Approbateur·rice').selectOption('u-ines');
  await button(page, 'Demander la validation de clôture').click();
  await expect(button(page, 'Clôturer')).toBeDisabled();
  await actAs(page, 'Inès Morel');
  await go(page, '#/tour/revues');
  await decideAtTerminal(page, page.locator('.card', { hasText: 'clôture' }).getByRole('button', { name: 'Approuver' }));
  await actAs(page, 'Yanis Belkacem');

  // 17. Closure, then publication of the documentation.
  await page.goto(questUrl);
  await button(page, 'Clôturer').click();
  await expect(page.locator('.panel').first().getByText('Terminée')).toBeVisible();
  await page.getByRole('link', { name: /Guide administrateur — Exporter/ }).first().click();
  await button(page, 'Publier').click();
  await expect(page.getByText('Publié').first()).toBeVisible();
  await shot(page, '05-forge-livrable-ouvert');
  const docId = page.url().split('/').pop()!.split('?')[0];

  // 18. Local share: authorised opening, revocation, refused opening.
  await go(page, `#/documentation/partages?doc=${docId}`);
  await button(page, 'Créer le lien').click();
  const card = page.locator('.card', { hasText: 'Guide administrateur — Exporter' }).first();
  await card.getByRole('button', { name: 'Simuler l’ouverture' }).click();
  await expect(card.getByText('autorisé')).toBeVisible();
  await card.getByRole('button', { name: 'Révoquer le lien' }).click();
  await dialog(page).getByRole('button', { name: 'Révoquer le lien' }).click();
  await card.getByRole('button', { name: 'Simuler l’ouverture' }).click();
  await expect(card.getByText('révoqué').first()).toBeVisible();

  // 19. Chronicles rebuild the chain from the published guide.
  await go(page, `#/chroniques/trace?kind=deliverable&id=${docId}`);
  for (const kind of ['Décision', 'Conseil', 'Quête', 'Blueprint']) await expect(page.locator('.trace-col h3', { hasText: kind }).first()).toBeVisible();
  await shot(page, '09-chroniques-trace');

  // 20. A later Blueprint evolution flags the objects to re-examine.
  await actAs(page, 'Inès Morel');
  await go(page, '#/blueprint/assistant');
  await page.getByLabel('Pourquoi cette évolution ?').fill('Étendre l’isolation aux traitements asynchrones.');
  await button(page, /Préparer la version 4/).click();
  await go(page, '#/blueprint/structure?version=4&regle=rul-iso');
  await button(page, 'Modifier').click();
  await dialog(page).getByLabel('Formulation vérifiable').fill('Toute lecture ou écriture de données métier, y compris dans les traitements asynchrones, est filtrée par client.');
  await dialog(page).getByRole('button', { name: /Enregistrer dans la v4/ }).click();
  await go(page, '#/blueprint/assistant');
  await button(page, 'Soumettre en revue').click();
  await dialog(page).getByRole('button', { name: 'Soumettre en revue' }).click();
  await actAs(page, 'Yanis Belkacem');
  await go(page, '#/blueprint/versions');
  await button(page, 'Publier la version').click();
  await go(page, '#/blueprint/impacts?projet=prj-export');
  await page.getByLabel('Version envisagée').selectOption('4');
  await button(page, 'Adopter la v4 pour ce projet').click();
  await dialog(page).getByLabel('Motif').fill('Adopter l’isolation étendue.');
  await dialog(page).getByRole('button', { name: 'Adopter la version' }).click();
  await expect(page.locator('.panel', { hasText: 'Éléments à réexaminer' }).getByText('À réexaminer').first()).toBeVisible();

  await page.waitForTimeout(600); // local save is debounced
  const s = await stateOf(page);
  const done = await page.evaluate(() => document.querySelector('.guide-link')?.textContent);
  expect(done).toContain('20/20');
  expect(Object.values(s.db.review as Record<string, { projectId: string }>).some((r) => r.projectId === 'prj-export')).toBe(true);

  // Reload keeps everything (direct route to a detail page).
  await page.goto(questUrl);
  await page.reload();
  await expect(page.getByText('Terminée').first()).toBeVisible();
});
