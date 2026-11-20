import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { evaluate } from './demo/check.mjs';

const [policyRepo, policyCommit, targetRepo, targetCommit, output] = process.argv.slice(2);
if (!policyRepo || !targetRepo || !output ||
    !/^[a-f0-9]{40}$/.test(policyCommit) || !/^[a-f0-9]{40}$/.test(targetCommit)) {
  console.error('Usage: node prototype/verify-refs.mjs POLICY_REPO POLICY_SHA TARGET_REPO TARGET_SHA OUTPUT_DIR');
  process.exit(2);
}

function readJsonAtCommit(repo, sha, path) {
  const content = execFileSync('git', ['-C', repo, 'show', `${sha}:${path}`], { encoding: 'utf8' });
  return JSON.parse(content);
}

try {
  const rule = readJsonAtCommit(policyRepo, policyCommit, 'policy/export-link.json');
  const config = readJsonAtCommit(targetRepo, targetCommit, 'export.json');
  const result = evaluate(rule, policyCommit, targetCommit, config);
  const evidence = JSON.stringify(result, null, 2) + '\n';
  mkdirSync(output, { recursive: true });
  writeFileSync(join(output, 'AGENTS.md'), result.guidance + '\n');
  writeFileSync(join(output, 'evidence.json'), evidence);
  process.stdout.write(evidence);
  process.exitCode = result.state === 'success' ? 0 : 1;
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
