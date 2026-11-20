import { execFileSync } from 'node:child_process';
import { gitSha, sha256 } from './check.mjs';
import { gh, latestStatus, sameStatus } from './github.mjs';

function archive(entry, branch, markdown) {
  const { project, pullRequest, work } = entry;
  const path = `openguildkit/pr-${pullRequest}/${work}/${sha256(markdown)}.md`;
  const endpoint = `repos/${project}/contents/${path}`;
  let saved;
  try {
    saved = JSON.parse(gh('api', `${endpoint}?ref=${encodeURIComponent(branch)}`));
  } catch (error) {
    if (!String(error.stderr).includes('HTTP 404')) throw error;
  }
  let commit;
  if (saved) {
    if (Buffer.from(saved.content, 'base64').toString('utf8') !== markdown) {
      throw new Error('Le rapport existant diffère du rapport attendu.');
    }
    commit = gh('api', '--method', 'GET', `repos/${project}/commits`,
      '-f', `sha=${branch}`, '-f', `path=${path}`, '-F', 'per_page=1', '--jq', '.[0].sha');
  } else {
    const response = JSON.parse(execFileSync('gh', ['api', endpoint, '--method', 'PUT', '--input', '-'], {
      encoding: 'utf8', timeout: 30_000,
      input: JSON.stringify({
        branch, message: 'Archive OpenGuildKit CI report', content: Buffer.from(markdown).toString('base64'),
      }),
    }));
    commit = response.commit.sha;
  }
  if (!gitSha.test(commit)) throw new Error('GitHub n’a pas confirmé le commit du rapport.');
  return `https://github.com/${project}/blob/${commit}/${path}`;
}

const verdict = {
  success: 'Conforme', failure: 'Écart', waived: 'Dérogation', pending: 'En attente', error: 'Erreur',
};
const literal = value => `\`${String(value).replace(/[`\r\n]/g, ' ')}\``;

export function renderWatchReport(entry, ticket) {
  const { project, pullRequest, commit, profileCommit, policyCommit, rule, mode, actions, decision } = entry;
  const { proof } = actions.proof;
  const actual = Number.isSafeInteger(proof.actualMinutes) ? `${proof.actualMinutes} min` : 'invalide';
  const jenkins = actions.jenkinsUrl && /^https?:\/\/[^<>\s]+$/.test(actions.jenkinsUrl)
    ? `[Jenkins](<${actions.jenkinsUrl}>)`
    : `Jenkins${/^\d+$/.test(actions.jenkinsBuild) ? ` #${actions.jenkinsBuild}` : ''}`;
  const rows = [
    '# Rapport OpenGuildKit', '',
    `[PR #${pullRequest}](https://github.com/${project}/pull/${pullRequest})`,
    ticket ? ` · [Ticket #${ticket}](https://github.com/${project}/issues/${ticket})` : '', '',
    `**${verdict[decision.effectiveStatus]}** · ${mode === 'observation' ? 'Observation' : 'Contrôle obligatoire'}`, '',
    `- Commit évalué ${literal(commit)}`,
    `- Profil approuvé ${literal(profileCommit)} · Responsable ${literal(proof.owner)}`,
    `- Règle ${literal(rule)} · Révision ${literal(policyCommit)}`,
    `- Seuil ${proof.maxMinutes} min · Valeur ${actual}`,
    `- Consigne ${literal(proof.guidance)}`,
    `- ${jenkins} et [GitHub Actions](${actions.url}) · ${verdict[proof.state]}`,
    `- Vérifié le ${literal(actions.verifiedAt)}`,
  ];
  if (decision.waiver) {
    const { id, reason, approver, expiresAt, registryCommit } = decision.waiver;
    rows.push(`- Dérogation ${literal(id)} · ${literal(reason)} · ${literal(approver)} · ${literal(expiresAt)} · Registre ${literal(registryCommit)}`);
  }
  return rows.join('\n') + '\n';
}

export function publishWatchReport(entry, branch) {
  const { project, pullRequest, commit, work, actions, decision } = entry;
  const pr = JSON.parse(gh('api', `repos/${project}/pulls/${pullRequest}`));
  if (pr.state !== 'open' || pr.head?.sha !== commit) return { work, posted: false };
  const tickets = [...(pr.body ?? '').matchAll(/^OpenGuildKit-Ticket:[ \t]*#([1-9]\d*)[ \t]*\r?$/gm)];
  const verified = actions?.state === 'verified' && decision.effectiveStatus !== 'error';
  const url = verified ? archive(entry, branch, renderWatchReport(entry, tickets.length === 1 ? tickets[0][1] : null)) : undefined;
  const context = `openguildkit/report-pr-${pullRequest}`;
  const error = ['mismatch', 'retry', 'failed', 'error'].includes(actions?.state) || decision.effectiveStatus === 'error';
  const state = verified ? 'success' : error ? 'error' : 'pending';
  const label = verified ? verdict[decision.effectiveStatus] : error ? 'Erreur de vérification CI' : 'Rapport des deux CI en attente';
  const description = `${label} (info) | règle ${entry.policyCommit.slice(0, 12)} | ${work.slice(0, 12)}`;
  if (sameStatus(latestStatus(project, commit, context), { state, description, url })) {
    return { work, posted: false, url };
  }
  const link = url ? ['-f', `target_url=${url}`] : [];
  gh('api', `repos/${project}/statuses/${commit}`, '-f', `context=${context}`, '-f', `state=${state}`,
    '-f', `description=${description}`, ...link);
  return { work, posted: true, url };
}
