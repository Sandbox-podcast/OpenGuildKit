import { expect, test, type Page } from '@playwright/test';
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * The project interface on a real OpenGuildKit project (scripts/serve-sample.mjs builds it fresh):
 * every action goes through `openguildkit ui` and the CLI. The tests run in order on the same project,
 * each one starting from what the previous ones changed.
 */
test.describe.configure({ mode: 'serial' });

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'tests', 'fixtures', 'alerts');
const PORT = Number(process.env.PW_PROJECT_PORT ?? 7322);
// The host name of the run, set by playwright.project.config.ts from the key the servers share.
const HOST = process.env.PW_PROJECT_HOST;
const EMPTY = `http://${HOST}:${PORT + 1}`;
const STRIPE = `http://${HOST}:${PORT + 2}`;
const GDPR = `http://${HOST}:${PORT + 3}`;
const errors: string[] = [];
/** How a to-do item names the person who acts, as opposed to the agent. */
const PERSON = 'Toi';

const watched = new WeakSet<Page>();
async function watch(page: Page) {
  if (watched.has(page)) return;
  watched.add(page);
  // Dialogs, notices and the setup open here, which the sweep does not: a style the policy refuses fails the run.
  await page.exposeFunction('reportPolicyViolation', (violation: string) => errors.push(`security policy: ${violation}`));
  await page.addInitScript(() => {
    document.addEventListener('securitypolicyviolation', (e) => {
      (window as unknown as { reportPolicyViolation: (v: string) => void }).reportPolicyViolation(
        `${e.effectiveDirective} ${e.blockedURI || 'inline'} (${e.sourceFile}:${e.lineNumber})`,
      );
    });
  });
  page.on('pageerror', (e) => errors.push(e.message));
  // Refusals answer 403 on purpose; the browser logs them as failed resources.
  page.on('console', (m) => {
    if (m.type() === 'error' && !/status of 403/.test(m.text())) errors.push(m.text());
  });
}

async function open(page: Page, hash: string) {
  await watch(page);
  await page.goto(`/#${hash}`);
  await expect(page.locator('.project-chip')).toContainText('Portail support');
}

/** Calls the local API the way the page does. */
function api<T>(page: Page, path: string, body: unknown): Promise<{ status: number; body: T }> {
  return page.evaluate(
    async ([p, b]) => {
      const session = await fetch('./api/session').then((r) => r.json());
      const response = await fetch(p as string, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-OGK-Token': session.token },
        body: JSON.stringify(b),
      });
      return { status: response.status, body: await response.json() };
    },
    [path, body] as const,
  );
}
const cli = async <T>(page: Page, argv: string[]) =>
  (await api<{ code: number; json: T; stdout: string }>(page, './api/run', { argv })).body;
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
  await expect(page.getByText('Lever les points bloquants de request-export')).toBeVisible();
  await expect(page.getByText('Réaliser request-history')).toBeVisible();
  // The name of a place link holds its visible words, then its counter for a screen reader.
  await expect(page.getByRole('navigation').getByRole('link', { name: /^Quêtes Tâches du projet\s*, 1 bloquée$/ })).toBeVisible();
});

test('lists every task by state and opens a new one', async ({ page }) => {
  await open(page, '/quetes');
  const board = page.getByRole('list', { name: 'Quêtes par état' });
  for (const id of ['dark-theme', 'status-labels', 'closing-survey', 'request-export', 'request-history', 'request-status']) {
    await expect(board.getByText(id, { exact: true })).toBeVisible();
  }
  // A task sent back is not sealed: its card says who returned it.
  const returned = board.locator('.task-card', { hasText: 'closing-survey' });
  await expect(returned).toContainText('renvoyée par Camille Martin');
  await expect(returned).not.toContainText('scellée');
  await page.getByRole('combobox', { name: 'État' }).selectOption('done');
  await expect(board.getByText('request-status', { exact: true })).toBeVisible();
  await expect(board.getByText('dark-theme', { exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: 'Nouvelle quête' }).click();
  const dialog = page.getByRole('dialog', { name: 'Ouvrir une quête' });
  await dialog
    .getByLabel('Ce que l’équipe doit faire')
    .fill('Let customers download a PDF summary of a request.\nKeep the layout of the portal.');
  await dialog.getByLabel('Identifiant (facultatif)').fill('request-pdf');
  await dialog.getByLabel('Fait suite à (facultatif)').selectOption('request-status');
  await dialog.getByRole('button', { name: 'Ouvrir la quête' }).click();
  await expect(page).toHaveURL(/#\/conseil\/request-pdf/);
  await expect(page.getByRole('heading', { name: /Cadrage : le questionnaire/ })).toBeVisible();
  const record = await cli<{ follows: { task: string }; brief: string }>(page, ['task', 'show', 'request-pdf', '--json']);
  expect(record.json.follows.task).toBe('request-status');
  expect(record.json.brief).toContain('Keep the layout of the portal.');
});

/* ------------------------------------------------------------------ council */

test('never approves: the decision is a command for the person’s terminal', async ({ page }) => {
  await open(page, '/conseil/request-export');
  await expect(page.getByRole('heading', { name: 'Avis des cerveaux' })).toBeVisible();
  await expect(page.getByLabel('Commande d’approbation')).toContainText('task decide request-export --approve');
  await expect(page.getByRole('button', { name: /^(Valider|Approuver)/ })).toHaveCount(0);
  const refused = await api<{ command: string }>(page, './api/run', {
    argv: ['task', 'decide', 'request-export', '--approve', '--by', 'Agent', '--reason', 'Self-approval'],
  });
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
  const terminal = page.getByRole('dialog', { name: /Dérogation : à faire dans ton terminal/ });
  await expect(terminal.getByLabel('Commande')).toContainText("task waive request-export security:1 --by 'Camille Martin'");
  await terminal.getByRole('button', { name: 'J’ai compris' }).click();
  expect((await cli<{ resolution: unknown }[]>(page, ['task', 'blockers', 'request-export', '--json'])).json[0].resolution).toBeNull();
});

test('hands the clearing of a blocker, with its evidence, to the person’s terminal', async ({ page }) => {
  await open(page, '/conseil/request-export');
  await page.getByRole('button', { name: 'Lever avec une preuve (au terminal)' }).click();
  const dialog = page.getByRole('dialog');
  const evidence = '.sample/request-export-evidence.md';
  await dialog.getByLabel('Preuve', { exact: true }).fill(evidence);
  await dialog.getByLabel('Ce que la preuve établit').fill('The export only holds the requester’s own requests');
  await dialog.getByLabel('Personne qui lève le point bloquant').fill('Alex Moreau');
  await dialog.getByRole('button', { name: 'Préparer la commande' }).click();
  const terminal = page.getByRole('dialog', { name: /Levée du point bloquant : à faire dans ton terminal/ });
  await expect(terminal.getByLabel('Commande')).toContainText(`task clear request-export security:1 --evidence ${evidence}`);
  await terminal.getByRole('button', { name: 'J’ai compris' }).click();
  const blockers = await cli<{ id: string; resolution: unknown }[]>(page, ['task', 'blockers', 'request-export', '--json']);
  expect(blockers.json.find((blocker) => blocker.id === 'security:1')?.resolution).toBeNull();
  const refused = await api<{ command: string }>(page, './api/run', {
    argv: ['task', 'clear', 'request-export', 'security:1', '--evidence', evidence, '--supports', 'Own requests only', '--by', 'Agent'],
  });
  expect(refused.status).toBe(403);
  expect(refused.body.command).toContain('task clear request-export security:1');
  await page.goto('/#/royaume');
  await expect(page.getByText('Lever les points bloquants de request-export')).toBeVisible();
});

test('reads the decision brief and sends a reviewed task back to the council', async ({ page }) => {
  await open(page, '/conseil/request-export');
  await page.getByRole('button', { name: 'Arbitrage (task challenge)' }).click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'Decision brief' })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();
  await page.getByLabel('Personne qui décide').fill('Camille Martin');
  await page.getByLabel('Motif', { exact: true }).fill('Agree on the CSV columns with support first');
  await page.getByRole('button', { name: 'Demander des changements' }).click();
  await expect(page.getByText('Tâche renvoyée au Conseil')).toBeVisible();
  await expect(page.locator('.quest-head').getByText('Renvoyée au Conseil')).toBeVisible();
  await expect(page.getByText(/Agree on the CSV columns with support first/).first()).toBeVisible();
});

test('frames a draft and gathers the council', async ({ page }) => {
  await open(page, '/conseil/dark-theme');
  await page.getByText('Fonctionnalité', { exact: true }).click();
  await page.getByText('Clients', { exact: true }).click();
  await page.getByText('Interne', { exact: true }).click();
  await page.getByText('Sources locales', { exact: true }).click();
  // The help of each question and what a "don't know" answer applies read in French.
  await expect(page.locator('[data-question="kind"] .hint')).toContainText('Quelque chose de nouveau, une réparation');
  await expect(page.locator('[data-question="data"] .hint')).toContainText('Si tu ne sais pas : traité comme des données personnelles');
  await expect(page.locator('[data-question="data"] .hint [lang="en"]')).toHaveCount(0);
  // The concerns question takes several answers, in French, and each one brings its board.
  const concerns = page.locator('[data-question="concerns"]');
  await expect(concerns.locator('legend')).toContainText('La tâche touche-t-elle à l’un de ces sujets');
  await expect(concerns.locator('legend')).toContainText('obligatoire');
  await expect(concerns.locator('input[type="radio"]')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: /Routage/ })).toHaveCount(0);
  await concerns.getByText('Prix, paiements, factures, paie ou dépenses').click();
  await concerns.getByText('Un modèle d’IA ou un LLM qui produit des réponses ou du contenu').click();
  await expect(concerns.locator('input:checked')).toHaveCount(2);
  await expect(page.getByText(/Sans réponse : Quel résultat observable/)).toBeVisible();
  await expect(page.getByRole('heading', { name: /Routage/ })).toBeVisible();
  await expect(page.locator('.board-pick', { hasText: 'Finance' })).toBeVisible();
  await page.getByRole('button', { name: 'Réunir le Conseil' }).click();
  await expect(page.getByText('Consultation préparée')).toBeVisible();
  await expect(page.locator('.board-seat').first()).toBeVisible();
  await expect(page.getByText(/0\/\d+ avis déposés/)).toBeVisible();
  const record = await cli<{ answers: { concerns: string[] }; consultation: { boards: string[] } }>(page, ['task', 'show', 'dark-theme', '--json']);
  expect(record.json.answers.concerns).toEqual(['money', 'ai']);
  expect(record.json.consultation.boards).toContain('finance');
});

test('passes each board, records its entry and assembles the review', async ({ page }) => {
  await open(page, '/conseil/status-labels');
  const root = await projectRoot(page);
  const progress = (await cli<{ board: string; status: string }[]>(page, ['task', 'progress', 'status-labels', '--json'])).json;
  const missing = progress.filter((p) => p.status !== 'done').map((p) => p.board);
  expect(missing.length).toBeGreaterThan(0);

  let done = progress.length - missing.length;
  for (const board of missing) {
    const seat = page.locator('.board-seat').nth(progress.findIndex((entry) => entry.board === board));
    await seat.getByRole('button', { name: 'Préparer la passe' }).click();
    const pass = page.getByRole('dialog', { name: `Passe du cerveau ${board}` });
    await expect(pass.getByRole('heading', { name: /Board pass/ })).toBeVisible();
    await pass.getByRole('button', { name: 'Fermer' }).last().click();

    await page.getByLabel('Déposer l’avis d’un cerveau (JSON)').setInputFiles(join(root, '.sample', `status-labels-${board}.json`));
    done++;
    await expect(page.getByText(`${done}/${progress.length} avis déposés.`)).toBeVisible();
  }
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
  await expect(page.getByRole('dialog', { name: /Autorisation : à faire dans ton terminal/ }).getByLabel('Commande')).toContainText(
    'task authorize request-history --action send-message --target Brevo --allow',
  );
  await page.getByRole('button', { name: 'J’ai compris' }).click();
});

test('shows an approval that no longer holds as work for a person, and names the tasks a change of rules touched', async ({ page }) => {
  await open(page, '/blueprint');
  const profilePath = join(await projectRoot(page), '.openguildkit', 'project.json');
  const original = readFileSync(profilePath, 'utf-8');
  // A convention alone voids no approval; a new check command does (only rules, checks and boards count).
  const convention = 'Name each branch after its task.';
  const add = page.getByLabel('Ajouter : Conventions de l’équipe');
  await add.fill(convention);
  await add.press('Enter');
  const check = page.getByLabel('Ajouter : Commandes de vérification');
  await check.fill('python -m compileall -q .');
  await check.press('Enter');
  await page.getByRole('button', { name: 'Enregistrer et synchroniser' }).click();
  const touched = page.locator('.touched-notice');
  await expect(touched).toContainText('request-history');
  await expect(touched).toContainText('la consulter à nouveau avec ses réponses (task consult request-history --reuse-answers)');

  // The approval no longer holds: a person consults the task again, nothing is left for the agent to build.
  await page.goto('/#/royaume');
  const todo = page.locator('.todo', { hasText: 'Consulter à nouveau request-history' });
  await expect(todo).toBeVisible();
  await expect(todo).toContainText(PERSON);
  await expect(todo).toContainText('L’approbation de request-history a été donnée sous des règles antérieures (vérifications modifiées)');
  await expect(page.getByText('Réaliser request-history')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Synchroniser' })).toHaveCount(0);
  await page.goto('/#/quetes');
  await expect(page.locator('.task-card', { hasText: 'request-history' })).toContainText('À consulter à nouveau, par une personne');
  await page.goto('/#/forge');
  await expect(page.getByRole('region', { name: /Approbation à reprendre/ })).toContainText('request-history');
  await expect(page.getByRole('region', { name: /à réaliser/ }).last()).not.toContainText('request-history');
  await page.goto('/#/tour');
  const instructions = page.getByRole('region', { name: 'Instructions du projet' });
  await expect(instructions.getByRole('link', { name: 'request-history' })).toBeVisible();
  await expect(instructions.getByRole('button', { name: 'Synchroniser' })).toHaveCount(0);

  // Instructions edited by hand: syncing them is offered, and afterwards the page names the touched tasks in full.
  await touched.getByRole('button', { name: 'Masquer' }).click();
  const agents = join(await projectRoot(page), 'AGENTS.md');
  writeFileSync(agents, readFileSync(agents, 'utf-8').replace(convention, 'Name branches freely.'));
  await page.goto('/#/royaume');
  await page.reload();
  await page.getByRole('button', { name: 'Synchroniser' }).click();
  await expect(touched).toContainText('request-history');

  // Removing the check again lowers a protection: the page refuses it and names the person's terminal command.
  await page.goto('/#/blueprint');
  await page.getByRole('button', { name: 'Retirer python -m compileall -q .' }).click();
  await page.getByRole('button', { name: 'Enregistrer et synchroniser' }).click();
  await expect(page.getByText('Ce changement affaiblit une protection du profil', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('profile remove check', { exact: false }).first()).toBeVisible();

  // The person puts back the profile the task was approved under, and syncs: the approval holds again.
  writeFileSync(profilePath, original);
  await page.goto('/#/royaume');
  await page.reload();
  await page.getByRole('button', { name: 'Synchroniser' }).click();
  await expect(page.getByText('Réaliser request-history')).toBeVisible();
});

test('shows a task record left in conflict, with the error, on the kingdom and the quests', async ({ page }) => {
  await open(page, '/royaume');
  const broken = join(await projectRoot(page), '.openguildkit', 'tasks', 'broken.json');
  writeFileSync(broken, '{\n<<<<<<< HEAD\n  "id": "broken"\n=======\n  "id": "broken-too"\n>>>>>>> other\n}\n');
  try {
    await page.reload();
    const todo = page.locator('.todo', { hasText: 'Réparer le fichier de broken' });
    await expect(todo).toContainText(PERSON);
    await expect(todo.locator('[lang="en"]')).toContainText(/broken\.json/);
    await page.goto('/#/quetes');
    const card = page.locator('.task-card', { hasText: 'broken' });
    await expect(card).toContainText('À réparer, par une personne');
    await expect(card).toContainText(/Invalid JSON|broken\.json/);
    await card.click();
    await expect(page.getByText('Le fichier de la tâche broken est illisible.')).toBeVisible();
    await expect(page.getByText('La commande a échoué')).toHaveCount(0);
  } finally {
    unlinkSync(broken);
  }
});

test('runs the checks, records the results and completes a task in the forge', async ({ page }) => {
  await open(page, '/forge/request-history');
  // A result that records only a Git revision opens on it, and stays a revision when it is saved again.
  await api(page, './api/run', {
    argv: ['task', 'result', 'request-history', '--file', '@upload:result.json'],
    uploads: { 'result.json': JSON.stringify({ revision: 'abc1234', criteria: [], checks: [] }) },
  });
  await page.reload();
  await expect(page.getByLabel('Livraison')).toHaveValue('revision');
  await expect(page.getByLabel('Révision', { exact: true })).toHaveValue('abc1234');
  await page.getByRole('button', { name: 'Enregistrer les résultats' }).click();
  await expect(page.getByText('Résultats enregistrés')).toBeVisible();
  const saved = await cli<{ result: { revision?: string; pull_request?: string } }>(page, ['task', 'show', 'request-history', '--json']);
  expect(saved.json.result).toMatchObject({ revision: 'abc1234' });
  expect(saved.json.result.pull_request).toBeUndefined();
  await page.getByLabel('Livraison').selectOption('pull_request');
  await page.getByRole('button', { name: 'Brief d’implémentation' }).click();
  await expect(
    page
      .getByRole('dialog', { name: 'Brief d’implémentation' })
      .getByText(/Approved implementation handoff|request-history/)
      .first(),
  ).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();
  await page.getByRole('button', { name: 'Lancer les commandes du projet' }).click();
  await expect(page.locator('tr', { hasText: 'command:1' }).getByText('Réussi')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/\d+ points? before the task can be done/)).toBeVisible();
  await expect(page.getByText('Une commande ne peut pas tourner ici')).toBeVisible();
  await page.getByLabel('Tes initiales').fill('CM');
  await page.getByRole('button', { name: /Marquer « non applicables » les règles non rapportées/ }).click();
  await page.getByLabel('Adresse de la pull request').fill('https://github.com/example/portal/pull/8');
  await page.getByRole('button', { name: 'Ajouter un critère' }).click();
  await page.getByLabel('Critère', { exact: true }).fill('Customers only see the history of their own requests.');
  await page.getByLabel('Preuve', { exact: true }).fill('tests/test_history_access.py');
  // The toast of the first save stays 3.5 s: once it is gone, the one found is the second save's.
  await expect(page.getByText('Résultats enregistrés')).toHaveCount(0);
  await page.getByRole('button', { name: 'Enregistrer les résultats' }).click();
  await expect(page.getByText('Résultats enregistrés')).toBeVisible();
  await page.getByRole('button', { name: 'Terminer la tâche' }).click();
  await expect(page.getByText('Tâche terminée', { exact: true })).toBeVisible();
  // Nothing was left open: the closing says so, and the task is done without reservations.
  await expect(page.getByRole('region', { name: 'Clôture' }).getByText('Aucun point laissé ouvert.')).toBeVisible();
  await page.goto('/#/quetes/request-history');
  await expect(page.locator('.quest-head').getByText('Accomplie')).toBeVisible();
});

test('records the GDPR named evidence with who provided it and completes a task on personal data', async ({ page }) => {
  await watch(page);
  await page.goto(`${GDPR}/#/forge/data-export`);
  await expect(page.locator('.project-chip')).toContainText('Portail RGPD');
  const expected = page.getByRole('region', { name: 'Tableau des vérifications' });
  const record = 'evidence:gdpr/update-processing-record/processing-record';
  const dpia = 'evidence:gdpr/assess-dpia-need/dpia-decision';
  // A named evidence the task's data requires is mandatory; a rule the task is not asked has nothing to report.
  const recordRow = expected.locator('tr', { hasText: record });
  await expect(recordRow.locator('td').nth(2)).toHaveText('oui');
  await expect(recordRow).toContainText('obligatoire : la tâche touche des données personnelles');
  const aside = expected.locator('tr', { hasText: 'rule:incident-notification/nis2-significant-incident' });
  await expect(aside.locator('td').nth(3)).toHaveText('Non demandée');

  const rules = page.getByRole('region', { name: 'Règles à rapporter' });
  await page.getByLabel('Tes initiales').fill('CM');
  // The one-click answer leaves the rules the task's answers select: each keeps its own answer.
  await page.getByRole('button', { name: /Marquer « non applicables » les règles non rapportées/ }).click();
  await expect(page.getByLabel('Issue de rule:python/follow-python-style')).toHaveValue('not-applicable');
  await expect(page.getByLabel('Issue de rule:gdpr/confirm-lawful-basis')).toHaveValue('');
  const selected = await rules
    .locator('tr', { hasText: 'Demandée par les réponses de la tâche' })
    .locator('td:first-child .mono')
    .allTextContents();
  expect(selected).toContain('rule:gdpr/confirm-lawful-basis');
  for (const id of selected) {
    await page.getByLabel(`Issue de ${id}`).selectOption('passed');
    await page.getByLabel(`Preuve de ${id}`).fill('tests/test_data_export.py');
  }
  // A named evidence passes with its document and the person who provided it.
  await page.getByLabel(`Issue de ${record}`).selectOption('passed');
  await page.getByLabel(`Preuve de ${record}`).fill('records/missing-record.md');
  await page.getByLabel(`Fournie par, pour ${record}`).fill('Dana (DPO)');
  await page.getByLabel(`Issue de ${dpia}`).selectOption('passed');
  await page.getByLabel(`Preuve de ${dpia}`).fill('records/dpia-decision.md');
  await expect(page.getByText(`Il manque une preuve, ou un motif et un responsable, pour : ${dpia}.`)).toBeVisible();
  await page.getByLabel(`Fournie par, pour ${dpia}`).fill('Dana (DPO)');
  await page.getByLabel('Livraison').selectOption('pull_request');
  await page.getByLabel('Adresse de la pull request').fill('https://github.com/example/portal/pull/9');
  await page.getByRole('button', { name: 'Enregistrer les résultats' }).click();
  // What the CLI did not record is said in French, with what to do in the page.
  await expect(page.getByText(`${record} : records/missing-record.md n’existe pas dans le projet.`, { exact: false })).toBeVisible();
  await page.getByLabel(`Issue de ${record}`).selectOption('passed');
  await page.getByLabel(`Preuve de ${record}`).fill('records/processing-record.md');
  await page.getByLabel(`Fournie par, pour ${record}`).fill('Dana (DPO)');
  await page.getByRole('button', { name: 'Enregistrer les résultats' }).click();
  await expect(page.getByText('Non enregistré :')).toHaveCount(0);
  const saved = await cli<{ result: { checks: { check: string; status: string; owner?: string }[] } }>(page, [
    'task',
    'show',
    'data-export',
  ]);
  const evidence = saved.json.result.checks.filter((c) => c.check.startsWith('evidence:'));
  expect(evidence).toHaveLength(2);
  expect(evidence).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ check: record, status: 'passed', owner: 'Dana (DPO)' }),
      expect.objectContaining({ check: dpia, status: 'passed', owner: 'Dana (DPO)' }),
    ]),
  );
  await page.getByRole('button', { name: 'Terminer la tâche' }).click();
  await expect(page.getByText('Tâche terminée', { exact: true })).toBeVisible();
  const done = await cli<{ status: string }>(page, ['task', 'show', 'data-export', '--json']);
  expect(done.json.status).toMatch(/^done/);
});

test('starts a business deliverable and lists what keeps it from review', async ({ page }) => {
  await open(page, '/forge/livrables');
  await expect(page.locator('.board-grid').getByText('Campaign brief', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Voir le modèle' }).first().click();
  await expect(page.getByRole('dialog').getByText(/Before starting the tool/)).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();
  const form = page.getByRole('region', { name: 'Nouveau brouillon' });
  await form.getByLabel('Modèle').selectOption('support-article');
  await form.getByLabel('Tâche approuvée').selectOption('request-status');
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

test('opens a task’s deliverable from its sheet', async ({ page }) => {
  await open(page, '/quetes/request-history');
  await page.getByRole('region', { name: 'Livrables' }).getByRole('link', { name: 'release-announcement' }).click();
  const draft = page.getByRole('dialog', { name: 'marketing/request-history-announcement.md' });
  await expect(draft).toBeVisible();
  await expect(draft.locator('.scroll-box')).not.toBeEmpty();
  await expect(draft.getByText(/La commande a échoué|Give a path relative/)).toHaveCount(0);
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

  await page.getByLabel('Rechercher un outil').fill('zendesk');
  await page
    .locator('tr')
    .filter({ has: page.getByLabel('Choisir Zendesk', { exact: true }) })
    .getByRole('button', { name: 'Essayer' })
    .click();
  const zendesk = page.getByRole('dialog', { name: 'Simulation zendesk' });
  await expect(zendesk.getByLabel('Outil de la simulation').locator('option')).toHaveText([
    'Choisir…',
    'search_tickets',
    'get_ticket',
    'add_internal_note',
  ]);
  await zendesk.getByLabel('Outil de la simulation').selectOption('get_ticket');
  await expect(zendesk.getByLabel('Arguments (JSON)')).toHaveValue('{"ticket_id":4101}');
  await zendesk.getByRole('button', { name: 'Fermer' }).last().click();
  await page.getByLabel('Rechercher un outil').fill('jira');
  await page
    .locator('tr')
    .filter({ has: page.getByLabel('Choisir Jira', { exact: true }) })
    .getByRole('button', { name: 'Essayer' })
    .click();
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
  await dialog.getByLabel('Tes initiales').fill('Alex Moreau');
  await dialog.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(critical.getByText('Confirmée')).toBeVisible();
  await expect(critical.getByText('Alex Moreau')).toBeVisible();

  await critical.getByRole('button', { name: 'Revoir' }).click();
  dialog = page.getByRole('dialog', { name: /Revoir form-parser/ });
  await dialog.getByLabel('Statut').selectOption('dismissed');
  await dialog.getByLabel('Motif').fill('Only used at build time');
  await dialog.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(page.getByRole('dialog', { name: 'À faire dans ton terminal' }).getByLabel('Commande')).toContainText(
    'alerts set npm:form-parser',
  );
  await page.getByRole('button', { name: 'J’ai compris' }).click();
  await expect(critical.getByText('Confirmée')).toBeVisible();
});

test('says a refusal in French by its code, keeps the command copyable, and marks an unknown one English', async ({ page }) => {
  await open(page, '/tour/alertes');
  // The server adds the code of each refusal; the page reads only the code, never the English sentence.
  let reason = 'alert-status-at-terminal';
  await page.route('**/api/run', async (route) => {
    if (route.request().postDataJSON()?.argv?.[0] !== 'alerts') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: body.command ? { ...body, reason } : body });
  });
  const dismiss = async () => {
    await page.locator('tr', { hasText: 'form-parser' }).getByRole('button', { name: 'Revoir' }).click({ timeout: 15_000 });
    const dialog = page.getByRole('dialog', { name: /Revoir form-parser/ });
    await dialog.getByLabel('Statut').selectOption('dismissed');
    await dialog.getByLabel('Tes initiales').fill('Alex Moreau');
    await dialog.getByLabel('Motif').fill('Only used at build time');
    await dialog.getByRole('button', { name: 'Enregistrer' }).click();
    return page.getByRole('dialog', { name: 'À faire dans ton terminal' });
  };
  let terminal = await dismiss();
  await expect(terminal.locator('p').first()).toHaveText(
    'Écarter une alerte critique, ou revenir sur une alerte critique confirmée, se fait par une personne, dans son terminal, avec ses initiales et la raison.',
  );
  await expect(terminal.locator('p').first()).not.toHaveAttribute('lang', 'en');
  await expect(terminal.getByLabel('Commande')).toContainText('alerts set npm:form-parser');
  await expect(terminal.getByRole('button', { name: 'Copier' })).toBeVisible();
  await terminal.getByText('Message du serveur').click();
  await expect(terminal.locator('.server-words [lang="en"]')).not.toBeEmpty();
  await terminal.getByRole('button', { name: 'J’ai compris' }).click();
  await page.keyboard.press('Escape');

  reason = 'a-code-from-a-newer-server';
  terminal = await dismiss();
  await expect(terminal.locator('p[lang="en"]').first()).not.toBeEmpty();
  await expect(terminal.getByLabel('Commande')).toContainText('alerts set npm:form-parser');
  await terminal.getByRole('button', { name: 'J’ai compris' }).click();
  await page.keyboard.press('Escape');
  await page.unroute('**/api/run');
});

test('tells the person to open the new address after the server restarted', async ({ page }) => {
  await open(page, '/royaume');
  await page.route('**/api/run', (route) =>
    route.fulfill({ status: 403, json: { error: 'Missing or invalid session token. Reload the page.', reason: 'stale-token' } }),
  );
  await page.getByRole('button', { name: 'Actualiser les données du projet' }).click();
  await expect(
    page
      .getByRole('alert')
      .filter({ hasText: 'Le serveur local a redémarré : ouvre la nouvelle adresse que « openguildkit ui » a écrite dans ton terminal.' }),
  ).toBeVisible();
  await page.unroute('**/api/run');
});

test('shows the controls: instructions, host rules and guard', async ({ page }) => {
  await open(page, '/tour');
  await expect(page.getByText('Les instructions correspondent au profil du projet.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Ce que l’hôte applique' }).locator('.card').first()).toBeVisible();
  await expect(page.getByText(/Le garde-fou est/)).toBeVisible();
  await page.getByRole('tab', { name: 'Points bloquants' }).click();
  await expect(page.getByText(/point\(s\) bloquant\(s\) ouvert\(s\)|Aucun point bloquant/)).toBeVisible();
});

test('keeps keyboard focus on the selected watchtower tab as the address changes', async ({ page }) => {
  await open(page, '/tour');
  const tabs = page.getByRole('tablist', { name: 'Tour de guet' });
  const controls = tabs.getByRole('tab', { name: 'Contrôles' });
  const alerts = tabs.getByRole('tab', { name: /Alertes de dépendances/ });
  const blockers = tabs.getByRole('tab', { name: 'Points bloquants' });

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
  // The sample project runs under local-only: no agent opens the page, a person records their review under their name.
  await expect(page.getByRole('button', { name: 'Relue, rien de neuf' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Relue par une personne' }).first().click();
  const reviewed = page.getByRole('dialog', { name: 'Page relue par une personne' });
  await reviewed.getByLabel('Qui a relu la page').fill('Camille Martin');
  await reviewed.getByRole('button', { name: 'Enregistrer' }).click();
  await expect(page.getByText('Relecture enregistrée')).toBeVisible();

  await page.getByRole('button', { name: 'Nouveau dossier' }).click();
  let dialog = page.getByRole('dialog', { name: 'Nouveau dossier de marché' });
  await dialog.getByLabel('Identifiant').fill('Chat Support');
  await expect(dialog.getByText(/Minuscules, chiffres et tirets simples, sans espace/)).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Créer' })).toBeDisabled();
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
  const day = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
  await open(page, '/documentation');
  await page.getByLabel(/request-status/).check();
  await page.getByLabel('Version du projet').fill('1.5.0');
  await page.getByRole('button', { name: 'Écrire les pages' }).click();
  await expect(page.getByText('Pages écrites')).toBeVisible();
  await page.getByRole('button', { name: 'request-status.md' }).first().click();
  await expect(page.getByRole('dialog', { name: /reference\/request-status\.md/ })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Fermer' }).last().click();

  await page.getByRole('tab', { name: /Partages/ }).click();
  // The project keeps the name an earlier journey typed (#463): a person who clears it is told why it is needed.
  await page.getByLabel('Personne qui enregistre un retrait').fill('');
  await expect(
    page.getByText(/Indique tes initiales ou l’identifiant de ton équipe pour enregistrer qu’un accès a été retiré/),
  ).toBeVisible();
  await page.getByLabel('Page ou dossier partagé').fill('docs-site/reference/request-status.md');
  await page.getByLabel('Dernier jour d’accès').fill(day(20));
  await page.getByLabel('Adresse du portail Documentalist').fill('https://docs.example.org/p/support-portal');
  await page.getByLabel('Responsable du partage').fill('Camille Martin');
  await page.getByRole('button', { name: 'Enregistrer le partage' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Il manque un destinataire' })).toBeVisible();
  await page.getByLabel('Ajouter : Destinataires (adresses)').fill('partner@example.org');
  await page.getByLabel('Ajouter : Destinataires (adresses)').press('Enter');
  await page.getByLabel('Page ou dossier partagé').fill('docs-site/reference/request-status.md');
  await page.getByLabel('Dernier jour d’accès').fill(day(20));
  await page.getByLabel('Adresse du portail Documentalist').fill('https://docs.example.org/p/support-portal');
  await page.getByLabel('Responsable du partage').fill('Camille Martin');
  await page.getByRole('button', { name: 'Enregistrer le partage' }).click();
  await expect(page.getByText('Partage enregistré')).toBeVisible();
  await page.getByLabel('Ajouter : Destinataires (adresses)').fill('partner@example.org');
  await page.getByLabel('Ajouter : Destinataires (adresses)').press('Enter');
  await page.getByLabel('Page ou dossier partagé').fill('docs-site');
  await page.getByLabel('Dernier jour d’accès').fill(day(30));
  await page.getByLabel('Adresse du portail Documentalist').fill('https://docs.example.org/p/support-portal');
  await page.getByLabel('Responsable du partage').fill('Camille Martin');
  await page.getByRole('button', { name: 'Enregistrer le partage' }).click();
  await expect(page.getByText('Avertissements de la commande')).toBeVisible();
  await expect(page.getByText(new RegExp(`later last day, ${day(30)}`))).toBeVisible();
  const row = page
    .getByRole('row')
    .filter({ has: page.getByRole('cell', { name: 'partner@example.org', exact: true }) })
    .filter({ has: page.getByText('Autres livrables visibles : docs-site', { exact: true }) });
  await expect(row.getByText('Autres livrables visibles : docs-site', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Masquer les avertissements' }).click();
  await row.getByRole('button', { name: 'Accès retiré' }).click();
  await expect(page.getByText(/docs share revoke --id [a-f0-9]{8} --by INITIALS/)).toBeVisible();

  await page.getByRole('tab', { name: /Relevés de décision/ }).click();
  await expect(page.getByRole('button', { name: /request-status/ }).first()).toBeVisible();
});

test('rebuilds the history from the task records', async ({ page }) => {
  await open(page, '/chroniques');
  await expect(page.getByText('Tâche terminée').first()).toBeVisible();
  await expect(page.getByText(/Renvoyée au Conseil par Camille Martin/).first()).toBeVisible();
  await page.getByRole('combobox', { name: 'Tâche', exact: true }).selectOption('request-history');
  await expect(page.getByText(/Approuvée par Camille Martin/)).toBeVisible();
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

test('hands a profile change that weakens a protection to the terminal', async ({ page }) => {
  await open(page, '/blueprint');
  await page.getByLabel('Recherche publique').selectOption('public-sources');
  await page.getByRole('button', { name: 'Enregistrer et synchroniser' }).click();
  const terminal = page.getByRole('dialog', { name: /Changement du profil : à faire dans ton terminal/ });
  await expect(terminal.getByLabel('Commande')).toContainText('profile set research public-sources --by INITIALS --reason WHY');
  await terminal.getByRole('button', { name: 'J’ai compris' }).click();
  const profile = await api<{ text: string }>(page, './api/files/read', { path: '.openguildkit/project.json' });
  expect(JSON.parse(profile.body.text).research).toBe('local-only');
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
  // A brain is named in French, and its English title still finds it.
  await expect(search.getByText('Sécurité et protection des données').first()).toBeVisible();
  // The count is announced, not the list of results at every keystroke.
  await expect(search.getByRole('status')).toHaveText(/^\d+ résultats?$/);
  await expect(search.locator('[aria-live]')).toHaveCount(0);
  await search.getByLabel('Rechercher').press('Enter');
  await expect(page).toHaveURL(/#\/guilde\/security/);
  await expect(page.getByRole('heading', { name: /Lentilles/ })).toBeVisible();
  await page.locator('body').click({ position: { x: 5, y: 300 } });
  await page.keyboard.press('g');
  await page.keyboard.press('q');
  await expect(page).toHaveURL(/#\/quetes/);
});

test('turns the single-key shortcuts off, and keeps the choice', async ({ page }) => {
  await open(page, '/intendance/interface');
  const single = page.getByLabel(/Raccourcis à une touche/);
  await expect(single).toBeChecked();
  await single.uncheck();
  await page.reload();
  await expect(page.getByLabel(/Raccourcis à une touche/)).not.toBeChecked();
  await page.locator('body').click({ position: { x: 5, y: 300 } });
  await page.keyboard.press('m');
  await expect(page.locator('.app')).toHaveClass(/mode-explorer/);
  await page.keyboard.press('g');
  await page.keyboard.press('q');
  await expect(page).toHaveURL(/#\/intendance\/interface/);
  await page.keyboard.press('/');
  await expect(page.getByRole('dialog', { name: 'Rechercher dans le projet' })).toHaveCount(0);
  // Ctrl+K has a modifier: it stays.
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('dialog', { name: 'Rechercher dans le projet' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByLabel(/Raccourcis à une touche/).check();
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

const settingUp = async (page: Page, origin: string, folder: string) => {
  await watch(page);
  await page.goto(`${origin}/`);
  await expect(page).toHaveURL(/#\/installation/);
  await expect(page.getByRole('heading', { name: new RegExp(`Installer la guilde dans ${folder}`) })).toBeVisible();
};
const savedProfile = async (page: Page) =>
  JSON.parse((await api<{ text: string }>(page, './api/files/read', { path: '.openguildkit/project.json' })).body.text);
const patternIds = (profile: { patterns: (string | { id: string })[] }) => profile.patterns.map((p) => (typeof p === 'string' ? p : p.id));

test('sets up a project with personal data once a person accepts the GDPR', async ({ page }) => {
  await settingUp(page, EMPTY, 'new-portal');
  const install = page.getByRole('button', { name: 'Installer la guilde' });
  const plan = page.getByRole('region', { name: 'Règles qui s’appliqueront' });
  // The questions and their choices are in French; the CLI's own help stays English, marked so.
  await expect(page.locator('[data-question="sector"] option[value="healthcare"]')).toHaveText('Santé');
  await expect(page.locator('[data-question="personal_data"] option[value="yes"]')).toHaveText('Oui');
  await expect(page.locator('[data-question="personal_data"] .hint [lang="en"]').first()).toContainText('Whether the software stores');
  await expect(page.getByText(/Sans réponse : the default/)).toHaveCount(0);
  await page.getByLabel('Nom du projet').fill('Brouillon');
  await expect(page.locator('[data-norm]').first()).toBeAttached();
  await expect(install).toBeDisabled();
  await page.locator('#setup-personal_data').selectOption('yes');
  const gdpr = page.locator('[data-norm="gdpr-personal-data"]').first();
  await expect(gdpr).toContainText('Proposée à cause de : données personnelles');
  await expect(plan.getByText(/Réponds à chaque norme proposée/)).toBeVisible();
  await expect(install).toBeDisabled();

  // A refusal of the plan reads once, and a plan with many rules says so.
  await page.route('**/api/run', async (route) => {
    if (route.request().postDataJSON()?.argv?.[0] !== 'preview') return route.continue();
    await route.fulfill({ json: { code: 1, stdout: '', stderr: 'OpenGuildKit: Sample refusal of the plan.', json: null } });
  });
  await gdpr.getByText('Oui, elle s’applique').click();
  await expect(plan.getByText('Sample refusal of the plan.')).toHaveCount(1);
  await expect(page.getByText('Sample refusal of the plan.')).toHaveCount(1);
  await expect(install).toBeDisabled();
  await page.unroute('**/api/run');
  await page.route('**/api/run', async (route) => {
    if (route.request().postDataJSON()?.argv?.[0] !== 'preview') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    body.json.rule_warning = '120 rules in force. Decline the patterns that do not concern the project.';
    await route.fulfill({ response, json: body });
  });
  await page.getByLabel('Nom du projet').fill('Brouillon 2');
  await expect(plan.getByText(/120 rules in force/)).toBeVisible();
  await page.unroute('**/api/run');
  await page.getByLabel('Nom du projet').fill('Nouveau portail');

  await expect(plan.getByText('GDPR personal data processing')).toBeVisible();
  await expect(install).toBeEnabled();
  await install.click();
  await expect(page).toHaveURL(/#\/royaume/);
  await expect(page.locator('.project-chip')).toContainText('Nouveau portail');
  const profile = await savedProfile(page);
  expect(patternIds(profile)).toContain('gdpr-personal-data');
  const agents = await api<{ text: string }>(page, './api/files/read', { path: 'AGENTS.md' });
  expect(agents.body.text).toContain('OpenGuildKit');
});

test('sets up a project with Stripe: PCI DSS accepted, a norm declined with who and why', async ({ page }) => {
  await settingUp(page, STRIPE, 'new-shop');
  const install = page.getByRole('button', { name: 'Installer la guilde' });
  await page.getByLabel('Nom du projet').fill('Nouvelle boutique');
  const pci = page.locator('[data-norm="pci-dss-cardholder-data"]').first();
  await expect(pci).toContainText('pile : Stripe');
  await page.locator('#setup-personal_data').selectOption('yes');
  const gdpr = page.locator('[data-norm="gdpr-personal-data"]').first();
  await expect(gdpr).toBeVisible();
  await pci.getByText('Oui, elle s’applique').click();
  await expect(install).toBeDisabled();
  await gdpr.getByText('Non', { exact: true }).click();
  await expect(gdpr.getByText('Un refus dit pourquoi.')).toBeVisible();
  await expect(install).toBeDisabled();
  await gdpr.getByLabel('Personne qui refuse').fill('Camille Martin');
  await gdpr.getByLabel('Pourquoi').fill('The pilot stores company accounts only');
  await expect(install).toBeEnabled();
  await expect(page.getByText(/La commande a échoué|n’est pas encore valide/)).toHaveCount(0);
  await install.click();
  await expect(page).toHaveURL(/#\/royaume/);
  // Setup sets the hash before reloading, so wait for the installed project's shell.
  await expect(page.locator('.project-chip-name')).toHaveText('Nouvelle boutique');
  const profile = await savedProfile(page);
  expect(patternIds(profile)).toContain('pci-dss-cardholder-data');
  expect(profile.declined).toEqual([
    expect.objectContaining({ id: 'gdpr-personal-data', by: 'Camille Martin', reason: 'The pilot stores company accounts only' }),
  ]);
});

/* ------------------------------------------------------------------ arsenal */

test('turns a feature on and off in the Arsenal, with who and why, and names the connection the agent keeps', async ({ page }) => {
  await open(page, '/arsenal');
  // A connection tools apply wrote, as the Forge does: turning the feature off leaves it in place.
  expect((await cli(page, ['tools', 'apply', 'jira', '--mock', '--host', 'claude-code'])).code).toBe(0);
  await page.getByRole('button', { name: 'Activer Jira' }).click();
  const on = page.getByRole('dialog', { name: 'Activer Jira' });
  await expect(on).toContainText('Le changement est inscrit dans l’historique du profil.');
  await on.getByLabel('Personne qui décide').fill('Camille Martin');
  await on.getByLabel('Pourquoi').fill('The team tracks its tickets in Jira');
  await on.getByRole('button', { name: 'Activer', exact: true }).click();
  await expect(page.getByText('Fonctionnalité activée')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Désactiver Jira' })).toBeVisible();
  expect((await savedProfile(page)).tools).toContain('Jira');
  await expect(page.getByText(/^Jira\b.* reste connecté à l’agent/)).toHaveCount(0);

  await page.getByRole('button', { name: 'Désactiver Jira' }).click();
  const off = page.getByRole('dialog', { name: 'Désactiver Jira' });
  await expect(off.getByLabel('Personne qui décide')).toHaveValue('Camille Martin');
  await off.getByLabel('Pourquoi').fill('We moved to Linear');
  await off.getByRole('button', { name: 'Désactiver', exact: true }).click();
  await expect(page.getByText('Fonctionnalité désactivée')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Activer Jira' })).toBeVisible();
  const profile = await savedProfile(page);
  expect(profile.tools).not.toContain('Jira');
  expect(profile.changes.at(-1)).toEqual(
    expect.objectContaining({ change: 'features disable jira', by: 'Camille Martin', reason: 'We moved to Linear' }),
  );
  // features disable names the connection and the command that removes it; the page says the same.
  await expect(page.getByText(/^Jira\b.* reste connecté à l’agent/)).toBeVisible();
  await expect(page.locator('.notice', { hasText: 'reste connecté' })).toContainText('Le serveur MCP jira (claude-code, simulation)');
  await expect(page.getByLabel('Commande qui retire la connexion')).toContainText(
    profile.host === 'claude-code' ? /tools remove jira$/ : /tools remove jira --host claude-code$/,
  );
});

test('shows on its card how many tasks a task waits for, and lists them with their status on its sheet', async ({ page }) => {
  await open(page, '/quetes');
  const created = await cli(page, [
    'task',
    'new',
    'Send the PDF summary by email.',
    '--id',
    'pdf-email',
    '--after',
    'request-pdf',
    '--after',
    'request-status',
  ]);
  expect(created.code).toBe(0);
  const listed = await cli<{ id: string; waiting_for?: { task: string; status: string }[] }[]>(page, ['task', 'list', '--json']);
  // request-status is done; request-pdf, opened earlier in this run, is not.
  expect(listed.json.find((t) => t.id === 'pdf-email')?.waiting_for?.map((w) => w.task)).toEqual(['request-pdf']);
  await page.reload();
  const card = page.locator('.task-card', { hasText: 'pdf-email' });
  await expect(card).toContainText('Attend 1 tâche');
  await card.click();
  const deps = page.getByLabel('Dépendances');
  await expect(deps).toContainText('request-pdf');
  await expect(deps).toContainText('request-status');
  await expect(deps.locator('li')).toHaveCount(2);
  await expect(deps.locator('li', { hasText: 'request-status' }).locator('.badge')).toHaveCount(1);
});
