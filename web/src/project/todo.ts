/** What waits on whom in the project, as the Royaume lists it: one entry per task, or one per kind when there are many. */
import type { PixelIconName } from '@/shared/pixel/icons';
import type { ProjectSignals } from './data';
import { nextLabel, nextLang } from './labels';
import type { TaskListItem } from './types';

export interface Todo { id: string; who: 'person' | 'agent'; icon: PixelIconName; title: string; detail: string; lang?: 'en'; to: string; tone: 'danger' | 'warning' | 'info' | 'ai' }

/** Above this many tasks of one kind, the Royaume shows one entry that opens the filtered list. */
export const GROUP_ABOVE = 5;

type Kind = Omit<Todo, 'id' | 'title' | 'detail' | 'to' | 'lang'> & {
  key: string; tasks: TaskListItem[]; title: (id: string) => string; to: (id: string) => string; many: (n: number) => string; list: string;
  /** The line under the title; the CLI's next step, in French when it is known, by default. */
  detail?: (t: TaskListItem) => { text: string; lang?: 'en' };
};

/** The entries of one kind: each task, or a single entry with the count when there are more than GROUP_ABOVE. */
function entries(kind: Kind): Todo[] {
  const { key, tasks, title, to, many, list, detail, ...look } = kind;
  if (tasks.length > GROUP_ABOVE) return [{ ...look, id: `${key}:*`, title: many(tasks.length), detail: `Les ${tasks.length} sont listées dans les quêtes.`, to: list }];
  const next = (t: TaskListItem) => ({ text: nextLabel(t.next), lang: nextLang(t.next) });
  return tasks.map((t) => { const line = (detail ?? next)(t); return { ...look, id: `${key}:${t.id}`, title: title(t.id), detail: line.text, lang: line.lang, to: to(t.id) }; });
}

export function todos(s: ProjectSignals): Todo[] {
  const out: Todo[] = [];
  const status = (value: string) => s.tasks.filter((t) => t.status === value);
  if (s.instructionsDrift) out.push({ id: 'check', who: 'person', icon: 'warn', title: 'Instructions à synchroniser', detail: 'AGENTS.md, les réglages de l’hôte ou le verrou du catalogue ne correspondent plus au profil.', to: '/intendance', tone: 'danger' });
  out.push(...entries({ key: 'u', tasks: s.unreadable, who: 'person', icon: 'warn', tone: 'danger', title: (id) => `Réparer le fichier de ${id}`, to: (id) => `/quetes/${id}`, many: (n) => `${n} fichiers de quête illisibles à réparer`, list: '/quetes?statut=unreadable', detail: (t) => ({ text: t.next, lang: 'en' }) }));
  out.push(...entries({ key: 'a', tasks: s.reconsult, who: 'person', icon: 'replace', tone: 'danger', title: (id) => `Consulter à nouveau ${id}`, to: (id) => `/conseil/${id}`, many: (n) => `${n} approbations à reprendre`, list: '/forge' }));
  out.push(...entries({ key: 'b', tasks: s.blocked, who: 'person', icon: 'ban', tone: 'danger', title: (id) => `Lever les blocages de ${id}`, to: (id) => `/conseil/${id}#blocages`, many: (n) => `${n} quêtes bloquées`, list: '/tour/blocages' }));
  out.push(...entries({ key: 'd', tasks: s.awaitingDecision, who: 'person', icon: 'lock', tone: 'warning', title: (id) => `Décider de ${id}`, to: (id) => `/conseil/${id}#decision`, many: (n) => `${n} quêtes à décider`, list: '/quetes?statut=reviewed', detail: () => ({ text: 'Les avis sont rendus : validez dans votre terminal ou renvoyez au Conseil.' }) }));
  out.push(...entries({ key: 'q', tasks: status('draft'), who: 'person', icon: 'question', tone: 'info', title: (id) => `Cadrer ${id}`, to: (id) => `/conseil/${id}`, many: (n) => `${n} quêtes à cadrer`, list: '/quetes?statut=draft' }));
  out.push(...entries({ key: 'r', tasks: status('changes-requested'), who: 'person', icon: 'replace', tone: 'warning', title: (id) => `Reprendre ${id}`, to: (id) => `/conseil/${id}`, many: (n) => `${n} quêtes à reprendre`, list: '/quetes?statut=changes-requested' }));
  out.push(...entries({ key: 'c', tasks: status('consulting'), who: 'agent', icon: 'council', tone: 'ai', title: (id) => `Avis attendus sur ${id}`, to: (id) => `/conseil/${id}`, many: (n) => `${n} quêtes en consultation`, list: '/quetes?statut=consulting' }));
  out.push(...entries({ key: 'f', tasks: s.toBuild, who: 'agent', icon: 'anvil', tone: 'ai', title: (id) => `Réaliser ${id}`, to: (id) => `/forge/${id}`, many: (n) => `${n} quêtes à réaliser`, list: '/forge' }));
  if (s.alertsOpen) out.push({ id: 'alerts', who: 'person', icon: 'shield', title: `${s.alertsOpen} alerte(s) de dépendance à revoir`, detail: 'Confirmez, écartez avec un motif, ou ouvrez une quête de correctif.', to: '/tour/alertes', tone: 'danger' });
  if (s.sharesExpired) out.push({ id: 'shares', who: 'person', icon: 'link', title: `${s.sharesExpired} partage(s) expiré(s)`, detail: 'Retirez l’accès dans Documentalist, puis enregistrez le retrait.', to: '/documentation/partages', tone: 'danger' });
  if (s.marketDue) out.push({ id: 'market', who: 'agent', icon: 'telescope', title: `${s.marketDue} source(s) de veille à relire`, detail: 'Selon la politique de recherche du projet.', to: '/observatoire', tone: 'info' });
  if (s.updates) out.push({ id: 'update', who: 'person', icon: 'download', title: `${s.updates} évolution(s) du catalogue installé`, detail: 'Comparez règle par règle, puis adoptez-les.', to: '/intendance/catalogue', tone: 'warning' });
  if (s.hostMissing) out.push({ id: 'host', who: 'person', icon: 'key', title: `${s.hostMissing} réglage(s) d’hôte manquant(s)`, detail: 'openguildkit host apply écrit les réglages de Claude Code ou Codex.', to: '/intendance/hote', tone: 'warning' });
  return out;
}
