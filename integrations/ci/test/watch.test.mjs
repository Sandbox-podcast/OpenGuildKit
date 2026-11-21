import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { hostname, tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { acquireWatchLock, watchGithub } from '../lib/watch.mjs';
import { renderWatchReport, watchReportStatus } from '../lib/github-report.mjs';
import { latestStatus } from '../lib/github.mjs';

const kitVersion = '0.16.1';
const policyRepo = { id: 'team/policies', ref: 'refs/heads/main' };
const profileRef = 'refs/heads/main';
const pins = () => ({
  settings: { policyRepository: policyRepo.id, policyRef: policyRepo.ref, profileRef },
  kit: `${'a'.repeat(64)}  openguildkit-${kitVersion}.tgz\n`,
});
const project = (id, workflow) => ({ id, profileRef, workflow });

function fixture(t, prefix, workflow = { file: 'recheck.yml', ref: 'pilot/base' }, watch) {
  const folder = mkdtempSync(join(tmpdir(), prefix));
  t.after(() => rmSync(folder, { recursive: true, force: true }));
  const configPath = join(folder, 'config.json');
  writeFileSync(configPath, JSON.stringify({ policyRepo, watch, projects: [project('team/repo', workflow)] }));
  return { folder, configPath };
}

function proofEntry(folder, work, state = 'success') {
  const proof = { commit: 'a'.repeat(40), policyCommit: 'b'.repeat(40), profileCommit: 'c'.repeat(40), state };
  const file = join(folder, `${work}.json`);
  writeFileSync(file, JSON.stringify({ evidence: proof }));
  return {
    project: 'team/repo', work, pullRequest: 1, status: state, evidence: [file], proof,
    commit: proof.commit, policyCommit: proof.policyCommit, profileCommit: proof.profileCommit,
    profileSha256: 'd'.repeat(64), rule: 'export-link-expiry', kitVersion,
  };
}

test('a restarted watcher resumes existing work and only dispatches the revised profile', t => {
  const folder = mkdtempSync(join(tmpdir(), 'openguildkit-watch-'));
  t.after(() => rmSync(folder, { recursive: true, force: true }));
  const configPath = join(folder, 'config.json');
  const [a, b] = ['team/a', 'team/b'];
  writeFileSync(configPath, JSON.stringify({
    policyRepo, projects: [a.toUpperCase(), b].map(id => project(id, { file: 'recheck.yml', ref: 'pilot/base' })),
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
  const scheduler = () => watchGithub({ configPath, stateDir: join(folder, 'state'), kitVersion }, {
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
      pins,
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
  const { folder, configPath } = fixture(t, 'openguildkit-publish-',
    { file: 'recheck.yml', ref: 'pilot/base', evidenceBranch: 'reports' });
  const old = { project: 'team/repo', status: 'failure', work: 'old', decision: { effectiveStatus: 'failure' } };
  const latest = { ...old, work: 'new' };
  const result = watchGithub({ configPath, stateDir: folder, publish: true, kitVersion }, {
    reconcile: ({ run }) => ({ current: [run ? old : latest] }),
    actions: { dispatch: () => ({ id: '1', url: 'https://example.org/1' }), pins },
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
  assert.match(body, /Threshold 30 min · Value invalid/);
  assert.match(body, /^\*\*Deviation\*\* · Observation$/m);
  assert.doesNotMatch(body, /untrusted|example\.org/);
});

test('the PR report and its status are written in English', () => {
  const work = 'c'.repeat(64);
  const entry = {
    project: 'team/repo', pullRequest: 7, commit: 'a'.repeat(40), profileCommit: 'b'.repeat(40),
    policyCommit: 'd'.repeat(40), rule: 'export-link-expiry', mode: 'required', work,
    actions: { state: 'verified', url: 'https://github.com/team/repo/actions/runs/1', verifiedAt: '2026-11-21T00:00:00Z',
      proof: { proof: { actualMinutes: 20, maxMinutes: 30, owner: '@lead', guidance: 'Keep links short.', state: 'success' } } },
    decision: { effectiveStatus: 'waived', waiver: { id: 'w1', reason: 'Migration', approver: '@lead',
      expiresAt: '2026-12-01T00:00:00Z', registryCommit: 'e'.repeat(40) } },
  };
  const body = renderWatchReport(entry, '3');
  assert.match(body, /^# OpenGuildKit report$/m);
  assert.match(body, /^\*\*Waived\*\* · Required check$/m);
  assert.match(body, /^- Evaluated commit `a{40}`$/m);
  assert.match(body, /^- Waiver `w1` · `Migration`/m);
  assert.doesNotMatch(body, /[éèàêç]|Conforme|Règle|Dérogation/);
  assert.deepEqual(watchReportStatus(entry), { verified: true, state: 'success', description: `Waived (info) | rule ${'d'.repeat(12)} | ${'c'.repeat(12)}` });
  assert.equal(watchReportStatus({ ...entry, actions: { state: 'failed' } }).description,
    `CI verification error (info) | rule ${'d'.repeat(12)} | ${'c'.repeat(12)}`);
  assert.equal(watchReportStatus({ ...entry, actions: { state: 'running' } }).description,
    `Waiting for the reports of both CIs (info) | rule ${'d'.repeat(12)} | ${'c'.repeat(12)}`);
});

test('a lost dispatch response is recovered by attempt before another dispatch', t => {
  const { folder, configPath } = fixture(t, 'openguildkit-attempt-');
  const work = 'a'.repeat(64);
  const path = join(folder, 'actions', `${work}.json`);
  let now = 1;
  let visible = false;
  const attempts = [];
  const run = { id: '1', url: 'https://github.com/team/repo/actions/runs/1' };
  const pass = () => watchGithub({ configPath, stateDir: folder, kitVersion }, {
    clock: () => now,
    reconcile: () => ({ current: [{ project: 'team/repo', work, status: 'success' }] }),
    actions: {
      pins,
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

test('a failing recheck is retried after a growing delay, then stays failed until it is reset', t => {
  const { folder, configPath } = fixture(t, 'openguildkit-retry-', undefined,
    { maxAttempts: 2, retryDelayMinutes: 1, runTimeoutMinutes: 10 });
  const entry = proofEntry(folder, 'e'.repeat(64));
  const dispatched = [];
  let now = 0;
  const pass = (options = {}) => watchGithub({ configPath, stateDir: folder, kitVersion, ...options }, {
    clock: () => now,
    reconcile: () => ({ current: [entry] }),
    actions: {
      pins,
      dispatch(_entry, _workflow, _attempt, expected) {
        dispatched.push(expected);
        return { id: String(dispatched.length), url: `https://github.com/team/repo/actions/runs/${dispatched.length}` };
      },
      status: () => ({ status: 'completed', conclusion: 'failure' }),
    },
  });
  assert.equal(pass().targets[0].actions.state, 'dispatched');
  assert.deepEqual(dispatched[0], {
    project: 'team/repo', pullRequest: 1, commit: entry.commit, profileCommit: entry.profileCommit,
    profileSha256: entry.profileSha256, policyCommit: entry.policyCommit, rule: entry.rule, kitVersion,
  });
  const retry = pass();
  assert.equal(retry.targets[0].actions.state, 'retry');
  assert.equal(retry.targets[0].actions.nextAttemptAt, 60_000);
  assert.match(retry.errors[0].message, /attempt 1\/2 did not succeed \(failure/);
  now = 59_000;
  assert.equal(pass().targets[0].actions.state, 'retry');
  assert.equal(dispatched.length, 1);
  now = 60_000;
  const second = pass().targets[0].actions;
  assert.equal(second.state, 'dispatched');
  assert.equal(second.attempts, 2);
  const failed = pass();
  assert.equal(failed.targets[0].actions.state, 'failed');
  assert.match(failed.errors[0].message, /2 attempts did not succeed.*--reset e{64}/);
  now = 36_000_000;
  const later = pass();
  assert.equal(later.targets[0].actions.state, 'failed');
  assert.equal(later.errors.length, 1);
  assert.equal(dispatched.length, 2);

  const reset = pass({ reset: [entry.work] });
  assert.deepEqual(reset.resets, [{ work: entry.work, state: 'failed', attempts: 2 }]);
  assert.equal(reset.targets[0].actions.state, 'dispatched');
  assert.equal(reset.targets[0].actions.attempts, 1);
  assert.equal(dispatched.length, 3);
  assert.equal(readdirSync(join(folder, 'actions', 'history')).length, 1);
  assert.match(pass({ reset: ['../escape'] }).errors[0].message, /--reset expects a work ID/);
});

test('a missing proof, a deleted run or a run left in the queue is dispatched again', t => {
  const { folder, configPath } = fixture(t, 'openguildkit-stuck-', undefined,
    { maxAttempts: 4, retryDelayMinutes: 1, runTimeoutMinutes: 10 });
  const entry = proofEntry(folder, 'f'.repeat(64));
  const runs = [];
  const cancelled = [];
  const outcomes = { 1: 'expired', 2: 'deleted', 3: 'queued', 4: 'verified' };
  let now = 0;
  const pass = () => watchGithub({ configPath, stateDir: folder, kitVersion }, {
    clock: () => now,
    reconcile: () => ({ current: [entry] }),
    actions: {
      pins,
      dispatch() {
        runs.push(String(runs.length + 1));
        return { id: runs.at(-1), url: `https://github.com/team/repo/actions/runs/${runs.at(-1)}` };
      },
      status: (_project, id) => ({
        deleted: { status: 'missing' }, queued: { status: 'queued' },
      })[outcomes[id]] ?? { status: 'completed', conclusion: 'success' },
      proof(_project, id) {
        if (outcomes[id] === 'expired') throw new Error('no artifact matches openguildkit-recheck');
        return { work: entry.work, project: entry.project, pullRequest: entry.pullRequest, proof: entry.proof };
      },
      cancel: (_project, id) => cancelled.push(id),
    },
  });
  pass();
  const expired = pass();
  assert.equal(expired.targets[0].actions.previous.reason, 'proof-unavailable');
  assert.match(expired.errors[0].message, /attempt 1\/4/);
  now = 60_000;
  pass();
  assert.equal(pass().targets[0].actions.previous.reason, 'missing');
  now = 180_000;
  pass();
  now = 180_000 + 9 * 60_000;
  assert.equal(pass().targets[0].actions.state, 'dispatched');
  now = 180_000 + 10 * 60_000;
  const timedOut = pass().targets[0].actions;
  assert.equal(timedOut.previous.reason, 'timeout');
  assert.deepEqual(cancelled, ['3']);
  now += 4 * 60_000;
  pass();
  const verified = pass();
  assert.equal(verified.targets[0].actions.state, 'verified');
  assert.deepEqual(verified.errors, []);
  assert.deepEqual(runs, ['1', '2', '3', '4']);
});

test('reset all only clears failed or mismatched work', t => {
  const { folder, configPath } = fixture(t, 'openguildkit-reset-');
  const entry = proofEntry(folder, '9'.repeat(64));
  const pass = options => watchGithub({ configPath, stateDir: folder, kitVersion, ...options }, {
    reconcile: () => ({ current: [entry] }),
    actions: {
      pins,
      dispatch: () => ({ id: '1', url: 'https://github.com/team/repo/actions/runs/1' }),
      status: () => ({ status: 'completed', conclusion: 'success' }),
      proof: () => ({ work: entry.work, project: entry.project, pullRequest: entry.pullRequest,
        proof: { ...entry.proof, state: 'failure' } }),
    },
  });
  pass();
  assert.equal(pass().targets[0].actions.state, 'mismatch');
  assert.equal(pass().targets[0].actions.state, 'mismatch');
  const reset = pass({ reset: ['all'] });
  assert.deepEqual(reset.resets, [{ work: entry.work, state: 'mismatch', attempts: 1 }]);
  assert.equal(reset.targets[0].actions.state, 'dispatched');
  assert.deepEqual(pass({ reset: ['all'] }).resets, []);
});

test('the watcher explains a recheck workflow that would compute another work key', t => {
  const { folder, configPath } = fixture(t, 'openguildkit-pins-');
  const entry = proofEntry(folder, '8'.repeat(64));
  const result = watchGithub({ configPath, stateDir: folder, kitVersion }, {
    reconcile: () => ({ current: [entry] }),
    actions: {
      pins: () => ({
        settings: { policyRepository: 'TEAM/Policies', policyRef: policyRepo.ref, profileRef: 'refs/heads/pilot/recheck-base' },
        kit: `${'a'.repeat(64)}  openguildkit-0.16.0.tgz`,
      }),
      dispatch: () => assert.fail('A recheck with another work key was dispatched'),
    },
  });
  assert.equal(result.targets[0].actions.state, 'error');
  const [error] = result.errors;
  assert.match(error.message, /profileRef "refs\/heads\/pilot\/recheck-base" instead of "refs\/heads\/main"/);
  assert.match(error.message, /recheck-kit\.sha256 "openguildkit-0\.16\.0\.tgz" instead of "openguildkit-0\.16\.1\.tgz"/);
  assert.doesNotMatch(error.message, /policyRepository/);
  assert.equal(existsSync(join(folder, 'actions', `${entry.work}.json`)), false);
});

test('only one watcher works on a state directory at a time', t => {
  const { folder, configPath } = fixture(t, 'openguildkit-lock-');
  const run = () => watchGithub({ configPath, stateDir: folder, kitVersion }, {
    reconcile: () => ({ current: [] }), actions: { pins },
  });
  const release = acquireWatchLock(folder);
  assert.throws(run, /Another watcher is using this state directory/);
  release();
  assert.deepEqual(run().errors, []);
  assert.equal(existsSync(join(folder, 'watch.lock')), false);

  const ended = spawnSync(process.execPath, ['-e', '']);
  writeFileSync(join(folder, 'watch.lock'), JSON.stringify({ pid: ended.pid, host: hostname(), since: 'earlier' }));
  assert.deepEqual(run().errors, []);
  writeFileSync(join(folder, 'watch.lock'), JSON.stringify({ pid: 1, host: 'other-host', since: 'earlier' }));
  assert.throws(run, /process 1 on other-host/);
});

test('a cycle keeps its report when the references cannot be read again before publication', t => {
  const { folder, configPath } = fixture(t, 'openguildkit-resync-',
    { file: 'recheck.yml', ref: 'pilot/base', evidenceBranch: 'reports' });
  const entry = { ...proofEntry(folder, '7'.repeat(64)), decision: { effectiveStatus: 'success' } };
  const result = watchGithub({ configPath, stateDir: folder, kitVersion, publish: true }, {
    reconcile: ({ run }) => {
      if (!run) throw new Error('GitHub API rate limit exceeded');
      return { current: [entry] };
    },
    actions: { pins, dispatch: () => ({ id: '1', url: 'https://github.com/team/repo/actions/runs/1' }) },
    publishReport: () => assert.fail('A report was published without fresh references'),
  });
  assert.equal(result.targets[0].actions.state, 'dispatched');
  assert.deepEqual(result.publications, []);
  assert.match(result.errors[0].message, /Publication skipped.*rate limit/);

  const offline = watchGithub({ configPath, stateDir: folder, kitVersion }, {
    reconcile: () => { throw new Error('GitHub is unreachable'); }, actions: { pins },
  });
  assert.deepEqual(offline.targets, []);
  assert.match(offline.errors[0].message, /unreachable/);
});

test('status deduplication reads every page of the combined status', () => {
  const calls = [];
  const request = (...args) => {
    calls.push(args);
    return JSON.stringify([
      { statuses: Array.from({ length: 100 }, (_, index) => ({ context: `other/${index}`, state: 'success' })) },
      { statuses: [{ context: 'openguildkit/report-pr-3', state: 'error', description: 'old' }] },
    ]);
  };
  const found = latestStatus('team/repo', '1'.repeat(40), 'openguildkit/report-pr-3', request);
  assert.equal(found.description, 'old');
  assert.deepEqual(calls, [['api', '--paginate', '--slurp', `repos/team/repo/commits/${'1'.repeat(40)}/status?per_page=100`]]);
});
