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
  unreadable: { ...L('Illisible', 'danger', 'warn'), rpg: 'Parchemin illisible', step: 0 },
};
export const taskStatus = (s: string) => TASK_STATUS[s as TaskStatus] ?? { ...L(s, 'neutral', 'dot'), rpg: s, step: 0 };
export const TASK_ORDER: TaskStatus[] = ['draft', 'consulting', 'changes-requested', 'reviewed', 'approved', 'done', 'done-with-reservations'];
/** A completed task: done, or done with the points it left open recorded in result.closing. */
export const isDone = (status: string) => status === 'done' || status === 'done-with-reservations';
/** A task a person approved: still to implement, or completed. */
export const isDecided = (status: string) => status === 'approved' || isDone(status);
/** An approved task whose approval no longer holds (rules changed, seal broken): a person consults it again. */
export const needsReconsult = (t: { status: string; severity?: string }) => t.status === 'approved' && t.severity === 'error';
/** The columns of a list of tasks: every status, and unreadable records only when there is one. */
export const statusesOf = (tasks: { status: string }[]): TaskStatus[] => (tasks.some((t) => t.status === 'unreadable') ? [...TASK_ORDER, 'unreadable'] : TASK_ORDER);

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

/** French names of the sectors and norms of the catalog, by ID; an ID the page does not know keeps the CLI's title. */
export const SECTOR_FR: Record<string, string> = {
  'critical-infrastructure': 'Infrastructures critiques et industrie', 'e-commerce': 'Commerce en ligne', education: 'Éducation',
  'financial-services': 'Services financiers', general: 'Général', healthcare: 'Santé', insurance: 'Assurance',
  'public-sector': 'Secteur public', 'software-publisher': 'Éditeur de logiciels',
};
export const NORM_FR: Record<string, string> = {
  'dora-financial-entity': 'DORA pour les entités financières',
  'eu-ai-act-system': 'Règlement européen sur l’IA, pour les systèmes d’IA',
  'gdpr-personal-data': 'RGPD : traitement de données personnelles',
  'health-data-protection': 'Données de santé et logiciels médicaux (UE)',
  'insurance-distribution': 'Distribution et tarification de l’assurance (UE)',
  'minors-data-protection': 'Données des enfants et des élèves (UE)',
  'nis2-essential-entity': 'NIS 2 pour les entités essentielles et importantes',
  'online-consumer-sales': 'Vente en ligne aux consommateurs (UE)',
  'pci-dss-cardholder-data': 'PCI DSS pour les données de carte de paiement',
  'public-sector-accessibility': 'Accessibilité du secteur public (UE)',
};
/** Why the CLI proposes a pattern (recommend --json, reasons), in French; an unknown reason is null. */
export function reasonLabel(reason: string): string | null {
  if (reason === 'personal data') return 'données personnelles';
  if (reason === 'decisions about people') return 'décisions sur des personnes';
  const m = /^(sector|stack|role) (.+)$/.exec(reason);
  if (!m) return null;
  return m[1] === 'sector' ? `secteur ${SECTOR_FR[m[2]] ?? m[2]}` : `${m[1] === 'stack' ? 'pile' : 'rôle'} : ${m[2]}`;
}

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
  [/^The approval for (\S+) was recorded under earlier rules(?: \((.*)\))?\. Consult it again with openguildkit task consult \S+, or open a linked task with openguildkit task new "BRIEF" --follows \S+\.$/s,
    (m) => `L’approbation de ${m[1]} a été donnée sous des règles antérieures${m[2] ? ` (${changesLabel(m[2])})` : ''}. ${RECONSULT(m[1])}`],
  [/^The approval for (\S+) has no seal: .*?\. Consult it again with .*$/s, (m) => `L’approbation de ${m[1]} n’a pas de sceau : elle a été modifiée à la main ou écrite par une ancienne version. ${RECONSULT(m[1])}`],
  [/^The record of (\S+) no longer matches what was approved\. Consult it again with .*$/s, (m) => `L’enregistrement de ${m[1]} ne correspond plus à ce qui a été approuvé. ${RECONSULT(m[1])}`],
];
const RECONSULT = (id: string) => `La consulter à nouveau (task consult ${id}), ou ouvrir une tâche liée (task new --follows ${id}).`;
/** What changed in the rules a task was approved under ("pack gdpr added; conventions changed"), in French. */
function changesLabel(text: string) {
  const FIELD: Record<string, string> = { sector: 'secteur modifié', stack: 'pile modifiée', conventions: 'conventions modifiées', checks: 'vérifications modifiées' };
  const DONE: Record<string, string> = { added: 'ajouté', removed: 'retiré', changed: 'modifié' };
  return text.split('; ').map((item) => {
    const field = /^(sector|stack|conventions|checks) changed$/.exec(item);
    if (field) return FIELD[field[1]];
    const rule = /^(pack|rule) (\S+) (added|removed|changed)$/.exec(item);
    if (rule) return `${rule[1] === 'pack' ? 'pack' : 'règle'} ${rule[2]} ${DONE[rule[3]]}${rule[1] === 'rule' ? 'e' : ''}`;
    return item === 'the task\'s components changed' ? 'composants de la tâche modifiés' : item;
  }).join(' ; ');
}
export function nextLabel(text: string) {
  for (const [re, fr] of NEXT) { const m = re.exec(text); if (m) return fr(m); }
  return text;
}
/** 'en' when nextLabel leaves the CLI's English as it is. */
export const nextLang = (text: string): 'en' | undefined => (NEXT.some(([re]) => re.test(text)) ? undefined : 'en');
export const isBlocked = (next: string) => /^Resolve blockers/i.test(next);

/** The tasks a change of rules touched, as sync, update --apply and the saved profile print them:
 * "Tasks consulted under the previous rules:", then one "  ID (status): step." line per task. */
export function touchedTasks(stdout: string): { id: string; status: string; step: string }[] {
  const lines = stdout.split('\n');
  const start = lines.findIndex((line) => /^Tasks (consulted under the previous rules|this change touches):$/.test(line.trim()));
  if (start < 0) return [];
  return lines.slice(start + 1).map((line) => /^\s+(\S+) \(([^)]+)\): (.*?)\.?$/.exec(line)).filter((m): m is RegExpExecArray => !!m)
    .map((m) => ({ id: m[1], status: m[2], step: m[3] }));
}
/** The step of a touched task, in French when the CLI's wording is known. */
export const touchedStep = (step: string) => {
  if (step === 'consult it again') return 'la consulter à nouveau';
  if (step === 'request changes and consult it again') return 'demander des changements, puis la consulter à nouveau';
  const m = /^consult it again \(openguildkit task consult (\S+)\) or open a linked task with --follows$/.exec(step);
  return m ? `la consulter à nouveau (task consult ${m[1]}) ou ouvrir une tâche liée (--follows)` : null;
};
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
