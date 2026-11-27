// Two rules the code does not meet yet, counted per file against a baseline frozen in style-baseline.json: a file may
// get better, never worse, and a file that got better must lower its number. Run: npm run check:ratchet.
//   longLines       the lines of src/*.ts and src/*.tsx over MAX_LINE characters
//   indexedAccess   the errors tsc gives src/project and src/shared (tsconfig.index.json) with noUncheckedIndexedAccess,
//                   in every file they import: the product reaches into src/domain, src/adapters and src/fixtures
// `--update` writes the counts into the baseline when no file is worse (or when there is no baseline yet).
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
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

function unsafeIndexes(root) {
  const tsc = createRequire(join(root, 'package.json')).resolve('typescript/bin/tsc');
  const run = spawnSync(process.execPath, [tsc, '-p', 'tsconfig.index.json', '--noEmit', '--pretty', 'false'], { cwd: root, encoding: 'utf8', maxBuffer: 1 << 26 });
  if (run.status === null || (run.status !== 0 && !/error TS\d+/.test(run.stdout))) throw new Error(`tsc failed: ${run.stderr || run.stdout}`);
  return parseTsc(run.stdout);
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

const RULES = { longLines, indexedAccess: unsafeIndexes };

function main() {
  const root = join(dirname(fileURLToPath(import.meta.url)), '..');
  const file = join(root, 'style-baseline.json');
  const update = process.argv.includes('--update');
  const baseline = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : null;
  const current = Object.fromEntries(Object.entries(RULES).map(([rule, count]) => [rule, count(root)]));
  const worse = [];
  const better = [];
  for (const rule of Object.keys(RULES)) {
    const found = compare(baseline?.[rule] ?? {}, current[rule]);
    worse.push(...found.worse.map((line) => `${rule}, worse: ${line}`));
    better.push(...found.better.map((line) => `${rule}, better: ${line}`));
  }
  if (update && (!baseline || !worse.length)) {
    writeFileSync(file, `${JSON.stringify(current, null, 2)}\n`);
    console.log(`Baseline written to ${relative(root, file)}.`);
  } else if (worse.length || better.length) {
    console.error([...worse, ...better].join('\n'));
    console.error(worse.length ? 'Fix the files that got worse.' : 'Lock in the gain: npm run check:ratchet -- --update');
    process.exit(1);
  } else {
    for (const rule of Object.keys(RULES)) console.log(`${rule}: ${Object.values(current[rule]).reduce((a, b) => a + b, 0)} deviations in ${Object.keys(current[rule]).length} files, as in the baseline.`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
