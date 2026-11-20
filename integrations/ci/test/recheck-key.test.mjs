import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
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

const template = readFileSync(new URL('../pilot/recheck-workflow.yml', import.meta.url), 'utf8');

test('Jenkins and the recheck template compute the same work key from the configured profile branch', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-key-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const origin = join(root, 'origin');
  mkdirSync(join(origin, 'policy'), { recursive: true });
  git(origin, 'init', '-q', '-b', 'main');
  const policyPath = 'policy/export-link.json';
  commitJson(origin, policyPath, { id: 'export-link-expiry', version: 1, maxMinutes: 30 });
  const profile = { schemaVersion: 1, owner: '@platform', policyPath, targetPath: 'export.json' };
  commitJson(origin, 'openguildkit.json', profile);
  git(origin, 'switch', '-q', '-c', 'pilot/recheck-base');
  commitJson(origin, 'openguildkit.json', { ...profile, owner: '@workflow-branch' });
  git(origin, 'switch', '-q', 'main');
  for (let index = 0; index < 3; index += 1) commitJson(origin, 'notes.json', { index });
  git(origin, 'switch', '-q', '-c', 'candidate');
  const head = commitJson(origin, 'export.json', { downloadLinkMinutes: 20 });
  git(origin, 'switch', '-q', 'main');

  const plan = (folder, config) => reconcile({
    configPath: join(folder, 'integration.json'), stateDir: join(folder, 'state'), kitVersion: '0.16.1',
    loadConfig: () => config,
  }).current[0];
  const jenkins = plan(root, {
    policyRepo: { path: origin, ref: 'refs/heads/main' },
    projects: [{ id: 'team/repo', path: origin, profileRef: 'refs/heads/main',
      pullRequests: [{ number: 4, ref: 'refs/heads/candidate' }] }],
  });

  // The template runs on its workflow branch and reads profileRef from pilot/recheck.json.
  assert.match(template, /profile_ref=\$\(jq -er '\.profileRef' pilot\/recheck\.json\)/);
  assert.match(template, /"\+\$profile_ref:refs\/openguildkit\/profile"/);
  assert.doesNotMatch(template, /PROFILE_REF: refs\/heads\//);
  const actions = join(root, 'actions');
  execFileSync('git', ['clone', '-q', '--branch', 'pilot/recheck-base', pathToFileURL(origin).href, actions]);
  const fetchAs = (source, target) => git(actions, 'fetch', '-q', '--no-tags', 'origin', `+${source}:${target}`);
  fetchAs('refs/heads/main', 'refs/openguildkit/profile');
  fetchAs('refs/heads/candidate', 'refs/openguildkit/pr');
  fetchAs('refs/heads/main', 'refs/openguildkit/policy');
  const recheck = profileRef => plan(actions, {
    policyRepo: { path: actions, ref: 'refs/openguildkit/policy' },
    projects: [{ id: 'team/repo', path: actions, profileRef,
      pullRequests: [{ number: 4, ref: 'refs/openguildkit/pr', sha: head }] }],
  });
  assert.equal(recheck('refs/openguildkit/profile').work, jenkins.work);
  // The former template read the profile from its own workflow branch.
  assert.notEqual(recheck('refs/remotes/origin/pilot/recheck-base').work, jenkins.work);

  const shallow = join(root, 'shallow');
  execFileSync('git', ['clone', '-q', '--depth', '1', '--no-single-branch', pathToFileURL(origin).href, shallow]);
  assert.throws(() => plan(root, {
    policyRepo: { path: origin, ref: 'refs/heads/main' },
    projects: [{ id: 'team/repo', path: shallow, profileRef: 'refs/remotes/origin/main',
      pullRequests: [{ number: 4, ref: 'refs/remotes/origin/candidate' }] }],
  }), /shallow clone.*git fetch --unshallow/);
});
