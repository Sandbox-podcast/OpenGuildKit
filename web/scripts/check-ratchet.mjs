// Four rules the code does not meet yet, counted per file against a baseline frozen in style-baseline.json: a file may
// get better, never worse, and a file that got better must lower its number.
//   longLines       the lines of src/*.ts and src/*.tsx over MAX_LINE characters
//   indexedAccess   the errors tsc gives src/project and src/shared (tsconfig.index.json) with noUncheckedIndexedAccess,
//                   in every file they import: the product reaches into src/domain, src/adapters and src/fixtures
//   lint            the problems ESLint reports (eslint.config.mjs), among them the product importing the demo
//   unformatted     1 for each file Prettier would change (.prettierrc.json); a file formatted by `npm run format` stays so
// Run: npm run check:ratchet (longLines and indexedAccess), npm run lint, npm run format:check; or
// `node scripts/check-ratchet.mjs [rule...] [--update]`. `--update` writes the counts of these rules into the baseline
// when no file is worse (or when there is no baseline yet).
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const MAX_LINE = 140;

function sources(folder) {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    return statSync(path).isDirectory() ? sources(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

/** The lines of `src` over MAX_LINE characters, by file. */
export function longLines(root) {
  const counts = {};
  for (const path of sources(join(root, 'src'))) {
    const n = readFileSync(path, 'utf8').split('\n').filter((line) => line.length > MAX_LINE).length;
    if (n) counts[relative(root, path)] = n;
  }
  return counts;
}

/** The errors of `tsc --pretty false`, by file. */
export function parseTsc(output) {
  const counts = {};
  for (const [, file] of output.matchAll(/^(\S[^(\n]*)\(\d+,\d+\): error TS\d+/gm)) counts[file] = (counts[file] ?? 0) + 1;
  return counts;
}

/** The problems of `eslint --format json`, by file, clean files left out. */
export function parseEslint(json, root) {
  const counts = {};
  for (const { filePath, messages } of JSON.parse(json)) if (messages.length) counts[relative(root, filePath)] = messages.length;
  return counts;
}

/** The files of `prettier --list-different`, one each. */
export function parseList(output) {
  return Object.fromEntries(output.split('\n').filter(Boolean).map((file) => [file, 1]));
}

/** Runs a tool of node_modules (its `bin`) in `root`; the exit code is the tool's verdict, not a failure of the run. */
function tool(root, bin, args) {
  return spawnSync(process.execPath, [join(root, 'node_modules', bin), ...args], { cwd: root, encoding: 'utf8', maxBuffer: 1 << 28 });
}

function unsafeIndexes(root) {
  const run = tool(root, 'typescript/bin/tsc', ['-p', 'tsconfig.index.json', '--noEmit', '--pretty', 'false']);
  if (run.status === null || (run.status !== 0 && !/error TS\d+/.test(run.stdout))) throw new Error(`tsc failed: ${run.stderr || run.stdout}`);
  return parseTsc(run.stdout);
}

function lint(root) {
  const run = tool(root, 'eslint/bin/eslint.js', ['.', '--format', 'json']);
  if (!run.stdout.startsWith('[')) throw new Error(`eslint failed: ${run.stderr || run.stdout}`);
  return parseEslint(run.stdout, root);
}

function unformatted(root) {
  const run = tool(root, 'prettier/bin/prettier.cjs', ['--list-different', 'src', 'tests', 'scripts', '*.ts', '*.mjs']);
  if (run.status !== 0 && run.status !== 1) throw new Error(`prettier failed: ${run.stderr}`);
  return parseList(run.stdout);
}

/** Files that got worse (or are new with a deviation), and files that got better and must lower their number. */
export function compare(baseline, current) {
  const worse = [];
  const better = [];
  for (const file of [...new Set([...Object.keys(baseline), ...Object.keys(current)])].sort()) {
    const before = baseline[file] ?? 0;
    const now = current[file] ?? 0;
    if (now > before) worse.push(`${file}: ${now} (baseline ${before})`);
    else if (now < before) better.push(`${file}: ${now} (baseline ${before})`);
  }
  return { worse, better };
}

const RULES = { longLines, indexedAccess: unsafeIndexes, lint, unformatted };

function main() {
  const root = join(dirname(fileURLToPath(import.meta.url)), '..');
  const file = join(root, 'style-baseline.json');
  const update = process.argv.includes('--update');
  const named = process.argv.slice(2).filter((argument) => !argument.startsWith('--'));
  const unknown = named.filter((name) => !(name in RULES));
  if (unknown.length) { console.error(`Unknown rule: ${unknown.join(', ')}. Rules: ${Object.keys(RULES).join(', ')}.`); process.exit(2); }
  const rules = named.length ? named : Object.keys(RULES);
  const baseline = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
  const current = Object.fromEntries(rules.map((rule) => [rule, RULES[rule](root)]));
  const worse = [];
  const better = [];
  for (const rule of rules) {
    const found = compare(baseline[rule] ?? {}, current[rule]);
    worse.push(...found.worse.map((line) => `${rule}, worse: ${line}`));
    better.push(...found.better.map((line) => `${rule}, better: ${line}`));
  }
  if (update && (!rules.every((rule) => baseline[rule]) || !worse.length)) {
    writeFileSync(file, `${JSON.stringify({ ...baseline, ...current }, null, 2)}\n`);
    console.log(`Baseline of ${rules.join(', ')} written to ${relative(root, file)}.`);
  } else if (worse.length || better.length) {
    console.error([...worse, ...better].join('\n'));
    console.error(worse.length ? 'Fix the files that got worse.' : `Lock in the gain: node scripts/check-ratchet.mjs ${rules.join(' ')} --update`);
    process.exit(1);
  } else {
    for (const rule of rules) console.log(`${rule}: ${Object.values(current[rule]).reduce((a, b) => a + b, 0)} deviations in ${Object.keys(current[rule]).length} files, as in the baseline.`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
