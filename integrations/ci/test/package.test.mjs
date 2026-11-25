import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, normalize, sep } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const packageRoot = fileURLToPath(new URL('..', import.meta.url));
const repositoryRoot = join(packageRoot, '..', '..');
const cli = join(packageRoot, 'bin', 'openguildkit.mjs');
const manifest = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
// Windows checkouts may convert line endings; compare text with LF only.
const readme = readFileSync(join(packageRoot, 'README.md'), 'utf8').replace(/\r\n/g, '\n');
const changelog = readFileSync(join(repositoryRoot, "CHANGELOG.md"), "utf8");
const releaseVersion = /^## (\d+\.\d+\.\d+)\s*$/m.exec(changelog)[1];
const read = path => readFileSync(join(packageRoot, path), 'utf8').replace(/\r\n/g, '\n');

function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'user.name=OpenGuildKit Test',
    '-c', 'user.email=openguildkit@example.invalid', '-c', 'commit.gpgsign=false',
    '-C', cwd, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

test('the package is private and ships every file its README links to', () => {
  assert.equal(manifest.private, true);
  const shipped = path => ['README.md', 'LICENSE', 'package.json'].includes(path) ||
    manifest.files.some(entry => path === entry || path.startsWith(`${entry}/`));
  const links = [...readme.matchAll(/\]\(([^)\s]+)\)/g)].map(match => match[1]).filter(link => !link.startsWith('#'));
  assert.ok(links.length > 5);
  const repository = 'https://github.com/Sandbox-podcast/OpenGuildKit/';
  for (const link of links) {
    if (link.startsWith(repository)) {
      const match = new RegExp(`^${repository}(?:blob|tree)/v${releaseVersion.replaceAll('.', '\\.')}/(.+)$`).exec(link);
      assert.ok(match, `${link} must be pinned to the v${releaseVersion} release tag`);
      assert.ok(existsSync(join(repositoryRoot, match[1])), `${link} must name a file of the repository`);
    } else if (!/^https?:/.test(link)) {
      const path = normalize(link).split(sep).join('/').replace(/\/$/, '');
      assert.ok(shipped(path), `${link} is not in the npm archive`);
      assert.ok(existsSync(join(packageRoot, path)), `${link} does not exist`);
    }
  }
});

test('init and reconcile run with the configuration shown in the README', t => {
  const root = mkdtempSync(join(tmpdir(), 'openguildkit-readme-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const [profileExample, configExample] = [...readme.matchAll(/```json\n([\s\S]*?)```/g)].map(match => JSON.parse(match[1]));
  const run = (...args) => spawnSync(process.execPath, [cli, ...args], { cwd: root, encoding: 'utf8' });
  const init = run('init', '--owner', profileExample.owner);
  assert.equal(init.status, 0, init.stderr);
  assert.deepEqual(JSON.parse(readFileSync(join(root, 'openguildkit.json'), 'utf8')), profileExample);

  for (const repo of [configExample.policyRepo, ...configExample.projects]) {
    const path = join(root, repo.path);
    mkdirSync(path);
    git(path, 'init', '-q', '-b', 'main');
    git(path, 'commit', '-q', '--allow-empty', '-m', 'Start');
  }
  writeFileSync(join(root, 'integration.json'), JSON.stringify(configExample));
  const reconcile = run('reconcile', '--config', 'integration.json', '--state', 'state');
  assert.equal(reconcile.status, 0, reconcile.stderr);
  assert.deepEqual(JSON.parse(reconcile.stdout), { current: [], errors: [] });
});

test('the workflow templates pin their actions and read the kit version from their pin file', () => {
  const templates = readdirSync(join(packageRoot, 'pilot')).filter(name => name.endsWith('.yml'));
  assert.equal(templates.length, 4);
  for (const name of templates) {
    const body = read(`pilot/${name}`);
    const uses = [...body.matchAll(/^\s*(?:- )?uses:\s*(\S+)(.*)$/gm)];
    assert.ok(uses.length > 0, name);
    for (const [, action, comment] of uses) {
      assert.match(action, /^[\w.-]+\/[\w.-]+@[a-f0-9]{40}$/, `${name}: ${action}`);
      assert.match(comment, /^ # v\d+\.\d+\.\d+$/, `${name}: ${action}`);
    }
    assert.doesNotMatch(body, /release download v\d|openguildkit-\d+\.\d+\.\d+\.tgz/, name);
    const pin = /read -r digest asset < (pilot\/[\w-]+-kit\.sha256)/.exec(body);
    assert.ok(pin, `${name} must read its kit pin`);
    assert.match(body, new RegExp(`sha256sum -c "\\$GITHUB_WORKSPACE/${pin[1]}"`), name);
  }
});

test('the Windows installer deploys the current watcher and writes files Jenkins can read', () => {
  const installer = read('prototype/windows/install-jenkins-watch.ps1');
  const launcher = read('prototype/windows/start-jenkins.ps1');
  const code = (installer + launcher).split('\n').filter(line => !line.trim().startsWith('#')).join('\n');
  assert.doesNotMatch(code, /-Encoding utf8|Set-Content|Out-File/i);
  assert.match(installer, /New-Object System\.Text\.UTF8Encoding\(\$false\)/);
  assert.match(installer, /\[System\.IO\.File\]::WriteAllText\(\$Path, \$Content, \$utf8\)/);
  assert.doesNotMatch(installer, /watch-rule\.mjs/);
  for (const file of ['pilot/run-watch-jenkins.mjs', 'pilot/install-kit.mjs', 'lib/state-directory.mjs']) {
    assert.ok(installer.includes(`'${file}'`), file);
  }
  const imports = [...read('pilot/run-watch-jenkins.mjs').matchAll(/from '(\.[^']+)'/g)].map(match => match[1]);
  assert.deepEqual(imports.sort(), ['../lib/state-directory.mjs', './install-kit.mjs']);
  assert.match(installer, /'--kit', \$kit, '--config', \$config, '--state', \$state/);
  assert.doesNotMatch(installer + launcher, /OGK_JENKINS_PASSWORD|getenv/);
  assert.match(installer, /secret\.delete\(\)/);
  assert.match(launcher, /Remove-Item -LiteralPath \$bootstrapSecret/);
});
