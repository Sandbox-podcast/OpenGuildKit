import { gitSha } from './check.mjs';
import { gh, reconcileGithub } from './github.mjs';
import { inspectMergeProtection } from './merge-protection.mjs';

const githubApi = (endpoint, ...args) => JSON.parse(gh('api', endpoint, ...args));

export function mergeGithub({ base, execute, ruleset, appId, ...options }, {
  api = githubApi, reconcile = reconcileGithub, clock = Date.now,
} = {}) {
  const { project, pullRequest, commit } = options.selection;
  if (!/^[a-z\d][a-z\d-]*\/[a-z\d_.-]+$/i.test(project) ||
      !Number.isSafeInteger(pullRequest) || pullRequest < 1 || !gitSha.test(commit) || !base) {
    throw new Error('A GitHub repository, a PR, a full SHA and a target branch are required.');
  }
  const endpoint = `repos/${project}/pulls/${pullRequest}`;
  const readCandidate = () => {
    const pr = api(endpoint);
    if (pr.state !== 'open' || pr.draft !== false || pr.head?.sha !== commit ||
        pr.base?.ref !== base || !gitSha.test(pr.base?.sha) ||
        pr.base?.repo?.full_name?.toLowerCase() !== project.toLowerCase()) {
      throw new Error('The PR is no longer open and ready to merge at the requested SHA and target branch.');
    }
    return pr.base.sha;
  };

  const baseCommit = readCandidate();
  const gateOptions = { ...options, selection: { ...options.selection, mode: 'required' } };
  const assessed = reconcile({ ...gateOptions, run: true });
  const outcome = (current, errors) => {
    if (errors.length || current.decision.effectiveStatus === 'error') {
      return { exitCode: 2, reason: 'check-error' };
    }
    if (!current.decision.conditionMet) return { exitCode: 1, reason: current.decision.effectiveStatus };
    const { waiver } = current.decision;
    if (waiver && clock() >= Date.parse(waiver.expiresAt)) {
      return { exitCode: 1, reason: 'waiver-expired' };
    }
    return { exitCode: 0, reason: null };
  };
  const result = (current, errors, decision, merge = null) => ({
    current, base, baseCommit, errors, merge, executedEvidence: assessed.executedEvidence ?? [], ...decision,
  });
  const checked = assessed.current[0];
  const firstErrors = assessed.errors ?? [];
  const firstOutcome = outcome(checked, firstErrors);
  if (firstOutcome.exitCode || !execute) return result(checked, firstErrors, firstOutcome);

  const latest = reconcile({ ...gateOptions, run: false });
  const [current] = latest.current;
  if (readCandidate() !== baseCommit) {
    throw new Error('The target branch changed during the check. Run the merge request again.');
  }
  if (ruleset !== undefined && !inspectMergeProtection({ repo: project, base, ruleset, appId }, api).approved) {
    return result(current, [], { exitCode: 2, reason: 'inactive-branch-protection' });
  }
  const errors = latest.errors ?? [];
  const finalOutcome = outcome(current, errors);
  if (finalOutcome.exitCode) return result(current, errors, finalOutcome);
  const merge = api(`${endpoint}/merge`, '-X', 'PUT', '-f', `sha=${commit}`);
  if (merge.merged !== true || !gitSha.test(merge.sha)) {
    throw new Error('GitHub did not confirm the merge.');
  }
  return result(current, errors, finalOutcome, { commit: merge.sha, head: commit });
}
