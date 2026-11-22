/** French labels and tones for the values the CLI prints. Unknown values are shown as they are. */
import type { Tone } from '@/domain/machines';
import type { PixelIconName } from '@/shared/pixel/icons';
import type { TaskStatus } from './types';

interface Label { label: string; tone: Tone; icon: PixelIconName }
const L = (label: string, tone: Tone, icon: PixelIconName): Label => ({ label, tone, icon });

export const TASK_STATUS: Record<TaskStatus, Label & { rpg: string; step: number }> = {
  draft: { ...L('Brouillon', 'muted', 'draft'), rpg: 'Quête esquissée', step: 0 },
  consulting: { ...L('Consultation', 'ai', 'council'), rpg: 'Au Conseil', step: 1 },
  reviewed: { ...L('Avis rendus', 'info', 'eye'), rpg: 'Avis rendus', step: 2 },
  'changes-requested': { ...L('À reprendre', 'warning', 'replace'), rpg: 'Renvoyée au Conseil', step: 1 },
  approved: { ...L('Validée', 'success', 'check'), rpg: 'Scellée', step: 3 },
  done: { ...L('Terminée', 'success', 'star'), rpg: 'Accomplie', step: 5 },
  'done-with-reservations': { ...L('Terminée avec réserves', 'warning', 'star'), rpg: 'Accomplie, sous réserves', step: 5 },
};
export const taskStatus = (s: string) => TASK_STATUS[s as TaskStatus] ?? { ...L(s, 'neutral', 'dot'), rpg: s, step: 0 };
export const TASK_ORDER: TaskStatus[] = ['draft', 'consulting', 'changes-requested', 'reviewed', 'approved', 'done', 'done-with-reservations'];
/** A completed task: done, or done with the points it left open recorded in result.closing. */
export const isDone = (status: string) => status === 'done' || status === 'done-with-reservations';
/** A task a person approved: still to implement, or completed. */
export const isDecided = (status: string) => status === 'approved' || isDone(status);

export const STEPS = [
  { id: 'frame', label: 'Cadrer', rpg: 'Esquisser', icon: 'quest' },
  { id: 'consult', label: 'Consulter', rpg: 'Réunir le Conseil', icon: 'council' },
  { id: 'review', label: 'Avis', rpg: 'Avis des sages', icon: 'eye' },
  { id: 'decide', label: 'Décider', rpg: 'Sceller', icon: 'lock' },
  { id: 'build', label: 'Réaliser', rpg: 'Forger', icon: 'anvil' },
  { id: 'prove', label: 'Prouver', rpg: 'Éprouver', icon: 'shield' },
] as const satisfies readonly { id: string; label: string; rpg: string; icon: PixelIconName }[];

/** Index of the current workflow step of a task. */
export function stepOf(status: string, hasResult: boolean): number {
  switch (status) {
    case 'draft': return 0;
    case 'consulting': case 'changes-requested': return 1;
    case 'reviewed': return 3;
    case 'approved': return hasResult ? 5 : 4;
    case 'done': case 'done-with-reservations': return 6;
    default: return 0;
  }
}

export const KIND: Record<string, string> = { feature: 'Fonctionnalité', bug: 'Anomalie', maintenance: 'Maintenance', decision: 'Décision', other: 'Autre', unsure: 'À préciser' };
export const SURFACE: Record<string, string> = { customer: 'Clients', service: 'Service', infrastructure: 'Infrastructure', business: 'Métier', other: 'Autre', unsure: 'À préciser' };
export const DATA: Record<string, string> = { none: 'Aucune donnée', internal: 'Interne', personal: 'Personnelle', regulated: 'Réglementée', unsure: 'À préciser' };
export const RESEARCH: Record<string, string> = { local: 'Sources locales', public: 'Sources publiques', unsure: 'À préciser', 'local-only': 'Locale uniquement', 'public-sources': 'Sources publiques autorisées' };

export const VERDICT: Record<string, Label> = {
  proceed: L('Avancer', 'success', 'check'), revise: L('Réviser', 'warning', 'edit'), block: L('Bloquer', 'danger', 'ban'), 'insufficient-evidence': L('Preuves insuffisantes', 'warning', 'question'),
};
export const verdict = (v?: string) => (v && VERDICT[v]) || L(v ?? 'sans verdict', 'neutral', 'dot');
export const CONFIDENCE: Record<string, string> = { high: 'confiance haute', medium: 'confiance moyenne', low: 'confiance faible' };
export const BASIS: Record<string, string> = { observed: 'observé', assumption: 'hypothèse', missing: 'manquant', inferred: 'déduit' };

export const PASS: Record<string, Label> = {
  done: L('Avis déposé', 'success', 'check'), failed: L('Avis refusé', 'danger', 'cross'), started: L('Passe commencée', 'ai', 'play'), missing: L('En attente', 'muted', 'clock'),
};
export const CHECK: Record<string, Label> = {
  passed: L('Réussi', 'success', 'check'), failed: L('Échec', 'danger', 'cross'), skipped: L('Ignoré', 'warning', 'pause'), 'not-applicable': L('Non applicable', 'muted', 'dot'),
};
export const checkLabel = (s?: string | null) => (s && CHECK[s]) || L('À rapporter', 'warning', 'clock');

export const ALERT: Record<string, Label> = {
  open: L('À vérifier', 'warning', 'question'), confirmed: L('Confirmée', 'danger', 'warn'), dismissed: L('Écartée', 'muted', 'ban'), resolved: L('Corrigée', 'success', 'check'), accepted: L('Risque accepté', 'info', 'lock'),
};
export const alertLabel = (s: string) => ALERT[s] ?? L(s, 'neutral', 'dot');
export const SEVERITY: Record<string, Tone> = { critical: 'danger', high: 'danger', moderate: 'warning', medium: 'warning', low: 'info', info: 'muted', unknown: 'neutral' };

export const HOST_CONTROL: Record<string, Label> = {
  enforced: L('Appliquée par l’hôte', 'success', 'shield'), instruction: L('Consigne seulement', 'warning', 'scroll'), missing: L('Manquante', 'danger', 'warn'), human: L('Décision d’une personne', 'info', 'user'),
};
export const hostControl = (s: string) => HOST_CONTROL[s] ?? L(s, 'neutral', 'dot');

/** The CLI writes an expired share as "expired: remove the access in Documentalist". */
export const shareState = (state: string) => (state.startsWith('expired') ? 'expired' : state.startsWith('revoked') ? 'revoked' : 'active');
export const SHARE: Record<string, Label> = { active: L('Actif', 'success', 'link'), expired: L('Expiré, à retirer', 'danger', 'warn'), revoked: L('Retiré', 'muted', 'ban') };
export const GUARD: Record<string, string> = { off: 'désactivée', observe: 'en observation', enforce: 'appliquée' };

export const fmtDay = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
};
export const fmtWhen = (iso?: string | null) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};
export const daysSince = (iso: string) => Math.floor((Date.now() - new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).getTime()) / 86_400_000);

/** French wording of the CLI's next open point (tasks.next_step); unknown texts are kept as they are. */
const NEXT: [RegExp, (m: RegExpExecArray) => string][] = [
  [/^Answer the questionnaire and consult the boards\.$/, () => 'Répondre au questionnaire et consulter les cerveaux.'],
  [/^Board reviews pending: (.*)\.$/, (m) => `Avis attendus : ${m[1]}.`],
  [/^Write the summary and record the review\.$/, () => 'Rédiger la synthèse et enregistrer la revue.'],
  [/^Resolve blockers (.*)\.$/, (m) => `Lever les blocages ${m[1]}.`],
  [/^Waiting for the person's decision\.$/, () => 'En attente de la décision d’une personne.'],
  [/^Consult again: (.*)$/, (m) => `Consulter à nouveau : ${m[1]}`],
  [/^Decision recorded: close it with task complete (\S+), then open a follow-up task to act on it\.$/, (m) => `Décision enregistrée : la clore avec task complete ${m[1]}, puis ouvrir une quête de suite pour la mettre en œuvre.`],
  [/^Implement, then record the results: task verify (\S+) and task result \S+, then task complete \S+\.$/, (m) => `Réaliser, puis rapporter les résultats (task verify ${m[1]}, task result) et terminer la quête.`],
  [/^Waiting for evidence: (.*)\.$/, (m) => `En attente de preuves : ${m[1]}.`],
  [/^Result recorded: run task verify (\S+) to list what remains, then task complete \S+\.$/, (m) => `Résultats enregistrés : task verify ${m[1]} liste ce qui reste, puis terminer la quête.`],
  [/^(\S+)(?: \(`([^`]*)`\))? failed(?:: (.*?))?(?: and (\d+) other check\(s\))?\. Fix it, then run task verify (\S+)\.$/s,
    (m) => `Échec de ${m[1]}${m[2] ? ` (${m[2]})` : ''}${m[3] ? ` : ${m[3]}` : ''}${m[4] ? `, et de ${m[4]} autre(s) contrôle(s)` : ''}. Corriger, puis relancer task verify ${m[5]}.`],
  [/^Done with reservations: see the open points in task show \(result\.closing\)\.$/, () => 'Terminée avec réserves : les points laissés ouverts sont dans la fiche de la quête.'],
  [/^Done\.$/, () => 'Terminée.'],
];
export function nextLabel(text: string) {
  for (const [re, fr] of NEXT) { const m = re.exec(text); if (m) return fr(m); }
  return text;
}
export const isBlocked = (next: string) => /^Resolve blockers/i.test(next);
/** The CLI's next step of an approved task whose last verification failed. */
export const hasFailedCheck = (next: string) => / failed.*Fix it, then run task verify /s.test(next);

/** French wording of the task questionnaire (workflow.task_questions). The CLI prompt stays as a tooltip. */
export const QUESTION_FR: Record<string, string> = {
  kind: 'Que demandez-vous à l’équipe ?',
  surface: 'Quelles zones la quête touche-t-elle ?',
  data: 'Quelle est la donnée la plus sensible que la quête peut lire ou modifier ?',
  research: 'Quelles preuves les cerveaux peuvent-ils consulter ?',
  context: 'Critères d’acceptation, contraintes ou autre contexte utile aux cerveaux',
  outcome: 'Quel résultat observable montre que c’est réussi ? (comportement attendu, ou comment reproduire l’anomalie)',
  affected: 'Qui est concerné : utilisateurs, clients, équipes ou partenaires ?',
  options: 'Quelles options sont sur la table, et qu’est-ce qui ferait choisir l’une d’elles ?',
};
/** Open points name the unanswered question in English; show it in French when it is known. */
export function openPointLabel(text: string, prompts: Record<string, string>) {
  const m = /^Unanswered: (.*)$/.exec(text);
  if (m) { const id = Object.keys(prompts).find((k) => prompts[k] === m[1]); return `Sans réponse : ${id && QUESTION_FR[id] ? QUESTION_FR[id] : m[1]}`; }
  return text.replace(/^The brief is short/, 'Le brief est court').replace(/^Unsure: /, 'Incertain : ');
}

/** Lines of `deliverable list`: "ID   Title (method M) [brain, brain]"; the method is optional. */
export function parseTemplates(text: string) {
  return text.trim().split('\n').filter(Boolean).map((line) => {
    const m = /^(\S+)\s+(.*?)(?:\s+\(method ([^)]+)\))?\s+\[([^\]]*)\]\s*$/.exec(line);
    return m ? { id: m[1], title: m[2], method: m[3] ?? '', brains: m[4].split(',').map((s) => s.trim()).filter(Boolean) } : { id: line.split(/\s+/)[0], title: line, method: '', brains: [] };
  });
}
