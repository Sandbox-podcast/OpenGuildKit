// The web/ tooling: what `npm run check` runs, and how often.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');
const scripts = JSON.parse(read('package.json')).scripts;

/** How many times `tsc` runs when `npm run NAME` runs: its own commands and the scripts it chains with `npm run`. */
function tscRuns(name) {
  return scripts[name].split('&&').reduce((total, command) => {
    const chained = command.trim().match(/^npm run (\S+)/);
    return total + (chained ? tscRuns(chained[1]) : /\btsc\b/.test(command) ? 1 : 0);
  }, 0);
}

describe('type check', () => {
  /** Issue #464: `tsc -b` rechecked the whole project on every call, and `npm run check` ran it twice. */
  it('is incremental, with its cache out of the sources', () => {
    const options = JSON.parse(read('tsconfig.json')).compilerOptions;
    expect(options.incremental).toBe(true);
    expect(options.tsBuildInfoFile).toMatch(/^node_modules\//);
  });

  /** Issue #464: `build` repeated the type check of `typecheck`. */
  it('runs once in npm run check, and not again in the build', () => {
    expect(tscRuns('check')).toBe(1);
    expect(tscRuns('build')).toBe(0);
    expect(tscRuns('typecheck')).toBe(1);
  });
});

describe('Node version', () => {
  const pkg = JSON.parse(read('package.json'));

  /** Issue #515: nothing in the project said which Node it needs; `npm ci` stayed silent on a Node outside the guides. */
  it('is declared in engines as the guides say, and .nvmrc names one of them', () => {
    expect(pkg.engines?.node).toBe('^22.12.0 || ^24.0.0');
    expect(read('README.md')).toContain('Node 22.12 ou Node 24');
    expect(read('../AGENTS.md')).toContain('Node 22.12 or 24');
    expect(read('.nvmrc').trim()).toBe('24');
    expect(JSON.parse(read('package-lock.json')).packages[''].engines).toEqual(pkg.engines);
  });

  it('runs the ratchet, the linter and the formatter check in CI, in the web job', () => {
    const workflow = read('../.github/workflows/ci.yml');
    const web = workflow.slice(workflow.indexOf('\n  web:'), workflow.indexOf('\n  web-e2e:'));
    for (const script of ['check:ratchet', 'lint', 'format:check']) expect(web).toContain(`npm run ${script}`);
  });
});
