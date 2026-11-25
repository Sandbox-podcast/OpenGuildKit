import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const packageRoot = fileURLToPath(new URL('..', import.meta.url));
const script = name => join(packageRoot, 'pilot', name);
// The installer only accepts published-format versions. This archive is a test fixture.
const version = '1.2.3';

function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'user.name=OpenGuildKit Test',
    '-c', 'user.email=openguildkit@example.invalid', '-c', 'commit.gpgsign=false',
    '-C', cwd, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function commitJson(repo, file, value) {
  mkdirSync(join(repo, file, '..'), { recursive: true });
  writeFileSync(join(repo, file), JSON.stringify(value));
  git(repo, 'add', '--', file);
  git(repo, 'commit', '-qm', `Update ${file}`);
  return git(repo, 'rev-parse', 'HEAD');
}

test('the Jenkins helpers exit with 2 when they cannot evaluate', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-helpers-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const run = (name, ...args) => spawnSync(process.execPath, [script(name), ...args], { cwd: root, encoding: 'utf8' });
  for (const [name, args, message] of [
    ['run-kit.mjs', [], /Usage: node pilot\/run-kit\.mjs/],
    ['run-kit.mjs', ['.', '1'.repeat(40), '2'.repeat(40), 'out'], /openguildkit-kit\.json|not a git repository/i],
    ['run-agent-jenkins.mjs', [], /Usage: node pilot\/run-agent-jenkins\.mjs/],
    ['jenkins-publish.mjs', ['not a repository', 'report.json'], /Dépôt, rapport ou contexte de statut invalide/],
  ]) {
    const result = run(name, ...args);
    assert.equal(result.status, 2, `${name}: ${result.stderr}`);
    assert.match(result.stderr, message);
    assert.doesNotMatch(result.stderr, /^\s+at /m);
  }
});

test('run-kit keeps the check exit codes: 0 conforming, 1 rule failed, 2 not evaluated',
  { skip: process.platform === 'win32' && 'needs a POSIX stand-in for the GitHub CLI' }, t => {
    const root = mkdtempSync(join(tmpdir(), 'openguildkit-run-kit-'));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    const staging = join(root, 'staging', 'package');
    for (const entry of ['bin', 'lib', 'prototype/demo', 'package.json']) {
      cpSync(join(packageRoot, entry), join(staging, entry), { recursive: true });
    }
    const manifestPath = join(staging, 'package.json');
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    writeFileSync(manifestPath, JSON.stringify({ ...manifest, version }));
    const archive = join(root, `openguildkit-${version}.tgz`);
    execFileSync('tar', ['-czf', archive, '-C', join(root, 'staging'), 'package']);
    const sha256 = createHash('sha256').update(readFileSync(archive)).digest('hex');
    const bin = join(root, 'bin');
    mkdirSync(bin);
    writeFileSync(join(bin, 'gh'), [
      '#!/bin/sh',
      'while [ "$#" -gt 0 ]; do case "$1" in -D) shift; dir="$1";; -p) shift; asset="$1";; esac; shift; done',
      'cp "$OPENGUILDKIT_TEST_ARCHIVE" "$dir/$asset"',
    ].join('\n') + '\n');
    chmodSync(join(bin, 'gh'), 0o755);

    const repo = join(root, 'repo');
    mkdirSync(repo);
    git(repo, 'init', '-q', '-b', 'main');
    const policyCommit = commitJson(repo, 'policy/export-link.json', { id: 'export-link-expiry', version: 1, maxMinutes: 30 });
    commitJson(repo, 'openguildkit.json', {
      schemaVersion: 1, owner: '@platform', policyPath: 'policy/export-link.json', targetPath: 'export.json',
      adoption: { state: 'approved', approver: '@platform', mode: 'required', inventoryCommit: policyCommit, catalogCommit: policyCommit },
    });
    commitJson(repo, 'openguildkit-kit.json', { repository: 'team/kit', version, sha256 });
    const conforming = commitJson(repo, 'export.json', { downloadLinkMinutes: 20 });
    const failing = commitJson(repo, 'export.json', { downloadLinkMinutes: 45 });
    const runKit = (policy, target) => spawnSync(process.execPath, [script('run-kit.mjs'), repo, policy, target, join(root, 'out')], {
      cwd: repo, encoding: 'utf8',
      env: { ...process.env, PATH: `${bin}${delimiter}${process.env.PATH}`, OPENGUILDKIT_TEST_ARCHIVE: archive },
    });
    assert.equal(runKit(policyCommit, conforming).status, 0);
    const failed = runKit(policyCommit, failing);
    assert.equal(failed.status, 1, failed.stderr);
    assert.equal(JSON.parse(failed.stdout).state, 'failure');
    const unknown = runKit('3'.repeat(40), failing);
    assert.equal(unknown.status, 2);
    assert.match(unknown.stderr, /must identify a commit/);
  });
