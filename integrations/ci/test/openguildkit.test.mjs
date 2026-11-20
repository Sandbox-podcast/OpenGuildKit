import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { reconcile } from '../lib/reconcile.mjs';
import { sameRepository } from '../lib/github-identifiers.mjs';

const cli = fileURLToPath(new URL('../bin/openguildkit.mjs', import.meta.url));
const agent = fileURLToPath(new URL('../bin/openguildkit-agent.mjs', import.meta.url));

function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'user.name=OpenGuildKit Test',
    '-c', 'user.email=openguildkit@example.invalid', '-c', 'commit.gpgsign=false',
    '-C', cwd, ...args], { encoding: 'utf8' }).trim();
}

function commitJson(repo, file, value) {
  writeFileSync(join(repo, file), JSON.stringify(value));
  git(repo, 'add', '--', file);
  git(repo, 'commit', '-qm', `Update ${file}`);
  return git(repo, 'rev-parse', 'HEAD');
}

test('install a profile and verify the same target commit against two policy revisions', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const policies = join(root, 'policies');
  const target = join(root, 'target');
  mkdirSync(join(policies, 'packs'), { recursive: true });
  mkdirSync(target);
  git(policies, 'init', '-q');
  git(target, 'init', '-q');

  const run = (...args) => spawnSync(process.execPath, [cli, ...args], {
    cwd: target,
    encoding: 'utf8',
    env: { ...process.env, GITHUB_ACTIONS: 'true' },
  });

  const profilePath = join(target, 'openguildkit.json');
  assert.equal(run('init', '--owner', '@equipe').status, 0);
  const profile = readFileSync(profilePath, 'utf8');
  assert.equal(run('init', '--owner', '@autre').status, 2);
  assert.equal(readFileSync(profilePath, 'utf8'), profile);

  const first = commitJson(policies, 'packs/export-link-expiry.json', { id: 'export-link-expiry', version: 1, maxMinutes: 60 });
  const second = commitJson(policies, 'packs/export-link-expiry.json', { id: 'export-link-expiry', version: 2, maxMinutes: 30 });
  const targetSha = commitJson(target, 'export.json', { downloadLinkMinutes: 45 });
  commitJson(target, 'export.json', { downloadLinkMinutes: 20 });

  const output = join(root, 'evidence');
  const check = (ruleSha, ...args) => run('check', '--policy-repo', policies, '--policy-commit',
    ruleSha, '--commit', targetSha, '--output', output, ...args);
  const before = check(first);
  assert.equal(before.status, 0, before.stderr);
  assert.equal(JSON.parse(before.stdout).state, 'success');
  const after = check(second);
  assert.equal(after.status, 0, after.stderr);
  const evidence = JSON.parse(after.stdout);
  assert.equal(evidence.state, 'failure');
  assert.equal(evidence.actualMinutes, 45);
  assert.equal(evidence.commit, targetSha);
  assert.equal(evidence.policyCommit, second);
  assert.equal(evidence.owner, '@equipe');
  assert.equal(evidence.kitVersion, run('--version').stdout.trim());
  assert.deepEqual(JSON.parse(readFileSync(join(output, 'evidence.json'), 'utf8')), evidence);
  assert.equal(readFileSync(join(output, 'AGENTS.md'), 'utf8'), evidence.guidance + '\n');
  assert.equal(check(second, '--enforce').status, 1);
  assert.equal(check(second.slice(0, 7)).status, 2);
});

test('reconcile current PR, policy and profile references without promoting a late result', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-f08-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const folder of ['policy-repo', 'a', 'b']) {
    const repo = join(root, folder);
    mkdirSync(repo);
    git(repo, 'init', '-q', '-b', 'main');
  }
  const policyRepo = join(root, 'policy-repo');
  mkdirSync(join(policyRepo, 'policy'));
  const policyFile = 'policy/export-link.json';
  const policy = { id: 'export-link-expiry', version: 1, maxMinutes: 60 };
  const firstRule = commitJson(policyRepo, policyFile, policy);
  const profile = { schemaVersion: 1, owner: '@pilote', policyPath: policyFile, targetPath: 'export.json' };
  const a = join(root, 'a');
  const b = join(root, 'b');
  for (const [repo, minutes] of [[a, 45], [b, 30]]) {
    commitJson(repo, 'openguildkit.json', profile);
    git(repo, 'switch', '-q', '-c', 'candidate');
    commitJson(repo, 'export.json', { downloadLinkMinutes: minutes });
    git(repo, 'switch', '-q', 'main');
  }

  const config = join(root, 'config.json');
  const state = join(root, 'state');
  writeFileSync(config, JSON.stringify({
    policyRepo: { path: 'policy-repo', ref: 'refs/heads/main' },
    projects: ['a', 'b'].map(id => ({
      id, path: id, profileRef: 'refs/heads/main',
      pullRequests: [{ number: 1, ref: 'refs/heads/candidate' }],
    })),
  }));
  const run = (...args) => spawnSync(process.execPath, [cli, ...args], { cwd: root, encoding: 'utf8' });
  function result(command) {
    assert.equal(command.status, 0, command.stderr);
    return JSON.parse(command.stdout);
  }
  const reconcile = (...args) => result(run('reconcile', '--config', config, '--state', state, ...args));
  const first = reconcile().current;
  assert.deepEqual(first.map(row => row.status), ['pending', 'pending']);

  function evidenceFor(input, repo) {
    return result(run('check', '--policy-repo', policyRepo, '--policy-commit', input.policyCommit,
      '--target-repo', repo, '--profile-commit', input.profileCommit, '--commit', input.commit));
  }
  function record(work, evidence) {
    const file = join(root, 'incoming.json');
    writeFileSync(file, JSON.stringify(evidence));
    return run('record', '--state', state, '--work', work, '--evidence', file);
  }

  const fromOtherCi = evidenceFor(first[1], b);
  const saved = result(record(first[1].work, fromOtherCi));
  assert.equal(saved.recorded, true);
  assert.equal(result(record(first[1].work, fromOtherCi)).recorded, false);
  const resumed = reconcile('--run');
  assert.deepEqual(resumed.executed, [first[0].work]);
  assert.deepEqual(resumed.current.map(row => row.status), ['success', 'success']);

  const secondRule = commitJson(policyRepo, policyFile, { ...policy, version: 2, maxMinutes: 30 });
  const changedRule = reconcile().current;
  assert.deepEqual(changedRule.map(row => row.commit), first.map(row => row.commit));
  assert.deepEqual(changedRule.map(row => row.status), ['pending', 'pending']);
  assert.equal(result(record(first[1].work, fromOtherCi)).recorded, false);
  assert.equal(reconcile().current[1].satisfiesRule, false);
  assert.equal(JSON.parse(readFileSync(saved.path, 'utf8')).evidence.policyCommit, firstRule);

  const evaluated = reconcile('--run').current;
  assert.deepEqual(evaluated.map(row => row.status), ['failure', 'success']);
  assert.equal(evaluated[0].policyCommit, secondRule);
  const oldA = evidenceFor(evaluated[0], a);

  const profileCommit = commitJson(a, 'openguildkit.json', { ...profile, owner: '@mainteneur' });
  const changedProfile = reconcile().current;
  assert.equal(changedProfile[0].profileCommit, profileCommit);
  assert.equal(changedProfile[0].commit, first[0].commit);
  assert.deepEqual(changedProfile.map(row => row.status), ['pending', 'success']);
  assert.equal(record(changedProfile[0].work, oldA).status, 2);
  assert.deepEqual(reconcile('--run').executed, [changedProfile[0].work]);

  git(a, 'switch', '-q', 'candidate');
  const changedCommit = commitJson(a, 'export.json', { downloadLinkMinutes: 30 });
  const updated = reconcile().current[0];
  assert.equal(updated.commit, changedCommit);
  assert.equal(updated.profileCommit, profileCommit);
  assert.equal(updated.status, 'pending');
  const correct = evidenceFor(updated, a);
  assert.equal(result(record(updated.work, correct)).recorded, true);
  assert.equal(reconcile().current[0].satisfiesRule, true);
  assert.equal(result(record(updated.work, { ...correct, state: 'failure' })).recorded, true);
  const disagreement = reconcile().current[0];
  assert.equal(disagreement.status, 'error');
  assert.equal(disagreement.satisfiesRule, false);
});

test('the CI coordinator uses the public catalog pack with its original Git commit', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-catalog-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const policy = join(root, 'central');
  const target = join(root, 'target');
  mkdirSync(join(policy, 'packs'), { recursive: true });
  mkdirSync(target);
  git(policy, 'init', '-q', '-b', 'main');
  git(target, 'init', '-q', '-b', 'main');
  const policyPath = 'packs/export-link-expiry.json';
  const example = new URL('../../../examples/export-expiry/policy/', import.meta.url);
  const pack = JSON.parse(readFileSync(new URL(policyPath, example)));
  const initial = commitJson(policy, policyPath, pack);
  mkdirSync(join(policy, 'policy'));
  const catalogCommit = commitJson(policy, 'policy/catalog.json',
    JSON.parse(readFileSync(new URL('policy/catalog.json', example))));
  const catalog = spawnSync(process.execPath, [
    cli, 'catalog', '--policy-repo', policy, '--policy-commit', catalogCommit,
  ], { encoding: 'utf8' });
  assert.equal(catalog.status, 0, catalog.stderr);
  assert.equal(JSON.parse(catalog.stdout).rules[0].version, '1.0.0');

  commitJson(target, 'openguildkit.json', {
    schemaVersion: 1, owner: '@platform', policyPath, targetPath: 'export.json',
  });
  const head = commitJson(target, 'export.json', { downloadLinkMinutes: 45 });
  const config = join(root, 'config.json');
  writeFileSync(config, JSON.stringify({
    policyRepo: { path: policy, ref: 'refs/heads/main' },
    projects: [{
      id: 'demo', path: target, profileRef: 'refs/heads/main',
      pullRequests: [{ number: 1, ref: 'refs/heads/main', sha: head }],
    }],
  }));
  const run = () => reconcile({ configPath: config, stateDir: join(root, 'state'), run: true, kitVersion: '0.16.0' });
  const before = run().current[0];
  assert.equal(before.status, 'success');
  assert.equal(before.policyCommit, initial);
  pack.version = '2.0.0';
  pack.rules[0].check.max_minutes = 30;
  const updated = commitJson(policy, policyPath, pack);
  const after = run().current[0];
  assert.equal(after.commit, head);
  assert.equal(after.status, 'failure');
  assert.equal(after.policyCommit, updated);
  const report = JSON.parse(readFileSync(after.evidence[0])).evidence;
  assert.equal(report.guidance, 'Limit downloadLinkMinutes in export.json to 30 minutes.');
  assert.equal(report.version, '2.0.0');
  assert.equal(JSON.parse(readFileSync(before.evidence[0])).evidence.state, 'success');
});

test('keep the executed proof when the active policy changes and skip sync when no check is pending', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-live-policy-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  git(root, 'init', '-q', '-b', 'main');
  mkdirSync(join(root, 'policy'));
  const policyPath = 'policy/export-link.json';
  const rule = { id: 'export-link-expiry', version: 1, maxMinutes: 60 };
  const before = commitJson(root, policyPath, rule);
  commitJson(root, 'openguildkit.json', {
    schemaVersion: 1, owner: '@platform', policyPath, targetPath: 'export.json',
    adoption: { state: 'approved', approver: '@platform', mode: 'required', inventoryCommit: before, catalogCommit: before },
  });
  git(root, 'switch', '-q', '-c', 'candidate');
  const head = commitJson(root, 'export.json', { downloadLinkMinutes: 45 });
  git(root, 'switch', '-q', 'main');
  const config = {
    policyRepo: { path: '.', ref: 'refs/heads/main' },
    projects: [{
      id: 'demo', path: '.', profileRef: 'refs/heads/main',
      pullRequests: [{ number: 1, ref: 'refs/heads/candidate', sha: head }],
    }],
  };
  const options = { configPath: join(root, 'config.json'), stateDir: join(root, 'state'), run: true, kitVersion: '0.16.0' };
  let reads = 0;
  let after;
  const drift = reconcile({ ...options, loadConfig() {
    reads += 1;
    if (reads === 2) after = commitJson(root, policyPath, { ...rule, version: 2, maxMinutes: 30 });
    return config;
  } });
  assert.equal(reads, 2);
  assert.equal(drift.current[0].policyCommit, after);
  assert.equal(drift.current[0].status, 'pending');
  assert.equal(drift.current[0].decision.conditionMet, false);
  assert.equal(drift.executedEvidence[0].work, drift.executed[0]);
  const historic = JSON.parse(readFileSync(drift.executedEvidence[0].path)).evidence;
  assert.equal(historic.policyCommit, before);
  assert.equal(historic.state, 'success');

  const loadConfig = () => { reads += 1; return config; };
  assert.equal(reconcile({ ...options, loadConfig }).current[0].status, 'failure');
  reads = 0;
  const stable = reconcile({ ...options, loadConfig });
  assert.equal(reads, 1);
  assert.equal(stable.current[0].status, 'failure');
  assert.deepEqual(stable.executedEvidence, []);

  commitJson(root, policyPath, { ...rule, version: 3, maxMinutes: 25 });
  reads = 0;
  const closed = reconcile({
    ...options,
    selection: { project: 'demo', pullRequest: 1, commit: head, mode: 'required' },
    loadConfig: () => ++reads === 1 ? config : { ...config, projects: [] },
  });
  assert.deepEqual(closed.current, []);
  assert.match(closed.errors[0].message, /références courantes/);
  assert.equal(JSON.parse(readFileSync(closed.executedEvidence[0].path)).evidence.state, 'failure');
});

test('prepare a questionnaire from committed files and activate only a reviewed profile', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-onboard-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  git(root, 'init', '-q', '-b', 'main');
  mkdirSync(join(root, 'policy'));
  mkdirSync(join(root, '.github/workflows'), { recursive: true });
  commitJson(root, 'package.json', { scripts: { test: 'should-never-run' } });
  commitJson(root, '.github/workflows/demo.yml', {});
  const candidate = commitJson(root, 'export.json', { downloadLinkMinutes: 45 });
  commitJson(root, 'policy/export-link.json', { id: 'export-link-expiry', version: 1, maxMinutes: 30 });
  const catalog = JSON.parse(readFileSync(new URL('../pilot/catalog.example.json', import.meta.url), 'utf8'));
  const catalogSha = commitJson(root, 'policy/catalog.json', catalog);
  writeFileSync(join(root, 'Jenkinsfile'), 'untracked');
  const run = (...args) => spawnSync(process.execPath, [cli, ...args], { cwd: root, encoding: 'utf8' });
  function read(result) {
    assert.equal(result.status, 0, result.stderr);
    return JSON.parse(result.stdout);
  }

  const source = ['--policy-repo', '.', '--policy-commit', catalogSha];
  const uninspected = read(run('onboard', ...source));
  assert.equal(uninspected.answers.stack, null);
  assert.equal(uninspected.inspection, 'revision-only');
  const form = read(run('onboard', ...source, '--inspect'));
  assert.deepEqual(form.answers.stack, ['Node.js']);
  assert.deepEqual(form.answers.tools, ['GitHub Actions']);
  assert.deepEqual(form.answers.testCommands, ['npm test']);
  assert.equal(form.answers.ruleId, 'export-link-expiry');
  assert.equal(form.answers.owner, null);
  assert.ok(form.toConfirm.includes('tools'));
  assert.equal(read(run('catalog', ...source)).rules[0].version, 1);

  const questionnairePath = join(root, 'answers.json');
  writeFileSync(questionnairePath, JSON.stringify(form));
  assert.equal(run('onboard', ...source, '--answers', 'answers.json').status, 2);
  Object.assign(form.answers, {
    project: 'equipe/portail', owner: '@mainteneur', environments: ['test'], conventions: [],
    sensitivePaths: ['export.json'], ticketTracker: 'GitHub Issues', dataAccess: ['fichiers versionnés'],
    aiModels: [], executionBudget: '5 minutes', requiredApprovals: ['mainteneur'], references: ['convention export'],
  });
  writeFileSync(questionnairePath, JSON.stringify(form));
  assert.equal(run('onboard', ...source, '--answers', 'answers.json').status, 0);
  const profilePath = join(root, 'openguildkit.json');
  const proposed = JSON.parse(readFileSync(profilePath, 'utf8'));
  assert.equal(proposed.adoption.state, 'proposed');
  assert.equal(proposed.adoption.catalogCommit, catalogSha);
  const proposedSha = commitJson(root, 'openguildkit.json', proposed);
  const check = sha => run('check', ...source, '--profile-commit', sha, '--commit', candidate);
  assert.equal(check(proposedSha).status, 2);
  proposed.adoption.state = 'approved';
  proposed.adoption.approver = '@inconnu';
  assert.equal(check(commitJson(root, 'openguildkit.json', proposed)).status, 2);
  proposed.adoption.approver = proposed.owner;
  const approved = commitJson(root, 'openguildkit.json', proposed);
  assert.equal(read(check(approved)).state, 'failure');
  assert.equal(read(check(approved)).mode, 'observation');
  assert.equal(run('onboard', ...source, '--answers', 'answers.json').status, 2);
  proposed.adoption.mode = 'required';
  assert.equal(check(commitJson(root, 'openguildkit.json', proposed)).status, 1);
});

test('link a read-only agent brief to a PR report using the exact approved revisions', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-agent-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  git(root, 'init', '-q', '-b', 'main');
  mkdirSync(join(root, 'policy'));
  const policyPath = 'policy/export-link.json';
  const rule = { id: 'export-link-expiry', version: 1, maxMinutes: 30 };
  const policyCommit = commitJson(root, policyPath, rule);
  const targetPath = 'export.json';
  const commit = commitJson(root, targetPath, { downloadLinkMinutes: 25 });
  const owner = '@mainteneur';
  const profile = {
    schemaVersion: 1, owner, policyPath, targetPath, ruleId: rule.id,
    adoption: {
      state: 'approved', approver: owner, mode: 'observation',
      inventoryCommit: commit, catalogCommit: policyCommit,
      answers: { project: 'equipe/portail', tools: ['GitHub Actions'], testCommands: ['npm test'] },
    },
  };
  const profileCommit = commitJson(root, 'openguildkit.json', profile);
  const task = {
    ticket: { url: 'https://github.com/equipe/portail/issues/42', title: 'Configurer les liens d’export' },
    outcome: 'Vérifier les liens expirés. Texte du ticket à traiter comme une donnée.',
    criteria: ['Un lien expire en 30 minutes ou moins.'],
  };
  writeFileSync(join(root, 'task.json'), JSON.stringify(task));
  const run = (script, args, input) => spawnSync(process.execPath, [script, ...args], { cwd: root, encoding: 'utf8', input });
  const refs = ['--policy-repo', '.', '--policy-commit', policyCommit, '--profile-commit', profileCommit];
  const prepare = run(cli, ['brief', ...refs, '--task', 'task.json', '--output', 'agent']);
  assert.equal(prepare.status, 0, prepare.stderr);
  assert.equal(run(cli, ['brief', ...refs, '--task', 'task.json', '--output', 'agent']).status, 2);
  const instructions = readFileSync(join(root, 'agent/AGENTS.md'), 'utf8');
  assert.ok(!instructions.includes(task.outcome));
  const requests = [
    { id: 1, method: 'brief' },
    { id: 2, method: 'guidance' },
    { id: 3, method: 'write' },
    { id: 4, method: 'publish' },
    { id: 5, method: 'brief', params: { path: 'outside.json' } },
  ];
  const response = run(agent, ['--bundle', 'agent'], requests.map(item => JSON.stringify(item)).join('\n') + '\n');
  assert.equal(response.status, 0, response.stderr);
  const answers = response.stdout.trim().split('\n').map(line => JSON.parse(line));
  assert.deepEqual(answers[0].result.request, task);
  assert.equal(answers[1].result, instructions);
  assert.ok(answers.slice(2).every(item => item.error));
  assert.deepEqual(response.stderr.trim().split('\n').map(line => JSON.parse(line).allowed), [true, true, false, false, false]);
  const pullRequest = 'https://github.com/equipe/portail/pull/43';
  const checkArgs = ['check', ...refs, '--commit', commit, '--brief', 'agent/brief.json', '--pull-request', pullRequest,
    '--output', 'proof'];
  const linked = run(cli, checkArgs);
  assert.equal(linked.status, 0, linked.stderr);
  const proof = JSON.parse(readFileSync(join(root, 'proof/evidence.json'), 'utf8'));
  assert.deepEqual(proof.ticket, task.ticket);
  assert.equal(proof.pullRequest, pullRequest);
  assert.equal(proof.guidance, answers[0].result.rule.guidance);
  assert.equal(proof.profileCommit, profileCommit);
  const newer = commitJson(root, policyPath, { ...rule, version: 2 });
  const stale = checkArgs.map(arg => arg === policyCommit ? newer : arg);
  assert.equal(run(cli, stale).status, 2);
});

test('gate applies an authorized waiver only during its scope and validity', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-waiver-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  git(root, 'init', '-q', '-b', 'main');
  mkdirSync(join(root, 'policy'));
  const owner = '@mainteneur';
  const project = 'equipe/portail';
  const rule = 'export-link-expiry';
  const policyPath = 'policy/export-link.json';
  const policyCommit = commitJson(root, policyPath, { id: rule, version: 1, maxMinutes: 30 });
  const profileCommit = commitJson(root, 'openguildkit.json', {
    schemaVersion: 1, owner, policyPath, targetPath: 'export.json', ruleId: rule,
    adoption: { state: 'approved', approver: owner, mode: 'required', inventoryCommit: policyCommit, catalogCommit: policyCommit },
  });
  git(root, 'switch', '-q', '-c', 'candidate');
  const commit = commitJson(root, 'export.json', { downloadLinkMinutes: 45 });
  git(root, 'switch', '-q', 'main');

  const waiverPath = 'policy/waivers.json';
  const config = join(root, 'integration.json');
  const state = join(root, 'state');
  const entry = {
    id: 'migration', project, pullRequest: 7, commit, profileCommit, policyCommit, rule,
    approver: '@securite', reason: 'Migration du client en cours',
    approvedAt: '2020-01-01T00:00:00Z', expiresAt: '2090-01-01T00:00:00Z',
  };
  const save = waivers => commitJson(root, waiverPath, { schemaVersion: 1, waivers });
  save([]);
  writeFileSync(config, JSON.stringify({
    policyRepo: { path: '.', ref: 'refs/heads/main', waiversPath: waiverPath },
    projects: [{ id: project, path: '.', profileRef: 'refs/heads/main', waiverApprovers: ['@securite'],
      pullRequests: [{ number: 7, ref: 'refs/heads/candidate' }] }],
  }));

  const run = (...args) => spawnSync(process.execPath, [cli, ...args], { cwd: root, encoding: 'utf8' });
  const gate = (...extra) => run('gate', '--config', config, '--state', state,
    '--project', project, '--pr', '7', '--commit', commit, ...extra);
  assert.equal(gate().status, 1);
  const blocked = gate('--run');
  assert.equal(blocked.status, 1, blocked.stderr);
  assert.equal(JSON.parse(blocked.stdout).current.status, 'failure');
  save([{ ...entry, approver: '@inconnu' }]);
  assert.equal(gate().status, 1);
  save([{ ...entry, profileCommit: policyCommit }]);
  assert.equal(gate().status, 1);
  const registryCommit = save([entry]);
  const waived = gate();
  assert.equal(waived.status, 0, waived.stderr);
  const current = JSON.parse(waived.stdout).current;
  assert.equal(current.status, 'failure');
  assert.equal(current.decision.effectiveStatus, 'waived');
  assert.equal(current.decision.waiver.registryCommit, registryCommit);
  assert.equal(JSON.parse(readFileSync(current.decisionPath, 'utf8')).decision.waiver.reason, entry.reason);
  const kitVersion = run('--version').stdout.trim();
  const atExpiry = reconcile({ configPath: config, stateDir: state, kitVersion,
    clock: () => Date.parse(entry.expiresAt) }).current[0];
  assert.equal(atExpiry.status, 'failure');
  assert.equal(atExpiry.decision.conditionMet, false);
  assert.equal(atExpiry.decision.waiver, null);
  assert.equal(JSON.parse(readFileSync(current.decisionPath, 'utf8')).decision.effectiveStatus, 'waived');
  save([{ ...entry, project: 'EQUIPE/Portail' }]);
  assert.equal(gate().status, 1);
  const github = reconcile({
    configPath: config, stateDir: state, kitVersion, sameProject: sameRepository,
    selection: { project: 'Equipe/PORTAIL', pullRequest: 7, commit, mode: 'required' },
  }).current[0];
  assert.equal(github.decision.effectiveStatus, 'waived');
  save([{ ...entry, project: 'EQUIPE/Autre' }]);
  assert.equal(reconcile({
    configPath: config, stateDir: state, kitVersion, sameProject: sameRepository,
  }).current[0].decision.effectiveStatus, 'failure');
  save([entry, { ...entry, id: 'overlap' }]);
  assert.equal(gate().status, 2);

  git(root, 'switch', '-q', 'candidate');
  const fixed = commitJson(root, 'export.json', { downloadLinkMinutes: 30 });
  assert.equal(gate().status, 2);
  const corrected = run('gate', '--config', config, '--state', state, '--project', project, '--pr', '7',
    '--commit', fixed, '--run');
  assert.equal(corrected.status, 0, corrected.stderr);
  assert.equal(JSON.parse(corrected.stdout).current.decision.effectiveStatus, 'success');
});
