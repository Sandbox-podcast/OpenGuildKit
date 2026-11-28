import { readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

// The product is what `openguildkit ui` serves: src/main.tsx without its `__OGK_DEMO__` branch, the only place that
// imports src/demo. Everything else the demo needs lives under src/demo, and the wheel leaves it out (#500).
const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SPECIFIERS = /(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s+)['"]([^'"]+)['"]/g;

/** The file an import names, or null for a package. */
function resolveImport(from: string, specifier: string, exists: (path: string) => boolean): string | null {
  const base = specifier.startsWith('@/')
    ? join(WEB, 'src', specifier.slice(2))
    : specifier.startsWith('.')
      ? resolve(dirname(from), specifier)
      : null;
  if (base === null) return null;
  const found = ['', '.ts', '.tsx', '/index.ts', '/index.tsx'].map((end) => base + end).find(exists);
  if (!found) throw new Error(`${relative(WEB, from)} imports ${specifier}, which does not exist`);
  return found;
}

const isFile = (path: string) => statSync(path, { throwIfNoEntry: false })?.isFile() ?? false;

/** Every source file reached from `entry`, the demo's own entry left out of main.tsx. */
function productFiles(entry: string, read = (path: string) => readFileSync(path, 'utf8'), exists = isFile): string[] {
  const seen = new Set<string>();
  const queue = [entry];
  while (queue.length) {
    const file = queue.pop()!;
    if (seen.has(file) || !/\.tsx?$/.test(file)) continue;
    seen.add(file);
    for (const [, specifier] of read(file).matchAll(SPECIFIERS)) {
      if (file === entry && specifier.startsWith('./demo/')) continue;
      const target = resolveImport(file, specifier, exists);
      if (target) queue.push(target);
    }
  }
  return [...seen].map((path) => relative(WEB, path).replaceAll('\\', '/')).sort();
}

describe('boundary between the product and the demo', () => {
  it('the product reaches no file of src/demo', () => {
    const files = productFiles(join(WEB, 'src', 'main.tsx'));
    expect(files).toContain('src/project/ProjectApp.tsx');
    expect(files).toContain('src/project/views/Council.tsx');
    expect(files.filter((file) => file.startsWith('src/demo/'))).toEqual([]);
  });

  /** Issue #500: the only guard against demo code in the wheel was an e2e test on the names of the files requested. */
  it('fails when a view of the product imports a module of the demo', () => {
    const at = (path: string) => join(WEB, path);
    const sources: Record<string, string> = {
      [at('src/main.tsx')]: "import('./project/ProjectApp'); import('./demo/app/App');",
      [at('src/project/ProjectApp.tsx')]: "import { Quests } from './views/Quests';",
      [at('src/project/views/Quests.tsx')]: "import { cmd } from '@/demo/domain/commands';",
      [at('src/demo/domain/commands/index.ts')]: '',
      [at('src/demo/app/App.tsx')]: '',
    };
    const files = productFiles(
      at('src/main.tsx'),
      (path) => sources[path]!,
      (path) => path in sources,
    );
    expect(files.filter((file) => file.startsWith('src/demo/'))).toEqual(['src/demo/domain/commands/index.ts']);
  });
});
