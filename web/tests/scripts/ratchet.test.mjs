// npm run check:ratchet: two rules the code does not meet yet, counted per file; a file may get better, never worse.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { MAX_LINE, compare, longLines, parseEslint, parseList, parseTsc } from '../../scripts/check-ratchet.mjs';

const roots = [];
function project(files) {
  const root = mkdtempSync(join(tmpdir(), 'ogk-ratchet-'));
  roots.push(root);
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(join(root, path, '..'), { recursive: true });
    writeFileSync(join(root, path), text);
  }
  return root;
}
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe('npm run check:ratchet', () => {
  /** Issue #515: lines of 731 characters, and nothing to stop a new one. */
  it('counts the lines of src over the width, per file', () => {
    const long = `const x = '${'a'.repeat(MAX_LINE)}';`;
    const root = project({
      'src/a.tsx': `${long}\nconst short = 1;\n${long}\n`,
      'src/deep/b.ts': `${long}\n`,
      'src/ok.ts': `const x = '${'a'.repeat(MAX_LINE - 20)}';\n`,
      'src/style.css': `${long}\n`,
      'tests/t.ts': `${long}\n`,
    });
    expect(longLines(root)).toEqual({ 'src/a.tsx': 2, 'src/deep/b.ts': 1 });
  });

  /** Issue #515: `noUncheckedIndexedAccess` reports 400 errors the code cannot fix at once. */
  it('counts the errors of tsc per file, and nothing else it prints', () => {
    const output = [
      "src/project/views/Council.tsx(172,5): error TS2532: Object is possibly 'undefined'.",
      "src/project/views/Council.tsx(180,9): error TS18048: 'x' is possibly 'undefined'.",
      "src/domain/commands/forge.ts(12,3): error TS2532: Object is possibly 'undefined'.",
      '  Type error continued on a second line',
      'Found 3 errors in 2 files.',
    ].join('\n');
    expect(parseTsc(output)).toEqual({ 'src/project/views/Council.tsx': 2, 'src/domain/commands/forge.ts': 1 });
  });

  /** Issue #515: no linter, so nothing said which files break which rule. */
  it('counts the problems of ESLint per file, from its JSON, and skips the clean files', () => {
    const root = '/web';
    const json = JSON.stringify([
      { filePath: '/web/src/project/data.ts', messages: [{ ruleId: 'eqeqeq' }, { ruleId: 'prefer-const' }] },
      { filePath: '/web/src/project/query.ts', messages: [] },
      { filePath: '/web/scripts/a.mjs', messages: [{ ruleId: null, fatal: true }] },
    ]);
    expect(parseEslint(json, root)).toEqual({ 'src/project/data.ts': 2, 'scripts/a.mjs': 1 });
  });

  /** Issue #515: no formatter, so nothing said which files are not formatted. */
  it('counts one per file Prettier would change, from its list', () => {
    expect(parseList('src/a.ts\nsrc/deep/b.tsx\n\n')).toEqual({ 'src/a.ts': 1, 'src/deep/b.tsx': 1 });
    expect(parseList('')).toEqual({});
  });

  it('lets a file get better, and a file with no baseline stay at zero', () => {
    expect(compare({ 'src/a.ts': 3 }, { 'src/a.ts': 3 })).toEqual({ worse: [], better: [] });
    expect(compare({ 'src/a.ts': 3, 'src/b.ts': 1 }, { 'src/a.ts': 1 }).better).toEqual(['src/a.ts: 1 (baseline 3)', 'src/b.ts: 0 (baseline 1)']);
  });

  it('refuses a file that gets worse, and a new file with a deviation', () => {
    expect(compare({ 'src/a.ts': 3 }, { 'src/a.ts': 4, 'src/new.ts': 1 }).worse).toEqual(['src/a.ts: 4 (baseline 3)', 'src/new.ts: 1 (baseline 0)']);
  });
});
