import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { sameRepositoryUrl } from '../lib/github-identifiers.mjs';
import { latestStatus, sameStatus } from '../lib/github.mjs';

function gh(args, input) {
  return execFileSync('gh', args, { encoding: 'utf8', input }).trim();
}

function publish([repo, file, context = 'openguildkit/pilot-jenkins']) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !file || !/^openguildkit\/[a-z\d/-]+$/.test(context)) {
    throw new Error('Dépôt, rapport ou contexte de statut invalide.');
  }
  const bytes = readFileSync(file);
  const report = JSON.parse(bytes);
  if (![report.commit, report.policyCommit].every(sha => /^[a-f0-9]{40}$/.test(sha)) ||
      !/^\d+\.\d+\.\d+$/.test(report.kitVersion) || !/^[a-f0-9]{64}$/.test(report.profileSha256) ||
      !['success', 'failure'].includes(report.state)) {
    throw new Error('Le rapport ne contient pas les références attendues.');
  }

  function verifyAgentPull() {
    const number = report.pullRequest?.split('/').at(-1);
    if (!/^[1-9]\d*$/.test(number) || !/^[a-f0-9]{64}$/.test(report.briefSha256) ||
        !sameRepositoryUrl(report.pullRequest, `https://github.com/${repo}/pull/${number}`)) {
      throw new Error('PR ou empreinte du brief invalide.');
    }
    const pr = JSON.parse(gh(['api', `repos/${repo}/pulls/${number}`]));
    if (!sameRepositoryUrl(pr.html_url, report.pullRequest) || pr.state !== 'open' || pr.head.sha !== report.commit) {
      throw new Error('La PR ou son commit courant ne correspond plus au rapport.');
    }
  }

  const agentProof = report.briefSha256 !== undefined;
  if (agentProof) verifyAgentPull();
  const branch = 'pilot/evidence';
  const suffix = agentProof ? `-${report.briefSha256}` : '';
  const path = `evidence/${report.commit}/${report.kitVersion}/${report.policyCommit}-${report.profileSha256}${suffix}.json`;
  const endpoint = `repos/${repo}/contents/${path}`;
  const content = bytes.toString('base64');
  let evidenceCommit;
  try {
    const saved = JSON.parse(gh(['api', `${endpoint}?ref=${encodeURIComponent(branch)}`]));
    if (!Buffer.from(saved.content, 'base64').equals(bytes)) throw new Error('Preuve existante différente.');
    evidenceCommit = gh(['api', `repos/${repo}/commits`, '--method', 'GET',
      '-f', `sha=${branch}`, '-f', `path=${path}`, '-F', 'per_page=1', '--jq', '.[0].sha']);
  } catch (error) {
    if (!String(error.stderr).includes('HTTP 404')) throw error;
    const created = gh(['api', endpoint, '--method', 'PUT', '--input', '-'],
      JSON.stringify({ branch, message: 'Archive OpenGuildKit Jenkins evidence', content }));
    evidenceCommit = JSON.parse(created).commit.sha;
  }
  const observation = report.state === 'success' ? 'Conforme' : 'Écart';
  const url = `https://github.com/${repo}/blob/${evidenceCommit}/${path}`;
  if (agentProof) verifyAgentPull();
  const description = `${observation} (obs.) | règle ${report.policyCommit}`;
  if (!sameStatus(latestStatus(repo, report.commit, context), { state: 'success', description, url })) {
    gh(['api', `repos/${repo}/statuses/${report.commit}`, '-f', `context=${context}`,
      '-f', 'state=success', '-f', `description=${description}`, '-f', `target_url=${url}`]);
  }
  console.log(url);
}

// The report is an observation: publishing it succeeds or fails with 2, like an evaluation that could not run.
try {
  publish(process.argv.slice(2));
} catch (error) {
  console.error(error.message);
  process.exitCode = 2;
}
