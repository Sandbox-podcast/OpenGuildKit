import { execFileSync, spawnSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { withInstalledKit } from './install-kit.mjs';

// Same exit codes as openguildkit-ci check: 1 when the rule fails and blocks, 2 when nothing could be evaluated.
try {
  const [policyRepo, policyCommit, targetCommit, output] = process.argv.slice(2);
  if (!policyRepo || !output || ![policyCommit, targetCommit].every(sha => /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(sha))) {
    throw new Error('Usage: node pilot/run-kit.mjs POLICY_REPO POLICY_SHA TARGET_SHA OUTPUT_DIR');
  }
  const kit = JSON.parse(execFileSync('git', ['show', 'HEAD:openguildkit-kit.json'], { encoding: 'utf8' }));
  process.exitCode = withInstalledKit(kit, (bin, install) => {
    const cli = join(bin, 'openguildkit.mjs');
    const profile = join(install, 'openguildkit.json');
    writeFileSync(profile, execFileSync('git', ['show', 'HEAD:openguildkit.json']));
    const result = spawnSync(process.execPath, [cli, 'check', '--policy-repo', policyRepo,
      '--policy-commit', policyCommit, '--commit', targetCommit, '--profile', profile,
      '--output', output], { stdio: 'inherit' });
    if (result.error) throw result.error;
    return result.status ?? 2;
  });
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
