import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { watchGithub } from '../lib/watch.mjs';
import { renderWatchReport } from '../lib/github-report.mjs';

test('a restarted watcher resumes existing work and only dispatches the revised profile', t => {
  const folder = mkdtempSync(join(tmpdir(), 'openguildkit-watch-'));
  t.after(() => rmSync(folder, { recursive: true, force: true }));
  const configPath = join(folder, 'config.json');
  const [a, b] = ['team/a', 'team/b'];
  writeFileSync(configPath, JSON.stringify({
    projects: [a.toUpperCase(), b].map(id => ({ id, workflow: { file: 'recheck.yml', ref: 'pilot/base' } })),
  }));
  const make = (project, work, profileCommit, state) => {
    const proof = { commit: 'a'.repeat(40), policyCommit: 'b'.repeat(40), profileCommit, state };
    const file = join(folder, `${work}.json`);
    writeFileSync(file, JSON.stringify({ evidence: proof }));
    return { project, work, pullRequest: 1, status: state, evidence: [file], proof };
  };
  const firstA = make(a, '1'.repeat(64), 'c'.repeat(40), 'failure');
  const firstB = make(b, '2'.repeat(64), 'd'.repeat(40), 'success');
  const updatedA = make(a, '3'.repeat(64), 'e'.repeat(40), 'success');
  const records = new Map();
  const calls = [];
  let current = [firstA, firstB];
  let complete = false;
  const scheduler = () => watchGithub({ configPath, stateDir: join(folder, 'state') }, {
    reconcile: ({ run }) => {
      assert.equal(run, true);
      return { current };
    },
    actions: {
      dispatch(entry, workflow) {
        assert.equal(workflow.file, 'recheck.yml');
        calls.push(entry.work);
        records.set(entry.work, entry);
        return { id: entry.work, url: `https://example.org/${entry.work}` };
      },
      status: () => complete ? { status: 'completed', conclusion: 'success' } : { status: 'in_progress' },
      proof: (_project, id) => records.get(id),
    },
  });
  assert.deepEqual(scheduler().targets.map(row => row.actions.state), ['dispatched', 'dispatched']);
  assert.deepEqual(scheduler().targets.map(row => row.actions.state), ['dispatched', 'dispatched']);
  current = [updatedA, firstB];
  complete = true;
  assert.deepEqual(scheduler().targets.map(row => row.actions.state), ['dispatched', 'verified']);
  assert.deepEqual(scheduler().targets.map(row => row.actions.state), ['verified', 'verified']);
  assert.deepEqual(calls, [firstA.work, firstB.work, updatedA.work]);

  const updatedB = make(b, '4'.repeat(64), 'f'.repeat(40), 'failure');
  current = [updatedA, updatedB];
  assert.deepEqual(scheduler().targets.map(row => row.actions.state), ['verified', 'dispatched']);
  records.set(updatedB.work, firstB);
  const stale = scheduler();
  assert.deepEqual(stale.targets.map(row => row.actions.state), ['verified', 'mismatch']);
  assert.equal(stale.errors[0].work, updatedB.work);
});

test('the watcher skips publication when the proof became stale after the evaluation', t => {
  const folder = mkdtempSync(join(tmpdir(), 'openguildkit-publish-'));
  t.after(() => rmSync(folder, { recursive: true, force: true }));
  const configPath = join(folder, 'config.json');
  const project = 'team/repo';
  writeFileSync(configPath, JSON.stringify({
    projects: [{ id: project, workflow: { file: 'recheck.yml', ref: 'pilot/base', evidenceBranch: 'reports' } }],
  }));
  const old = { project, status: 'failure', work: 'old', decision: { effectiveStatus: 'failure' } };
  const latest = { ...old, work: 'new' };
  const result = watchGithub({ configPath, stateDir: folder, publish: true }, {
    reconcile: ({ run }) => ({ current: [run ? old : latest] }),
    actions: { dispatch: () => ({ id: '1', url: 'https://example.org/1' }) },
    publishReport: () => assert.fail('An obsolete proof reached publication'),
  });
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.publications, []);
});

test('the PR report treats malformed export values as an invalid measurement', () => {
  const body = renderWatchReport({
    project: 'team/repo', pullRequest: 7, mode: 'observation',
    actions: { proof: { proof: { actualMinutes: '[untrusted](https://example.org)', maxMinutes: 30 } } },
    decision: { effectiveStatus: 'failure' },
  });
  assert.match(body, /Seuil 30 min · Valeur invalide/);
  assert.doesNotMatch(body, /untrusted|example\.org/);
});

test('a lost dispatch response is recovered by attempt before another dispatch', t => {
  const folder = mkdtempSync(join(tmpdir(), 'openguildkit-attempt-'));
  t.after(() => rmSync(folder, { recursive: true, force: true }));
  const configPath = join(folder, 'config.json');
  const project = 'team/repo';
  const work = 'a'.repeat(64);
  writeFileSync(configPath, JSON.stringify({
    projects: [{ id: project, workflow: { file: 'recheck.yml', ref: 'pilot/base' } }],
  }));
  const path = join(folder, 'actions', `${work}.json`);
  let now = 1;
  let visible = false;
  const attempts = [];
  const run = { id: '1', url: 'https://github.com/team/repo/actions/runs/1' };
  const pass = () => watchGithub({ configPath, stateDir: folder }, {
    clock: () => now,
    reconcile: () => ({ current: [{ project, work, status: 'success' }] }),
    actions: {
      dispatch(_entry, _workflow, attempt) {
        const persisted = JSON.parse(readFileSync(path, 'utf8'));
        assert.equal(persisted.state, 'requesting');
        assert.equal(persisted.attempt, attempt);
        attempts.push(attempt);
        throw new Error('response lost');
      },
      find(_entry, { attempt }) {
        assert.equal(attempt, attempts.at(-1));
        return visible ? run : null;
      },
      status: () => ({ status: 'in_progress' }),
    },
  });
  assert.match(pass().errors[0].message, /response lost/);
  now += 60_000;
  assert.equal(pass().targets[0].actions.state, 'requesting');
  assert.equal(attempts.length, 1);
  visible = true;
  const recovered = pass().targets[0].actions;
  assert.equal(recovered.state, 'dispatched');
  assert.equal(recovered.id, run.id);
  assert.equal(recovered.recovered, true);
  assert.equal(attempts.length, 1);

  rmSync(path);
  visible = false;
  assert.match(pass().errors[0].message, /response lost/);
  now += 120_000;
  assert.match(pass().errors[0].message, /response lost/);
  assert.equal(new Set(attempts).size, 3);
});
