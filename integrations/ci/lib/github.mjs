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

export function gh(...args) {
  return execFileSync('gh', args, { encoding: 'utf8', timeout: 30_000 }).trim();
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
    throw new Error('Dépôt GitHub, numéro de PR et SHA complet requis.');
  }
  const pullUrl = `https://github.com/${repo}/pull/${pullRequest}`;
  const pr = api(`repos/${repo}/pulls/${pullRequest}`);
  if (pr.state !== 'open' || pr.head.sha !== commit || !sameRepositoryUrl(pr.html_url, pullUrl)) {
    throw new Error('La PR ou son commit courant ne correspond plus à la demande.');
  }
  const links = [...(pr.body ?? '').matchAll(/^OpenGuildKit-Ticket:[ \t]*#([1-9]\d*)[ \t]*\r?$/gm)];
  if (links.length !== 1) throw new Error('La PR doit déclarer un seul ticket avec OpenGuildKit-Ticket: #NUMERO.');
  const number = links[0][1];
  const issue = api(`repos/${repo}/issues/${number}`);
  if (issue.pull_request || !sameRepositoryUrl(issue.html_url, `https://github.com/${repo}/issues/${number}`)) {
    throw new Error('La référence doit désigner un ticket du dépôt de la PR.');
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
    throw new Error('Dépôt GitHub, chemin du clone et branche de confiance refs/heads/… requis.');
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
      errors.push({ project: id, ...pullRequest, message: `PR GitHub invalide dans ${id}.` });
      return [];
    }
    return [{ number: pr.number, sha: pr.head.sha, repository }];
  });
}

function synchronizeProject(project, folder, { request, fetchRefs }, errors) {
  validateRepo(project.id, resolve(folder, project.path), project.profileRef);
  if (project.prNumbers !== undefined && (!Array.isArray(project.prNumbers) ||
      project.prNumbers.some(number => !Number.isSafeInteger(number) || number < 1))) {
    throw new Error('prNumbers doit contenir des numéros de PR positifs.');
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
      throw new Error(`Le profil actif de ${project.id} diffère de la proposition approuvée.`);
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
      message: `La PR ${project.id}#${pr.number} a évolué pendant le chargement. Relancer la synchronisation.` });
    return false;
  });
  const id = listed[0]?.repository ?? project.id;
  return { id, path: project.path, profileRef, pullRequests, waiverApprovers: project.waiverApprovers };
}

// An error on the policy repository stops everything. An error on one project or one PR is reported for that item.
function synchronize(configPath, dependencies) {
  const config = JSON.parse(readFileSync(configPath, 'utf8'));
  const folder = dirname(resolve(configPath));
  const policy = config.policyRepo;
  const policyPath = resolve(folder, policy.path);
  validateRepo(policy.id, policyPath, policy.ref);
  if (!Array.isArray(config.projects)) throw new Error('projects doit être une liste.');

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

function publishObservation(entry, reportUrl, request) {
  const { project, pullRequest, commit, policyCommit, profileCommit, work } = entry;
  const status = entry.decision.effectiveStatus;
  const pr = JSON.parse(request('api', `repos/${project}/pulls/${pullRequest}`));
  if (pr.state !== 'open' || pr.head.sha !== commit) return { work, posted: false };

  const state = { success: 'success', failure: 'success', waived: 'success', pending: 'pending', error: 'error' }[status];
  const label = { success: 'Compliant', failure: 'Deviation', waived: 'Waived', pending: 'Pending', error: 'Undetermined' }[status];
  const description = `${label} (obs.) | rule ${policyCommit.slice(0, 12)} | profile ${profileCommit.slice(0, 12)} | ${work.slice(0, 12)}`;
  const context = `openguildkit/observation-pr-${pullRequest}`;
  if (sameStatus(latestStatus(project, commit, context, request), { state, description, url: reportUrl })) {
    return { work, posted: false };
  }
  const target = reportUrl ? ['-f', `target_url=${reportUrl}`] : [];
  request('api', `repos/${project}/statuses/${commit}`, '-f', `context=${context}`, '-f', `state=${state}`, '-f', `description=${description}`, ...target);
  return { work, posted: true };
}

export function reconcileGithub({ publish, reportUrl, ...options }, { request = gh, fetchRefs = fetch } = {}) {
  if (reportUrl !== undefined && (!publish || !['http:', 'https:'].includes(new URL(reportUrl).protocol))) {
    throw new Error('--report-url requiert --publish et une URL HTTP ou HTTPS.');
  }
  const result = reconcile({
    ...options, sameProject: sameRepository, loadConfig: () => synchronize(options.configPath, { request, fetchRefs }),
  });
  if (publish) {
    result.publications = [];
    for (const entry of result.current) {
      try {
        result.publications.push(publishObservation(entry, reportUrl, request));
      } catch (error) {
        result.errors.push({ work: entry.work, message: error.message });
      }
    }
  }
  return result;
}
