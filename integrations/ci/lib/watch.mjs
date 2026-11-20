import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { gh, reconcileGithub } from './github.mjs';
import { sameRepositoryUrl } from './github-identifiers.mjs';
import { checkStateDirectory } from './state-directory.mjs';
import { publishWatchReport } from './github-report.mjs';

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function loadRun(path) {
  try {
    return readJson(path);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return null;
  }
}

function saveRun(path, run) {
  const temp = `${path}.tmp`;
  writeFileSync(temp, JSON.stringify(run, null, 2) + '\n', { flush: true });
  renameSync(temp, path);
}

const githubActions = {
  dispatch({ project, pullRequest, commit, work }, { file, ref }, attempt) {
    const output = execFileSync('gh', ['workflow', 'run', file, '-R', project, '--ref', ref, '--json'], {
      input: JSON.stringify({ pr: String(pullRequest), commit, work, attempt }), encoding: 'utf8', timeout: 30_000,
    }).trim();
    const match = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/actions\/runs\/(\d+)$/.exec(output);
    if (!match || !sameRepositoryUrl(output, `https://github.com/${project}/actions/runs/${match[1]}`)) {
      throw new Error('GitHub Actions n’a pas renvoyé d’identifiant d’exécution.');
    }
    return { id: match[1], url: output };
  },
  find({ project, work }, { file, ref, attempt, startedAt }) {
    const since = new Date(startedAt - 60_000).toISOString();
    const endpoint = `repos/${project}/actions/workflows/${encodeURIComponent(file)}/runs`;
    const pages = JSON.parse(gh('api', '--method', 'GET', '--paginate', '--slurp', endpoint,
      '-f', `branch=${ref}`, '-f', 'event=workflow_dispatch', '-f', `created=>=${since}`, '-F', 'per_page=100'));
    const title = `OpenGuildKit recheck ${work} ${attempt}`;
    const match = pages.flatMap(page => page.workflow_runs).find(run => run.display_title === title);
    if (!match) return null;
    const id = String(match.id);
    if (!/^\d+$/.test(id) || !sameRepositoryUrl(match.html_url, `https://github.com/${project}/actions/runs/${id}`)) {
      throw new Error('Exécution GitHub Actions retrouvée avec des références invalides.');
    }
    return { id, url: match.html_url };
  },
  status(project, id) {
    return JSON.parse(gh('run', 'view', id, '-R', project, '--json', 'status,conclusion'));
  },
  proof(project, id) {
    const folder = mkdtempSync(join(tmpdir(), 'openguildkit-actions-'));
    try {
      gh('run', 'download', id, '-R', project, '-n', 'openguildkit-recheck', '-D', folder);
      return readJson(join(folder, 'result.json'));
    } finally {
      rmSync(folder, { recursive: true, force: true });
    }
  },
};

const proofFields = ['commit', 'policyCommit', 'profileCommit', 'profileSha256', 'kitVersion',
  'rule', 'state', 'actualMinutes', 'maxMinutes', 'guidance', 'owner', 'targetPath', 'policyPath'];
const dispatchRecoveryMs = 120_000;

function startOrRecover(entry, workflow, path, run, actions, now) {
  if (run?.state === 'requesting') {
    const recovered = actions.find(entry, run);
    if (recovered) {
      const next = { ...run, ...recovered, state: 'dispatched', recovered: true };
      saveRun(path, next);
      return next;
    }
    if (now < run.startedAt + dispatchRecoveryMs) return run;
  }

  const request = {
    state: 'requesting', attempt: randomUUID(), startedAt: now, file: workflow.file, ref: workflow.ref,
  };
  saveRun(path, request);
  const dispatched = { ...request, ...actions.dispatch(entry, workflow, request.attempt), state: 'dispatched' };
  saveRun(path, dispatched);
  return dispatched;
}

export function watchGithub({ publish, ...options }, {
  reconcile = reconcileGithub, actions = githubActions, publishReport = publishWatchReport, clock = Date.now,
} = {}) {
  const { configPath, stateDir } = options;
  checkStateDirectory(stateDir);
  const config = readJson(configPath);
  const workflows = new Map(config.projects.map(({ id, workflow }) => {
    if (!workflow || !/^[\w.-]+\.ya?ml$/.test(workflow.file) ||
        typeof workflow.ref !== 'string' || !/^[\w./-]+$/.test(workflow.ref) || workflow.ref.startsWith('-')) {
      throw new Error(`Workflow de réévaluation absent ou invalide pour ${id}.`);
    }
    if (publish && (typeof workflow.evidenceBranch !== 'string' ||
        !/^[\w./-]+$/.test(workflow.evidenceBranch) || workflow.evidenceBranch.startsWith('-'))) {
      throw new Error(`Branche de rapports absente ou invalide pour ${id}.`);
    }
    return [id.toLowerCase(), workflow];
  }));
  const report = reconcile({ ...options, run: true });
  const errors = [...(report.errors ?? [])];
  const folder = join(stateDir, 'actions');
  mkdirSync(folder, { recursive: true });
  const targets = report.current.map(entry => {
    const path = join(folder, `${entry.work}.json`);
    const target = { ...entry, actions: null };
    if (!['success', 'failure'].includes(entry.status)) return target;
    try {
      let run = loadRun(path);
      if (!run?.id) {
        run = startOrRecover(entry, workflows.get(entry.project.toLowerCase()), path, run, actions, clock());
      } else if (run.state === 'dispatched') {
        const status = actions.status(entry.project, run.id);
        if (status.status === 'completed') {
          if (status.conclusion === 'success') {
            const remote = actions.proof(entry.project, run.id);
            const local = readJson(entry.evidence[0]).evidence;
            const matches = remote.work === entry.work && remote.project === entry.project &&
              remote.pullRequest === entry.pullRequest &&
              proofFields.every(field => isDeepStrictEqual(remote.proof?.[field], local[field]));
            run = { ...run, state: matches ? 'verified' : 'mismatch', proof: remote };
            if (matches) {
              run.verifiedAt = new Date().toISOString();
              run.jenkinsBuild = process.env.BUILD_NUMBER;
              run.jenkinsUrl = process.env.BUILD_URL;
            }
          } else {
            run = { ...run, id: null, state: 'retry', previous: { url: run.url, conclusion: status.conclusion } };
          }
          saveRun(path, run);
        }
      }
      target.actions = run;
      if (run.state === 'mismatch' || run.state === 'retry') {
        errors.push({ work: entry.work, message: `GitHub Actions : ${run.state} (${run.url}).` });
      }
    } catch (error) {
      target.actions = { state: 'error' };
      errors.push({ work: entry.work, message: error.message });
    }
    return target;
  });
  const result = { targets, executedEvidence: report.executedEvidence ?? [], errors };
  if (publish) {
    result.publications = [];
    if (!targets.length) return result;
    const latest = new Map(reconcile({ ...options, run: false }).current.map(entry => [entry.work, entry]));
    for (const target of targets) {
      const live = latest.get(target.work);
      if (!live || !isDeepStrictEqual(live.decision, target.decision)) continue;
      try {
        result.publications.push(publishReport(target, workflows.get(target.project.toLowerCase()).evidenceBranch));
      } catch (error) {
        errors.push({ work: target.work, message: error.message });
      }
    }
  }
  return result;
}
