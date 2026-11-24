#!/usr/bin/env node
// Replays the coordinator resume checks of issue #261 against a built Node archive and a local GitHub stand-in.
// Usage: node rehearse.mjs --archive openguildkit-X.Y.Z.tgz --work EMPTY_DIR
// It writes WORK/timeline.json and WORK/github-calls.jsonl and prints the timeline. Exit code 1 when an expectation fails.
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ options: { archive: { type: 'string' }, work: { type: 'string' } } });
if (!values.archive || !values.work) throw new Error('Usage: rehearse.mjs --archive FILE.tgz --work EMPTY_DIR');
const archive = resolve(values.archive);
const work = resolve(values.work);
if (existsSync(work) && readdirSync(work).length) throw new Error(`${work} must be empty.`);
mkdirSync(work, { recursive: true });
const fakeGh = new URL('./fake-gh.mjs', import.meta.url).pathname;
const asset = basename(archive);
const digest = createHash('sha256').update(readFileSync(archive)).digest('hex');
const kit = join(work, 'kit');
mkdirSync(kit);
execFileSync('tar', ['-xzf', archive, '-C', kit]);
const cli = join(kit, 'package', 'bin', 'openguildkit.mjs');
const version = execFileSync(process.execPath, [cli, '--version'], { encoding: 'utf8' }).trim();

const timeline = [];
const note = (scenario, event, details = {}) => {
  const entry = { at: new Date().toISOString(), scenario, event, ...details };
  timeline.push(entry);
  console.log(JSON.stringify(entry));
  return entry;
};
const short = sha => sha?.slice(0, 12);
// Fixed author and dates so that every rehearsal produces the same Git SHAs for the same archive.
let tick = 0;
const gitEnv = () => {
  const date = `2026-11-24T08:${String(tick++).padStart(2, '0')}:00Z`;
  return { ...process.env, GIT_AUTHOR_NAME: 'pilot', GIT_AUTHOR_EMAIL: 'pilot@example.invalid',
    GIT_COMMITTER_NAME: 'pilot', GIT_COMMITTER_EMAIL: 'pilot@example.invalid',
    GIT_AUTHOR_DATE: date, GIT_COMMITTER_DATE: date, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null' };
};
const git = (repo, ...args) => execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', env: gitEnv() }).trim();
const json = value => JSON.stringify(value, null, 2) + '\n';

function commit(repo, files, message) {
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(join(repo, path, '..'), { recursive: true });
    writeFileSync(join(repo, path), typeof content === 'string' ? content : json(content));
    git(repo, 'add', path);
  }
  git(repo, 'commit', '--quiet', '-m', message);
  return git(repo, 'rev-parse', 'HEAD');
}

const pack = maxMinutes => ({
  id: 'export-link-expiry', title: 'Download link expiry', version: '1.0.0', sources: [],
  rules: [{ id: 'export-link-expiry', check: { kind: 'field', path: 'export.json', field: 'downloadLinkMinutes',
    integer: true, min: 1, max: maxMinutes } }],
});

// One GitHub stand-in, one set of repositories and one Jenkins state directory per scenario.
function environment(name, projects) {
  const dir = join(work, name);
  const github = join(dir, 'github');
  const authoring = join(dir, 'authoring');
  const jenkins = join(dir, 'jenkins');
  mkdirSync(join(github, 'releases'), { recursive: true });
  copyFileSync(archive, join(github, 'releases', asset));
  const bin = join(dir, 'bin');
  mkdirSync(bin);
  writeFileSync(join(bin, 'gh'), `#!/bin/sh\nexec "${process.execPath}" "${fakeGh}" "$@"\n`, { mode: 0o755 });
  const gitconfig = join(dir, 'gitconfig');
  const bareOf = id => join(github, `${id}.git`);
  const ids = ['team/policies', ...Object.keys(projects)];
  writeFileSync(gitconfig, ids.map(id => `[url "${bareOf(id)}"]\n\tinsteadOf = https://github.com/${id}.git\n`).join(''));
  const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, FAKE_GH_ROOT: github,
    GIT_CONFIG_GLOBAL: gitconfig, GIT_CONFIG_NOSYSTEM: '1' };
  const refs = { pulls: {} };

  const create = id => {
    const repo = join(authoring, id);
    mkdirSync(repo, { recursive: true });
    git(repo, 'init', '--quiet', '-b', 'main');
    execFileSync('git', ['init', '--quiet', '--bare', '-b', 'main', bareOf(id)], { env: gitEnv() });
    return repo;
  };
  const policy = create('team/policies');
  refs.policy = commit(policy, { 'packs/export-link-expiry.json': pack(60) }, 'Export links expire after 60 minutes');
  git(policy, 'push', '--quiet', bareOf('team/policies'), 'main');
  for (const [id, prs] of Object.entries(projects)) {
    const repo = create(id);
    refs[id] = commit(repo, {
      'openguildkit.json': { schemaVersion: 1, owner: '@platform', ruleId: 'export-link-expiry',
        policyPath: 'packs/export-link-expiry.json', targetPath: 'export.json' },
      'export.json': { downloadLinkMinutes: 60 },
    }, 'Profile and export');
    git(repo, 'push', '--quiet', bareOf(id), 'main');
    git(repo, 'checkout', '--quiet', '-b', 'pilot/recheck-base');
    commit(repo, {
      'pilot/recheck.json': { policyRepository: 'team/policies', policyRef: 'refs/heads/main', profileRef: 'refs/heads/main' },
      'pilot/recheck-kit.sha256': `${digest}  ${asset}\n`,
    }, 'Recheck pins');
    git(repo, 'push', '--quiet', bareOf(id), 'pilot/recheck-base');
    for (const [number, minutes] of Object.entries(prs)) {
      git(repo, 'checkout', '--quiet', '-B', `pr-${number}`, 'main');
      const sha = commit(repo, { 'export.json': { downloadLinkMinutes: minutes } }, `Export link of ${minutes} minutes`);
      git(repo, 'push', '--quiet', bareOf(id), `HEAD:refs/pull/${number}/head`);
      refs.pulls[`${id}#${number}`] = sha;
    }
  }
  // The Jenkins agent's full clones and configuration.
  mkdirSync(jenkins);
  const clone = id => execFileSync('git', ['clone', '--quiet', bareOf(id), join(jenkins, id.split('/')[1])], { env: gitEnv() });
  ids.forEach(clone);
  const configPath = join(jenkins, 'integration.json');
  writeFileSync(configPath, json({
    policyRepo: { id: 'team/policies', path: './policies', ref: 'refs/heads/main' },
    projects: Object.entries(projects).map(([id, prs]) => ({
      id, path: `./${id.split('/')[1]}`, profileRef: 'refs/heads/main', prNumbers: Object.keys(prs).map(Number),
      workflow: { file: 'openguildkit.yml', ref: 'pilot/recheck-base' },
    })),
  }));
  const stateDir = join(jenkins, 'state');
  const control = changes => {
    const path = join(github, 'state.json');
    const current = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8'))
      : { nextRun: 101, runs: {}, killAfterDispatch: [], hold: true, startOnRelease: false, artifactFrom: {} };
    writeFileSync(path, json({ ...current, ...changes }));
  };
  const stub = () => JSON.parse(readFileSync(join(github, 'state.json'), 'utf8'));
  const release = (...ids) => execFileSync(process.execPath, [fakeGh, '__release', ...ids.map(String)], { env });
  const watch = (label, ...extra) => {
    const child = spawnSync(process.execPath, [cli, 'watch', '--config', configPath, '--state', stateDir, ...extra],
      { env, encoding: 'utf8', timeout: 120_000 });
    let report = null;
    try {
      report = JSON.parse(child.stdout);
    } catch {
      // A killed watcher prints nothing.
    }
    const targets = (report?.targets ?? []).map(row => ({
      check: `${row.project}#${row.pullRequest}`, work: short(row.work), commit: short(row.commit),
      policyCommit: short(row.policyCommit), local: row.status, actions: row.actions?.state,
      run: row.actions?.id ?? null, attempt: row.actions?.attempt, recovered: row.actions?.recovered,
      proofPolicy: short(row.actions?.proof?.proof?.policyCommit), proofCommit: short(row.actions?.proof?.proof?.commit),
    }));
    note(name, `watch ${label}`, { exit: child.status, signal: child.signal, targets,
      errors: (report?.errors ?? []).map(error => error.message) });
    return { child, report, targets };
  };
  const records = () => Object.fromEntries(readdirSync(join(stateDir, 'actions'))
    .filter(file => file.endsWith('.json'))
    .map(file => [file.slice(0, 12), JSON.parse(readFileSync(join(stateDir, 'actions', file), 'utf8'))]));
  const runs = () => Object.values(stub().runs).map(run => ({
    run: run.id, work: short(run.inputs.work), attempt: run.inputs.attempt, commit: short(run.inputs.commit),
    policyAtStart: short(run.policyTip), conclusion: run.conclusion, error: run.error,
  }));
  const push = (id, files, message, ref) => {
    const repo = join(authoring, id);
    git(repo, 'checkout', '--quiet', ref.startsWith('refs/pull/') ? `pr-${ref.split('/')[2]}` : 'main');
    const sha = commit(repo, files, message);
    git(repo, 'push', '--quiet', bareOf(id), `HEAD:${ref}`);
    return sha;
  };
  return { refs, control, stub, release, watch, records, runs, push, stateDir };
}

function scenarioOne() {
  const s = environment('s1-interruption', { 'team/portal': { 1: 45, 2: 30 }, 'team/service': { 1: 20 } });
  note('s1-interruption', 'references', { policy: s.refs.policy, profiles: { portal: s.refs['team/portal'],
    service: s.refs['team/service'] }, pulls: s.refs.pulls });
  // The stand-in kills the watcher right after GitHub accepted the second dispatch of the batch.
  s.control({ killAfterDispatch: [2] });
  const first = s.watch('1 (killed after the 2nd accepted dispatch)');
  assert.equal(first.child.signal, 'SIGKILL');
  assert.equal(existsSync(join(s.stateDir, 'watch.lock')), true);
  const atKill = s.records();
  note('s1-interruption', 'state after the interruption', { records: Object.fromEntries(Object.entries(atKill)
    .map(([key, run]) => [key, { state: run.state, id: run.id ?? null, attempt: run.attempt }])),
  lock: 'watch.lock left by the killed process', localEvidence: readdirSync(join(s.stateDir, 'evidence')).length,
  runs: s.runs() });
  const states = Object.values(atKill).map(run => run.state).sort();
  assert.deepEqual(states, ['dispatched', 'requesting']);
  const pending = Object.values(atKill).find(run => run.state === 'requesting');
  const accepted = s.runs().find(run => run.attempt === pending.attempt);
  assert.equal(accepted.run, 102);

  const second = s.watch('2 (restart on the same state)');
  assert.equal(second.child.status, 0);
  const byCheck = Object.fromEntries(second.targets.map(row => [row.check, row]));
  assert.equal(byCheck['team/portal#2'].run, '102');
  assert.equal(byCheck['team/portal#2'].recovered, true);
  assert.equal(byCheck['team/portal#2'].attempt, pending.attempt);
  assert.equal(byCheck['team/portal#1'].run, '101');
  assert.equal(byCheck['team/service#1'].run, '103');
  assert.equal(s.runs().length, 3);

  s.release(101, 102, 103);
  const third = s.watch('3 (runs completed)');
  assert.deepEqual(third.targets.map(row => row.actions), ['verified', 'verified', 'verified']);
  const fourth = s.watch('4 (idle cycle)');
  assert.deepEqual(fourth.targets.map(row => row.actions), ['verified', 'verified', 'verified']);
  const runs = s.runs();
  assert.equal(runs.length, 3);
  assert.equal(new Set(runs.map(run => run.work)).size, 3);
  const evidence = readdirSync(join(s.stateDir, 'evidence'));
  assert.equal(evidence.length, 3);
  for (const key of evidence) assert.equal(readdirSync(join(s.stateDir, 'evidence', key)).length, 1);
  note('s1-interruption', 'result', { runs, localEvidence: evidence.length,
    lockAfterRestart: existsSync(join(s.stateDir, 'watch.lock')) });
}

function scenarioTwo() {
  const name = 's2-active-references';
  const s = environment(name, { 'team/portal': { 1: 45 } });
  const p1 = s.refs.policy;
  const c1 = s.refs.pulls['team/portal#1'];
  note(name, 'references', { policy: p1, profile: s.refs['team/portal'], pr: c1 });

  // A. The rule changes while the run for the previous rule is in progress.
  const a1 = s.watch('A1 (rule 60 min)');
  assert.equal(a1.targets[0].run, '101');
  const p2 = s.push('team/policies', { 'packs/export-link-expiry.json': pack(30) }, 'Export links expire after 30 minutes',
    'refs/heads/main');
  note(name, 'rule changed during run 101', { policy: p2 });
  const a2 = s.watch('A2 (rule 30 min)');
  assert.equal(a2.targets.length, 1);
  assert.equal(a2.targets[0].policyCommit, short(p2));
  assert.equal(a2.targets[0].local, 'failure');
  assert.equal(a2.targets[0].run, '102');
  // The local proof of the previous rule is still on disk, under its own work key, and is not reused.
  const kept = Object.fromEntries(readdirSync(join(s.stateDir, 'evidence'))
    .map(key => [key.slice(0, 12), readdirSync(join(s.stateDir, 'evidence', key))]));
  assert.deepEqual(kept[a1.targets[0].work], ['success.json']);
  assert.deepEqual(kept[a2.targets[0].work], ['failure.json']);
  note(name, 'local evidence after the rule change', { evidence: kept, current: a2.targets[0].work });
  s.release(101);
  const a3 = s.watch('A3 (run 101 for the old rule completed)');
  assert.equal(a3.targets.length, 1);
  assert.equal(a3.targets[0].actions, 'dispatched');
  assert.equal(a3.targets[0].run, '102');
  s.release(102);
  const a4 = s.watch('A4 (run 102 completed)');
  assert.equal(a4.targets[0].actions, 'verified');
  assert.equal(a4.targets[0].proofPolicy, short(p2));
  const old = s.records()[short(a1.targets[0].work)];
  assert.equal(old.state, 'dispatched');
  note(name, 'record of the old rule', { work: a1.targets[0].work, state: old.state, run: old.id,
    note: 'kept as history, no longer followed or compared' });

  // B. The PR commit changes, and the run serves an artifact computed on the previous commit.
  const c2 = s.push('team/portal', { 'export.json': { downloadLinkMinutes: 30 } }, 'Export link of 30 minutes',
    'refs/pull/1/head');
  note(name, 'PR commit changed', { pr: c2 });
  s.control({ artifactFrom: { 103: 102 } });
  const b1 = s.watch('B1 (new PR commit)');
  assert.equal(b1.targets[0].commit, short(c2));
  assert.equal(b1.targets[0].run, '103');
  s.release(103);
  const b2 = s.watch('B2 (run 103 serves the proof of the previous commit)');
  assert.equal(b2.targets[0].actions, 'mismatch');
  assert.equal(b2.targets[0].proofCommit, short(c1));
  assert.equal(b2.child.status, 2);
  s.control({ artifactFrom: {} });
  const fullWork = b2.report.targets[0].work;
  const b3 = s.watch('B3 (operator reset)', '--reset', fullWork);
  assert.equal(b3.targets[0].run, '104');
  s.release(104);
  const b4 = s.watch('B4 (run 104 completed)');
  assert.equal(b4.targets[0].actions, 'verified');
  assert.equal(b4.targets[0].proofCommit, short(c2));
  assert.equal(b4.targets[0].local, 'success');

  // C. The rule changes after the dispatch but before the run reads it.
  s.control({ startOnRelease: true });
  const p3 = s.push('team/policies', { 'packs/export-link-expiry.json': pack(20) }, 'Export links expire after 20 minutes',
    'refs/heads/main');
  const c1w = s.watch('C1 (rule 20 min)');
  assert.equal(c1w.targets[0].policyCommit, short(p3));
  assert.equal(c1w.targets[0].run, '105');
  const p4 = s.push('team/policies', { 'packs/export-link-expiry.json': pack(45) }, 'Export links expire after 45 minutes',
    'refs/heads/main');
  note(name, 'rule changed before run 105 started', { policy: p4 });
  const c2w = s.watch('C2 (rule 45 min)');
  assert.equal(c2w.targets[0].run, '106');
  s.release(105, 106);
  const c3 = s.watch('C3 (runs 105 and 106 completed)');
  assert.equal(c3.targets[0].actions, 'verified');
  assert.equal(c3.targets[0].proofPolicy, short(p4));
  const late = s.runs().find(run => run.run === 105);
  assert.equal(late.conclusion, 'failure');
  assert.match(late.error, /another work key/);
  note(name, 'result', { runs: s.runs(), policies: { p1, p2, p3, p4 }, commits: { c1, c2 } });
}

let failed = null;
note('setup', 'archive', { file: asset, sha256: digest, version, node: process.version,
  git: execFileSync('git', ['--version'], { encoding: 'utf8' }).trim() });
scenarioOne.label = 's1-interruption';
scenarioTwo.label = 's2-active-references';
for (const scenario of [scenarioOne, scenarioTwo]) {
  try {
    scenario();
    note(scenario.label, 'passed');
  } catch (error) {
    failed = error;
    note(scenario.label, 'FAILED', { message: error.message });
  }
}
writeFileSync(join(work, 'timeline.json'), json(timeline));
// The requests the GitHub stand-in received, in order, for both scenarios.
writeFileSync(join(work, 'github-calls.jsonl'), ['s1-interruption', 's2-active-references'].flatMap(name => {
  const path = join(work, name, 'github', 'calls.jsonl');
  return existsSync(path) ? readFileSync(path, 'utf8').split('\n').filter(Boolean)
    .map(line => JSON.stringify({ scenario: name, ...JSON.parse(line) })) : [];
}).join('\n') + '\n');
if (failed) {
  console.error(failed);
  process.exitCode = 1;
}
