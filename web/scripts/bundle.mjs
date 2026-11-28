// Copies the product build (web/dist, without the Atelier Nova demo) into the Python package, so the wheel
// ships the interface that `openguildkit ui` serves, and refuses a build that holds the demo, a style rule for a
// class no script of the build names, or exceeds its budget. Run after `npm run build`; the copy is ignored by Git.
import { cpSync, existsSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/**
 * Budget of the copy, in KB as `du -sk` counts them on 4 KB blocks: 1,148 KB measured on 27 November 2026 once the
 * demo was left out, the logo of the header shrunk and the header scenes re-exported in quality 82 (1,252 KB before),
 * plus 10 %. The build weighed 1,124 KB on 28 November 2026 once the demo's style rules left it (#500), 139 KB (11 %)
 * under the budget. Raise it only with the measure that justifies it.
 */
export const BUDGET_KB = 1263;

/** What only the demo uses: the product build must not contain them (vite.config.ts leaves them out). */
export const DEMO_ONLY = ['assets/world', 'assets/characters'];

/**
 * Classes of the demo that the product's sheets still style, because a later rule of the product with the same
 * specificity could apply to the same element: moved to src/demo/styles, which loads after, they would change the
 * cascade of the demo (#500). Each one stays here only while no script of the build names it.
 */
export const KEPT_FOR_THE_DEMO = new Set(
  (
    'ai-mark badge-box board-col bullets clickable closure entry-actions entry-copy entry-landscape form-grid guide-steps identity ' +
    'identity-text menu-pop mobile-context pickers responsive run-steps timeline timeline-bar today trace-col with-guide'
  ).split(' '),
);

/** Whether the scripts name a class, whole or by the prefix of a name composed at run time (`tone-${tone}`). */
function named(scripts, name) {
  if (scripts.includes(name)) return true;
  return [...name.matchAll(/-/g)].some(({ index }) =>
    ['${', '"', "'", '`'].some((end) => scripts.includes(name.slice(0, index + 1) + end)),
  );
}

/** The classes the style sheets target (outside :not()) that no script names, sorted. */
export function unnamedClasses(css, scripts) {
  const classes = new Set();
  for (const [, selector] of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(?:^|[{};])\s*([^{}@;][^{};]*)\{/g)) {
    const bare = selector.replace(/:not\((?:[^()]|\([^()]*\))*\)/g, '').replace(/\[[^\]]*\]/g, '');
    for (const [, name] of bare.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)) classes.add(name);
  }
  return [...classes].filter((name) => !named(scripts, name)).sort();
}

function texts(folder, extension) {
  const assets = join(folder, 'assets');
  if (!existsSync(assets)) return '';
  return readdirSync(assets)
    .filter((name) => name.endsWith(extension))
    .map((name) => readFileSync(join(assets, name), 'utf8'))
    .join('\n');
}

/** The size of a folder in KB, each file rounded up to 4 KB blocks, as `du -sk` reports it on most file systems. */
export function sizeKb(folder) {
  let total = 0;
  for (const entry of readdirSync(folder, { withFileTypes: true })) {
    const path = join(folder, entry.name);
    total += entry.isDirectory() ? sizeKb(path) : Math.ceil(statSync(path).size / 4096) * 4;
  }
  return total;
}

/** The problems that keep a build out of the package: no page, the demo, or more than the budget. */
export function bundleProblems(folder, budget = BUDGET_KB) {
  if (!existsSync(join(folder, 'index.html'))) return [`${folder}/index.html is missing: run npm run build first.`];
  const problems = DEMO_ONLY.filter((path) => existsSync(join(folder, path))).map(
    (path) => `${path} belongs to the demo: build with npm run build, not npm run build:demo.`,
  );
  const unused = unnamedClasses(texts(folder, '.css'), texts(folder, '.js')).filter((name) => !KEPT_FOR_THE_DEMO.has(name));
  if (unused.length)
    problems.push(
      `The CSS styles ${unused.map((name) => `.${name}`).join(', ')}, which no script of the build names: move the rule to src/demo/styles or drop it.`,
    );
  const size = sizeKb(folder);
  if (size > budget) problems.push(`The build takes ${size} KB, over its budget of ${budget} KB (BUDGET_KB in web/scripts/bundle.mjs).`);
  return problems;
}

function main() {
  const web = join(dirname(fileURLToPath(import.meta.url)), '..');
  const source = join(web, 'dist');
  const target = join(web, '..', 'src', 'openguildkit', 'web_dist');
  const problems = bundleProblems(source);
  if (problems.length) {
    for (const problem of problems) console.error(problem);
    process.exit(1);
  }
  rmSync(target, { recursive: true, force: true });
  // Source drawings (docs/art) are not part of the build; the interface needs only what Vite emitted.
  cpSync(source, target, { recursive: true });
  console.log(`Copied ${source} to ${target}: ${sizeKb(target)} KB of a ${BUDGET_KB} KB budget.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
