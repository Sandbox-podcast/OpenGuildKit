import { gitSha, parseProfile, sha256 } from './check.mjs';

const path = '.openguildkit/proposal.json';

export function approvedGitHubProfile({ repo, pullRequest, base, maintainer }, api) {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo) || !Number.isSafeInteger(pullRequest) || pullRequest < 1 ||
      typeof base !== 'string' || !/^[\w./-]+$/.test(base) ||
      typeof maintainer !== 'string' || !/^[a-z\d][a-z\d-]{0,38}$/i.test(maintainer)) {
    throw new Error('Dépôt, numéro de PR, branche et identifiant GitHub du mainteneur requis.');
  }
  const endpoint = `repos/${repo}/pulls/${pullRequest}`;
  const pr = api(endpoint);
  if (pr.merged !== true || pr.base?.ref !== base || pr.base?.repo?.full_name !== repo ||
      pr.merged_by?.login?.toLowerCase() !== maintainer.toLowerCase() ||
      !gitSha.test(pr.merge_commit_sha) || !gitSha.test(pr.head?.sha)) {
    throw new Error('La proposition doit être fusionnée par le mainteneur désigné sur la branche de confiance.');
  }
  const files = api(`${endpoint}/files?per_page=100`, '--paginate', '--slurp').flat();
  const proposal = files.find(file => file.filename === path && ['added', 'modified'].includes(file.status));
  if (!proposal) throw new Error('La PR doit modifier la proposition OpenGuildKit.');
  const source = api(`repos/${repo}/contents/${path}?ref=${pr.merge_commit_sha}`);
  if (source.type !== 'file' || source.encoding !== 'base64' || source.sha !== proposal.sha) {
    throw new Error('Le profil proposé dans la PR doit être repris à l’identique dans le commit de fusion.');
  }
  const bytes = Buffer.from(source.content, 'base64');
  const profile = parseProfile(bytes, { allowProposal: true });
  if (profile.adoption?.state !== 'proposed' || profile.adoption.approval ||
      profile.owner.toLowerCase() !== `@${maintainer.toLowerCase()}` || profile.adoption.answers?.project !== repo) {
    throw new Error('La proposition doit désigner le dépôt et le mainteneur configurés.');
  }
  return {
    ...profile,
    adoption: {
      ...profile.adoption, state: 'approved', approver: profile.owner,
      approval: {
        provider: 'github', repository: repo, pullRequest, base, actor: pr.merged_by.login,
        proposalCommit: pr.head.sha, mergeCommit: pr.merge_commit_sha, proposalSha256: sha256(bytes),
      },
    },
  };
}
