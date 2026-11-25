import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import {
  mkdtempSync, mkdirSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync,
} from 'node:fs';
import { hostname, tmpdir } from 'node:os';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { gh, reconcileGithub } from './github.mjs';
import { sameRepository, sameRepositoryUrl } from './github-identifiers.mjs';
import { parseJsonObject } from './json.mjs';
import { checkStateDirectory } from './state-directory.mjs';
import { publishWatchReport } from './github-report.mjs';

function readJson(path) {
  return parseJsonObject(readFileSync(path), path);
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
  const temp = `${path}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temp, JSON.stringify(run, null, 2) + '\n', { flag: 'wx', flush: true });
    renameSync(temp, path);
  } finally {
    rmSync(temp, { force: true });
  }
}

const notFound = error => /HTTP 404/.test(`${error.stderr ?? ''} ${error.message ?? ''}`);

const githubActions = {
  dispatch({ project, pullRequest, commit, work }, { file, ref }, attempt, expected) {
    const output = execFileSync('gh', ['workflow', 'run', file, '-R', project, '--ref', ref, '--json'], {
      input: JSON.stringify({ pr: String(pullRequest), commit, work, attempt, expected: JSON.stringify(expected) }),
      encoding: 'utf8', timeout: 30_000,
    }).trim();
    const match = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/actions\/runs\/(\d+)$/.exec(output);
    if (!match || !sameRepositoryUrl(output, `https://github.com/${project}/actions/runs/${match[1]}`)) {
      throw new Error('GitHub Actions did not return a run ID.');
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
      throw new Error('The GitHub Actions run that was found has invalid references.');
    }
    return { id, url: match.html_url };
  },
  status(project, id) {
    try {
      return JSON.parse(gh('run', 'view', id, '-R', project, '--json', 'status,conclusion'));
    } catch (error) {
      if (notFound(error)) return { status: 'missing' };
      throw error;
    }
  },
  cancel(project, id) {
    gh('run', 'cancel', id, '-R', project);
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
  // The recheck template reads these two files from its trusted branch to compute the same work key.
  pins(project, ref) {
    const read = path => {
      const file = JSON.parse(gh('api', `repos/${project}/contents/${path}?ref=${encodeURIComponent(ref)}`));
      return Buffer.from(file.content, 'base64').toString('utf8');
    };
    return { settings: JSON.parse(read('pilot/recheck.json')), kit: read('pilot/recheck-kit.sha256') };
  },
};

const proofFields = ['commit', 'policyCommit', 'profileCommit', 'profileSha256', 'kitVersion',
  'rule', 'state', 'actualMinutes', 'maxMinutes', 'guidance', 'owner', 'targetPath', 'policyPath'];
const keyFields = ['project', 'pullRequest', 'commit', 'profileCommit', 'profileSha256', 'policyCommit',
  'rule', 'kitVersion'];
const dispatchRecoveryMs = 120_000;
const workPattern = /^[a-f0-9]{64}$/;
const minute = 60_000;

function watchLimits(settings = {}) {
  const { maxAttempts = 3, retryDelayMinutes = 15, runTimeoutMinutes = 360 } = settings;
  if (![maxAttempts, retryDelayMinutes, runTimeoutMinutes].every(value => Number.isSafeInteger(value) && value > 0)) {
    throw new Error('watch.maxAttempts, watch.retryDelayMinutes and watch.runTimeoutMinutes must be positive integers.');
  }
  return { maxAttempts, retryDelayMs: retryDelayMinutes * minute, runTimeoutMs: runTimeoutMinutes * minute };
}

function checkPins({ settings, kit }, policyRepo, project, kitVersion) {
  const [, asset] = String(kit).split('\n')[0].trim().split(/\s+/);
  const expected = [
    ['policyRepository', settings?.policyRepository, policyRepo?.id, sameRepository],
    ['policyRef', settings?.policyRef, policyRepo?.ref],
    ['profileRef', settings?.profileRef, project.profileRef],
    ['recheck-kit.sha256', asset, `openguildkit-${kitVersion}.tgz`],
  ];
  const differences = expected
    .filter(([, actual, wanted, same = (a, b) => a === b]) => !same(actual, wanted))
    .map(([name, actual, wanted]) => `${name} ${JSON.stringify(actual ?? null)} instead of ${JSON.stringify(wanted ?? null)}`);
  if (differences.length) {
    throw new Error(`The recheck workflow of ${project.id} at ${project.workflow.ref} would compute another work key: ` +
      `${differences.join('; ')}. Update pilot/recheck.json and pilot/recheck-kit.sha256 on that branch.`);
  }
}

function failAttempt(run, outcome, now, { maxAttempts, retryDelayMs }) {
  const attempts = run.attempts ?? 1;
  const previous = { url: run.url, ...outcome };
  if (attempts >= maxAttempts) return { ...run, id: null, state: 'failed', previous };
  return { ...run, id: null, state: 'retry', previous, nextAttemptAt: now + retryDelayMs * 2 ** (attempts - 1) };
}

function startOrRecover(entry, workflow, path, run, actions, now, limits, beforeDispatch) {
  if (run?.state === 'requesting') {
    const recovered = actions.find(entry, run);
    if (recovered) {
      const next = { ...run, ...recovered, state: 'dispatched', dispatchedAt: run.startedAt, recovered: true };
      saveRun(path, next);
      return next;
    }
    if (now < run.startedAt + dispatchRecoveryMs) return run;
    if ((run.attempts ?? 1) >= limits.maxAttempts) {
      const failed = failAttempt(run, { reason: 'dispatch-lost', attempt: run.attempt }, now, limits);
      saveRun(path, failed);
      return failed;
    }
  }

  beforeDispatch();
  const request = {
    state: 'requesting', attempt: randomUUID(), startedAt: now, file: workflow.file, ref: workflow.ref,
    attempts: (run?.attempts ?? 0) + 1, ...(run?.previous ? { previous: run.previous } : {}),
  };
  saveRun(path, request);
  const expected = Object.fromEntries(keyFields.map(field => [field, entry[field]]));
  const dispatched = {
    ...request, ...actions.dispatch(entry, workflow, request.attempt, expected), state: 'dispatched', dispatchedAt: now,
  };
  saveRun(path, dispatched);
  return dispatched;
}

function follow(entry, run, path, actions, now, limits) {
  const status = actions.status(entry.project, run.id);
  let next;
  if (status.status === 'missing') {
    next = failAttempt(run, { reason: 'missing' }, now, limits);
  } else if (status.status !== 'completed') {
    if (now < (run.dispatchedAt ?? run.startedAt ?? now) + limits.runTimeoutMs) return run;
    try {
      actions.cancel?.(entry.project, run.id);
    } catch {
      // The attempt is abandoned even if GitHub refuses the cancellation.
    }
    next = failAttempt(run, { reason: 'timeout', status: status.status }, now, limits);
  } else if (status.conclusion !== 'success') {
    next = failAttempt(run, { reason: 'conclusion', conclusion: status.conclusion }, now, limits);
  } else {
    let remote;
    try {
      remote = actions.proof(entry.project, run.id);
    } catch (error) {
      next = failAttempt(run, { reason: 'proof-unavailable', message: error.message }, now, limits);
    }
    if (!next) {
      const local = readJson(entry.evidence[0]).evidence;
      const matches = remote.work === entry.work && remote.project === entry.project &&
        remote.pullRequest === entry.pullRequest &&
        proofFields.every(field => isDeepStrictEqual(remote.proof?.[field], local[field]));
      next = { ...run, state: matches ? 'verified' : 'mismatch', proof: remote };
      if (matches) {
        next.verifiedAt = new Date(now).toISOString();
        next.jenkinsBuild = process.env.BUILD_NUMBER;
        next.jenkinsUrl = process.env.BUILD_URL;
      }
    }
  }
  saveRun(path, next);
  return next;
}

function problem(run, work, { maxAttempts }) {
  const reason = run.previous?.conclusion ?? run.previous?.reason;
  const where = run.previous?.url ?? run.url ?? 'no run';
  const reset = `Fix the cause, then run watch with --reset ${work}.`;
  if (run.state === 'mismatch') {
    return `GitHub Actions: mismatch (${run.url}). The two CI results differ for the same work. ${reset}`;
  }
  if (run.state === 'retry') {
    return `GitHub Actions: attempt ${run.attempts ?? 1}/${maxAttempts} did not succeed (${reason}, ${where}). ` +
      `Next attempt after ${new Date(run.nextAttemptAt ?? 0).toISOString()}.`;
  }
  if (run.state === 'failed') {
    return `GitHub Actions: ${run.attempts ?? 1} attempts did not succeed (last: ${reason}, ${where}). ${reset}`;
  }
  return null;
}

function reset(folder, requested, errors) {
  const all = requested.includes('all');
  const works = all
    ? readdirSync(folder).filter(name => /^[a-f0-9]{64}\.json$/.test(name)).map(name => name.slice(0, 64))
    : requested;
  const resets = [];
  for (const work of works) {
    if (!workPattern.test(work)) {
      errors.push({ message: `--reset expects a work ID or all: ${JSON.stringify(work)}.` });
      continue;
    }
    const path = join(folder, `${work}.json`);
    const run = loadRun(path);
    if (!run) {
      errors.push({ work, message: 'No watcher record to reset for this work.' });
      continue;
    }
    if (all && !['failed', 'mismatch'].includes(run.state)) continue;
    const history = join(folder, 'history');
    mkdirSync(history, { recursive: true });
    renameSync(path, join(history, `${work}.${Date.now()}.${randomUUID()}.json`));
    resets.push({ work, state: run.state, attempts: run.attempts ?? null });
  }
  return resets;
}

function processAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

function readLock(path) {
  try {
    return readJson(path);
  } catch {
    // An empty lock can be left by a crash between creation and write.
    return null;
  }
}

function watcherBusy(holder, path) {
  const who = holder ? `process ${holder.pid} on ${holder.host} since ${holder.since}` : 'an unknown process';
  return new Error(`Another watcher is using this state directory (${who}). ` +
    `Wait for it to finish, or delete ${path} if no watcher is running.`);
}

// One watcher at a time removes a stale lock, and only while the file is still the one it judged stale.
function removeStaleLock(path, holder, modified, now) {
  const guard = `${path}.break`;
  for (let tries = 0; ; tries += 1) {
    try {
      writeFileSync(guard, '', { flag: 'wx' });
      break;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
    const created = statSync(guard, { throwIfNoEntry: false })?.mtimeMs;
    // A guard older than a minute was left by a watcher that stopped while it held it.
    if (tries > 0 || (created !== undefined && now() - created <= minute)) return false;
    rmSync(guard, { force: true });
  }
  try {
    const current = statSync(path, { throwIfNoEntry: false });
    if (current && (current.mtimeMs !== modified || (readLock(path)?.token ?? null) !== (holder?.token ?? null))) {
      return false;
    }
    rmSync(path, { force: true });
    return true;
  } finally {
    rmSync(guard, { force: true });
  }
}

export function acquireWatchLock(stateDir, { alive = processAlive, now = Date.now } = {}) {
  const path = join(stateDir, 'watch.lock');
  const owner = { pid: process.pid, host: hostname(), since: new Date(now()).toISOString(), token: randomUUID() };
  for (let tries = 0; tries < 3; tries += 1) {
    try {
      writeFileSync(path, JSON.stringify(owner) + '\n', { flag: 'wx', flush: true });
      return () => {
        try {
          if (readJson(path).token === owner.token) rmSync(path, { force: true });
        } catch {
          // A lock that was already removed needs no release.
        }
      };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
    const modified = statSync(path, { throwIfNoEntry: false })?.mtimeMs;
    if (modified === undefined) continue;
    const holder = readLock(path);
    const stale = holder
      ? holder.host === hostname() && Number.isSafeInteger(holder.pid) && !alive(holder.pid)
      : now() - modified > minute;
    if (!stale) throw watcherBusy(holder, path);
    if (!removeStaleLock(path, holder, modified, now)) throw watcherBusy(readLock(path), path);
  }
  throw new Error(`Could not acquire the watcher lock ${path}.`);
}

export function watchGithub({ publish, reset: requestedResets = [], ...options }, {
  reconcile = reconcileGithub, actions = githubActions, publishReport = publishWatchReport, clock = Date.now,
  lock = acquireWatchLock,
} = {}) {
  const { configPath, stateDir, kitVersion } = options;
  checkStateDirectory(stateDir);
  const release = lock(stateDir);
  try {
    const config = readJson(configPath);
    const limits = watchLimits(config.watch);
    const projects = new Map(config.projects.map(project => {
      const { id, workflow } = project;
      if (!workflow || !/^[\w.-]+\.ya?ml$/.test(workflow.file) ||
          typeof workflow.ref !== 'string' || !/^[\w./-]+$/.test(workflow.ref) || workflow.ref.startsWith('-')) {
        throw new Error(`Missing or invalid recheck workflow for ${id}.`);
      }
      if (publish && (typeof workflow.evidenceBranch !== 'string' ||
          !/^[\w./-]+$/.test(workflow.evidenceBranch) || workflow.evidenceBranch.startsWith('-'))) {
        throw new Error(`Missing or invalid reports branch for ${id}.`);
      }
      return [id.toLowerCase(), project];
    }));
    const folder = join(stateDir, 'actions');
    mkdirSync(folder, { recursive: true });
    const errors = [];
    const resets = requestedResets.length ? reset(folder, requestedResets, errors) : undefined;
    let report;
    try {
      report = reconcile({ ...options, run: true });
    } catch (error) {
      errors.push({ message: error.message });
      return { targets: [], executedEvidence: [], errors, ...(resets ? { resets } : {}),
        ...(publish ? { publications: [] } : {}) };
    }
    errors.push(...(report.errors ?? []));
    const pinChecks = new Map();
    const verifyPins = project => {
      const key = project.id.toLowerCase();
      if (!pinChecks.has(key)) {
        try {
          checkPins(actions.pins(project.id, project.workflow.ref), config.policyRepo, project, kitVersion);
          pinChecks.set(key, null);
        } catch (error) {
          pinChecks.set(key, error);
        }
      }
      if (pinChecks.get(key)) throw pinChecks.get(key);
    };
    const targets = report.current.map(entry => {
      const path = join(folder, `${entry.work}.json`);
      const target = { ...entry, actions: null };
      if (!['success', 'failure'].includes(entry.status)) return target;
      try {
        const project = projects.get(entry.project.toLowerCase());
        const now = clock();
        let run = loadRun(path);
        if (run?.state === 'dispatched' && run.id) run = follow(entry, run, path, actions, now, limits);
        if (!run || run.state === 'requesting' || (run.state === 'retry' && now >= (run.nextAttemptAt ?? 0))) {
          run = startOrRecover(entry, project.workflow, path, run, actions, now, limits, () => verifyPins(project));
        }
        target.actions = run;
        const message = problem(run, entry.work, limits);
        if (message) errors.push({ work: entry.work, message });
      } catch (error) {
        target.actions = { state: 'error' };
        errors.push({ work: entry.work, message: error.message });
      }
      return target;
    });
    const result = { targets, executedEvidence: report.executedEvidence ?? [], errors, ...(resets ? { resets } : {}) };
    if (publish) {
      result.publications = [];
      if (!targets.length) return result;
      let latest;
      try {
        latest = new Map(reconcile({ ...options, run: false }).current.map(entry => [entry.work, entry]));
      } catch (error) {
        errors.push({ message: `Publication skipped, the active references could not be read again: ${error.message}` });
        return result;
      }
      for (const target of targets) {
        const live = latest.get(target.work);
        if (!live || !isDeepStrictEqual(live.decision, target.decision)) continue;
        try {
          result.publications.push(publishReport(target, projects.get(target.project.toLowerCase()).workflow.evidenceBranch));
        } catch (error) {
          errors.push({ work: target.work, message: error.message });
        }
      }
    }
    return result;
  } finally {
    release();
  }
}
