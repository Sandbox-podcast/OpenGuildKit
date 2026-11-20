import { execFileSync } from 'node:child_process';
import { evaluate } from './demo/check.mjs';

const [policyRepo, ...targets] = process.argv.slice(2);
const repoPattern = /^[\w.-]+\/[\w.-]+$/;
const targetPattern = /^([\w.-]+\/[\w.-]+)#([1-9]\d*)$/;
if (!policyRepo || !repoPattern.test(policyRepo) ||
    targets.length === 0 || targets.some(target => !targetPattern.test(target))) {
  throw new Error('Usage : node prototype/recheck.mjs PROPRIETAIRE/DEPOT-REGLE PROPRIETAIRE/DEPOT#PR [...]');
}

function gh(args, input) {
  return execFileSync('gh', args, { encoding: 'utf8', input }).trim();
}

const policyRef = process.env.OPENGUILDKIT_POLICY_REF || 'main';
const workflowRef = process.env.OPENGUILDKIT_WORKFLOW_REF || 'main';
const policyCommit = gh(['api', `repos/${policyRepo}/commits/${encodeURIComponent(policyRef)}`, '--jq', '.sha']);
const encodedPolicy = gh(['api', `repos/${policyRepo}/contents/policy/export-link.json?ref=${policyCommit}`, '--jq', '.content']);
const policyJson = Buffer.from(encodedPolicy, 'base64').toString('utf8');
const policy = JSON.parse(policyJson);
const { guidance } = evaluate(policy, policyCommit, policyCommit, {});
console.log(guidance);

for (const target of targets) {
  const [, repo, number] = target.match(targetPattern);
  const pr = JSON.parse(gh(['api', `repos/${repo}/pulls/${number}`]));
  if (pr.state !== 'open' || pr.head.repo?.full_name !== repo) {
    throw new Error(`PR ${target} : une PR ouverte depuis une branche du dépôt est requise.`);
  }
  const payload = JSON.stringify({
    target_commit: pr.head.sha,
    policy_commit: policyCommit,
    policy_json: JSON.stringify(policy),
  });
  const run = gh(['workflow', 'run', 'openguildkit.yml', '--repo', repo, '--ref', workflowRef, '--json'], payload);
  console.log(`${target} | commit ${pr.head.sha} | règle v${policy.version} | ${run || 'contrôle demandé'}`);
}
