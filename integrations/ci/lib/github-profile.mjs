import { gitSha, parseProfile, sha256 } from './check.mjs';
import { sameRepository } from './github-identifiers.mjs';

const path = '.openguildkit/proposal.json';

export function approvedGitHubProfile({ repo, pullRequest, base, maintainer }, api) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !Number.isSafeInteger(pullRequest) || pullRequest < 1 ||
      typeof base !== 'string' || !/^[\w./-]+$/.test(base) ||
      typeof maintainer !== 'string' || !/^[a-z\d][a-z\d-]{0,38}$/i.test(maintainer)) {
    throw new Error('A repository, a PR number, a branch and the GitHub login of the maintainer are required.');
  }
  const endpoint = `repos/${repo}/pulls/${pullRequest}`;
  const pr = api(endpoint);
  const repository = pr.base?.repo?.full_name;
  if (pr.merged !== true || pr.base?.ref !== base || !sameRepository(repository, repo) ||
      pr.merged_by?.login?.toLowerCase() !== maintainer.toLowerCase() ||
      !gitSha.test(pr.merge_commit_sha) || !gitSha.test(pr.head?.sha)) {
    throw new Error('The proposal must be merged by the designated maintainer into the trusted branch.');
  }
  const files = api(`${endpoint}/files?per_page=100`, '--paginate', '--slurp').flat();
  const proposal = files.find(file => file.filename === path && ['added', 'modified'].includes(file.status));
  if (!proposal) throw new Error('The PR must modify the OpenGuildKit proposal.');
  const source = api(`repos/${repo}/contents/${path}?ref=${pr.merge_commit_sha}`);
  if (source.type !== 'file' || source.encoding !== 'base64' || source.sha !== proposal.sha) {
    throw new Error('The profile proposed in the PR must be carried over unchanged into the merge commit.');
  }
  const bytes = Buffer.from(source.content, 'base64');
  const profile = parseProfile(bytes, { allowProposal: true });
  if (profile.adoption?.state !== 'proposed' || profile.adoption.approval ||
      profile.owner.toLowerCase() !== `@${maintainer.toLowerCase()}` ||
      !sameRepository(profile.adoption.answers?.project, repository)) {
    throw new Error('The proposal must designate the configured repository and maintainer.');
  }
  return {
    ...profile,
    adoption: {
      ...profile.adoption, state: 'approved', approver: profile.owner,
      approval: {
        provider: 'github', repository, pullRequest, base, actor: pr.merged_by.login,
        proposalCommit: pr.head.sha, mergeCommit: pr.merge_commit_sha, proposalSha256: sha256(bytes),
      },
    },
  };
}
