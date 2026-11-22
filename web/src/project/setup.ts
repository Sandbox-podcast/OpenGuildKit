/** The setup answers the page sends to `init`: the norms a person accepts or declines, and what is still missing. */
import type { Question } from './types';

/** One norm as the page keeps it while the person answers: yes, or no with who and why. */
export interface NormDraft { answer: 'yes' | 'no'; by?: string; reason?: string }
export type NormAnswer = 'yes' | { answer: 'no'; by: string; reason: string };

const complete = (draft: NormDraft) => draft.answer === 'yes' || (!!draft.by?.trim() && !!draft.reason?.trim());

/** The norms answers `init` takes: "yes", or a no with who and why. A no without both is not sent yet. */
export function normAnswers(drafts: Record<string, NormDraft>): Record<string, NormAnswer> {
  const out: Record<string, NormAnswer> = {};
  for (const [id, draft] of Object.entries(drafts)) {
    if (!complete(draft)) continue;
    out[id] = draft.answer === 'yes' ? 'yes' : { answer: 'no', by: draft.by!.trim(), reason: draft.reason!.trim() };
  }
  return out;
}

/** The proposed norms without a complete answer: `init` refuses to write the profile while one is left. */
export const pendingNorms = (proposed: string[], drafts: Record<string, NormDraft>) => proposed.filter((id) => !drafts[id] || !complete(drafts[id]));

/** Required questions (the CLI marks them `required`) the person has not answered. */
export const missingRequired = (questions: (Question & { required?: boolean })[], answers: Record<string, unknown>) =>
  questions.filter((q) => q.required && (answers[q.id] === undefined || answers[q.id] === '')).map((q) => q.id);

/** The answers sent to `init` and `preview`: the questions answered, and the norms once one is answered. */
export function setupAnswers(answers: Record<string, unknown>, drafts: Record<string, NormDraft>) {
  const norms = normAnswers(drafts);
  return Object.keys(norms).length ? { ...answers, norms } : { ...answers };
}

/** French prompts of the setup questions (init --questions), by ID. */
export const SETUP_PROMPT: Record<string, string> = {
  name: 'Nom du projet',
  sector: 'Quel secteur décrit le projet ? Ses réglementations sont proposées, à confirmer une par une.',
  stack: 'Quels langages, frameworks et services composent la pile ? Ajoute une version quand elle compte.',
  components: 'Quels composants le dépôt contient-il ? Confirme ou corrige le chemin et la pile de chacun.',
  roles: 'Quels métiers le projet doit-il servir ?',
  personal_data: 'Le projet traite-t-il des données personnelles, comme des noms, des adresses e-mail, des données de santé ou de paiement ?',
  people_decisions: 'Le projet note-t-il, classe-t-il ou décide-t-il pour des personnes, par exemple à l’embauche, pour un crédit, une assurance, une place d’école ou un prix par personne ?',
  patterns: 'Quels autres modèles de projet appliquer ? Sans choix, ceux que présélectionnent la pile, le secteur et les métiers.',
  packs: 'Quels packs de règles ajouter aux packs recommandés et à ceux des modèles choisis ?',
  boards: 'Quels cerveaux peuvent conseiller ? Sans choix, tous, y compris ceux ajoutés plus tard.',
  tools: 'Avec quels outils l’équipe travaille-t-elle : suivi, documentation, CI, messagerie, temps, RH, analyse de sécurité ?',
  host: 'Quel agent hôte l’équipe utilise-t-elle ?',
  guard: 'Quel garde-fou pour les modifications de l’agent ?',
  research: 'L’agent peut-il consulter des sources publiques quand tu l’autorises pour une tâche ?',
  conventions: 'Quelles conventions d’équipe l’agent doit-il suivre ?',
  checks: 'Quelles commandes de vérification l’agent ou la CI lancent-ils ? task verify les lance à la racine du projet.',
};

/** French labels of the setup choices that are not catalog titles, by question and choice ID. */
export const SETUP_CHOICE: Record<string, Record<string, string>> = {
  personal_data: { yes: 'Oui', no: 'Non' },
  people_decisions: { yes: 'Oui', no: 'Non' },
  host: { 'claude-code': 'Claude Code', codex: 'Codex', other: 'Un autre agent, ou aucun : les règles restent dans AGENTS.md, sans réglage d’hôte' },
  guard: {
    off: 'Désactivé : rien ne rappelle le conseil à l’agent, aucune modification n’est vérifiée',
    observe: 'Observation : chaque demande rappelle d’ouvrir une tâche ; une modification sans tâche approuvée est signalée à l’agent',
    enforce: 'Appliqué : les modifications de l’agent sont refusées tant qu’une personne n’a pas approuvé une tâche (avec des approbations signées)',
  },
  research: { 'local-only': 'Sources du projet seulement', 'public-sources': 'Recherche publique quand une tâche l’autorise' },
  roles: {
    backend: 'Développement back-end', communication: 'Communication', 'customer-success': 'Succès client', data: 'Données et IA', design: 'Design et UX',
    'developer-relations-and-docs': 'Relations développeurs et documentation', devops: 'DevOps et plateforme', engineering: 'Développement logiciel',
    finance: 'Finance', frontend: 'Développement front-end', hr: 'Ressources humaines', 'it-and-workplace': 'Informatique interne',
    leadership: 'Direction générale', legal: 'Juridique et conformité', localisation: 'Traduction et internationalisation', marketing: 'Marketing',
    operations: 'Opérations', partnerships: 'Partenariats', performance: 'Performance', procurement: 'Achats', product: 'Produit',
    'project-management': 'Gestion de projet', qa: 'Assurance qualité', sales: 'Commerce', security: 'Cybersécurité', support: 'Support client',
    'trust-and-safety': 'Confiance et sécurité des contenus',
  },
};

/** A setup text in French when the page knows it by ID, or the CLI's English, marked as such. */
export const setupPrompt = (q: Question) => (SETUP_PROMPT[q.id] ? { text: SETUP_PROMPT[q.id] } : { text: q.prompt, lang: 'en' as const });
export function setupChoice(questionId: string, choice: { id: string; label: string }, sectors: Record<string, string>) {
  const known = questionId === 'sector' ? sectors[choice.id] : SETUP_CHOICE[questionId]?.[choice.id];
  return known ? { text: known } : { text: choice.label, lang: 'en' as const };
}
