import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { git, gitSha, sha256 } from './check.mjs';
import { reconcile } from './reconcile.mjs';
import { approvedGitHubProfile } from './github-profile.mjs';
import { sameRepository, sameRepositoryUrl } from './github-identifiers.mjs';

const repositoryPattern = /^[a-z\d][a-z\d-]*\/[a-z\d_.-]+$/i;
const branchPattern = /^refs\/heads\/[\w./-]+$/;

export function gh(...args) {
  return execFileSync('gh', args, { encoding: 'utf8', timeout: 30_000 }).trim();
}

export function approveGitHubProfile(options) {
  return approvedGitHubProfile(options, (endpoint, ...args) => JSON.parse(gh('api', ...args, endpoint)));
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

function listPullRequests(id, numbers) {
  const all = JSON.parse(gh('api', '--paginate', '--slurp', `repos/${id}/pulls?state=open&per_page=100`)).flat();
  return all.filter(pr => !numbers || numbers.includes(pr.number)).map(pr => {
    const repository = pr.base?.repo?.full_name;
    if (pr.state !== 'open' || !Number.isSafeInteger(pr.number) || pr.number < 1 ||
        !gitSha.test(pr.head?.sha) || !sameRepository(repository, id)) {
      throw new Error(`PR GitHub invalide dans ${id}.`);
    }
    return { number: pr.number, sha: pr.head.sha, repository };
  });
}

function synchronize(configPath) {
  const config = JSON.parse(readFileSync(configPath, 'utf8'));
  const folder = dirname(resolve(configPath));
  const policy = config.policyRepo;
  const policyPath = resolve(folder, policy.path);
  validateRepo(policy.id, policyPath, policy.ref);
  for (const project of config.projects) {
    validateRepo(project.id, resolve(folder, project.path), project.profileRef);
    if (project.prNumbers !== undefined && (!Array.isArray(project.prNumbers) ||
        project.prNumbers.some(number => !Number.isSafeInteger(number) || number < 1))) {
      throw new Error('prNumbers doit contenir des numéros de PR positifs.');
    }
  }

  const policyRef = `refs/openguildkit/policy/${sha256(`${policy.id}:${policy.ref}`)}`;
  fetch(policyPath, policy.id, [`+${policy.ref}:${policyRef}`]);
  const projects = config.projects.map(project => {
    const target = resolve(folder, project.path);
    const namespace = `refs/openguildkit/projects/${sha256(`${project.id}:${project.profileRef}`)}`;
    let profileRef = `${namespace}/profile`;
    const pullRequests = listPullRequests(project.id, project.prNumbers).map(pr => ({
      ...pr, ref: `${namespace}/pull/${pr.number}`,
    }));
    const refspecs = pullRequests.map(pr => `+refs/pull/${pr.number}/head:${pr.ref}`);
    fetch(target, project.id, [`+${project.profileRef}:${profileRef}`, ...refspecs]);
    if (project.profileMaintainer !== undefined && pullRequests.length > 0) {
      const tip = git(target, 'rev-parse', '--verify', profileRef).toString().trim();
      const profile = JSON.parse(git(target, 'show', `${tip}:openguildkit.json`));
      const approved = approveGitHubProfile({
        repo: project.id, pullRequest: profile.adoption?.approval?.pullRequest,
        base: project.profileRef.slice('refs/heads/'.length), maintainer: project.profileMaintainer,
      });
      if (!isDeepStrictEqual(profile, approved)) {
        throw new Error(`Le profil actif de ${project.id} diffère de la proposition approuvée.`);
      }
      git(target, 'merge-base', '--is-ancestor', approved.adoption.approval.mergeCommit, tip);
      profileRef = `${namespace}/approved-profiles/${tip}`;
      git(target, 'update-ref', profileRef, tip);
    }
    for (const pr of pullRequests) {
      const fetched = git(target, 'rev-parse', '--verify', pr.ref).toString().trim();
      if (fetched !== pr.sha) {
        throw new Error(`La PR ${project.id}#${pr.number} a évolué pendant le chargement. Relancer la synchronisation.`);
      }
    }
    const id = pullRequests[0]?.repository ?? project.id;
    return { id, path: project.path, profileRef, pullRequests, waiverApprovers: project.waiverApprovers };
  });
  return { policyRepo: { path: policy.path, ref: policyRef, waiversPath: policy.waiversPath }, projects };
}

function publishObservation(entry, reportUrl) {
  const { project, pullRequest, commit, policyCommit, profileCommit, work } = entry;
  const status = entry.decision.effectiveStatus;
  const pr = JSON.parse(gh('api', `repos/${project}/pulls/${pullRequest}`));
  if (pr.state !== 'open' || pr.head.sha !== commit) return { work, posted: false };

  const state = { success: 'success', failure: 'success', waived: 'success', pending: 'pending', error: 'error' }[status];
  const label = { success: 'Conforme', failure: 'Écart', waived: 'Dérogation', pending: 'En attente', error: 'Contrôle indéterminé' }[status];
  const description = `${label} (obs.) | règle ${policyCommit.slice(0, 12)} | profil ${profileCommit.slice(0, 12)} | ${work.slice(0, 12)}`;
  const statuses = JSON.parse(gh('api', `repos/${project}/commits/${commit}/status`)).statuses;
  const context = `openguildkit/observation-pr-${pullRequest}`;
  if (statuses.some(item => item.context === context && item.state === state && item.description === description &&
      (item.target_url || undefined) === reportUrl)) {
    return { work, posted: false };
  }
  const target = reportUrl ? ['-f', `target_url=${reportUrl}`] : [];
  gh('api', `repos/${project}/statuses/${commit}`, '-f', `context=${context}`, '-f', `state=${state}`, '-f', `description=${description}`, ...target);
  return { work, posted: true };
}

export function reconcileGithub({ publish, reportUrl, ...options }) {
  if (reportUrl !== undefined && (!publish || !['http:', 'https:'].includes(new URL(reportUrl).protocol))) {
    throw new Error('--report-url requiert --publish et une URL HTTP ou HTTPS.');
  }
  const result = reconcile({
    ...options, sameProject: sameRepository, loadConfig: () => synchronize(options.configPath),
  });
  if (publish) result.publications = result.current.map(entry => publishObservation(entry, reportUrl));
  return result;
}
