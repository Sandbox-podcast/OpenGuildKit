/**
 * Central definition of states and transitions (brief §7).
 * Labels are French; guards and effects live in commands/transitions.ts so they can be
 * tested without rendering. The UI reads these tables to draw badges and action bars.
 */
import type { Capability } from './permissions';

import type { IconName, Tone } from '@/shared/tone';

export type { IconName, Tone };

export interface StateDef { label: string; tone: Tone; icon: IconName; hint?: string }
export interface TransitionDef {
  action: string;
  label: string;
  from: readonly string[];
  to: string;
  capability: Capability;
  needsReason?: boolean;
  humanOnly?: boolean;
  danger?: boolean;
  /** A person records it in their own terminal in OpenGuildKit: the demo shows the command (terminal.ts) before simulating it. */
  terminal?: boolean;
}
export interface Machine { title: string; states: Record<string, StateDef>; transitions: readonly TransitionDef[] }

const s = (label: string, tone: Tone, icon: IconName, hint?: string): StateDef => ({ label, tone, icon, hint });

export const MACHINES = {
  blueprint: {
    title: 'Blueprint',
    states: {
      draft: s('Brouillon', 'neutral', 'draft'),
      review: s('En revue', 'info', 'eye'),
      published: s('Publié', 'success', 'check', 'Version immuable'),
      archived: s('Archivé', 'muted', 'archive'),
    },
    transitions: [
      { action: 'submit', label: 'Soumettre en revue', from: ['draft'], to: 'review', capability: 'propose' },
      { action: 'reject', label: 'Renvoyer en brouillon', from: ['review'], to: 'draft', capability: 'publish', needsReason: true },
      { action: 'publish', label: 'Publier la version', from: ['review'], to: 'published', capability: 'publish', humanOnly: true },
      { action: 'archive', label: 'Archiver la version', from: ['published', 'draft'], to: 'archived', capability: 'publish', needsReason: true, danger: true },
    ],
  },
  council: {
    title: 'Conseil',
    states: {
      prepared: s('Préparé', 'neutral', 'draft'),
      running: s('En cours', 'ai', 'play'),
      suspended: s('Suspendu', 'warning', 'pause'),
      awaiting: s("En attente d’arbitrage", 'info', 'clock'),
      done: s('Terminé', 'success', 'check'),
      cancelled: s('Annulé', 'muted', 'ban'),
    },
    transitions: [
      { action: 'launch', label: 'Demander les avis', from: ['prepared'], to: 'running', capability: 'propose' },
      { action: 'suspend', label: 'Suspendre', from: ['running'], to: 'suspended', capability: 'propose', needsReason: true },
      { action: 'resume', label: 'Reprendre', from: ['suspended'], to: 'running', capability: 'propose' },
      { action: 'arbitrate', label: "Passer à l’arbitrage", from: ['running'], to: 'awaiting', capability: 'propose' },
      { action: 'reopen', label: 'Rouvrir les échanges', from: ['awaiting'], to: 'running', capability: 'propose', needsReason: true },
      { action: 'cancel', label: 'Annuler la session', from: ['prepared', 'running', 'suspended', 'awaiting'], to: 'cancelled', capability: 'propose', needsReason: true, danger: true },
    ],
  },
  decision: {
    title: 'Décision',
    states: {
      draft: s('Brouillon', 'neutral', 'draft'),
      review: s('En revue', 'info', 'eye'),
      approved: s('Approuvée', 'success', 'check'),
      refused: s('Refusée', 'danger', 'cross'),
      replaced: s('Remplacée', 'muted', 'replace'),
      cancelled: s('Annulée', 'muted', 'ban'),
    },
    transitions: [
      { action: 'submit', label: 'Soumettre à approbation', from: ['draft'], to: 'review', capability: 'propose' },
      { action: 'approve', label: 'Approuver la décision', from: ['review'], to: 'approved', capability: 'approve', humanOnly: true, terminal: true },
      { action: 'refuse', label: 'Refuser', from: ['review'], to: 'refused', capability: 'approve', humanOnly: true, needsReason: true, danger: true, terminal: true },
      { action: 'requestRevision', label: 'Demander une révision', from: ['review'], to: 'draft', capability: 'approve', humanOnly: true, needsReason: true, terminal: true },
      { action: 'cancel', label: 'Annuler', from: ['draft', 'review'], to: 'cancelled', capability: 'propose', needsReason: true, danger: true },
    ],
  },
  quest: {
    title: 'Quête',
    states: {
      todo: s('À préparer', 'neutral', 'draft'),
      ready: s('Prête', 'info', 'flag'),
      doing: s('En cours', 'ai', 'play'),
      blocked: s('Bloquée', 'danger', 'lock'),
      review: s('En revue', 'warning', 'eye'),
      done: s('Terminée', 'success', 'check'),
      cancelled: s('Annulée', 'muted', 'ban'),
    },
    transitions: [
      { action: 'prepare', label: 'Marquer prête', from: ['todo'], to: 'ready', capability: 'edit' },
      { action: 'start', label: 'Démarrer', from: ['ready', 'todo'], to: 'doing', capability: 'edit' },
      { action: 'block', label: 'Bloquer', from: ['todo', 'ready', 'doing', 'review'], to: 'blocked', capability: 'edit', needsReason: true },
      { action: 'unblock', label: 'Débloquer', from: ['blocked'], to: 'doing', capability: 'edit' },
      { action: 'submitReview', label: 'Mettre en revue', from: ['doing'], to: 'review', capability: 'edit' },
      { action: 'backToWork', label: 'Reprendre le travail', from: ['review'], to: 'doing', capability: 'edit' },
      { action: 'close', label: 'Clôturer', from: ['review'], to: 'done', capability: 'publish', humanOnly: true },
      { action: 'reopen', label: 'Rouvrir', from: ['done', 'cancelled'], to: 'doing', capability: 'edit', needsReason: true },
      { action: 'cancel', label: 'Annuler', from: ['todo', 'ready', 'doing', 'blocked', 'review'], to: 'cancelled', capability: 'edit', needsReason: true, danger: true },
    ],
  },
  task: {
    title: 'Tâche',
    states: {
      todo: s('À préparer', 'neutral', 'draft'),
      ready: s('Prête', 'info', 'flag'),
      doing: s('En cours', 'ai', 'play'),
      blocked: s('Bloquée', 'danger', 'lock'),
      review: s('En revue', 'warning', 'eye'),
      done: s('Terminée', 'success', 'check'),
      cancelled: s('Annulée', 'muted', 'ban'),
    },
    transitions: [
      { action: 'start', label: 'Démarrer', from: ['todo', 'ready'], to: 'doing', capability: 'edit' },
      { action: 'block', label: 'Bloquer', from: ['todo', 'ready', 'doing'], to: 'blocked', capability: 'edit', needsReason: true },
      { action: 'unblock', label: 'Débloquer', from: ['blocked'], to: 'doing', capability: 'edit' },
      { action: 'finish', label: 'Terminer', from: ['doing', 'review'], to: 'done', capability: 'edit' },
      { action: 'reopen', label: 'Rouvrir', from: ['done', 'cancelled'], to: 'doing', capability: 'edit', needsReason: true },
      { action: 'cancel', label: 'Annuler', from: ['todo', 'ready', 'doing', 'blocked'], to: 'cancelled', capability: 'edit', needsReason: true, danger: true },
    ],
  },
  deliverable: {
    title: 'Livrable',
    states: {
      draft: s('Brouillon', 'neutral', 'draft'),
      review: s('En revue', 'info', 'eye'),
      approved: s('Approuvé', 'success', 'check'),
      published: s('Publié', 'success', 'book'),
      replaced: s('Remplacé', 'muted', 'replace'),
      archived: s('Archivé', 'muted', 'archive'),
    },
    transitions: [
      { action: 'submit', label: 'Soumettre en revue', from: ['draft'], to: 'review', capability: 'propose' },
      { action: 'requestChanges', label: 'Demander des changements', from: ['review'], to: 'draft', capability: 'approve', needsReason: true, humanOnly: true, terminal: true },
      { action: 'approve', label: 'Approuver cette version', from: ['review'], to: 'approved', capability: 'approve', humanOnly: true, terminal: true },
      { action: 'publish', label: 'Publier', from: ['approved'], to: 'published', capability: 'publish', humanOnly: true },
      { action: 'archive', label: 'Archiver', from: ['draft', 'approved', 'published', 'replaced'], to: 'archived', capability: 'archive', needsReason: true, danger: true },
    ],
  },
  run: {
    title: 'Exécution technique',
    states: {
      pending: s('En attente', 'neutral', 'clock'),
      running: s('En cours', 'ai', 'play'),
      suspended: s('Suspendue', 'warning', 'pause'),
      done: s('Terminée', 'success', 'check'),
      error: s('Erreur', 'danger', 'warn'),
      cancelled: s('Annulée', 'muted', 'ban'),
    },
    transitions: [
      { action: 'suspend', label: 'Suspendre', from: ['running', 'pending'], to: 'suspended', capability: 'run_controls' },
      { action: 'resume', label: 'Reprendre', from: ['suspended'], to: 'running', capability: 'run_controls' },
      { action: 'cancel', label: "Annuler l’exécution", from: ['pending', 'running', 'suspended'], to: 'cancelled', capability: 'run_controls', needsReason: true, danger: true },
    ],
  },
  result: {
    title: 'Résultat de contrôle',
    states: {
      not_evaluated: s('Non évalué', 'neutral', 'question'),
      passed: s('Réussi', 'success', 'check'),
      failed: s('Échoué', 'danger', 'cross'),
      inconclusive: s('Non concluant', 'warning', 'question'),
      not_applicable: s('Non applicable', 'muted', 'dot', 'Justification obligatoire'),
    },
    transitions: [],
  },
  freshness: {
    title: "Actualité d’un résultat",
    states: { current: s('Actuel', 'success', 'clock'), stale: s('À réévaluer', 'warning', 'stale') },
    transitions: [],
  },
  approval: {
    title: 'Approbation',
    states: {
      expected: s('Attendue', 'info', 'clock'),
      approved: s('Approuvée', 'success', 'check'),
      refused: s('Refusée', 'danger', 'cross'),
      expired: s('Expirée', 'warning', 'stale'),
      revoked: s('Révoquée', 'muted', 'ban'),
    },
    transitions: [
      { action: 'approve', label: 'Approuver', from: ['expected'], to: 'approved', capability: 'approve', humanOnly: true, terminal: true },
      { action: 'refuse', label: 'Refuser', from: ['expected'], to: 'refused', capability: 'approve', humanOnly: true, needsReason: true, danger: true, terminal: true },
      { action: 'revoke', label: 'Révoquer', from: ['approved'], to: 'revoked', capability: 'approve', humanOnly: true, needsReason: true, danger: true },
    ],
  },
  exception: {
    title: 'Exception',
    states: {
      draft: s('Brouillon', 'neutral', 'draft'),
      requested: s('Demandée', 'info', 'clock'),
      approved: s('Approuvée', 'success', 'check'),
      refused: s('Refusée', 'danger', 'cross'),
      expired: s('Expirée', 'warning', 'stale'),
      revoked: s('Révoquée', 'muted', 'ban'),
    },
    transitions: [
      { action: 'request', label: 'Demander la dérogation', from: ['draft'], to: 'requested', capability: 'request_exception' },
      { action: 'approve', label: "Approuver l’exception", from: ['requested'], to: 'approved', capability: 'approve_exception', humanOnly: true, terminal: true },
      { action: 'refuse', label: 'Refuser', from: ['requested'], to: 'refused', capability: 'approve_exception', humanOnly: true, needsReason: true, danger: true, terminal: true },
      { action: 'revoke', label: 'Révoquer', from: ['approved'], to: 'revoked', capability: 'approve_exception', humanOnly: true, needsReason: true, danger: true },
    ],
  },
  share: {
    title: 'Partage de démonstration',
    states: { active: s('Actif', 'success', 'link'), expired: s('Expiré', 'warning', 'stale'), revoked: s('Révoqué', 'muted', 'ban') },
    transitions: [{ action: 'revoke', label: 'Révoquer le lien', from: ['active'], to: 'revoked', capability: 'share', danger: true }],
  },
  integration: {
    title: 'Intégration',
    states: {
      not_configured: s('Non configurée', 'neutral', 'dot'),
      connecting: s('Connexion de démonstration en cours', 'info', 'clock'),
      available: s('Disponible en simulation', 'success', 'check'),
      error: s('Erreur simulée', 'danger', 'warn'),
      expired: s('Accès expiré', 'warning', 'stale'),
      disconnected: s('Déconnectée', 'muted', 'ban'),
    },
    transitions: [],
  },
  finding: {
    title: 'Constat',
    states: {
      open: s('Ouvert', 'danger', 'warn'),
      in_progress: s('En traitement', 'info', 'play'),
      resolved: s('Résolu', 'success', 'check'),
      waived: s('Couvert par une exception', 'warning', 'shield'),
    },
    transitions: [],
  },
  review: {
    title: 'Réexamen',
    states: { open: s('À réexaminer', 'warning', 'stale'), done: s('Réexaminé', 'success', 'check') },
    transitions: [],
  },
  project: {
    title: 'Projet',
    states: { active: s('Actif', 'success', 'dot'), archived: s('Archivé', 'muted', 'archive') },
    transitions: [],
  },
  skillUpdate: {
    title: 'Mise à jour de skill',
    states: {
      proposed: s('Proposée', 'info', 'spark'),
      review: s('En revue', 'warning', 'eye'),
      adopted: s('Adoptée', 'success', 'check'),
      dismissed: s('Écartée', 'muted', 'ban'),
    },
    transitions: [],
  },
} satisfies Record<string, Machine>;

export type MachineKind = keyof typeof MACHINES;
export const stateDef = (kind: MachineKind, state: string): StateDef =>
  (MACHINES[kind].states as Record<string, StateDef>)[state] ?? { label: state, tone: 'neutral', icon: 'dot' };
export const transitionsFrom = (kind: MachineKind, state: string): TransitionDef[] => (MACHINES[kind].transitions as readonly TransitionDef[]).filter((t) => t.from.includes(state));
export const findTransition = (kind: MachineKind, action: string): TransitionDef | undefined => (MACHINES[kind].transitions as readonly TransitionDef[]).find((t) => t.action === action);
