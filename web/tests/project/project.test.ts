import { describe, expect, it } from 'vitest';
import { quoteFor } from '@/project/api';
import { changesCatalog, invalidate, load, peek, remember } from '@/project/query';
import { placeCounts, signalsOf } from '@/project/data';
import { hasFailedCheck, isBlocked, isDecided, isDone, nextLabel, openPointLabel, parseTemplates, shareState, stepOf, taskStatus } from '@/project/labels';
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
    expect(taskStatus('unreadable').label).toBe('unreadable');
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
    expect(s.checkFailed).toBe(true);
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
