// npm run check:exports: an export that nothing uses fails the check; every way the code uses one counts.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { unusedExports } from '../../scripts/unused-exports.mjs';

const roots = [];
function project(files) {
  const root = mkdtempSync(join(tmpdir(), 'ogk-exports-'));
  roots.push(root);
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(join(root, path, '..'), { recursive: true });
    writeFileSync(join(root, path), text);
  }
  return root;
}
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe('npm run check:exports', () => {
  it('reports an export that no file uses, and only that one', () => {
    const root = project({
      'src/router.ts': 'export const navigate = (to: string) => to;\nexport const confirmLeave = () => true;\n',
      'src/main.tsx': "import { navigate } from './router';\nnavigate('/');\n",
    });
    expect(unusedExports(root)).toEqual(['src/router.ts: confirmLeave']);
  });

  it('counts the alias, a namespace, a re-export, a test and the module itself', () => {
    const root = project({
      'src/a.ts': 'export const viaAlias = 1;\nexport const viaTest = 2;\nexport type Local = { n: number };\nexport const local: Local = { n: 1 };\n',
      'src/b.ts': 'export const all = 1;\nexport const every = 2;\n',
      'src/c.ts': 'export const forwarded = 1;\n',
      'src/index.ts': "import { viaAlias } from '@/a';\nimport * as b from './b';\nexport { forwarded } from './c';\nconsole.log(viaAlias, b, local);\nimport { local } from './a';\n",
      'tests/a.test.ts': "import { viaTest } from '../src/a';\nconsole.log(viaTest);\n",
    });
    expect(unusedExports(root)).toEqual(['src/index.ts: forwarded']);
  });

  it('follows the names a lazy import reads', () => {
    const root = project({
      'src/places.tsx': 'export function Kingdom() { return null; }\nexport function Forgotten() { return null; }\nexport const preload = () => 1;\n',
      'src/app.tsx': "const lazy = (load: () => Promise<unknown>, name: string) => [load, name];\nlazy(() => import('./places'), 'Kingdom');\nasync function start() { const m = await import('./places'); m.preload(); }\nstart();\n",
    });
    expect(unusedExports(root)).toEqual(['src/places.tsx: Forgotten']);
  });
});
