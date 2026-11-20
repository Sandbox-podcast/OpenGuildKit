import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { reconcileGithub } from '../lib/github.mjs';
import { mergeGithub } from '../lib/merge.mjs';

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
    pulls.push({ number, state: 'open', head: { sha: head }, base: { repo: { full_name: 'team/repo' } } });
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
    if (endpoint === 'repos/team/repo/pulls?state=open&per_page=100') return JSON.stringify([pulls]);
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
  const configure = project => writeFileSync(configPath, JSON.stringify({
    policyRepo: { id: 'team/policies', path: 'clone', ref: 'refs/heads/main' },
    projects: [{ id: 'team/repo', path: 'clone', profileRef: 'refs/heads/main', ...project }],
  }));
  const sync = (options = {}) => reconcileGithub({
    configPath, stateDir: join(root, 'state'), kitVersion: '0.16.1', ...options,
  }, { request, fetchRefs });
  return { root, origin, api, addPull, configure, sync, request, fetchRefs, configPath, approved };
}

test('the GitHub flows accept an adopted profile only after the maintainer approval is verified', t => {
  const { origin, api, addPull, configure, sync, approved } = githubFixture(t);
  addPull(7, 45);
  configure({});
  assert.throws(() => sync(), /Set profileMaintainer for team\/repo/);

  configure({ profileMaintainer: 'lead' });
  const [current] = sync().current;
  assert.equal(current.mode, 'required');
  assert.equal(current.status, 'pending');

  api.mergedBy = 'someone-else';
  assert.throws(() => sync(), /fusionnée par le mainteneur désigné/);
  api.mergedBy = 'lead';

  commitJson(origin, 'openguildkit.json', { ...approved, owner: '@intruder',
    adoption: { ...approved.adoption, approver: '@intruder' } });
  assert.throws(() => sync(), /diffère de la proposition approuvée/);
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
  const read = name => readFileSync(new URL(`../pilot/${name}`, import.meta.url), 'utf8');
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
});
