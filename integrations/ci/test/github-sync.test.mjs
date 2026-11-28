import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join } from 'node:path';
import { test } from 'node:test';
import { reconcileGithub } from '../lib/github.mjs';
import { publishWatchReport, renderWatchReport, watchReportStatus } from '../lib/github-report.mjs';
import { sha256 } from '../lib/check.mjs';
import { mergeGithub } from '../lib/merge.mjs';
import { reconcile } from '../lib/reconcile.mjs';

function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'user.name=OpenGuildKit Test',
    '-c', 'user.email=openguildkit@example.invalid', '-c', 'commit.gpgsign=false',
    '-C', cwd, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function commitJson(repo, file, value) {
  writeFileSync(join(repo, file), JSON.stringify(value));
  git(repo, 'add', '--', file);
  git(repo, 'commit', '-qm', `Update ${file}`);
  return git(repo, 'rev-parse', 'HEAD');
}

// A GitHub repository with an approved profile, served to the coordinator through local Git and a fake API.
function githubFixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-sync-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const origin = join(root, 'origin');
  mkdirSync(join(origin, 'policy'), { recursive: true });
  mkdirSync(join(origin, '.openguildkit'));
  git(origin, 'init', '-q', '-b', 'main');
  const policyPath = 'policy/export-link.json';
  const policyCommit = commitJson(origin, policyPath, { id: 'export-link-expiry', version: 1, maxMinutes: 30 });
  const proposal = {
    schemaVersion: 1, owner: '@lead', policyPath, targetPath: 'export.json', ruleId: 'export-link-expiry',
    adoption: { state: 'proposed', mode: 'required', inventoryCommit: policyCommit, catalogCommit: policyCommit,
      answers: { project: 'team/repo' } },
  };
  const mergeCommit = commitJson(origin, '.openguildkit/proposal.json', proposal);
  const proposalBytes = readFileSync(join(origin, '.openguildkit/proposal.json'));
  const approved = {
    ...proposal,
    adoption: {
      ...proposal.adoption, state: 'approved', approver: '@lead',
      approval: {
        provider: 'github', repository: 'team/repo', pullRequest: 3, base: 'main', actor: 'lead',
        proposalCommit: mergeCommit, mergeCommit,
        proposalSha256: createHash('sha256').update(proposalBytes).digest('hex'),
      },
    },
  };
  commitJson(origin, 'openguildkit.json', approved);
  const pulls = [];
  const addPull = (number, minutes) => {
    git(origin, 'switch', '-q', '-c', `pr-${number}`, 'main');
    const head = commitJson(origin, 'export.json', { downloadLinkMinutes: minutes });
    git(origin, 'update-ref', `refs/pull/${number}/head`, head);
    git(origin, 'switch', '-q', 'main');
    pulls.push({ number, state: 'open', head: { sha: head }, base: { ref: 'main', repo: { full_name: 'team/repo' } } });
    return head;
  };
  execFileSync('git', ['clone', '-q', origin, join(root, 'clone')]);
  const api = {
    mergedBy: 'lead',
    responses: new Map(),
  };
  const request = (...args) => {
    const endpoint = args.at(-1);
    if (api.responses.has(endpoint)) return JSON.stringify(api.responses.get(endpoint)());
    if (endpoint === 'repos/team/repo/pulls?state=open&base=main&per_page=100') return JSON.stringify([pulls]);
    if (endpoint === 'repos/team/repo/pulls/3') {
      return JSON.stringify({
        merged: true, merged_by: { login: api.mergedBy }, merge_commit_sha: mergeCommit,
        base: { ref: 'main', repo: { full_name: 'team/repo' } }, head: { sha: mergeCommit },
      });
    }
    if (endpoint === 'repos/team/repo/pulls/3/files?per_page=100') {
      return JSON.stringify([[{ filename: '.openguildkit/proposal.json', status: 'added', sha: 'b'.repeat(40) }]]);
    }
    if (endpoint === `repos/team/repo/contents/.openguildkit/proposal.json?ref=${mergeCommit}`) {
      return JSON.stringify({ type: 'file', encoding: 'base64', sha: 'b'.repeat(40), content: proposalBytes.toString('base64') });
    }
    throw new Error(`Unexpected GitHub request: ${args.join(' ')}`);
  };
  const fetchRefs = (repo, _id, refspecs) => git(repo, 'fetch', '--quiet', '--atomic', '--no-tags', origin, ...refspecs);
  const configPath = join(root, 'integration.json');
  const configure = (project, { others = [], policy = {} } = {}) => writeFileSync(configPath, JSON.stringify({
    policyRepo: { id: 'team/policies', path: 'clone', ref: 'refs/heads/main', ...policy },
    projects: [{ id: 'team/repo', path: 'clone', profileRef: 'refs/heads/main', ...project }, ...others],
  }));
  const sync = (options = {}) => reconcileGithub({
    configPath, stateDir: join(root, 'state'), kitVersion: '0.16.1', ...options,
  }, { request, fetchRefs });
  return { root, origin, api, addPull, pulls, configure, sync, request, fetchRefs, configPath, approved };
}

function refused(result, pattern) {
  assert.deepEqual(result.current, []);
  assert.equal(result.errors.length, 1);
  assert.equal(result.errors[0].project, 'team/repo');
  assert.match(result.errors[0].message, pattern);
}

test('the Jenkins coordinator evaluates only the configured open PR numbers', t => {
  const { addPull, configure, sync } = githubFixture(t);
  const target = addPull(7, 45);
  addPull(8, 20);
  configure({ profileMaintainer: 'lead', prNumbers: [7] });

  const result = sync({ run: true });
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.current.map(row => [row.pullRequest, row.commit, row.status]), [[7, target, 'failure']]);
});

test('the GitHub flows accept an adopted profile only after the maintainer approval is verified', t => {
  const { origin, api, addPull, configure, sync, approved } = githubFixture(t);
  addPull(7, 45);
  configure({});
  refused(sync(), /Set profileMaintainer for team\/repo/);

  configure({ profileMaintainer: 'lead' });
  const [current] = sync().current;
  assert.equal(current.mode, 'required');
  assert.equal(current.status, 'pending');

  api.mergedBy = 'someone-else';
  refused(sync(), /merged by the designated maintainer/);
  api.mergedBy = 'lead';

  commitJson(origin, 'openguildkit.json', { ...approved, owner: '@intruder',
    adoption: { ...approved.adoption, approver: '@intruder' } });
  refused(sync(), /differs from the approved proposal/);
});

test('the GitHub flows read a configuration that starts with a byte order mark', t => {
  const { addPull, configure, configPath, sync } = githubFixture(t);
  const target = addPull(7, 45);
  configure({ profileMaintainer: 'lead' });
  writeFileSync(configPath, Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), readFileSync(configPath)]));

  const result = sync({ run: true });
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.current.map(row => [row.pullRequest, row.commit, row.status]), [[7, target, 'failure']]);
});

test('an error limited to one project or one PR is reported without stopping the others', t => {
  const { root, origin, api, addPull, pulls, configure, sync } = githubFixture(t);
  const head = addPull(7, 45);
  const moved = addPull(8, 20);
  pulls.push({ number: 9, state: 'open', head: { sha: 'not-a-commit' }, base: { ref: 'main', repo: { full_name: 'team/repo' } } });
  api.responses.set('repos/team/repo/pulls?state=open&base=main&per_page=100',
    () => [pulls.map(pr => pr.number === 8 ? { ...pr, head: { sha: '0'.repeat(40) } } : pr)]);
  git(origin, 'switch', '-q', '-c', 'broken');
  writeFileSync(join(origin, 'openguildkit.json'),
    '{"schemaVersion": 1, "owner": "@x", "owner": "@y", "policyPath": "policy/export-link.json", "targetPath": "export.json"}');
  git(origin, 'commit', '-qam', 'Duplicate a key');
  git(origin, 'switch', '-q', 'main');
  api.responses.set('repos/team/broken/pulls?state=open&base=broken&per_page=100',
    () => [[{ number: 7, state: 'open', head: { sha: head }, base: { ref: 'broken', repo: { full_name: 'team/broken' } } }]]);
  configure({ profileMaintainer: 'lead' }, { others: [{ id: 'team/broken', path: 'clone', profileRef: 'refs/heads/broken' }] });

  const result = sync({ run: true });
  assert.deepEqual(result.current.map(row => [row.project, row.pullRequest, row.status]), [['team/repo', 7, 'failure']]);
  assert.deepEqual(result.errors.map(error => [error.project, error.pullRequest]),
    [['team/repo', 9], ['team/repo', 8], ['team/broken', undefined]]);
  assert.equal(result.errors[0].message, 'Invalid GitHub PR in team/repo.');
  assert.match(result.errors[1].message, /^PR team\/repo#8 changed during loading\. Run the synchronization again\.$/);
  assert.match(result.errors[2].message, /Duplicate JSON key: owner/);
  assert.throws(() => sync({ selection: { project: 'team/repo', pullRequest: 8, commit: moved, mode: 'required' } }),
    /PR team\/repo#8 changed during loading\. Run the synchronization again\./);

  const local = join(root, 'local.json');
  writeFileSync(local, JSON.stringify({
    policyRepo: { path: 'origin', ref: 'refs/heads/main' },
    projects: [
      { id: 'local/broken', path: 'origin', profileRef: 'refs/heads/broken', pullRequests: [{ number: 1, ref: 'refs/heads/pr-7' }] },
      { id: 'local/plain', path: 'origin', profileRef: 'refs/heads/main', pullRequests: [
        { number: 1, ref: 'refs/heads/pr-7' }, { number: 2, ref: 'refs/heads/missing' }] },
    ],
  }));
  const plain = reconcile({ configPath: local, stateDir: join(root, 'local-state'), kitVersion: '0.16.1' });
  assert.deepEqual(plain.current.map(row => [row.project, row.pullRequest]), [['local/plain', 1]]);
  assert.deepEqual(plain.errors.map(error => [error.project, error.pullRequest]), [['local/broken', undefined], ['local/plain', 2]]);

  writeFileSync(join(origin, 'policy/waivers.json'), JSON.stringify({ schemaVersion: 1, waivers: [{ id: 'incomplete' }] }));
  git(origin, 'add', 'policy/waivers.json');
  git(origin, 'commit', '-qm', 'Add an invalid waiver');
  configure({ profileMaintainer: 'lead' }, { policy: { waiversPath: 'policy/waivers.json' } });
  assert.throws(() => sync(), /Invalid waiver: incomplete/);
});

test('the GitHub synchronization refuses an invalid configuration with an English message', t => {
  const { configure, configPath, sync } = githubFixture(t);
  assert.throws(() => { configure({}, { policy: { ref: 'main' } }); sync(); },
    error => error.message === 'A GitHub repository, a clone path and a trusted branch refs/heads/… are required.');

  configure({ profileMaintainer: 'lead', prNumbers: [0] });
  refused(sync(), /^prNumbers must contain positive PR numbers\.$/);

  writeFileSync(configPath, JSON.stringify({ policyRepo: { id: 'team/policies', path: 'clone', ref: 'refs/heads/main' }, projects: {} }));
  assert.throws(() => sync(), error => error.message === 'projects must be a list.');

  configure({ profileMaintainer: 'lead' });
  for (const options of [{ reportUrl: 'https://example.org/report' }, { publish: true, reportUrl: 'ftp://example.org/report' }]) {
    assert.throws(() => sync(options), error => error.message === '--report-url requires --publish and an HTTP or HTTPS URL.');
  }
});

// What `gh api graphql` answers for the open PRs: the head, the body and the statuses recorded for that head.
function graphqlPulls(pulls, statuses = new Map(), bodies = {}) {
  const nodes = pulls.map(pr => ({
    number: pr.number, state: 'OPEN', headRefOid: pr.head.sha, body: bodies[pr.number] ?? '',
    commits: { nodes: [{ commit: { oid: pr.head.sha, status: { contexts: statuses.get(pr.head.sha) ?? [] } } }] },
  }));
  return JSON.stringify([{ data: { repository: { pullRequests: { pageInfo: { hasNextPage: false, endCursor: null }, nodes } } } }]);
}

// A GitHub that keeps the statuses it is given, counts the requests, and lets a test move the head of a PR.
function recordingApi({ request, pulls }, { moved = {} } = {}) {
  const calls = [];
  const statuses = new Map();
  const writes = [];
  const api = (...args) => {
    calls.push(args);
    if (args[1] === 'graphql') return graphqlPulls(pulls, statuses);
    const write = /^repos\/team\/repo\/statuses\/([0-9a-f]{40})$/.exec(args[1]);
    if (write) {
      const field = name => args.find(arg => arg.startsWith(`${name}=`))?.slice(name.length + 1);
      const context = { context: field('context'), state: field('state').toUpperCase(), description: field('description'), targetUrl: field('target_url') ?? null };
      statuses.set(write[1], [...(statuses.get(write[1]) ?? []).filter(item => item.context !== context.context), context]);
      writes.push(args);
      return '{}';
    }
    const pull = /^repos\/team\/repo\/pulls\/(\d+)$/.exec(args.at(-1));
    if (pull && pull[1] !== '3') {
      const sha = moved[pull[1]] ?? pulls.find(item => item.number === Number(pull[1]))?.head.sha;
      return JSON.stringify({ state: 'open', head: { sha } });
    }
    return request(...args);
  };
  return { api, calls, writes, statuses };
}

test('only the PRs into the profile branch are evaluated, and their statuses are in English', t => {
  const fixture = githubFixture(t);
  const { root, addPull, pulls, configure, fetchRefs, configPath } = fixture;
  const head = addPull(7, 45);
  addPull(8, 20);
  pulls[1] = { ...pulls[1], base: { ...pulls[1].base, ref: 'release/1' } };
  configure({ profileMaintainer: 'lead' });
  const { api, calls, writes } = recordingApi(fixture);
  const result = reconcileGithub({ configPath, stateDir: join(root, 'state'), kitVersion: '0.16.1', run: true, publish: true },
    { request: api, fetchRefs });

  assert.ok(calls.some(args => args.at(-1) === 'repos/team/repo/pulls?state=open&base=main&per_page=100'));
  assert.deepEqual(result.current.map(row => [row.pullRequest, row.status]), [[7, 'failure']]);
  assert.deepEqual(result.errors, []);
  assert.equal(writes.length, 1);
  assert.equal(writes[0][1], `repos/team/repo/statuses/${head}`);
  assert.match(writes[0].find(arg => arg.startsWith('description=')),
    /^description=Deviation \(obs\.\) \| rule [a-f0-9]{12} \| profile [a-f0-9]{12} \| [a-f0-9]{12}$/);
});

test('Issue #531: a cycle with nothing to publish makes the same GitHub requests whatever the number of PRs', t => {
  const cycle = count => {
    const fixture = githubFixture(t);
    for (let index = 0; index < count; index += 1) fixture.addPull(10 + index, 45);
    fixture.configure({ profileMaintainer: 'lead' });
    const { api, calls, writes } = recordingApi(fixture);
    const run = () => reconcileGithub({ configPath: fixture.configPath, stateDir: join(fixture.root, 'state'), kitVersion: '0.16.1',
      run: true, publish: true }, { request: api, fetchRefs: fixture.fetchRefs });
    const first = run();
    assert.equal(first.publications.filter(item => item.posted).length, count);
    assert.equal(writes.length, count);
    const before = calls.length;
    const second = run();
    assert.deepEqual(second.errors, []);
    assert.deepEqual(second.publications.map(item => item.posted), Array(count).fill(false));
    assert.equal(writes.length, count, 'nothing is written again');
    return calls.slice(before);
  };
  const one = cycle(1);
  const five = cycle(5);
  assert.equal(five.length, one.length);
  assert.equal(five.filter(args => args[1] === 'graphql').length, 1);
  assert.ok(five.every(args => !/\/pulls\/\d+$|\/commits\//.test(args.at(-1)) || args.at(-1).endsWith('/pulls/3')),
    'no PR and no status is read one by one');
});

test('Issue #531: the open PRs and their statuses come in one paginated GraphQL query per repository', t => {
  const fixture = githubFixture(t);
  fixture.addPull(7, 45);
  fixture.configure({ profileMaintainer: 'lead' });
  const { api, calls } = recordingApi(fixture);
  reconcileGithub({ configPath: fixture.configPath, stateDir: join(fixture.root, 'state'), kitVersion: '0.16.1', run: true,
    publish: true }, { request: api, fetchRefs: fixture.fetchRefs });
  const graphql = calls.filter(args => args[1] === 'graphql');
  assert.equal(graphql.length, 1);
  const [args] = graphql;
  assert.ok(args.includes('--paginate') && args.includes('--slurp'));
  assert.ok(args.includes('owner=team') && args.includes('name=repo'), 'raw string fields: a name made of digits stays a string');
  const query = args.find(arg => arg.startsWith('query=')).slice('query='.length);
  for (const word of ['$endCursor', 'pageInfo', 'hasNextPage', 'headRefOid', 'states: OPEN', 'contexts', 'targetUrl']) {
    assert.ok(query.includes(word), word);
  }
});

test('Issue #531: a status is never written on a head that moved since the read', t => {
  const fixture = githubFixture(t);
  fixture.addPull(7, 45);
  fixture.configure({ profileMaintainer: 'lead' });
  const { api, writes } = recordingApi(fixture, { moved: { 7: 'f'.repeat(40) } });
  const result = reconcileGithub({ configPath: fixture.configPath, stateDir: join(fixture.root, 'state'), kitVersion: '0.16.1',
    run: true, publish: true }, { request: api, fetchRefs: fixture.fetchRefs });
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.publications.map(item => item.posted), [false]);
  assert.deepEqual(writes, []);
});

test('Issue #531: when the open PRs cannot be read, each result says so and nothing is written', t => {
  const fixture = githubFixture(t);
  fixture.addPull(7, 45);
  fixture.addPull(8, 45);
  fixture.configure({ profileMaintainer: 'lead' });
  const { api, calls, writes } = recordingApi(fixture);
  const failing = (...args) => {
    if (args[1] === 'graphql') {
      calls.push(args);
      throw new Error('GraphQL rate limit exceeded');
    }
    return api(...args);
  };
  const result = reconcileGithub({ configPath: fixture.configPath, stateDir: join(fixture.root, 'state'), kitVersion: '0.16.1',
    run: true, publish: true }, { request: failing, fetchRefs: fixture.fetchRefs });
  assert.equal(result.errors.length, 2);
  assert.ok(result.errors.every(error => /rate limit/.test(error.message)));
  assert.deepEqual(writes, []);
  assert.equal(calls.filter(args => args[1] === 'graphql').length, 1, 'the failed query is not repeated for each PR');
});

test('the merge rechecks that the merge application is the only bypass actor', () => {
  const head = '1'.repeat(40);
  const api = endpoint => {
    if (endpoint === 'repos/team/project/pulls/3') {
      return { state: 'open', draft: false, head: { sha: head },
        base: { ref: 'main', sha: '2'.repeat(40), repo: { full_name: 'team/project' } } };
    }
    if (endpoint.includes('/rules/branches/')) {
      return [[{ ruleset_id: 40, ruleset_source_type: 'Repository', ruleset_source: 'team/project', type: 'update' }]];
    }
    if (endpoint === 'repos/team/project/rulesets/40?includes_parents=false') {
      return { enforcement: 'active', rules: [{ type: 'update' }], bypass_actors: [
        { actor_id: 7, actor_type: 'Integration', bypass_mode: 'pull_request' },
        { actor_id: 1, actor_type: 'RepositoryRole', bypass_mode: 'always' },
      ] };
    }
    assert.fail(`Unexpected request ${endpoint}`);
  };
  const reconcile = () => ({ current: [{ decision: { conditionMet: true, effectiveStatus: 'success', waiver: null } }] });
  const result = mergeGithub({
    base: 'main', ruleset: 40, appId: 7, execute: true, selection: { project: 'team/project', pullRequest: 3, commit: head },
  }, { api, reconcile });
  assert.equal(result.exitCode, 2);
  assert.equal(result.reason, 'inactive-branch-protection');
});

test('the enforcement templates guard organization repositories and verifiable sources', () => {
  const read = name => readFileSync(new URL(`../pilot/${name}`, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
  const broker = read('broker-workflow.yml');
  assert.doesNotMatch(broker, /repository_owner/);
  assert.match(broker, /contains\(fromJSON\(vars\.OPENGUILDKIT_MERGE_ACTORS \|\| '\[\]'\), github\.actor\)/);
  assert.match(broker, /contains\(fromJSON\(vars\.OPENGUILDKIT_MERGE_ACTORS \|\| '\[\]'\), github\.triggering_actor\)/);
  assert.match(broker, /merge-protection \\\n\s+--repo "\$GITHUB_REPOSITORY" --base "\$BASE" --ruleset "\$NATIVE_RULESET" --app-id "\$EXPECTED_APP_ID"/);
  assert.match(broker, /--ruleset "\$NATIVE_RULESET" --app-id "\$EXPECTED_APP_ID" \\\n\s+--execute/);
  assert.match(broker, /profileMaintainer:\$maintainer/);

  const required = read('required-workflow.yml');
  assert.match(required, /\n {2}schedule:\n {4}- cron: /);
  assert.match(required, /profileMaintainer:\$maintainer/);
  const posts = [...required.matchAll(/(.*)gh api "repos\/\$GITHUB_REPOSITORY\/statuses\//g)];
  assert.equal(posts.length, 2);
  assert.ok(posts.every(([, prefix]) => prefix.includes('GH_TOKEN="$STATUS_TOKEN"')));
  assert.match(required, /description='OpenGuildKit is checking the current commit'/);
  assert.match(required, /description='OpenGuildKit check incomplete'/);
  assert.match(required, /effectiveStatus \+ " \| rule " \+/);
  for (const name of ['agent-workflow.yml', 'broker-workflow.yml', 'recheck-workflow.yml', 'required-workflow.yml']) {
    assert.doesNotMatch(read(name), /[^\x00-\x7f]/, name);
  }
});

// A PR whose Jenkins and GitHub Actions results are both verified, as the watcher hands it to the report.
const reportEntry = (commit, actions = {}) => ({
  project: 'team/repo', pullRequest: 7, commit, profileCommit: 'b'.repeat(40), policyCommit: 'd'.repeat(40),
  rule: 'export-link-expiry', mode: 'required', work: 'c'.repeat(64),
  actions: { state: 'verified', url: 'https://github.com/team/repo/actions/runs/1', verifiedAt: '2026-11-21T00:00:00Z',
    proof: { proof: { actualMinutes: 20, maxMinutes: 30, owner: '@lead', guidance: 'Keep links short.', state: 'success' } },
    ...actions },
  decision: { effectiveStatus: 'success' },
});

// A stand-in `gh` on the PATH that logs each call. `answers` maps the start of the arguments to a reply.
function fakeGh(t, answers = '') {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-fake-gh-'));
  const bin = join(root, 'bin');
  mkdirSync(bin);
  const log = join(root, 'calls.log');
  writeFileSync(join(bin, 'gh'), `#!/bin/sh\necho "$*" >> "${log}"\n${answers}\necho "Unexpected gh call: $*" >&2\nexit 1\n`);
  chmodSync(join(bin, 'gh'), 0o755);
  const { PATH } = process.env;
  process.env.PATH = `${bin}${delimiter}${PATH}`;
  t.after(() => {
    process.env.PATH = PATH;
    rmSync(root, { recursive: true, force: true });
  });
  return () => (existsSync(log) ? readFileSync(log, 'utf8').trim().split('\n') : []);
}

test('Issue #531: a report already published for the same content costs no GitHub request',
  { skip: process.platform === 'win32' && 'needs a POSIX stand-in for the GitHub CLI' }, t => {
    const calls = fakeGh(t);
    const commit = 'a'.repeat(40);
    const entry = reportEntry(commit);
    const path = `openguildkit/pr-7/${entry.work}/${sha256(renderWatchReport(entry, null))}.md`;
    const url = `https://github.com/team/repo/blob/${'e'.repeat(40)}/${path}`;
    const status = { context: 'openguildkit/report-pr-7', state: 'success', description: watchReportStatus(entry).description, target_url: url };
    const pulls = () => new Map([[7, { state: 'open', head: commit, body: '', statuses: [status] }]]);
    assert.deepEqual(publishWatchReport(entry, 'reports', pulls), { work: entry.work, posted: false, url });
    assert.deepEqual(calls(), []);
    // The same status on another path is another report: it goes to the archive, which this fake refuses.
    const other = () => new Map([[7, { state: 'open', head: commit, body: '', statuses: [{ ...status, target_url: url.replace('.md', 'x.md') }] }]]);
    assert.throws(() => publishWatchReport(entry, 'reports', other), /Unexpected gh call/);
  });

test('Issue #531: the report status is written after the head is read again, and not on a head that moved',
  { skip: process.platform === 'win32' && 'needs a POSIX stand-in for the GitHub CLI' }, t => {
    const commit = 'a'.repeat(40);
    const calls = fakeGh(t, [
      'case "$*" in',
      '  "api repos/team/repo/pulls/7") printf \'{"state":"open","head":{"sha":"%s"}}\' "$FAKE_LIVE_HEAD"; exit 0;;',
      '  "api repos/team/repo/statuses/"*) exit 0;;',
      'esac'].join('\n'));
    t.after(() => delete process.env.FAKE_LIVE_HEAD);
    const entry = reportEntry(commit, { state: 'dispatched', proof: undefined });
    const pulls = () => new Map([[7, { state: 'open', head: commit, body: '', statuses: [] }]]);
    process.env.FAKE_LIVE_HEAD = 'f'.repeat(40);
    assert.equal(publishWatchReport(entry, 'reports', pulls).posted, false);
    assert.deepEqual(calls(), ['api repos/team/repo/pulls/7']);
    process.env.FAKE_LIVE_HEAD = commit;
    assert.equal(publishWatchReport(entry, 'reports', pulls).posted, true);
    assert.match(calls().at(-1), new RegExp(`^api repos/team/repo/statuses/${commit} -f context=openguildkit/report-pr-7 -f state=pending `));
  });

test('the PR report archive refuses a different or an unconfirmed report with an English message',
  { skip: process.platform === 'win32' && 'needs a POSIX stand-in for the GitHub CLI' }, t => {
    const root = mkdtempSync(join(tmpdir(), 'openguildkit-report-'));
    const bin = join(root, 'bin');
    mkdirSync(bin);
    writeFileSync(join(bin, 'gh'), [
      '#!/bin/sh',
      'case "$*" in',
      '  "api repos/team/repo/pulls/7") printf \'{"state":"open","head":{"sha":"%s"},"body":""}\' "$FAKE_HEAD";;',
      '  *"--method PUT"*) cat >/dev/null; printf \'{"commit":{"sha":"not-a-commit"}}\';;',
      '  "api repos/team/repo/contents/"*) if [ -n "$FAKE_SAVED" ]; then printf \'{"content":"%s"}\' "$FAKE_SAVED"; else echo "HTTP 404" >&2; exit 1; fi;;',
      '  *) echo "Unexpected gh call: $*" >&2; exit 1;;',
      'esac',
    ].join('\n') + '\n');
    chmodSync(join(bin, 'gh'), 0o755);
    const { PATH } = process.env;
    t.after(() => {
      process.env.PATH = PATH;
      delete process.env.FAKE_HEAD;
      delete process.env.FAKE_SAVED;
      rmSync(root, { recursive: true, force: true });
    });
    const commit = 'a'.repeat(40);
    process.env.PATH = `${bin}${delimiter}${PATH}`;
    process.env.FAKE_HEAD = commit;
    const entry = reportEntry(commit);

    const pulls = () => new Map([[7, { state: 'open', head: commit, body: '', statuses: [] }]]);
    process.env.FAKE_SAVED = Buffer.from('Another report').toString('base64');
    assert.throws(() => publishWatchReport(entry, 'reports', pulls), error => error.message === 'The existing report differs from the expected report.');
    delete process.env.FAKE_SAVED;
    assert.throws(() => publishWatchReport(entry, 'reports', pulls), error => error.message === 'GitHub did not confirm the commit of the report.');
  });

test('the error messages of the GitHub modules are in English', () => {
  // The PR report keeps its middle dots, so the check looks for French letters and punctuation, not for every non-ASCII character.
  const french = /[\u00ab\u00bb\u00c0-\u00ff\u0152\u0153\u2019]/;
  const accented = ['github', 'github-profile', 'github-report'].flatMap(name =>
    readFileSync(new URL(`../lib/${name}.mjs`, import.meta.url), 'utf8').split('\n')
      .flatMap((line, index) => french.test(line) ? [`${name}.mjs:${index + 1}`] : []));
  assert.deepEqual(accented, []);
});
