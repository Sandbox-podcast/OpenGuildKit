import { readFileSync } from 'node:fs';
import { sameRepositoryUrl } from '../lib/github-identifiers.mjs';
import { archiveFile, gh, latestStatus, sameStatus } from '../lib/github.mjs';

function publish([repo, file, context = 'openguildkit/pilot-jenkins']) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !file || !/^openguildkit\/[a-z\d/-]+$/.test(context)) {
    throw new Error('Invalid repository, report or status context.');
  }
  const bytes = readFileSync(file);
  const report = JSON.parse(bytes);
  if (![report.commit, report.policyCommit].every(sha => /^[a-f0-9]{40}$/.test(sha)) ||
      !/^\d+\.\d+\.\d+$/.test(report.kitVersion) || !/^[a-f0-9]{64}$/.test(report.profileSha256) ||
      !['success', 'failure'].includes(report.state)) {
    throw new Error('The report does not contain the expected references.');
  }

  function verifyAgentPull() {
    const number = report.pullRequest?.split('/').at(-1);
    if (!/^[1-9]\d*$/.test(number) || !/^[a-f0-9]{64}$/.test(report.briefSha256) ||
        !sameRepositoryUrl(report.pullRequest, `https://github.com/${repo}/pull/${number}`)) {
      throw new Error('Invalid PR or brief digest.');
    }
    const pr = JSON.parse(gh('api', `repos/${repo}/pulls/${number}`));
    if (!sameRepositoryUrl(pr.html_url, report.pullRequest) || pr.state !== 'open' || pr.head.sha !== report.commit) {
      throw new Error('The PR or its current commit no longer matches the report.');
    }
  }

  const agentProof = report.briefSha256 !== undefined;
  if (agentProof) verifyAgentPull();
  const branch = 'pilot/evidence';
  const suffix = agentProof ? `-${report.briefSha256}` : '';
  const path = `evidence/${report.commit}/${report.kitVersion}/${report.policyCommit}-${report.profileSha256}${suffix}.json`;
  const evidenceCommit = archiveFile({ project: repo, branch, path, bytes, subject: 'evidence',
    message: 'Archive OpenGuildKit Jenkins evidence' });
  const observation = report.state === 'success' ? 'Compliant' : 'Deviation';
  const url = `https://github.com/${repo}/blob/${evidenceCommit}/${path}`;
  if (agentProof) verifyAgentPull();
  const description = `${observation} (obs.) | rule ${report.policyCommit}`;
  if (!sameStatus(latestStatus(repo, report.commit, context), { state: 'success', description, url })) {
    gh('api', `repos/${repo}/statuses/${report.commit}`, '-f', `context=${context}`,
      '-f', 'state=success', '-f', `description=${description}`, '-f', `target_url=${url}`);
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
