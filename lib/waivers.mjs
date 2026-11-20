import { gitSha } from './check.mjs';

const fields = ['project', 'pullRequest', 'commit', 'profileCommit', 'policyCommit', 'rule'];
const text = value => typeof value === 'string' && value.trim().length > 0;

function timestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value)) return NaN;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return NaN;
  const canonical = value.includes('.') ? value : value.replace('Z', '.000Z');
  return date.toISOString() === canonical ? date.getTime() : NaN;
}

export function parseWaivers(bytes) {
  const registry = JSON.parse(bytes);
  if (registry.schemaVersion !== 1 || !Array.isArray(registry.waivers)) {
    throw new Error('Registre de dérogations invalide.');
  }
  const ids = new Set();
  return registry.waivers.map(item => {
    const start = timestamp(item.approvedAt);
    const end = timestamp(item.expiresAt);
    if (![item.id, item.project, item.rule, item.reason, item.approver].every(text) ||
        ids.has(item.id) || !Number.isSafeInteger(item.pullRequest) || item.pullRequest < 1 ||
        ![item.commit, item.profileCommit, item.policyCommit].every(sha => gitSha.test(sha)) ||
        !Number.isFinite(start) || !Number.isFinite(end) || start >= end) {
      throw new Error(`Dérogation invalide : ${item.id ?? '(sans identifiant)'}.`);
    }
    ids.add(item.id);
    return { item, start, end };
  });
}

export function decide({ mode, status, inputs, registry, registryCommit, approvers, now }) {
  if (status !== 'failure') {
    return {
      effectiveStatus: status,
      conditionMet: mode === 'observation' || status === 'success',
      waiver: null,
    };
  }
  const eligible = registry.filter(({ item, start, end }) => start <= now && now < end &&
    approvers.includes(item.approver) && fields.every(field => item[field] === inputs[field]));
  if (eligible.length > 1) {
    return { effectiveStatus: 'error', conditionMet: mode === 'observation', waiver: null, waiverConflict: true };
  }
  if (eligible.length === 1) {
    return {
      effectiveStatus: 'waived', conditionMet: true,
      waiver: { ...eligible[0].item, registryCommit },
    };
  }
  return { effectiveStatus: 'failure', conditionMet: mode === 'observation', waiver: null };
}
