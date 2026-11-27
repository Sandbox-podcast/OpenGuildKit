import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const root = fileURLToPath(new URL('../../', import.meta.url));
const sources = (folder: string): string[] =>
  readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    return statSync(path).isDirectory() ? sources(path) : /\.(ts|tsx|html)$/.test(name) ? [path] : [];
  });

describe('page served by openguildkit ui', () => {
  /** Issue #514: the policy allowed any style element or attribute; it now has no 'unsafe-inline' for styles. */
  it('writes no style element and no style attribute, which that policy refuses', () => {
    // React sets `style={{…}}` through the DOM (allowed). Markup with `style="…"`, a <style> element, setAttribute('style') and cssText are not.
    const product = [...sources(join(root, 'src/project')), ...sources(join(root, 'src/shared')), join(root, 'index.html')];
    const inline = /<style[\s>]|\bstyle="|\bstyle='|setAttribute\(\s*['"]style['"]|\.cssText\b|insertRule|adoptedStyleSheets/;
    const found = product.flatMap((path) =>
      readFileSync(path, 'utf8')
        .split('\n')
        .map((line, i) => (inline.test(line) ? `${path.replace(root, '')}:${i + 1}: ${line.trim().slice(0, 100)}` : ''))
        .filter(Boolean),
    );
    expect(found).toEqual([]);
  });
});
