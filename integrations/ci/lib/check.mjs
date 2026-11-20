import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { evaluate, isCatalogVersion } from '../prototype/demo/check.mjs';

export const gitSha = /^[a-f0-9]{40}$/;
export const sha256 = value => createHash('sha256').update(value).digest('hex');
export const isGitPath = file => typeof file === 'string' &&
  /^[\w./-]+$/.test(file) && file.split('/').every(part => part && part !== '.' && part !== '..');

export function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args]);
}

export function parseProfile(bytes, { allowProposal = false } = {}) {
  const profile = JSON.parse(bytes.toString('utf8'));
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
  const source = JSON.parse(git(policyRepo, 'show', `${policyCommit}:${profile.policyPath}`));
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
  const config = JSON.parse(git(targetRepo, 'show', `${commit}:${profile.targetPath}`));
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
