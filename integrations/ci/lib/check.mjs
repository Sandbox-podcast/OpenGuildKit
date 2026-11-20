import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { evaluate, isCatalogVersion } from '../prototype/demo/check.mjs';
import { parseJsonObject } from './json.mjs';

// SHA-1 and SHA-256 repositories, in full lowercase, as accepted by openguildkit ci-check.
export const gitSha = /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/;
export const sha256 = value => createHash('sha256').update(value).digest('hex');
export const isGitPath = file => typeof file === 'string' &&
  /^[\w./-]+$/.test(file) && file.split('/').every(part => part && part !== '.' && part !== '..');

// Like ci-check, ignore replacement objects and never fetch missing objects while reading.
export function git(repo, ...args) {
  return execFileSync('git', ['--no-replace-objects', '-c', 'protocol.allow=never', '-C', repo, ...args], {
    env: { ...process.env, GIT_NO_LAZY_FETCH: '1' },
  });
}

export function committedFile(repo, commit, path) {
  if (!gitSha.test(commit)) throw new Error(`Use a full lowercase Git commit SHA: ${commit}.`);
  let resolved = null;
  try {
    resolved = git(repo, 'rev-parse', '--verify', '--quiet', '--end-of-options', `${commit}^{commit}`).toString().trim();
  } catch {
    // An unknown object is reported below.
  }
  if (resolved !== commit) throw new Error(`${commit} must identify a commit of ${repo} directly.`);
  return git(repo, 'show', `${commit}:${path}`);
}

export function parseProfile(bytes, { allowProposal = false } = {}) {
  const profile = parseJsonObject(bytes, 'openguildkit.json');
  const { owner, policyPath, targetPath } = profile;
  if (profile.schemaVersion !== 1 || typeof owner !== 'string' || !owner.trim() ||
      !isGitPath(policyPath) || !isGitPath(targetPath)) {
    throw new Error('Profil invalide : schemaVersion 1, owner et chemins relatifs au dépôt attendus.');
  }
  if (profile.adoption !== undefined) {
    const { state, approver, mode } = profile.adoption;
    if (!['observation', 'required'].includes(mode) || !['proposed', 'approved'].includes(state) ||
        !gitSha.test(profile.adoption.inventoryCommit) || !gitSha.test(profile.adoption.catalogCommit)) {
      throw new Error('État ou mode d’adoption du profil invalide.');
    }
    if (!(allowProposal && state === 'proposed') && (state !== 'approved' || approver !== owner)) {
      throw new Error('Le profil doit être approuvé par son mainteneur avant activation.');
    }
  }
  return profile;
}

export function readRule(policyRepo, policyCommit, profile) {
  const source = parseJsonObject(committedFile(policyRepo, policyCommit, profile.policyPath), profile.policyPath);
  let rule = source;
  if (source.rules !== undefined) {
    const [entry] = Array.isArray(source.rules) ? source.rules : [];
    const maxMinutes = entry?.check?.max_minutes;
    if (source.id !== 'export-link-expiry' || !Array.isArray(source.rules) || source.rules.length !== 1 ||
        entry?.id !== source.id || !isCatalogVersion(source.version) ||
        !Number.isSafeInteger(maxMinutes) || maxMinutes <= 0 || profile.targetPath !== 'export.json') {
      throw new Error('Pack export-link-expiry invalide : version X.Y.Z, seuil entier et export.json requis.');
    }
    rule = { id: source.id, version: source.version, maxMinutes, format: 'catalog' };
  }
  if (profile.ruleId !== undefined && rule.id !== profile.ruleId) {
    throw new Error('La règle active ne correspond pas à celle sélectionnée dans le profil.');
  }
  return rule;
}

export function evaluateRefs({ policyRepo, policyCommit, targetRepo, commit, profileBytes, kitVersion }) {
  const profile = parseProfile(profileBytes);
  const rule = readRule(policyRepo, policyCommit, profile);
  const config = parseJsonObject(committedFile(targetRepo, commit, profile.targetPath), profile.targetPath);
  return {
    ...evaluate(rule, policyCommit, commit, config),
    kitVersion,
    profileSha256: sha256(profileBytes),
    owner: profile.owner,
    policyPath: profile.policyPath,
    targetPath: profile.targetPath,
    ...(profile.adoption ? { mode: profile.adoption.mode, project: profile.adoption.answers?.project } : {}),
  };
}
