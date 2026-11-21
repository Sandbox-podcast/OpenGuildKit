import { expect, test, type Page } from '@playwright/test';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * The project interface on a real OpenGuildKit project (scripts/serve-sample.mjs builds it fresh):
 * every action goes through `openguildkit ui` and the CLI. The tests run in order on the same project,
 * each one starting from what the previous ones changed.
 */
test.describe.configure({ mode: 'serial' });

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'tests', 'fixtures', 'alerts');
const EMPTY = `http://127.0.0.1:${Number(process.env.PW_PROJECT_PORT ?? 7322) + 1}`;
const errors: string[] = [];

function watch(page: Page) {
  page.on('pageerror', (e) => errors.push(e.message));
  // Refusals answer 403 on purpose; the browser logs them as failed resources.
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 403/.test(m.text())) errors.push(m.text()); });
}

async function open(page: Page, hash: string) {
  watch(page);
  await page.goto(`/#${hash}`);
  await expect(page.locator('.project-chip')).toContainText('Portail support');
}

/** Calls the local API the way the page does. */
function api<T>(page: Page, path: string, body: unknown): Promise<{ status: number; body: T }> {
  return page.evaluate(async ([p, b]) => {
    const session = await fetch('./api/session').then((r) => r.json());
    const response = await fetch(p as string, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-OGK-Token': session.token }, body: JSON.stringify(b) });
    return { status: response.status, body: await response.json() };
  }, [path, body] as const);
}
const cli = async <T,>(page: Page, argv: string[]) => (await api<{ code: number; json: T; stdout: string }>(page, './api/run', { argv })).body;
const projectRoot = (page: Page) => page.evaluate(async () => (await fetch('./api/session').then((r) => r.json())).project.root as string);

test.afterAll(() => {
  expect(errors, errors.join('\n')).toEqual([]);
});

/* ------------------------------------------------------------------ royaume and quests */

test('opens the project with its counters, map and next actions', async ({ page }) => {
  await open(page, '/royaume');
  await expect(page.getByRole('heading', { level: 1, name: 'Royaume' })).toBeVisible();
  await expect(page.locator('.project-chip')).toContainText('Projet réel');
  await expect(page.getByRole('region', { name: 'Carte du projet' })).toBeVisible();
  await expect(page.getByText('Lever les blocages de request-export')).toBeVisible();
  await expect(page.getByText('Réaliser request-history')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Quêtes', exact: true })).toHaveAttribute('aria-description', /1 bloquée/);
});

test('lists every task by state and opens a new one', async ({ page }) => {
  await open(page, '/quetes');
  const board = page.getByRole('list', { name: 'Quêtes par état' });
  for (const id of ['dark-theme', 'status-labels', 'closing-survey', 'request-export', 'request-history', 'request-status']) {
    await expect(board.getByText(id, { exact: true })).toBeVisible();
  }
  await page.getByRole('combobox', { name: 'État' }).selectOption('done');
  await expect(board.getByText('request-status', { exact: true })).toBeVisible();
  await expect(board.getByText('dark-theme', { exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: 'Nouvelle quête' }).click();
  const dialog = page.getByRole('dialog', { name: 'Ouvrir une quête' });
  await dialog.getByLabel('Ce que l’équipe doit faire').fill('Let customers download a PDF summary of a request.\nKeep the layout of the portal.');
  await dialog.getByLabel('Identifiant (facultatif)').fill('request-pdf');
  await dialog.getByLabel('Fait suite à (facultatif)').selectOption('request-status');
  await dialog.getByRole('button', { name: 'Ouvrir la quête' }).click();
  await expect(page).toHaveURL(/#\/conseil\/request-pdf/);
  await expect(page.getByRole('heading', { name: /Cadrage : le questionnaire/ })).toBeVisible();
  const record = await cli<{ follows: { task: string }; brief: string }>(page, ['task', 'show', 'request-pdf']);
  expect(record.json.follows.task).toBe('request-status');
  expect(record.json.brief).toContain('Keep the layout of the portal.');
});

/* ------------------------------------------------------------------ council */

test('never approves: the decision is a command for the person’s terminal', async ({ page }) => {
  await open(page, '/conseil/request-export');
  await expect(page.getByRole('heading', { name: 'Avis des cerveaux' })).toBeVisible();
  await expect(page.getByLabel('Commande de validation')).toContainText('task decide request-export --approve');
  await expect(page.getByRole('button', { name: /^Valider/ })).toHaveCount(0);
  const refused = await api<{ command: string }>(page, './api/run', { argv: ['task', 'decide', 'request-export', '--approve', '--by', 'Agent', '--reason', 'Self-approval'] });
  expect(refused.status).toBe(403);
  expect(refused.body.command).toContain('task decide request-export --approve');
});

test('hands a waiver to the named person’s terminal', async ({ page }) => {
  await open(page, '/conseil/request-export');
  await page.getByRole('button', { name: 'Déroger (au terminal)' }).click();
  const dialog = page.getByRole('dialog', { name: /Déroger à security:1/ });
  await dialog.getByLabel('Personne qui déroge').selectOption('Camille Martin');
  await dialog.getByLabel('Pourquoi le risque est accepté').fill('Internal pilot');
  await dialog.getByLabel('Ce que la dérogation couvre').fill('Support team accounts');
  await dialog.getByLabel('Dernier jour').fill('2026-12-15');
  await dialog.getByRole('button', { name: 'Préparer la commande' }).click();
  const terminal = page.getByRole('dialog', { name: /Dérogation : à faire dans votre terminal/ });
  await expect(terminal.getByLabel('Commande')).toContainText("task waive request-export security:1 --by 'Camille Martin'");
  await terminal.getByRole('button', { name: 'J’ai compris' }).click();
  expect((await cli<{ resolution: unknown }[]>(page, ['task', 'blockers', 'request-export', '--json'])).json[0].resolution).toBeNull();
});

test('clears a blocker with its evidence', async ({ page }) => {
  await open(page, '/conseil/request-export');
  await page.getByRole('button', { name: 'Lever avec une preuve' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Preuve', { exact: true }).fill('tests/test_export_access.py');
  await dialog.getByLabel('Ce que la preuve établit').fill('The export only holds the requester’s own requests');
  await dialog.getByLabel('Votre nom').fill('Alex Moreau');
  await dialog.getByRole('button', { name: 'Enregistrer la preuve' }).click();
  await expect(page.getByText('levé par Alex Moreau')).toBeVisible();
  await page.goto('/#/royaume');
  await expect(page.getByText('Décider de request-export')).toBeVisible();
});

test('reads the decision brief and sends a reviewed task back to the council', async ({ page }) => {
  await open(page, '/conseil/request-export');
  await page.getByRole('button', { name: 'Arbitrage (task challenge)' }).click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'Decision brief' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();
  await page.getByLabel('Personne qui décide').fill('Camille Martin');
  await page.getByLabel('Motif', { exact: true }).fill('Agree on the CSV columns with support first');
  await page.getByRole('button', { name: 'Demander des changements' }).click();
  await expect(page.getByText('Quête renvoyée au Conseil')).toBeVisible();
  await expect(page.locator('.quest-head').getByText('Renvoyée au Conseil')).toBeVisible();
  await expect(page.getByText(/Agree on the CSV columns with support first/).first()).toBeVisible();
});

test('frames a draft and gathers the council', async ({ page }) => {
  await open(page, '/conseil/dark-theme');
  await page.getByText('Fonctionnalité', { exact: true }).click();
  await page.getByText('Clients', { exact: true }).click();
  await page.getByText('Interne', { exact: true }).click();
  await page.getByText('Sources locales', { exact: true }).click();
  await expect(page.getByText(/Sans réponse : Quel résultat observable/)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Routage/ })).toBeVisible();
  await expect(page.locator('.board-pick').first()).toBeVisible();
  await page.getByRole('button', { name: 'Réunir le Conseil' }).click();
  await expect(page.getByText('Consultation préparée')).toBeVisible();
  await expect(page.locator('.board-seat').first()).toBeVisible();
  await expect(page.getByText(/0\/\d+ avis déposés/)).toBeVisible();
});

test('passes each board, records its entry and assembles the review', async ({ page }) => {
  await open(page, '/conseil/status-labels');
  const root = await projectRoot(page);
  const progress = (await cli<{ board: string; status: string }[]>(page, ['task', 'progress', 'status-labels', '--json'])).json;
  const missing = progress.filter((p) => p.status !== 'done').map((p) => p.board);
  expect(missing.length).toBeGreaterThan(0);

  let submitted = progress.length - missing.length;
  for (const board of missing) {
    const seat = page.locator('.board-seat').filter({ hasText: 'En attente' }).first();
    await seat.getByRole('button', { name: 'Préparer la passe' }).click();
    const pass = page.getByRole('dialog', { name: /Passe du cerveau/ });
    await expect(pass.getByRole('heading', { name: /Board pass/ })).toBeVisible();
    await pass.getByRole('button', { name: 'Fermer' }).last().click();
    await page.getByLabel('Déposer l’avis d’un cerveau (JSON)').setInputFiles(join(root, '.sample', `status-labels-${board}.json`));
    submitted += 1;
    await expect(page.getByText(`${submitted}/${progress.length} avis déposés.`)).toBeVisible();
  }
  await expect(page.getByText(`${progress.length}/${progress.length} avis déposés.`)).toBeVisible();
  await page.getByLabel(/Synthèse pour assembler la revue/).fill('Map internal states to four customer labels; support owns the wording.');
  await page.getByRole('button', { name: 'Assembler la revue' }).click();
  await expect(page.getByText('Revue assemblée')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Avis des cerveaux' })).toBeVisible();
  await expect(page.locator('.quest-head').getByText('Avis rendus')).toBeVisible();
});

/* ------------------------------------------------------------------ forge */

test('refuses an external action here and hands an allowance to the terminal', async ({ page }) => {
  await open(page, '/forge/request-history');
  const section = page.getByRole('region', { name: 'Actions externes hors périmètre' });
  await section.getByLabel('Action').selectOption('send-message');
  await section.getByLabel('Hôte ou outil').fill('Brevo');
  await section.getByLabel('Décision').selectOption('deny');
  await section.getByLabel('Personne qui décide').fill('Camille Martin');
  await section.getByLabel('Motif').fill('No customer email before the release note');
  await section.getByRole('button', { name: 'Préparer' }).click();
  await expect(page.getByText('Refus enregistré')).toBeVisible();
  await expect(section.getByText(/Envoi de messages.*sur Brevo : refusée par Camille Martin/)).toBeVisible();

  await section.getByLabel('Décision').selectOption('allow');
  await section.getByRole('button', { name: 'Préparer' }).click();
  await expect(page.getByRole('dialog', { name: /Autorisation : à faire dans votre terminal/ }).getByLabel('Commande')).toContainText('task authorize request-history --action send-message --target Brevo --allow');
  await page.getByRole('button', { name: 'J’ai compris' }).click();
});

test('runs the checks, records the results and completes a task in the forge', async ({ page }) => {
  await open(page, '/forge/request-history');
  await page.getByRole('button', { name: 'Passation (handoff)' }).click();
  await expect(page.getByRole('dialog', { name: 'Passation validée' }).getByText(/Approved implementation handoff|request-history/).first()).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();
  await page.getByRole('button', { name: 'Lancer les commandes du projet' }).click();
  await expect(page.locator('tr', { hasText: 'command:1' }).getByText('Réussi')).toBeVisible({ timeout: 30_000 });
  await page.getByLabel('Votre nom').fill('Camille Martin');
  await page.getByRole('button', { name: /Marquer les règles non rapportées/ }).click();
  await page.getByLabel('Adresse de la pull request').fill('https://github.com/example/portal/pull/8');
  await page.getByRole('button', { name: 'Ajouter un critère' }).click();
  await page.getByLabel('Critère', { exact: true }).fill('Customers only see the history of their own requests.');
  await page.getByLabel('Preuve', { exact: true }).fill('tests/test_history_access.py');
  await page.getByRole('button', { name: 'Enregistrer les résultats' }).click();
  await expect(page.getByText('Résultats enregistrés')).toBeVisible();
  await page.getByRole('button', { name: 'Terminer la quête' }).click();
  await expect(page.getByText('Quête terminée', { exact: true })).toBeVisible();
  await page.goto('/#/quetes/request-history');
  await expect(page.locator('.quest-head').getByText('Accomplie')).toBeVisible();
});

test('starts a business deliverable and lists what keeps it from review', async ({ page }) => {
  await open(page, '/forge/livrables');
  await expect(page.locator('.board-grid').getByText('Campaign brief', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Voir le modèle' }).first().click();
  await expect(page.getByRole('dialog').getByText(/Before starting the tool/)).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();
  const form = page.getByRole('region', { name: 'Nouveau brouillon' });
  await form.getByLabel('Modèle').selectOption('support-article');
  await form.getByLabel('Quête validée').selectOption('request-status');
  await form.getByLabel('Outil de l’équipe').selectOption('Notion');
  await form.getByLabel('Fichier Markdown à écrire').fill('support/request-status.md');
  await form.getByRole('button', { name: 'Écrire le brouillon' }).click();
  await expect(page.getByText('Brouillon écrit')).toBeVisible();
  const row = page.locator('tr', { hasText: 'support/request-status.md' });
  await row.getByRole('button', { name: 'Ouvrir' }).click();
  const draft = page.getByRole('dialog', { name: 'support/request-status.md' });
  await expect(draft.getByText('Ce qui empêche la relecture :')).toBeVisible();
  await expect(draft.getByText(/placeholder/)).toBeVisible();
});

test('connects a tool with its mock and calls it', async ({ page }) => {
  await open(page, '/forge/outils');
  await page.getByLabel('Rechercher un outil').fill('jira');
  await page.getByLabel('Choisir Jira', { exact: true }).check();
  await page.getByLabel('Hôte de l’agent').selectOption('claude-code');
  await page.getByRole('button', { name: 'Voir le plan' }).click();
  await expect(page.locator('pre').filter({ hasText: /jira/i }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Écrire la configuration' }).click();
  await expect(page.getByText('Configuration de l’hôte écrite')).toBeVisible();
  await expect(page.getByText('1 connexion(s)')).toBeVisible();
  const status = await cli<{ key: string; mode: string }[]>(page, ['tools', 'status', '--json']);
  expect(status.json).toEqual([expect.objectContaining({ key: 'jira', mode: 'mock' })]);

  await page.locator('tr').filter({ has: page.getByLabel('Choisir Jira', { exact: true }) }).getByRole('button', { name: 'Essayer' }).click();
  const mock = page.getByRole('dialog', { name: 'Simulation jira' });
  await mock.getByLabel('Outil de la simulation').selectOption('search_issues');
  await mock.getByLabel('Arguments (JSON)').fill('{"query": "export"}');
  await mock.getByRole('button', { name: 'Appeler' }).click();
  await expect(mock.locator('pre').last()).toContainText('"key"');
});

test('validates the proposals of the extracted design system and generates it', async ({ page }) => {
  await open(page, '/forge/storybook');
  await expect(page.getByText(/composant\(s\) et \d+ feuille\(s\) de style lus/)).toBeVisible();
  await expect(page.getByRole('tab', { name: /Composants/ })).toBeVisible();
  await page.getByRole('button', { name: 'Valider ce qui est observé' }).click();
  await page.getByRole('tab', { name: /Jetons/ }).click();
  await page.getByRole('button', { name: 'Valider ce qui est observé' }).click();
  await page.getByLabel('Nom de token:color:#0a66c2').fill('color.brand.primary');
  await page.getByRole('button', { name: 'Enregistrer les décisions' }).click();
  await expect(page.getByText('Décisions enregistrées')).toBeVisible();
  await page.getByRole('button', { name: /^Générer \([1-9]/ }).click();
  await expect(page.getByText('Jetons, stories et index générés')).toBeVisible();
  const tokens = await api<{ text: string }>(page, './api/files/read', { path: 'src/design-system/design.tokens.json' });
  expect(tokens.status).toBe(200);
  expect(tokens.body.text).toContain('primary');
});

/* ------------------------------------------------------------------ watchtower */

test('imports a scanner report into the alert register', async ({ page }) => {
  await open(page, '/tour/alertes');
  await expect(page.getByRole('heading', { name: /Registre : 1 alerte/ })).toBeVisible();
  await page.getByLabel('Rapport JSON').setInputFiles(join(FIXTURES, 'pip-audit.json'));
  await page.getByRole('button', { name: 'Importer', exact: true }).click();
  await expect(page.getByText('Rapport importé')).toBeVisible();
  await expect(page.getByRole('heading', { name: /Registre : [2-9] alerte/ })).toBeVisible();
});

test('reviews an alert, and hands the dismissal of a critical one to the terminal', async ({ page }) => {
  await open(page, '/tour/alertes');
  const critical = page.locator('tr', { hasText: 'form-parser' });
  await critical.getByRole('button', { name: 'Revoir' }).click();
  let dialog = page.getByRole('dialog', { name: /Revoir form-parser/ });
  await dialog.getByLabel('Statut').selectOption('confirmed');
  await dialog.getByLabel('Votre nom').fill('Alex Moreau');
  await dialog.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(critical.getByText('Confirmée')).toBeVisible();
  await expect(critical.getByText('Alex Moreau')).toBeVisible();

  await critical.getByRole('button', { name: 'Revoir' }).click();
  dialog = page.getByRole('dialog', { name: /Revoir form-parser/ });
  await dialog.getByLabel('Statut').selectOption('dismissed');
  await dialog.getByLabel('Motif').fill('Only used at build time');
  await dialog.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(page.getByRole('dialog', { name: 'À faire dans votre terminal' }).getByLabel('Commande')).toContainText('alerts set npm:form-parser');
  await page.getByRole('button', { name: 'J’ai compris' }).click();
  await expect(critical.getByText('Confirmée')).toBeVisible();
});

test('shows the controls: instructions, host rules and guard', async ({ page }) => {
  await open(page, '/tour');
  await expect(page.getByText('OpenGuildKit instructions match the project profile.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ce que l’hôte applique' }).locator('.card').first()).toBeVisible();
  await expect(page.getByText(/La garde est/)).toBeVisible();
  await page.getByRole('tab', { name: 'Blocages' }).click();
  await expect(page.getByText(/blocage\(s\) ouvert\(s\)|Aucun blocage/)).toBeVisible();
});

test('keeps keyboard focus on the selected watchtower tab as the address changes', async ({ page }) => {
  await open(page, '/tour');
  const tabs = page.getByRole('tablist', { name: 'Tour de guet' });
  const controls = tabs.getByRole('tab', { name: 'Contrôles' });
  const alerts = tabs.getByRole('tab', { name: /Alertes de dépendances/ });
  const blockers = tabs.getByRole('tab', { name: 'Blocages' });

  await controls.focus();
  await page.keyboard.press('ArrowRight');
  await expect(page).toHaveURL(/#\/tour\/alertes$/);
  await expect(alerts).toHaveAttribute('aria-selected', 'true');
  await expect(alerts).toBeFocused();

  await page.keyboard.press('ArrowRight');
  await expect(page).toHaveURL(/#\/tour\/blocages$/);
  await expect(blockers).toHaveAttribute('aria-selected', 'true');
  await expect(blockers).toBeFocused();

  await page.keyboard.press('ArrowLeft');
  await expect(page).toHaveURL(/#\/tour\/alertes$/);
  await expect(alerts).toBeFocused();

  await page.goBack();
  await expect(page).toHaveURL(/#\/tour\/blocages$/);
  await expect(page.getByRole('main')).toBeFocused();
});

/* ------------------------------------------------------------------ observatory and documentation */

test('creates a market dossier, adds a competitor and an observation, and reviews a watched source', async ({ page }) => {
  await open(page, '/observatoire');
  await page.getByRole('button', { name: 'Relue, rien de neuf' }).first().click();
  await expect(page.getByText('Source marquée relue')).toBeVisible();

  await page.getByRole('button', { name: 'Nouveau dossier' }).click();
  let dialog = page.getByRole('dialog', { name: 'Nouveau dossier de marché' });
  await dialog.getByLabel('Identifiant').fill('chat-support');
  await dialog.getByLabel('Titre').fill('Chat support tools');
  await dialog.getByLabel('Marché').fill('Support desks in France');
  await dialog.getByLabel('Public').fill('Support agents');
  await dialog.getByLabel('Fonctionnalité comparée').fill('Live chat on the portal');
  await dialog.getByRole('button', { name: 'Créer' }).click();
  await expect(page).toHaveURL(/#\/observatoire\/chat-support/);

  await page.getByRole('button', { name: 'Concurrent' }).click();
  dialog = page.getByRole('dialog', { name: 'Ajouter un concurrent' });
  await dialog.getByLabel('Identifiant', { exact: true }).fill('vendor-b');
  await dialog.getByLabel('Nom', { exact: true }).fill('Fictional Vendor B');
  await dialog.getByLabel('Type').selectOption('direct');
  await dialog.getByRole('button', { name: 'Ajouter' }).click();
  await expect(page.locator('.card').getByText('Fictional Vendor B', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Observation' }).click();
  dialog = page.getByRole('dialog', { name: 'Enregistrer une observation' });
  await dialog.getByLabel('Concurrent', { exact: true }).selectOption('vendor-b');
  await dialog.getByLabel('Identifiant de l’observation').fill('b-chat');
  await dialog.getByLabel('Ce que le concurrent propose').fill('Offers a chat widget with business hours.');
  await dialog.getByLabel('Source', { exact: true }).fill('Sales call notes, synthetic example');
  await dialog.getByLabel('Date de l’information').fill('2026-11-15');
  await dialog.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(page.getByText('market:chat-support/b-chat')).toBeVisible();
  await expect(page.getByText('Lacunes du dossier :')).toBeVisible();
});

test('exports a completed task for Documentalist, then records and revokes a share', async ({ page }) => {
  await open(page, '/documentation');
  await page.getByLabel(/request-status/).check();
  await page.getByLabel('Version du projet').fill('1.5.0');
  await page.getByRole('button', { name: 'Écrire les pages' }).click();
  await expect(page.getByText('Pages écrites')).toBeVisible();
  await page.getByRole('button', { name: 'request-status.md' }).first().click();
  await expect(page.getByRole('dialog', { name: /reference\/request-status\.md/ })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();

  await page.getByRole('tab', { name: /Partages/ }).click();
  await page.getByLabel('Ajouter : Destinataires (adresses)').fill('partner@example.org');
  await page.getByLabel('Ajouter : Destinataires (adresses)').press('Enter');
  await page.getByLabel('Page ou dossier partagé').fill('docs-site/reference/request-status.md');
  await page.getByLabel('Dernier jour d’accès').fill('2026-12-20');
  await page.getByLabel('Adresse du portail Documentalist (https)').fill('https://docs.example.org/p/support-portal');
  await page.getByLabel('Responsable du partage').fill('Camille Martin');
  await page.getByRole('button', { name: 'Enregistrer le partage' }).click();
  await expect(page.getByText('Partage enregistré')).toBeVisible();
  const row = page.locator('tr', { hasText: 'partner@example.org' });
  await row.getByRole('button', { name: 'Accès retiré' }).click();
  await expect(row.getByText('Retiré')).toBeVisible();

  await page.getByRole('tab', { name: /Relevés de décision/ }).click();
  await expect(page.getByRole('button', { name: /request-status/ }).first()).toBeVisible();
});

test('rebuilds the history from the task records', async ({ page }) => {
  await open(page, '/chroniques');
  await expect(page.getByText('Quête terminée').first()).toBeVisible();
  await expect(page.getByText(/Renvoyée au Conseil par Camille Martin/).first()).toBeVisible();
  await page.getByRole('combobox', { name: 'Quête', exact: true }).selectOption('request-history');
  await expect(page.getByText(/Validée par Camille Martin/)).toBeVisible();
  await expect(page.getByText(/Action externe send-message sur Brevo : refusée/)).toBeVisible();
});

/* ------------------------------------------------------------------ settings */

test('edits the profile and synchronizes the instructions', async ({ page }) => {
  await open(page, '/blueprint');
  await page.getByLabel('Ajouter : Conventions de l’équipe').fill('Keep pull requests under 400 lines.');
  await page.getByLabel('Ajouter : Conventions de l’équipe').press('Enter');
  await page.getByRole('button', { name: 'Enregistrer et synchroniser' }).click();
  await expect(page.getByText('Profil enregistré et instructions synchronisées')).toBeVisible();
  const agents = await api<{ text: string }>(page, './api/files/read', { path: 'AGENTS.md' });
  expect(agents.body.text).toContain('Keep pull requests under 400 lines.');

  await page.getByRole('tab', { name: 'project.json' }).click();
  await page.getByLabel('Profil (JSON)').fill('{"name": "Portail support", "research": "everywhere"}');
  await page.getByRole('button', { name: 'Enregistrer et synchroniser' }).click();
  await expect(page.getByText('Profil refusé, version précédente remise')).toBeVisible();
  await page.getByRole('tab', { name: 'Règles en vigueur' }).click();
  await expect(page.getByText('Agent workflow')).toBeVisible();
  await page.getByRole('tab', { name: 'Pile détectée' }).click();
  await expect(page.getByRole('heading', { name: /Retenus/ })).toBeVisible();
});

test('installs the agent files and reads the catalog state', async ({ page }) => {
  await open(page, '/intendance');
  await page.getByRole('button', { name: 'Claude Code', exact: true }).click();
  await expect(page.getByText('Fichiers Claude Code installés')).toBeVisible();
  await page.getByRole('tab', { name: 'Catalogue' }).click();
  await expect(page.getByText('Le projet suit le catalogue installé.')).toBeVisible();
  await page.getByRole('tab', { name: 'Interface' }).click();
  await expect(page.getByText(/task decide --approve/)).toBeVisible();
});

/* ------------------------------------------------------------------ navigation */

test('searches the library and opens a reference', async ({ page }) => {
  await open(page, '/bibliotheque?q=owasp');
  const first = page.locator('.ref-card').first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.getByRole('heading', { name: 'Sources' })).toBeVisible();
  await page.goto('/#/bibliotheque/packs?q=python');
  const pythonPack = page.locator('details.pack').filter({ has: page.locator('summary').getByText('Python', { exact: true }) });
  await pythonPack.locator('summary').click();
  await expect(pythonPack.getByText('follow-python-style')).toBeVisible();
});

test('finds a brain from the search and moves with the keyboard', async ({ page }) => {
  await open(page, '/royaume');
  await page.keyboard.press('Control+k');
  const search = page.getByRole('dialog', { name: 'Rechercher dans le projet' });
  await search.getByLabel('Rechercher').fill('security privacy');
  await expect(search.getByText('Security and privacy').first()).toBeVisible();
  await search.getByLabel('Rechercher').press('Enter');
  await expect(page).toHaveURL(/#\/guilde\/security/);
  await expect(page.getByRole('heading', { name: /Lentilles/ })).toBeVisible();
  await page.locator('body').click({ position: { x: 5, y: 300 } });
  await page.keyboard.press('g');
  await page.keyboard.press('q');
  await expect(page).toHaveURL(/#\/quetes/);
});

test('keeps the Pro style across places', async ({ page }) => {
  await open(page, '/guilde');
  await page.getByRole('button', { name: 'Pro', exact: true }).click();
  await expect(page.locator('.app')).toHaveClass(/mode-focus/);
  await expect(page.getByRole('heading', { level: 1, name: 'Cerveaux' })).toBeVisible();
  await page.goto('/#/observatoire');
  await expect(page.getByRole('heading', { level: 1, name: 'Marché' })).toBeVisible();
  await page.getByRole('button', { name: 'RPG', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Observatoire' })).toBeVisible();
});

/* ------------------------------------------------------------------ setup */

test('sets up a folder without OpenGuildKit', async ({ page }) => {
  watch(page);
  await page.goto(`${EMPTY}/`);
  await expect(page).toHaveURL(/#\/installation/);
  await expect(page.getByRole('heading', { name: /Installer la guilde dans new-portal/ })).toBeVisible();
  await page.getByLabel('Project name').fill('Nouveau portail');
  await expect(page.getByRole('region', { name: 'Règles qui s’appliqueront' }).getByText('Agent workflow')).toBeVisible();
  await page.getByRole('button', { name: 'Installer la guilde' }).click();
  await expect(page).toHaveURL(/#\/royaume/);
  await expect(page.locator('.project-chip')).toContainText('Nouveau portail');
  const agents = await api<{ text: string }>(page, './api/files/read', { path: 'AGENTS.md' });
  expect(agents.body.text).toContain('OpenGuildKit');
});
