import { execFileSync, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { withInstalledKit } from './install-kit.mjs';

// Same exit codes as openguildkit-ci check: 1 when the rule fails and blocks, 2 when nothing could be evaluated.
try {
  const [config, destination] = process.argv.slice(2);
  if (!config || !destination) {
    throw new Error('Usage: node pilot/run-agent-jenkins.mjs CONFIG_JSON OUTPUT_DIR');
  }

  const { kit, repository, pr, commit, profileCommit, policyCommit, checkout } = JSON.parse(readFileSync(config, 'utf8'));
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository) || !Number.isSafeInteger(pr) || pr < 1 ||
      ![commit, profileCommit, policyCommit].every(sha => /^[a-f0-9]{40}$/.test(sha)) || typeof checkout !== 'string') {
    throw new Error('Invalid OpenGuildKit Jenkins configuration.');
  }
  const output = resolve(destination);
  const bundle = join(output, 'agent-bundle');
  const control = join(output, 'control');
  const prUrl = `https://github.com/${repository}/pull/${pr}`;

  process.exitCode = withInstalledKit(kit, (bin, install) => {
    const cli = join(bin, 'openguildkit.mjs');
    const refs = ['--target-repo', checkout, '--policy-repo', checkout,
      '--profile-commit', profileCommit, '--policy-commit', policyCommit];
    execFileSync(process.execPath, [cli, 'github-brief', '--repo', repository,
      '--pr', String(pr), '--commit', commit, ...refs, '--output', bundle], { stdio: 'inherit' });

    const requests = ['brief', 'guidance', 'write', 'publish'].map((method, index) => ({
      id: index + 1, method,
    }));
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
      ['PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'].includes(key.toUpperCase())));
    env.GH_CONFIG_DIR = join(install, 'agent-no-auth');
    env.GIT_TERMINAL_PROMPT = '0';
    const child = spawnSync(process.execPath, [join(bin, 'openguildkit-agent.mjs'), '--bundle', bundle], {
      input: requests.map(item => JSON.stringify(item)).join('\n') + '\n',
      encoding: 'utf8', env, cwd: bundle,
    });
    if (child.status !== 0) throw new Error(child.error?.message ?? child.stderr);
    const responses = child.stdout.trim().split('\n').map(line => JSON.parse(line));
    const audit = child.stderr.trim().split('\n').map(line => JSON.parse(line));
    if (responses.length !== requests.length || audit.length !== requests.length ||
        !responses[0].result || !responses[1].result || !responses[2].error || !responses[3].error ||
        audit.some((event, index) => event.method !== requests[index].method || event.allowed !== (index < 2))) {
      throw new Error('Unexpected decisions from the agent adapter.');
    }
    writeFileSync(join(output, 'agent-audit.jsonl'), child.stderr);
    const checked = spawnSync(process.execPath, [cli, 'check', ...refs, '--commit', commit,
      '--brief', join(bundle, 'brief.json'), '--pull-request', prUrl, '--output', control], { stdio: 'inherit' });
    if (checked.error) throw checked.error;
    return checked.status ?? 2;
  });
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
