// npm run bundle: what it lets into the Python package, and what it refuses.
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { BUDGET_KB, bundleProblems, sizeKb } from '../../scripts/bundle.mjs';

const folders = [];
function build(files) {
  const folder = mkdtempSync(join(tmpdir(), 'ogk-bundle-'));
  folders.push(folder);
  for (const [path, bytes] of Object.entries(files)) {
    mkdirSync(join(folder, path, '..'), { recursive: true });
    writeFileSync(join(folder, path), Buffer.alloc(bytes));
  }
  return folder;
}
afterEach(() => { for (const folder of folders.splice(0)) rmSync(folder, { recursive: true, force: true }); });

describe('npm run bundle', () => {
  it('counts each file in 4 KB blocks, as du -sk does', () => {
    expect(sizeKb(build({ 'index.html': 700, 'assets/a.js': 4096, 'assets/b.js': 4097 }))).toBe(16);
  });

  it('accepts a product build within the budget, which stays at most 1,500 KB', () => {
    expect(BUDGET_KB).toBeLessThanOrEqual(1500);
    expect(bundleProblems(build({ 'index.html': 700, 'assets/index.js': 400_000 }))).toEqual([]);
  });

  it('refuses a build over the budget', () => {
    const problems = bundleProblems(build({ 'index.html': 700, 'assets/index.js': (BUDGET_KB + 4) * 1024 }));
    expect(problems).toHaveLength(1);
    expect(problems[0]).toMatch(/over its budget of \d+ KB/);
  });

  it('refuses a build that holds the images of the demo', () => {
    const problems = bundleProblems(build({ 'index.html': 700, 'assets/world/guildhall.webp': 1000 }));
    expect(problems).toEqual(['assets/world belongs to the demo: build with npm run build, not npm run build:demo.']);
  });

  it('is described in both guides with the measure and the margin the script gives', () => {
    const script = readFileSync(new URL('../../scripts/bundle.mjs', import.meta.url), 'utf8');
    const measured = Number(/weighed ([\d,]+) KB/.exec(script)?.[1].replace(',', ''));
    const french = (kb) => `${String(kb).replace(/(\d)(\d{3})$/, '$1 $2')} Ko`;
    expect(measured).toBeGreaterThan(0);
    expect(measured).toBeLessThanOrEqual(BUDGET_KB);
    for (const guide of ['../../README.md', '../../docs/interface-projet.md']) {
      const text = readFileSync(new URL(guide, import.meta.url), 'utf8');
      for (const kb of [BUDGET_KB, measured, BUDGET_KB - measured]) expect(text, `${guide} says ${french(kb)}`).toContain(french(kb));
    }
  });

  it('builds with the chunk options of the current bundler, which warns about advancedChunks', () => {
    const config = readFileSync(new URL('../../vite.config.ts', import.meta.url), 'utf8');
    expect(config).not.toContain('advancedChunks');
    expect(config).toContain('codeSplitting');
  });

  it('refuses a folder without the page', () => {
    expect(bundleProblems(build({ 'assets/index.js': 10 }))[0]).toMatch(/index\.html is missing/);
  });
});
