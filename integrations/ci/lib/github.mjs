import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { git, gitSha, sha256 } from './check.mjs';
import { reconcile } from './reconcile.mjs';
import { parseJsonObject } from './json.mjs';
import { approvedGitHubProfile } from './github-profile.mjs';
import { sameRepository, sameRepositoryUrl } from './github-identifiers.mjs';

const repositoryPattern = /^[a-z\d][a-z\d-]*\/[a-z\d_.-]+$/i;
const branchPattern = /^refs\/heads\/[\w./-]+$/;

// The one wrapper around the GitHub CLI: a `gh` that does not answer stops after 30 seconds instead of holding a job.
function run(args, input) {
  return execFileSync('gh', args, { encoding: 'utf8', timeout: 30_000, input }).trim();
}

export function gh(...args) {
  return run(args);
}

// For the calls that read their body from the standard input (`--input -`, `workflow run --json`).
export function ghWithInput(input, ...args) {
  return run(args, input);
}

// The tickets a PR declares, one per `OpenGuildKit-Ticket: #N` line.
export const ticketNumbers = body => [...(body ?? '').matchAll(/^OpenGuildKit-Ticket:[ \t]*#([1-9]\d*)[ \t]*\r?$/gm)]
  .map(match => match[1]);

// Files `bytes` at `path` on `branch`, and returns the commit that holds them: the one that already does, or a new one.
export function archiveFile({ project, branch, path, bytes, message, subject }) {
  const endpoint = `repos/${project}/contents/${path}`;
  let saved;
  try {
    saved = JSON.parse(gh('api', `${endpoint}?ref=${encodeURIComponent(branch)}`));
  } catch (error) {
    if (!String(error.stderr).includes('HTTP 404')) throw error;
  }
  let commit;
  if (saved) {
    if (!Buffer.from(saved.content, 'base64').equals(bytes)) {
      throw new Error(`The existing ${subject} differs from the expected ${subject}.`);
    }
    commit = gh('api', '--method', 'GET', `repos/${project}/commits`,
      '-f', `sha=${branch}`, '-f', `path=${path}`, '-F', 'per_page=1', '--jq', '.[0].sha');
  } else {
    const input = JSON.stringify({ branch, message, content: bytes.toString('base64') });
    commit = JSON.parse(ghWithInput(input, 'api', endpoint, '--method', 'PUT', '--input', '-')).commit.sha;
  }
  if (!gitSha.test(commit)) throw new Error(`GitHub did not confirm the commit of the ${subject}.`);
  return commit;
}

// The combined status lists the latest status of each context, one page at a time.
export function latestStatus(project, commit, context, request = gh) {
  const pages = JSON.parse(request('api', '--paginate', '--slurp', `repos/${project}/commits/${commit}/status?per_page=100`));
  return pages.flatMap(page => page.statuses ?? []).find(item => item.context === context);
}

export function sameStatus(item, { state, description, url }) {
  return item?.state === state && item.description === description && (item.target_url || undefined) === url;
}

export function approveGitHubProfile(options, request = gh) {
  return approvedGitHubProfile(options, (endpoint, ...args) => JSON.parse(request('api', ...args, endpoint)));
}

export function readGitHubTicket({ repo, pullRequest, commit }, api = endpoint => JSON.parse(gh('api', endpoint))) {
  if (!repositoryPattern.test(repo) || !Number.isSafeInteger(pullRequest) || pullRequest < 1 || !gitSha.test(commit)) {
    throw new Error('A GitHub repository, a PR number and a full SHA are required.');
  }
  const pullUrl = `https://github.com/${repo}/pull/${pullRequest}`;
  const pr = api(`repos/${repo}/pulls/${pullRequest}`);
  if (pr.state !== 'open' || pr.head.sha !== commit || !sameRepositoryUrl(pr.html_url, pullUrl)) {
    throw new Error('The PR or its current commit no longer matches the request.');
  }
  const links = ticketNumbers(pr.body);
  if (links.length !== 1) throw new Error('The PR must declare a single ticket with OpenGuildKit-Ticket: #NUMBER.');
  const [number] = links;
  const issue = api(`repos/${repo}/issues/${number}`);
  if (issue.pull_request || !sameRepositoryUrl(issue.html_url, `https://github.com/${repo}/issues/${number}`)) {
    throw new Error('The reference must point to a ticket in the repository of the PR.');
  }
  return {
    issue, source: { pullRequest: pr.html_url, commit, ticketUpdatedAt: issue.updated_at },
  };
}

function fetch(repo, id, refspecs) {
  execFileSync('git', ['-C', repo, '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
    'fetch', '--quiet', '--atomic', '--no-tags', '--no-write-fetch-head',
    `https://github.com/${id}.git`, ...refspecs], { timeout: 120_000 });
}

function validateRepo(id, path, ref) {
  if (typeof id !== 'string' || !repositoryPattern.test(id) || typeof path !== 'string' || !path ||
      typeof ref !== 'string' || !branchPattern.test(ref)) {
    throw new Error('A GitHub repository, a clone path and a trusted branch refs/heads/… are required.');
  }
  git(path, 'check-ref-format', ref);
}

// Only the PRs into the profile branch are judged by its profile. A PR into another branch follows that branch's rules.
function listPullRequests(id, base, numbers, request, errors) {
  const endpoint = `repos/${id}/pulls?state=open&base=${encodeURIComponent(base)}&per_page=100`;
  const all = JSON.parse(request('api', '--paginate', '--slurp', endpoint)).flat();
  return all.filter(pr => pr.base?.ref === base && (!numbers || numbers.includes(pr.number))).flatMap(pr => {
    const repository = pr.base?.repo?.full_name;
    if (pr.state !== 'open' || !Number.isSafeInteger(pr.number) || pr.number < 1 ||
        !gitSha.test(pr.head?.sha) || !sameRepository(repository, id)) {
      const pullRequest = Number.isSafeInteger(pr.number) ? { pullRequest: pr.number } : {};
      errors.push({ project: id, ...pullRequest, message: `Invalid GitHub PR in ${id}.` });
      return [];
    }
    return [{ number: pr.number, sha: pr.head.sha, repository }];
  });
}

function synchronizeProject(project, folder, { request, fetchRefs }, errors) {
  validateRepo(project.id, resolve(folder, project.path), project.profileRef);
  if (project.prNumbers !== undefined && (!Array.isArray(project.prNumbers) ||
      project.prNumbers.some(number => !Number.isSafeInteger(number) || number < 1))) {
    throw new Error('prNumbers must contain positive PR numbers.');
  }
  const target = resolve(folder, project.path);
  const namespace = `refs/openguildkit/projects/${sha256(`${project.id}:${project.profileRef}`)}`;
  let profileRef = `${namespace}/profile`;
  const base = project.profileRef.slice('refs/heads/'.length);
  const listed = listPullRequests(project.id, base, project.prNumbers, request, errors).map(pr => ({
    ...pr, ref: `${namespace}/pull/${pr.number}`,
  }));
  const refspecs = listed.map(pr => `+refs/pull/${pr.number}/head:${pr.ref}`);
  fetchRefs(target, project.id, [`+${project.profileRef}:${profileRef}`, ...refspecs]);
  const tip = listed.length > 0 && git(target, 'rev-parse', '--verify', profileRef).toString().trim();
  const profile = tip && parseJsonObject(git(target, 'show', `${tip}:openguildkit.json`), 'openguildkit.json');
  // An adoption profile states its own approval. Only the merged proposal PR on GitHub can confirm it.
  if (profile && profile.adoption !== undefined && project.profileMaintainer === undefined) {
    throw new Error(`Set profileMaintainer for ${project.id}: an adopted profile is only accepted after ` +
      'verifying the proposal PR merged by that maintainer.');
  }
  if (profile && project.profileMaintainer !== undefined) {
    const approved = approveGitHubProfile({
      repo: project.id, pullRequest: profile.adoption?.approval?.pullRequest,
      base, maintainer: project.profileMaintainer,
    }, request);
    if (!isDeepStrictEqual(profile, approved)) {
      throw new Error(`The active profile of ${project.id} differs from the approved proposal.`);
    }
    try {
      git(target, 'merge-base', '--is-ancestor', approved.adoption.approval.mergeCommit, tip);
    } catch {
      throw new Error(`The approval of ${project.id} was not merged into ${project.profileRef}.`);
    }
    profileRef = `${namespace}/approved-profiles/${tip}`;
    git(target, 'update-ref', profileRef, tip);
  }
  // A PR pushed between the listing and the fetch is evaluated on the next synchronization.
  const pullRequests = listed.filter(pr => {
    if (git(target, 'rev-parse', '--verify', pr.ref).toString().trim() === pr.sha) return true;
    errors.push({ project: project.id, pullRequest: pr.number,
      message: `PR ${project.id}#${pr.number} changed during loading. Run the synchronization again.` });
    return false;
  });
  const id = listed[0]?.repository ?? project.id;
  return { id, path: project.path, profileRef, pullRequests, waiverApprovers: project.waiverApprovers };
}

// An error on the policy repository stops everything. An error on one project or one PR is reported for that item.
function synchronize(configPath, dependencies) {
  const config = parseJsonObject(readFileSync(configPath), configPath);
  const folder = dirname(resolve(configPath));
  const policy = config.policyRepo;
  const policyPath = resolve(folder, policy.path);
  validateRepo(policy.id, policyPath, policy.ref);
  if (!Array.isArray(config.projects)) throw new Error('projects must be a list.');

  const policyRef = `refs/openguildkit/policy/${sha256(`${policy.id}:${policy.ref}`)}`;
  dependencies.fetchRefs(policyPath, policy.id, [`+${policy.ref}:${policyRef}`]);
  const errors = [];
  const projects = config.projects.flatMap(project => {
    try {
      return [synchronizeProject(project, folder, dependencies, errors)];
    } catch (error) {
      errors.push({ project: project.id, message: error.message });
      return [];
    }
  });
  return { policyRepo: { path: policy.path, ref: policyRef, waiversPath: policy.waiversPath }, projects, errors };
}

// The open PRs of a repository, with the head and the statuses of each, in one GraphQL query: the cost of reading
// them does not grow with the number of PRs. The statuses are those of the head commit, in the shape of the REST API.
const openPullsQuery = `query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 100, after: $endCursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number state headRefOid body
        commits(last: 1) { nodes { commit { oid status { contexts { context state description targetUrl } } } } }
      }
    }
  }
}`;

export function readOpenPulls(project, request = gh) {
  const [owner, name] = project.split('/');
  const pages = JSON.parse(request('api', 'graphql', '--paginate', '--slurp',
    '-f', `query=${openPullsQuery}`, '-f', `owner=${owner}`, '-f', `name=${name}`));
  const nodes = pages.flatMap(page => {
    const found = page.data?.repository?.pullRequests?.nodes;
    if (!Array.isArray(found)) throw new Error(`GitHub did not list the open PRs of ${project}.`);
    return found;
  });
  return new Map(nodes.map(pr => {
    const { oid, status } = pr.commits?.nodes?.[0]?.commit ?? {};
    // Statuses of another commit than the head say nothing about the head: they are left out, and the write goes on.
    const contexts = oid === pr.headRefOid ? (status?.contexts ?? []).map(item => ({
      context: item.context, state: String(item.state).toLowerCase(), description: item.description, target_url: item.targetUrl,
    })) : undefined;
    return [pr.number, { state: String(pr.state).toLowerCase(), head: pr.headRefOid, body: pr.body, statuses: contexts }];
  }));
}

// Reads the open PRs of each repository once, when the first PR of that repository is published, and keeps the answer
// (or the failure) for the others.
export function openPullReader(request = gh) {
  const read = new Map();
  return project => {
    const key = project.toLowerCase();
    if (!read.has(key)) {
      try {
        read.set(key, { pulls: readOpenPulls(project, request) });
      } catch (error) {
        read.set(key, { error });
      }
    }
    const { pulls, error } = read.get(key);
    if (error) throw error;
    return pulls;
  };
}

// The head is read again right before a write: the snapshot is as old as the cycle, a push may have come since.
export function headStillIs(project, pullRequest, commit, request = gh) {
  const pr = JSON.parse(request('api', `repos/${project}/pulls/${pullRequest}`));
  return pr.state === 'open' && pr.head.sha === commit;
}

function publishObservation(entry, reportUrl, request, pulls) {
  const { project, pullRequest, commit, policyCommit, profileCommit, work } = entry;
  const status = entry.decision.effectiveStatus;
  const pr = pulls(project).get(pullRequest);
  if (pr?.state !== 'open' || pr.head !== commit) return { work, posted: false };

  const state = { success: 'success', failure: 'success', waived: 'success', pending: 'pending', error: 'error' }[status];
  const label = { success: 'Compliant', failure: 'Deviation', waived: 'Waived', pending: 'Pending', error: 'Undetermined' }[status];
  const description = `${label} (obs.) | rule ${policyCommit.slice(0, 12)} | profile ${profileCommit.slice(0, 12)} | ${work.slice(0, 12)}`;
  const context = `openguildkit/observation-pr-${pullRequest}`;
  if (sameStatus(pr.statuses?.find(item => item.context === context), { state, description, url: reportUrl })) {
    return { work, posted: false };
  }
  if (!headStillIs(project, pullRequest, commit, request)) return { work, posted: false };
  const target = reportUrl ? ['-f', `target_url=${reportUrl}`] : [];
  request('api', `repos/${project}/statuses/${commit}`, '-f', `context=${context}`, '-f', `state=${state}`, '-f', `description=${description}`, ...target);
  return { work, posted: true };
}

export function reconcileGithub({ publish, reportUrl, ...options }, { request = gh, fetchRefs = fetch } = {}) {
  if (reportUrl !== undefined && (!publish || !['http:', 'https:'].includes(new URL(reportUrl).protocol))) {
    throw new Error('--report-url requires --publish and an HTTP or HTTPS URL.');
  }
  const result = reconcile({
    ...options, sameProject: sameRepository, loadConfig: () => synchronize(options.configPath, { request, fetchRefs }),
  });
  if (publish) {
    result.publications = [];
    const pulls = openPullReader(request);
    for (const entry of result.current) {
      try {
        result.publications.push(publishObservation(entry, reportUrl, request, pulls));
      } catch (error) {
        result.errors.push({ work: entry.work, message: error.message });
      }
    }
  }
  return result;
}
