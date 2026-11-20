import { randomUUID } from 'node:crypto';
import { existsSync, linkSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { evaluateRefs, git, gitSha, isGitPath, parseProfile, sha256 } from './check.mjs';
import { decide, parseWaivers } from './waivers.mjs';

const json = value => JSON.stringify(value, null, 2) + '\n';
const readJson = path => JSON.parse(readFileSync(path, 'utf8'));
const workKey = inputs => sha256(JSON.stringify(inputs));
const profilePath = 'openguildkit.json';

function storeOnce(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temp = `${path}.${randomUUID()}.tmp`;
  writeFileSync(temp, json(value), { flag: 'wx' });
  try {
    linkSync(temp, path);
    return true;
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    return false;
  } finally {
    rmSync(temp, { force: true });
  }
}

function resolveRef(repo, ref) {
  if (typeof ref !== 'string' || !ref.startsWith('refs/')) {
    throw new Error('Référence Git complète attendue (refs/…).');
  }
  const commit = git(repo, 'rev-parse', '--verify', '--end-of-options', `${ref}^{commit}`).toString().trim();
  if (!gitSha.test(commit)) throw new Error(`SHA Git invalide : ${ref}`);
  return commit;
}

function fileRevision(repo, tip, path) {
  // The work key names the last commit that changed each file. A truncated history names another commit.
  if (git(repo, 'rev-parse', '--is-shallow-repository').toString().trim() !== 'false') {
    throw new Error(`${repo} is a shallow clone, so the last commit that changed ${path} cannot be identified ` +
      'and the work key would differ from the recheck workflow. Run git fetch --unshallow in that clone.');
  }
  const bytes = git(repo, 'show', `${tip}:${path}`);
  const lastChange = git(repo, 'log', '-1', '--format=%H', tip, '--', path).toString().trim();
  // A merge can resolve the path differently from the revision selected by Git history simplification.
  const matches = gitSha.test(lastChange) && git(repo, 'show', `${lastChange}:${path}`).equals(bytes);
  return { bytes, commit: matches ? lastChange : tip };
}

function snapshot(config, folder, kitVersion) {
  const policyRepo = resolve(folder, config.policyRepo.path);
  const policyTip = resolveRef(policyRepo, config.policyRepo.ref);
  const waiversPath = config.policyRepo.waiversPath;
  if (waiversPath !== undefined && !isGitPath(waiversPath)) {
    throw new Error('Chemin Git du registre de dérogations invalide.');
  }
  const waiverFile = waiversPath === undefined ? null : fileRevision(policyRepo, policyTip, waiversPath);
  const registry = waiverFile ? parseWaivers(waiverFile.bytes) : [];
  const entries = [];
  const projects = new Set();
  for (const project of config.projects) {
    if (typeof project.id !== 'string' || !project.id.trim() || projects.has(project.id)) {
      throw new Error('Chaque projet doit avoir un identifiant distinct.');
    }
    projects.add(project.id);
    // The GitHub commands list open PRs. A local configuration without pullRequests has nothing to evaluate.
    const pullRequests = project.pullRequests ?? [];
    if (!Array.isArray(pullRequests)) throw new Error(`pullRequests must be a list for ${project.id}.`);
    if (pullRequests.length === 0) continue;
    const targetRepo = resolve(folder, project.path);
    const profile = fileRevision(targetRepo, resolveRef(targetRepo, project.profileRef), profilePath);
    const { policyPath, adoption } = parseProfile(profile.bytes);
    const approvers = project.waiverApprovers ?? [];
    if (!Array.isArray(approvers) || !approvers.every(item => typeof item === 'string' && item.trim())) {
      throw new Error(`Approbateurs de dérogations invalides pour ${project.id}.`);
    }
    const policy = fileRevision(policyRepo, policyTip, policyPath);
    const { id: rule } = JSON.parse(policy.bytes);
    const numbers = new Set();
    for (const pr of pullRequests) {
      if (!Number.isSafeInteger(pr.number) || pr.number < 1 || numbers.has(pr.number)) {
        throw new Error(`Numéro de PR invalide ou dupliqué pour ${project.id}.`);
      }
      numbers.add(pr.number);
      const commit = resolveRef(targetRepo, pr.ref);
      if (pr.sha !== undefined && commit !== pr.sha) {
        throw new Error(`La PR ${project.id}#${pr.number} a évolué pendant la lecture des références.`);
      }
      const inputs = {
        project: project.id,
        pullRequest: pr.number,
        commit,
        profileCommit: profile.commit,
        profileSha256: sha256(profile.bytes),
        policyCommit: policy.commit,
        rule,
        kitVersion,
      };
      entries.push({
        key: workKey(inputs), inputs, policyRepo, targetRepo, profileBytes: profile.bytes,
        mode: adoption?.mode ?? 'observation', approvers, registry, registryCommit: waiverFile?.commit,
      });
    }
  }
  return entries;
}

function currentVerdict(stateDir, { key, inputs, mode, approvers, registry, registryCommit }, now, sameProject) {
  const folder = join(stateDir, 'evidence', key);
  const successPath = join(folder, 'success.json');
  const failurePath = join(folder, 'failure.json');
  const success = existsSync(successPath);
  const failure = existsSync(failurePath);
  const status = success && failure ? 'error' : success ? 'success' : failure ? 'failure' : 'pending';
  const decision = decide({ mode, status, inputs, registry, registryCommit, approvers, now, sameProject });
  const decisionPath = join(stateDir, 'decisions', key, `${workKey({ status, mode, decision, registryCommit })}.json`);
  const evidence = [success && successPath, failure && failurePath].filter(Boolean);
  storeOnce(decisionPath, {
    work: key, inputs, mode, status, decision, registryCommit, evidence, at: new Date(now).toISOString(),
  });
  return {
    work: key, ...inputs, status, mode, satisfiesRule: status === 'success',
    evidence, decision, decisionPath,
  };
}

export function recordEvidence(stateDir, key, evidence) {
  if (!/^[a-f0-9]{64}$/.test(key)) throw new Error('Identifiant de contrôle invalide.');
  const inputs = readJson(join(stateDir, 'work', `${key}.json`));
  if (workKey(inputs) !== key || !['success', 'failure'].includes(evidence.state) ||
      ['commit', 'policyCommit', 'profileCommit', 'profileSha256', 'kitVersion', 'rule']
        .some(field => inputs[field] !== evidence[field])) {
    throw new Error('La preuve ne correspond pas aux références du contrôle planifié.');
  }
  const path = join(stateDir, 'evidence', key, `${evidence.state}.json`);
  const recorded = storeOnce(path, { inputs, evidence });
  return { work: key, recorded, path };
}

export function reconcile({ configPath, stateDir, run, kitVersion,
  loadConfig = () => readJson(configPath), selection, clock = Date.now,
  sameProject = (actual, expected) => actual === expected }) {
  const folder = dirname(resolve(configPath));
  const readSnapshot = () => {
    const config = loadConfig();
    if (!selection) return snapshot(config, folder, kitVersion);
    const projects = config.projects.filter(project => sameProject(project.id, selection.project)).map(project => ({
      ...project, pullRequests: (project.pullRequests ?? []).filter(pr => pr.number === selection.pullRequest),
    }));
    const chosen = snapshot({ ...config, projects }, folder, kitVersion);
    if (chosen.length !== 1 || chosen[0].inputs.commit !== selection.commit) {
      throw new Error('La PR ou le commit demandé ne correspond plus aux références courantes.');
    }
    if (selection.mode && chosen[0].mode !== selection.mode) {
      throw new Error('Le profil approuvé doit être en mode obligatoire pour utiliser gate.');
    }
    return chosen;
  };
  const plan = entries => entries.map(entry => {
    storeOnce(join(stateDir, 'work', `${entry.key}.json`), entry.inputs);
    return currentVerdict(stateDir, entry, clock(), sameProject);
  });
  const entries = readSnapshot();
  const current = plan(entries);
  if (!run) return { current };

  const pending = entries.filter((_, index) => current[index].status === 'pending');
  const errors = [];
  const executed = [];
  const executedEvidence = [];
  if (!pending.length) return { current, executed, executedEvidence, errors };
  for (const entry of pending) {
    try {
      const evidence = evaluateRefs({ ...entry, ...entry.inputs });
      const { work, path } = recordEvidence(
        stateDir, entry.key, { ...evidence, profileCommit: entry.inputs.profileCommit },
      );
      executed.push(entry.key);
      executedEvidence.push({ work, path });
    } catch (error) {
      errors.push({ work: entry.key, message: error.message });
    }
  }
  // A check may finish against an older revision. Keep its report accessible without promoting it to current.
  try {
    return { current: plan(readSnapshot()), executed, executedEvidence, errors };
  } catch (error) {
    errors.push({ message: error.message });
    return { current: [], executed, executedEvidence, errors };
  }
}
