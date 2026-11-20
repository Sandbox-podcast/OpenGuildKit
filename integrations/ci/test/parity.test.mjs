import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { parseJson } from '../lib/json.mjs';

// tests/e2e/test_export_ci.py judges the same fixture with openguildkit ci-check.
const fixture = JSON.parse(readFileSync(new URL('fixtures/parity.json', import.meta.url), 'utf8'));
const cli = fileURLToPath(new URL('../bin/openguildkit.mjs', import.meta.url));
const exitCodes = { success: 0, failure: 1, error: 2 };
const policyPath = 'packs/export-link-expiry.json';
const bytesOf = item => item.base64 === undefined ? Buffer.from(item.text, 'utf8') : Buffer.from(item.base64, 'base64');
const valid = Buffer.from('{"downloadLinkMinutes": 30}');

function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'user.name=OpenGuildKit Test',
    '-c', 'user.email=openguildkit@example.invalid', '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false',
    '-C', cwd, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function repository(root, name, objectFormat = 'sha1') {
  const path = join(root, name);
  mkdirSync(path);
  git(path, 'init', '-q', `--object-format=${objectFormat}`);
  return path;
}

function commitBytes(repo, file, bytes) {
  mkdirSync(join(repo, file, '..'), { recursive: true });
  writeFileSync(join(repo, file), bytes);
  git(repo, 'add', '--', file);
  git(repo, 'commit', '-qm', `Update ${file}`);
  return git(repo, 'rev-parse', 'HEAD');
}

function setup(t) {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-parity-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const policy = repository(root, 'policy');
  const policyCommit = commitBytes(policy, policyPath, JSON.stringify(fixture.pack, null, 2));
  const profile = JSON.stringify({
    schemaVersion: 1, owner: '@platform', ruleId: 'export-link-expiry', policyPath, targetPath: 'export.json',
  });
  const target = (name, objectFormat) => {
    const repo = repository(root, name, objectFormat);
    return { repo, profileCommit: commitBytes(repo, 'openguildkit.json', profile) };
  };
  const check = ({ repo, profileCommit }, commit, policySha = policyCommit) => spawnSync(process.execPath, [
    cli, 'check', '--policy-repo', policy, '--policy-commit', policySha, '--target-repo', repo,
    '--profile-commit', profileCommit, '--commit', commit, '--enforce',
  ], { encoding: 'utf8' });
  return { root, policy, policyCommit, target, check };
}

test('the coordinator judges the shared export files like ci-check', t => {
  const { target, check } = setup(t);
  const repo = target('exports');
  for (const item of fixture.exports) {
    const result = check(repo, commitBytes(repo.repo, 'export.json', bytesOf(item)));
    assert.equal(result.status, exitCodes[item.verdict], `${item.name}: ${result.stderr}`);
  }
});

test('the coordinator reads the shared policy packs like ci-check', t => {
  const { policy, target, check } = setup(t);
  const repo = target('packs');
  const commit = commitBytes(repo.repo, 'export.json', valid);
  for (const item of fixture.packs) {
    const result = check(repo, commit, commitBytes(policy, policyPath, bytesOf(item)));
    assert.equal(result.status, exitCodes[item.verdict], `${item.name}: ${result.stderr}`);
  }
});

test('the coordinator accepts the same commit names as ci-check', t => {
  const { policy, policyCommit, target, check } = setup(t);
  git(policy, 'tag', '-a', 'parity-policy', '-m', 'Policy tag', policyCommit);
  const names = (repo, commit, tag, file) => ({
    commit,
    tree: git(repo, 'rev-parse', `${commit}^{tree}`),
    tag: git(repo, 'rev-parse', tag),
    blob: git(repo, 'rev-parse', `${commit}:${file}`),
    short: commit.slice(0, 12),
    upper: commit.toUpperCase(),
  });
  const policyNames = names(policy, policyCommit, 'parity-policy', policyPath);
  for (const item of fixture.commits) {
    const repo = target(`commit-${fixture.commits.indexOf(item)}`, item.objectFormat);
    const commit = commitBytes(repo.repo, 'export.json', valid);
    git(repo.repo, 'tag', '-a', 'parity-target', '-m', 'Target tag', commit);
    const result = check(repo, names(repo.repo, commit, 'parity-target', 'export.json')[item.target], policyNames[item.policy]);
    assert.equal(result.status, exitCodes[item.verdict], `${item.name}: ${result.stderr}`);
    if (item.objectFormat === 'sha256') assert.equal(JSON.parse(result.stdout).commit.length, 64);
  }
});

test('the JSON reader keeps a __proto__ key as data and reports deep nesting', () => {
  const parsed = parseJson('{"__proto__": {"polluted": true}}');
  assert.equal(Object.getPrototypeOf(parsed), Object.prototype);
  assert.deepEqual(Object.keys(parsed), ['__proto__']);
  assert.equal({}.polluted, undefined);
  assert.throws(() => parseJson('['.repeat(100_000) + ']'.repeat(100_000), 'deep.json'), /deep\.json: nested too deeply/);
});
