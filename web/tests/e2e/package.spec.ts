/**
 * The build that the wheel ships (npm run build, then npm run bundle), served by `openguildkit ui`: it holds
 * no demo, and ?demo=1 says how to start the demo instead. Run `npm run build` first; OGK_PYTHON picks the
 * interpreter, as for the project journeys.
 */
import { expect, test } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = fileURLToPath(new URL('../..', import.meta.url));
let server: ChildProcess | undefined;
let printed = '';

test.beforeAll(async () => {
  test.skip(!existsSync(join(web, 'dist', 'index.html')), 'run npm run build first');
  const project = mkdtempSync(join(tmpdir(), 'ogk-package-'));
  const env = { ...process.env, PYTHONPATH: [join(web, '..', 'src'), process.env.PYTHONPATH].filter(Boolean).join(delimiter), PYTHONIOENCODING: 'utf-8' };
  server = spawn(process.env.OGK_PYTHON ?? 'python', ['-m', 'openguildkit', '--project', project, 'ui', '--no-browser', '--port', '0', '--static', join(web, 'dist')], { env });
  printed = await new Promise<string>((resolve, reject) => {
    let out = '';
    server!.stdout!.on('data', (chunk) => { out += chunk; const found = /http:\/\/127\.0\.0\.1:\d+\/\?key=\S+/.exec(out); if (found) resolve(found[0]); });
    server!.on('exit', (code) => reject(new Error(`openguildkit ui exited with ${code}`)));
  });
});
test.afterAll(() => { server?.kill(); });

test('la page servie par openguildkit ui ne contient pas la démo et dit comment la lancer', async ({ page }) => {
  const requested: string[] = [];
  page.on('request', (request) => requested.push(new URL(request.url()).pathname));
  // The printed address opens the session (its key becomes a cookie), as when a person opens it.
  await page.goto(printed);
  await page.goto(`${printed.split('?')[0]}?demo=1`);
  await expect(page.getByRole('heading', { level: 1, name: 'La démonstration n\'est pas incluse' })).toBeVisible();
  await expect(page.locator('main')).toContainText('npm run dev');
  await expect(page.locator('main')).toContainText('openguildkit ui');
  expect(requested.filter((path) => /\/assets\/(App|domain|demo-|zod|world\/|characters\/)/.test(path))).toEqual([]);
});
