import assert from 'node:assert/strict';
import { test } from 'node:test';
import { approvedGitHubProfile } from '../lib/github-profile.mjs';
import { readGitHubTicket } from '../lib/github.mjs';
import { sameRepositoryUrl } from '../lib/github-identifiers.mjs';

const commit = '1'.repeat(40);
const repository = 'Example/Portal';

test('GitHub URLs accept repository casing variants and retain exact resource identity', () => {
  const run = 'https://github.com/Example/Portal/actions/runs/42';
  assert.equal(sameRepositoryUrl(run, 'https://github.com/example/portal/actions/runs/42'), true);
  assert.equal(sameRepositoryUrl(run, 'https://github.com/example/portal/actions/runs/43'), false);
  assert.equal(sameRepositoryUrl(run, 'https://github.com/example/different/actions/runs/42'), false);
  assert.equal(sameRepositoryUrl(run, 'https://github.com.example.org/example/portal/actions/runs/42'), false);
});

test('profile approval and ticket lookup return the canonical GitHub repository', () => {
  const proposal = {
    schemaVersion: 1,
    owner: '@lead',
    policyPath: 'packs/export-link-expiry.json',
    targetPath: 'export.json',
    adoption: {
      state: 'proposed', mode: 'observation', inventoryCommit: commit, catalogCommit: commit,
      answers: { project: 'EXAMPLE/portal' },
    },
  };
  const pull = {
    merged: true, merged_by: { login: 'lead' }, merge_commit_sha: commit,
    base: { ref: 'main', repo: { full_name: repository } }, head: { sha: commit },
  };
  const approval = approvedGitHubProfile({
    repo: 'example/portal', pullRequest: 1, base: 'main', maintainer: 'lead',
  }, endpoint => {
    if (endpoint.includes('/files?')) return [[{ filename: '.openguildkit/proposal.json', status: 'added', sha: commit }]];
    if (endpoint.includes('/contents/')) return {
      type: 'file', encoding: 'base64', sha: commit,
      content: Buffer.from(JSON.stringify(proposal)).toString('base64'),
    };
    return pull;
  });
  assert.equal(approval.adoption.approval.repository, repository);

  const url = `https://github.com/${repository}`;
  const result = readGitHubTicket({ repo: 'example/portal', pullRequest: 2, commit }, endpoint =>
    endpoint.endsWith('/pulls/2')
      ? { state: 'open', head: { sha: commit }, html_url: `${url}/pull/2`, body: 'OpenGuildKit-Ticket: #3' }
      : { html_url: `${url}/issues/3` });
  assert.equal(result.source.pullRequest, `${url}/pull/2`);
  assert.equal(result.issue.html_url, `${url}/issues/3`);
});
