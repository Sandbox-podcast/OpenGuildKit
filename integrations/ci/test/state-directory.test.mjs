import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { checkStateDirectory } from '../lib/state-directory.mjs';
import { watchGithub } from '../lib/watch.mjs';

test('check-state accepts a writable directory and removes its probe', t => {
  const root = mkdtempSync(join(tmpdir(), 'ogk-state-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cli = fileURLToPath(new URL('../bin/openguildkit.mjs', import.meta.url));
  const result = spawnSync(process.execPath, [cli, 'check-state', '--state', root], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /hard links verified/);
  assert.deepEqual(readdirSync(root), []);
});

test('an exFAT hard-link failure gives recovery instructions and preserves existing state', t => {
  const root = mkdtempSync(join(tmpdir(), 'ogk-state-exfat-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const state = join(root, 'existing.json');
  writeFileSync(state, '{}');
  const link = () => { throw Object.assign(new Error('unsupported hard link'), { code: 'EISDIR' }); };
  assert.throws(() => checkStateDirectory(root, { link, volumeFormat: () => 'exFAT' }), /exFAT.*NTFS.*--state/);
  assert.equal(readFileSync(state, 'utf8'), '{}');
  assert.deepEqual(readdirSync(root), ['existing.json']);
});

test('watch rejects an invalid state path before synchronizing GitHub', t => {
  const root = mkdtempSync(join(tmpdir(), 'ogk-state-invalid-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const configPath = join(root, 'integration.json');
  const stateDir = join(root, 'not-a-directory');
  writeFileSync(configPath, '{"projects":[]}');
  writeFileSync(stateDir, 'sentinel');
  assert.throws(() => watchGithub({ configPath, stateDir }, {
    reconcile: () => assert.fail('GitHub synchronization ran before the state directory check'),
  }), /OpenGuildKit state directory/);
  assert.equal(readFileSync(stateDir, 'utf8'), 'sentinel');
});

test('the Jenkins launcher validates the state directory before reading the kit manifest', t => {
  const root = mkdtempSync(join(tmpdir(), 'ogk-state-launcher-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const launcher = fileURLToPath(new URL('../pilot/run-watch-jenkins.mjs', import.meta.url));
  const stateDir = join(root, 'not-a-directory');
  writeFileSync(stateDir, 'sentinel');
  const result = spawnSync(process.execPath, [
    launcher, '--kit', 'missing.json', '--config', 'integration.json', '--state', stateDir,
  ], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /OpenGuildKit state directory/);
  assert.doesNotMatch(result.stderr, /missing\.json/);
});
