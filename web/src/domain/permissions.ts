/**
 * Capabilities, roles and the single authorization decision used by commands,
 * buttons, shortcuts and transitions (RG-12, RG-13, RG-16).
 * Roles are a demo of the domain rules, not a browser-side security boundary.
 */
import type { Actor, AppState, ID } from './types';

export const CAPABILITIES = {
  view: 'Consulter',
  propose: 'Proposer',
  edit: 'Modifier',
  publish: 'Publier',
  approve: 'Approuver',
  manage_members: 'Gérer les membres',
  configure_agents: 'Configurer les agents',
  run_controls: 'Lancer les contrôles',
  request_exception: 'Demander une exception',
  approve_exception: 'Approuver une exception',
  export: 'Exporter',
  share: 'Partager',
  archive: 'Archiver et restaurer',
  configure_org: "Paramétrer l’organisation",
} as const;
export type Capability = keyof typeof CAPABILITIES;

export const ROLES = {
  owner: { label: "Propriétaire de l’organisation", short: 'Propriétaire' },
  admin: { label: 'Administrateur', short: 'Admin' },
  maintainer: { label: 'Responsable de projet ou mainteneur', short: 'Mainteneur' },
  contributor: { label: 'Contributeur', short: 'Contributeur' },
  reader: { label: 'Lecteur', short: 'Lecteur' },
  auditor: { label: 'Auditeur', short: 'Auditeur' },
} as const;
export type RoleId = keyof typeof ROLES;

const ALL = Object.keys(CAPABILITIES) as Capability[];
export const ROLE_CAPABILITIES: Record<RoleId, readonly Capability[]> = {
  owner: ALL,
  admin: ALL,
  maintainer: ['view', 'propose', 'edit', 'publish', 'approve', 'run_controls', 'request_exception', 'export', 'share', 'archive'],
  contributor: ['view', 'propose', 'edit', 'run_controls', 'request_exception', 'export'],
  reader: ['view'],
  auditor: ['view', 'export'],
};

/** Agents never publish, approve, manage people, configure agents or change policies (RG-13, RG-14). */
export const AGENT_CAPABILITIES: readonly Capability[] = ['view', 'propose'];

/** Capabilities that keep working on an archived project. */
const ARCHIVE_SAFE: readonly Capability[] = ['view', 'export', 'archive'];

export interface Decision { ok: boolean; reason?: string }
export const allow: Decision = { ok: true };
export const deny = (reason: string): Decision => ({ ok: false, reason });

export function actorLabel(state: AppState, actor: Actor): string {
  if (actor.type === 'human') return state.users[actor.userId]?.name ?? 'Personne inconnue';
  if (actor.type === 'agent') return `${state.db.expert[actor.expertId]?.name ?? 'Agent'} (agent IA)`;
  return 'Système de démonstration';
}

export function rolesOf(state: AppState, userId: ID, orgId: ID, projectId?: ID): RoleId[] {
  return Object.values(state.db.member)
    .filter((m) => m.orgId === orgId && m.userId === userId && (!m.projectId || m.projectId === projectId))
    .map((m) => m.role);
}

/** The one authorization decision. `projectId` narrows the scope when the action targets a project. */
export function authorize(state: AppState, actor: Actor, capability: Capability, scope: { orgId: ID; projectId?: ID }): Decision {
  if (actor.type === 'system') return allow;
  const project = scope.projectId ? state.db.project[scope.projectId] : undefined;
  if (project && project.orgId !== scope.orgId) return deny("Cet objet n’appartient pas à l’organisation active.");
  if (project?.status === 'archived' && !ARCHIVE_SAFE.includes(capability)) {
    return deny(`Le projet « ${project.name} » est archivé : il reste consultable mais n'accepte plus de nouvelles opérations.`);
  }
  if (actor.type === 'agent') {
    const expert = state.db.expert[actor.expertId];
    if (!expert || expert.orgId !== scope.orgId) return deny("Cet agent n’appartient pas à l’organisation active.");
    if (!AGENT_CAPABILITIES.includes(capability)) {
      return deny(`Un agent IA ne peut pas « ${CAPABILITIES[capability].toLowerCase()} » : cette action revient à un humain identifié.`);
    }
    return allow;
  }
  const roles = rolesOf(state, actor.userId, scope.orgId, scope.projectId);
  if (roles.length === 0) return deny("Vous n’êtes pas membre de cette organisation.");
  if (roles.some((r) => ROLE_CAPABILITIES[r].includes(capability))) return allow;
  const names = roles.map((r) => ROLES[r].short).join(', ');
  return deny(`Votre rôle (${names}) ne permet pas de « ${CAPABILITIES[capability].toLowerCase()} ».`);
}
