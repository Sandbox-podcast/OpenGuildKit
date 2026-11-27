// Builds a fresh sample project and serves it with `openguildkit ui`, for the project end-to-end tests.
//   node scripts/serve-sample.mjs           (port PW_PROJECT_PORT, 7322 by default)
//   node scripts/serve-sample.mjs --empty   (a folder without OpenGuildKit, to test the setup)
//   node scripts/serve-sample.mjs --empty --stripe   (the same, with Stripe in its stack: setup proposes PCI DSS)
//   node scripts/serve-sample.mjs --gdpr    (the GDPR pattern and one approved task on personal data)
// The built front end (npm run build) is served from web/dist. OGK_PYTHON picks the interpreter.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { delimiter, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = join(dirname(fileURLToPath(import.meta.url)), '..');
const repo = join(web, '..');
const empty = process.argv.includes('--empty');
const stripe = process.argv.includes('--stripe');
const gdpr = process.argv.includes('--gdpr');
const port = process.env.PW_PROJECT_PORT ?? (empty ? '7323' : '7322');
const python = process.env.OGK_PYTHON
  ?? [join(repo, '.venv', 'Scripts', 'python.exe'), join(repo, '.venv', 'bin', 'python')].find((p) => existsSync(p))
  ?? 'python';
if (!existsSync(join(web, 'dist', 'index.html'))) {
  console.error('web/dist is missing: run npm run build first.');
  process.exit(1);
}
// A server left over from an earlier run would answer the tests with another project: refuse a busy port.
const free = await new Promise((resolve) => { const probe = createServer().once('error', () => resolve(false)).once('listening', () => probe.close(() => resolve(true))).listen(Number(port), '127.0.0.1'); });
if (!free) {
  console.error(`Port ${port} is busy: stop the server that uses it, or set PW_PROJECT_PORT.`);
  process.exit(1);
}
const env = { ...process.env, PYTHONPATH: [join(repo, 'src'), process.env.PYTHONPATH].filter(Boolean).join(delimiter), PYTHONIOENCODING: 'utf-8' };
const name = stripe ? 'new-shop' : empty ? 'new-portal' : gdpr ? 'gdpr-portal' : 'portal';
const root = mkdtempSync(join(tmpdir(), 'ogk-e2e-'));
const project = join(root, name);
let server;
// Playwright ends this script with SIGTERM (gracefulShutdown in its config): the sample project goes with it.
process.on('exit', () => {
  server?.kill();
  try { rmSync(root, { recursive: true, force: true, maxRetries: 3 }); } catch { /* the next cleaning of the temporary folder takes it */ }
});
if (empty) {
  mkdirSync(project);
  const dependencies = { react: '^19.0.0', ...(stripe ? { stripe: '^14.0.0' } : {}) };
  writeFileSync(join(project, 'package.json'), JSON.stringify({ name, dependencies }, null, 2));
} else {
  const built = spawnSync(python, [join(web, 'scripts', 'sample-project.py'), project, ...(gdpr ? ['--gdpr'] : [])], { env, stdio: 'inherit' });
  if (built.status !== 0) process.exit(built.status ?? 1);
}
server = spawn(python, ['-m', 'openguildkit', '--project', project, 'ui', '--no-browser', '--port', port, '--static', join(web, 'dist')], { env, stdio: 'inherit' });
const stop = () => { server.kill(); process.exit(0); };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
server.on('exit', (code) => process.exit(code ?? 0));
