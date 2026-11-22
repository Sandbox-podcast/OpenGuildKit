import { describe, expect, it } from 'vitest';
import { projectPath, quoteFor } from '@/project/api';
import { shortcutFor } from '@/shared/shortcuts';
import { GROUP_ABOVE, todos } from '@/project/todo';
import { changesCatalog, invalidate, load, peek, remember } from '@/project/query';
import { onlyTasksFail, placeCounts, signalsOf } from '@/project/data';
import { decidedBy, deliveryOf, hasFailedCheck, isBlocked, isDecided, isDone, nextLabel, nextLang, openPointLabel, parseTemplates, reasonLabel, shareState, statusesOf, stepOf, taskStatus, touchedStep, touchedTasks } from '@/project/labels';
import { missingRequired, normAnswers, pendingNorms, setupAnswers, type NormDraft } from '@/project/setup';
import { isMultiple, toggleChoice, unanswered } from '@/project/answers';
import type { CliResult } from '@/project/api';

const ok = (json: unknown): CliResult => ({ code: 0, stdout: JSON.stringify(json), stderr: '', json });

describe('wording of the CLI', () => {
  it('translates every next step the CLI prints', () => {
    expect(nextLabel('Answer the questionnaire and consult the boards.')).toBe('Répondre au questionnaire et consulter les cerveaux.');
    expect(nextLabel('Board reviews pending: marketing, security.')).toBe('Avis attendus : marketing, security.');
    expect(nextLabel('Write the summary and record the review.')).toMatch(/^Rédiger la synthèse/);
    expect(nextLabel('Resolve blockers security:1, qa:2.')).toBe('Lever les blocages security:1, qa:2.');
    expect(nextLabel("Waiting for the person's decision.")).toBe('En attente de la décision d’une personne.');
    expect(nextLabel('Consult again: Check consent first')).toBe('Consulter à nouveau : Check consent first');
    expect(nextLabel('Decision recorded: close it with task complete pick-db, then open a follow-up task to act on it.')).toMatch(/^Décision enregistrée : la clore avec task complete pick-db/);
    expect(nextLabel('Implement, then record the results: task verify status and task result status, then task complete status.')).toMatch(/^Réaliser.*task verify status/);
    expect(nextLabel('Waiting for evidence: Record of processing from data protection officer.')).toBe('En attente de preuves : Record of processing from data protection officer.');
    expect(nextLabel('Result recorded: run task verify status to list what remains, then task complete status.')).toMatch(/^Résultats enregistrés : task verify status/);
    const failed = "command:1 (`python -m pytest`) failed: exit code 127, command not found: /bin/sh: python: command not found. Next: install the project's dependencies. Log: .openguildkit/tasks/status-checks/command-1.log and 2 other check(s). Fix it, then run task verify status.";
    expect(nextLabel(failed)).toMatch(/^Échec de command:1 \(python -m pytest\) : exit code 127.*, et de 2 autre\(s\) contrôle\(s\)\. Corriger, puis relancer task verify status\.$/s);
    expect(nextLabel('rule:x/y failed. Fix it, then run task verify status.')).toBe('Échec de rule:x/y. Corriger, puis relancer task verify status.');
    expect(hasFailedCheck(failed)).toBe(true);
    expect(nextLabel('Done with reservations: see the open points in task show (result.closing).')).toMatch(/^Terminée avec réserves/);
    expect(nextLabel('Done.')).toBe('Terminée.');
    expect(nextLabel('Something new.')).toBe('Something new.');
    expect(isBlocked('Resolve blockers security:1.')).toBe(true);
    expect(isBlocked("Waiting for the person's decision.")).toBe(false);
  });

  it('names an unanswered question in French when the CLI prompt is known', () => {
    const prompts = { outcome: 'What observable result shows that the feature works?' };
    expect(openPointLabel('Unanswered: What observable result shows that the feature works?', prompts)).toMatch(/^Sans réponse : Quel résultat observable/);
    expect(openPointLabel('Unanswered: Something else?', prompts)).toBe('Sans réponse : Something else?');
  });

  it('places each status on the workflow and keeps unknown ones', () => {
    expect([stepOf('draft', false), stepOf('consulting', false), stepOf('reviewed', false), stepOf('approved', false), stepOf('approved', true), stepOf('done', true), stepOf('done-with-reservations', true)]).toEqual([0, 1, 3, 4, 5, 6, 6]);
    expect(taskStatus('done-with-reservations').label).toBe('Terminée avec réserves');
    expect(['approved', 'done', 'done-with-reservations', 'reviewed'].map(isDecided)).toEqual([true, true, true, false]);
    expect(['done', 'done-with-reservations', 'approved'].map(isDone)).toEqual([true, true, false]);
    expect(shareState('expired: remove the access in Documentalist')).toBe('expired');
    expect(shareState('revoked')).toBe('revoked');
    expect(shareState('active')).toBe('active');
  });

  it('reads the deliverable templates, with or without a method', () => {
    const text = 'campaign-brief           Campaign brief (method marketing-campaign-planning) [marketing, communication, legal]\nsupport-article          Knowledge base article [support, communication]\n';
    expect(parseTemplates(text)).toEqual([
      { id: 'campaign-brief', title: 'Campaign brief', method: 'marketing-campaign-planning', brains: ['marketing', 'communication', 'legal'] },
      { id: 'support-article', title: 'Knowledge base article', method: '', brains: ['support', 'communication'] },
    ]);
  });
});

describe('task questionnaire', () => {
  const questions = [
    { id: 'kind', prompt: 'What?', choices: [{ id: 'feature', label: 'Feature' }] },
    { id: 'concerns', prompt: 'Topics?', type: 'multi-select', choices: [{ id: 'money', label: 'Money' }, { id: 'ai', label: 'AI' }, { id: 'none', label: 'None' }] },
    { id: 'context', prompt: 'Context?', type: 'text' },
  ];

  it('takes several concerns when the CLI says multi-select, and keeps none and unsure alone', () => {
    expect(questions.map(isMultiple)).toEqual([false, true, false]);
    expect(toggleChoice(toggleChoice([], 'money'), 'ai')).toEqual(['money', 'ai']);
    expect(toggleChoice(['money', 'ai'], 'none')).toEqual(['none']);
    expect(toggleChoice(['none'], 'ai')).toEqual(['ai']);
    expect(toggleChoice(['money', 'ai'], 'money')).toEqual(['ai']);
  });

  it('waits for every question with choices before routing', () => {
    expect(unanswered(questions, { kind: 'feature' })).toEqual(['concerns']);
    expect(unanswered(questions, { kind: 'feature', concerns: [] })).toEqual(['concerns']);
    expect(unanswered(questions, { kind: 'feature', concerns: ['money', 'ai'] })).toEqual([]);
  });
});

describe('setup answers', () => {
  it('sends a yes, or a no with who and why, and waits for every proposed norm', () => {
    const drafts: Record<string, NormDraft> = { 'gdpr-personal-data': { answer: 'yes' }, 'pci-dss-cardholder-data': { answer: 'no', by: 'Camille Martin', reason: ' ' } };
    expect(normAnswers(drafts)).toEqual({ 'gdpr-personal-data': 'yes' });
    expect(pendingNorms(['gdpr-personal-data', 'pci-dss-cardholder-data', 'dora-financial-entity'], drafts)).toEqual(['pci-dss-cardholder-data', 'dora-financial-entity']);
    drafts['pci-dss-cardholder-data'].reason = 'No card data reaches the project';
    expect(normAnswers(drafts)['pci-dss-cardholder-data']).toEqual({ answer: 'no', by: 'Camille Martin', reason: 'No card data reaches the project' });
    expect(pendingNorms(['gdpr-personal-data', 'pci-dss-cardholder-data'], drafts)).toEqual([]);
    expect(setupAnswers({ name: 'Shop' }, {})).toEqual({ name: 'Shop' });
    expect(setupAnswers({ name: 'Shop' }, drafts)).toMatchObject({ name: 'Shop', norms: { 'gdpr-personal-data': 'yes' } });
  });

  it('names the required questions left unanswered and says why a norm is proposed', () => {
    const questions = [{ id: 'personal_data', prompt: 'Personal data?', required: true }, { id: 'name', prompt: 'Name' }];
    expect(missingRequired(questions, {})).toEqual(['personal_data']);
    expect(missingRequired(questions, { personal_data: 'no' })).toEqual([]);
    expect(['stack Stripe', 'personal data', 'sector healthcare', 'something else'].map(reasonLabel)).toEqual(['pile : Stripe', 'données personnelles', 'secteur Santé', null]);
  });
});

describe('task pages', () => {
  it('opens a result on what it records, and says who sent a task back', () => {
    expect(deliveryOf({ revision: 'abc1234' })).toBe('revision');
    expect(deliveryOf({ revision: 'abc1234', pull_request: 'https://example.test/pull/7' })).toBe('pull_request');
    expect(deliveryOf(undefined)).toBe('pull_request');
    expect([decidedBy('changes-requested', true), decidedBy('approved', true), decidedBy('done', false)]).toEqual(['renvoyée par', 'scellée par', 'approuvée par']);
  });

  it('turns a path the CLI records into one the file API takes, on POSIX and Windows', () => {
    expect(projectPath('/home/camille/portal/marketing/a.md', '/home/camille/portal')).toBe('marketing/a.md');
    expect(projectPath('C:\\Users\\Camille\\portal\\marketing\\a.md', 'C:\\Users\\Camille\\portal')).toBe('marketing/a.md');
    expect(projectPath('marketing/a.md', '/home/camille/portal')).toBe('marketing/a.md');
  });

  it('lists each task to do, and one entry per kind when there are many', () => {
    const drafts = Array.from({ length: 503 }, (_, i) => ({ id: `t${i}`, status: 'draft', next: 'Answer the questionnaire and consult the boards.' }));
    const few = signalsOf({ tasks: ok(drafts.slice(0, GROUP_ABOVE)) });
    expect(todos(few).map((t) => t.title)).toEqual(drafts.slice(0, GROUP_ABOVE).map((t) => `Cadrer ${t.id}`));
    const many = todos(signalsOf({ tasks: ok(drafts) }));
    expect(many).toHaveLength(1);
    expect(many[0]).toMatchObject({ title: '503 quêtes à cadrer', to: '/quetes?statut=draft', who: 'person' });
  });
});

describe('keyboard shortcuts of both shells', () => {
  const key = (k: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean }> = {}) => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, ...mods });
  it('acts on single keys only while they are on, and always on Ctrl+K', () => {
    expect(shortcutFor(key('k', { ctrlKey: true }), false, Infinity)).toEqual({ action: 'search' });
    expect(shortcutFor(key('k', { metaKey: true }), true, Infinity)).toEqual({ action: 'search' });
    expect(['/', 'm', 'g', '?'].map((k) => shortcutFor(key(k), true, Infinity))).toEqual([{ action: 'search' }, { action: 'mode' }, { action: 'prefix' }, { action: 'help' }]);
    expect(['/', 'm', 'g', '?'].map((k) => shortcutFor(key(k), false, Infinity))).toEqual([null, null, null, null]);
    expect(shortcutFor(key('q'), true, 300)).toEqual({ action: 'go', route: '/quetes' });
    expect(shortcutFor(key('q'), true, 5000)).toBeNull();
    expect(shortcutFor(key('m', { ctrlKey: true }), true, Infinity)).toBeNull();
  });
});

describe('commands to type in a terminal', () => {
  it('quotes for PowerShell and for POSIX shells', () => {
    expect(quoteFor('request-status', true)).toBe('request-status');
    expect(quoteFor('C:\\Users\\Camille\\portal', true)).toBe("'C:\\Users\\Camille\\portal'");
    expect(quoteFor("Camille's scope", true)).toBe("'Camille''s scope'");
    expect(quoteFor("Camille's scope", false)).toBe("'Camille'\\''s scope'");
    expect(quoteFor('a $HOME `x`', false)).toBe("'a $HOME `x`'");
  });
});

describe('project signals', () => {
  const overview = {
    tasks: ok([
      { id: 'a', status: 'reviewed', created: '2026-11-21', owner: null, brief: 'A', next: 'Resolve blockers security:1.' },
      { id: 'b', status: 'reviewed', created: '2026-11-21', owner: null, brief: 'B', next: "Waiting for the person's decision." },
      { id: 'c', status: 'approved', created: '2026-11-21', owner: 'Camille', brief: 'C', next: 'Implement, then record the results: task verify c and task result c, then task complete c.' },
      { id: 'e', status: 'done-with-reservations', created: '2026-11-20', owner: 'Camille', brief: 'E', next: 'Done with reservations: see the open points in task show (result.closing).', closed_by: 'Camille' },
      { id: 'd', status: 'consulting', created: '2026-11-21', owner: null, brief: 'D', next: 'Board reviews pending: qa.' },
    ]),
    check: { code: 1, stdout: '', stderr: 'OpenGuildKit: AGENTS.md is out of date.', json: null },
    alerts: ok({ summary: { total: 3, by_status: { open: 1, confirmed: 1, dismissed: 1, resolved: 0 }, by_severity: {}, imports: [] }, alerts: [] }),
    shares: ok([{ state: 'expired: remove the access in Documentalist' }, { state: 'active' }]),
    due: ok({ dossiers: [], due: [{ competitor: 'x', url: 'https://example.com', kind: 'notes', dossier: 'd' }] }),
    update: ok({ changes: [{}, {}], conflicts: [], applied: false, stale_tasks: [{ id: 'c', status: 'approved', step: 'consult it again (openguildkit task consult c) or open a linked task with --follows' }] }),
    host: ok([{ id: 'research', title: 'R', status: 'missing', detail: '' }, { id: 'approval', title: 'A', status: 'enforced', detail: '' }]),
  };

  it('derives what waits on whom and the counters of the places', () => {
    const s = signalsOf(overview);
    expect(s.instructionsDrift).toBe(true);
    expect(s.blocked.map((t) => t.id)).toEqual(['a']);
    expect(s.awaitingDecision.map((t) => t.id)).toEqual(['b']);
    expect(s.toBuild.map((t) => t.id)).toEqual(['c']);
    expect([s.alertsOpen, s.sharesExpired, s.marketDue, s.updates, s.hostMissing]).toEqual([2, 1, 1, 2, 1]);
    expect(s.staleTasks.map((t) => t.id)).toEqual(['c']);
    const counts = placeCounts(s);
    expect(counts.quetes?.n).toBe(1);
    expect(counts.conseil?.n).toBe(2);
    expect(counts.forge?.n).toBe(1);
    expect(counts.documentation?.n).toBe(1);
    expect(counts.intendance?.n).toBe(3);
  });

  it('sends an approval that no longer holds and an unreadable record to a person, not to the agent', () => {
    const stale = 'The approval for c was recorded under earlier rules (conventions changed). Consult it again with openguildkit task consult c, or open a linked task with openguildkit task new "BRIEF" --follows c.';
    const tasks = ok([
      { id: 'c', status: 'approved', created: '2026-11-21', owner: 'Camille', brief: 'C', next: stale, approval_problem: 'earlier-rules', severity: 'error' },
      { id: 'f', status: 'approved', created: '2026-11-21', owner: 'Camille', brief: 'F', next: 'Implement, then record the results: task verify f and task result f, then task complete f.' },
      { id: 'broken', status: 'unreadable', next: 'Invalid JSON in .openguildkit/tasks/broken.json: Expecting property name enclosed in double quotes' },
    ]);
    const check = { code: 1, stdout: '', stderr: 'OpenGuildKit: c: ...\nOpenGuildKit: The instructions match the project profile, but 1 approval no longer holds: each line above gives the command to run.', json: null };
    const s = signalsOf({ tasks, check });
    expect(s.instructionsDrift).toBe(false);
    expect(onlyTasksFail(check)).toBe(true);
    expect(s.reconsult.map((t) => t.id)).toEqual(['c']);
    expect(s.unreadable.map((t) => t.id)).toEqual(['broken']);
    expect(s.toBuild.map((t) => t.id)).toEqual(['f']);
    const counts = placeCounts(s);
    expect(counts.blueprint).toBeNull();
    expect(counts.quetes).toMatchObject({ n: 2, label: 'à reprendre par une personne' });
    expect(nextLabel(stale)).toBe('L’approbation de c a été donnée sous des règles antérieures (conventions modifiées). La consulter à nouveau (task consult c), ou ouvrir une tâche liée (task new --follows c).');
    expect([nextLang(stale), nextLang('Invalid JSON in x')]).toEqual([undefined, 'en']);
    expect(statusesOf(tasks.json as { status: string }[])).toContain('unreadable');
    expect(statusesOf([{ status: 'draft' }])).not.toContain('unreadable');
    expect(taskStatus('unreadable').label).toBe('Illisible');
  });

  it('reads the tasks that sync names after a change of rules', () => {
    const stdout = 'OpenGuildKit instructions updated.\nTasks consulted under the previous rules:\n  request-history (approved): consult it again (openguildkit task consult request-history) or open a linked task with --follows.\n  status-labels (consulting): consult it again.\n';
    expect(touchedTasks(stdout)).toEqual([
      { id: 'request-history', status: 'approved', step: 'consult it again (openguildkit task consult request-history) or open a linked task with --follows' },
      { id: 'status-labels', status: 'consulting', step: 'consult it again' },
    ]);
    expect(touchedTasks('OpenGuildKit instructions updated.\n')).toEqual([]);
    expect(touchedStep('request changes and consult it again')).toMatch(/^demander des changements/);
    expect(touchedStep('something new')).toBeNull();
  });

  it('shows nothing for an empty or failed overview', () => {
    const s = signalsOf(undefined);
    expect(s.tasks).toEqual([]);
    expect(Object.values(placeCounts(s)).every((c) => c === null)).toBe(true);
  });
});

describe('cache', () => {
  it('reloads an entry that an action invalidated while it was loading', async () => {
    let finish: (value: unknown) => void = () => {};
    const pending = load('test:race', () => new Promise((resolve) => { finish = resolve; }));
    expect(peek('test:race')?.loading).toBe(true);
    invalidate();
    finish(['old answer']);
    await pending;
    expect(peek('test:race')).toMatchObject({ data: ['old answer'], loading: false, stale: true });
    await load('test:race', async () => ['new answer']);
    expect(peek('test:race')).toMatchObject({ data: ['new answer'], stale: false });
  });

  it('keeps the answers that depend only on the catalog across an ordinary action', async () => {
    remember('test:brains', ['brains', '--json']);
    remember('test:tasks', ['task', 'list', '--json']);
    await load('test:brains', async () => ({ product: {} }));
    await load('test:tasks', async () => []);
    invalidate('project');
    expect(peek('test:brains')?.stale).toBe(false);
    expect(peek('test:tasks')?.stale).toBe(true);
    invalidate('all');
    expect(peek('test:brains')?.stale).toBe(true);
    expect([changesCatalog(['update', '--apply']), changesCatalog(['sync']), changesCatalog(['task', 'clear'])]).toEqual([true, true, false]);
  });

  it('keeps the previous data when a reload fails', async () => {
    await load('test:fail', async () => 'kept');
    await load('test:fail', async () => { throw new Error('server stopped'); });
    expect(peek('test:fail')).toMatchObject({ data: 'kept', loading: false });
    expect(peek('test:fail')?.error?.message).toContain('server stopped');
  });
});
