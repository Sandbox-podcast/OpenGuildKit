import { spawnSync } from 'node:child_process';
import { readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { withInstalledKit } from './install-kit.mjs';

try {
  const { values } = parseArgs({ options: {
    kit: { type: 'string' }, config: { type: 'string' }, state: { type: 'string' }, publish: { type: 'boolean' },
  } });
  if (!values.kit || !values.config || !values.state) {
    throw new Error('Usage : node pilot/run-watch-jenkins.mjs --kit FILE --config FILE --state DIR [--publish]');
  }
  const output = resolve('result.json');
  if ([values.kit, values.config].some(path => resolve(path).toLowerCase() === output.toLowerCase())) {
    throw new Error('Le chemin result.json est réservé au rapport du job Jenkins.');
  }
  rmSync(output, { force: true });
  const kit = JSON.parse(readFileSync(values.kit, 'utf8'));
  process.exitCode = withInstalledKit(kit, bin => {
    const args = [join(bin, 'openguildkit.mjs'), 'watch', '--config', values.config, '--state', values.state];
    if (values.publish) args.push('--publish');
    const result = spawnSync(process.execPath, args, {
      encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, stdio: ['ignore', 'pipe', 'inherit'],
    });
    if (result.error) throw result.error;
    if (!result.stdout && result.status === 0) throw new Error('Le coordinateur n’a produit aucun rapport.');
    if (result.stdout) {
      JSON.parse(result.stdout);
      const temporary = `${output}.tmp`;
      try {
        writeFileSync(temporary, result.stdout, 'utf8');
        renameSync(temporary, output);
      } finally {
        rmSync(temporary, { force: true });
      }
    }
    return result.status ?? 2;
  }, { cacheDir: join(values.state, 'packages') });
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
