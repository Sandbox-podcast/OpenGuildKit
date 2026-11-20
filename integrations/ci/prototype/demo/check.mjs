import { execFileSync } from 'node:child_process';
import { appendFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export const isCatalogVersion = version => typeof version === 'string' &&
  /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version);

export function describeRule(rule, source) {
  const catalogVersion = rule.format === 'catalog' && isCatalogVersion(rule.version);
  if (rule.id !== 'export-link-expiry' ||
      (!catalogVersion && (!Number.isSafeInteger(rule.version) || rule.version < 1)) ||
      !Number.isSafeInteger(rule.maxMinutes) || rule.maxMinutes < 1 ||
      !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(source)) {
    throw new Error('Règle ou références Git invalides.');
  }
  return {
    rule: rule.id, version: rule.version, policyCommit: source, maxMinutes: rule.maxMinutes,
    guidance: catalogVersion
      ? `Limit downloadLinkMinutes in export.json to ${rule.maxMinutes} minutes.`
      : `Pour tout export, limiter downloadLinkMinutes à ${rule.maxMinutes} minutes (règle v${rule.version}).`,
  };
}

export function evaluate(rule, source, commit, config) {
  const details = describeRule(rule, source);
  if (!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(commit)) throw new Error('Commit Git invalide.');
  const actualMinutes = config.downloadLinkMinutes;
  const passes = Number.isSafeInteger(actualMinutes) &&
    actualMinutes > 0 && actualMinutes <= rule.maxMinutes;
  return {
    ...details,
    commit,
    actualMinutes,
    state: passes ? 'success' : 'failure',
  };
}

if (process.env.GITHUB_ACTIONS === 'true' && process.argv[1] &&
    pathToFileURL(process.argv[1]).href === import.meta.url) {
  const { POLICY_JSON, POLICY_COMMIT, TARGET_COMMIT, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY } = process.env;
  if (!/^[a-f0-9]{40}$/.test(TARGET_COMMIT)) {
    throw new Error('Commit à vérifier invalide.');
  }
  const config = JSON.parse(execFileSync('git', ['show', `${TARGET_COMMIT}:export.json`], { encoding: 'utf8' }));
  const result = evaluate(JSON.parse(POLICY_JSON), POLICY_COMMIT, TARGET_COMMIT, config);
  const actual = Number.isSafeInteger(result.actualMinutes) ? result.actualMinutes : 'invalid';
  const description = `v${result.version}: ${actual} min (max ${result.maxMinutes} min) | règle ${result.policyCommit}`;
  appendFileSync(GITHUB_OUTPUT, `state=${result.state}\ndescription=${description}\n`);
  const report = JSON.stringify(result, null, 2);
  const codeFence = '```';
  appendFileSync(GITHUB_STEP_SUMMARY, `## OpenGuildKit\n\n${result.guidance}\n\n${codeFence}json\n${report}\n${codeFence}\n`);
  console.log(report);
}
