/**
 * Derived data. Counters, statuses, freshness, closure checks and notifications are computed
 * from the objects every time (RG-40): there is no stored copy that could drift.
 */
import baseCatalogue from '@/fixtures/catalogue.json';
import type { Catalogue, Reference } from '@/adapters/catalogue';
import { DAY, get, list, nowOf } from './engine';
import { stateDef, type Tone } from './machines';
import type {
  AppState, Approval, BlueprintVersion, ContextFact, ControlDef, Decision, Deliverable, ID, Project, Quest, Ref, RefKind,
  Result, Rule, RuleException, RuleRef, RuleScope, RuleVersion, Share,
} from './types';

/* ----------------------------------------------------------------- catalogue */
const BASE = (baseCatalogue as Catalogue).references;
const catalogueCache = new WeakMap<object, Reference[]>();
export function allReferences(s: AppState): Reference[] {
  let refs = catalogueCache.get(s.catalogue);
  if (!refs) {
    const overrides = new Map(s.catalogue.added.map((r) => [r.id, r]));
    refs = BASE.map((r) => overrides.get(r.id) ?? r).concat(s.catalogue.added.filter((r) => !BASE.some((b) => b.id === r.id)));
    catalogueCache.set(s.catalogue, refs);
  }
  return refs;
}
export const baseCatalogueInfo = baseCatalogue as Catalogue;
export const referenceById = (s: AppState, id: string) => allReferences(s).find((r) => r.id === id);

/* ----------------------------------------------------------------- blueprint and rules */
export const blueprintOf = (s: AppState, orgId: ID | null) => list(s, 'blueprint', orgId)[0];
export function bpVersion(s: AppState, orgId: ID | null, n?: number): BlueprintVersion | undefined {
  const bp = blueprintOf(s, orgId);
  return n === undefined ? undefined : bp?.versions.find((v) => v.number === n);
}
export const latestPublished = (s: AppState, orgId: ID | null) =>
  blueprintOf(s, orgId)?.versions.filter((v) => v.status === 'published').at(-1);
export const openDraft = (s: AppState, orgId: ID | null) =>
  blueprintOf(s, orgId)?.versions.find((v) => v.status === 'draft' || v.status === 'review');

export const latestRuleVersion = (r: Rule) => r.versions.filter((v) => v.status === 'published').at(-1) ?? r.versions.at(-1)!;

export const fact = (v: BlueprintVersion | undefined, key: string): ContextFact | undefined => v?.context.find((f) => f.key === key);
export const unknownFacts = (v: BlueprintVersion | undefined) => v?.context.filter((f) => f.provenance === 'unknown') ?? [];
export const unconfirmedInferred = (v: BlueprintVersion | undefined) => v?.context.filter((f) => f.provenance === 'inferred' && !f.confirmedBy) ?? [];

export const LEVELS: Record<RuleScope['level'], { label: string; rank: number }> = {
  org: { label: 'Organisation', rank: 0 },
  product: { label: 'Produit', rank: 1 },
  repo: { label: 'Dépôt', rank: 2 },
  module: { label: 'Module', rank: 3 },
};
export const POLICIES = {
  imposed: { label: 'Imposée', hint: 'Aucune adaptation possible aux niveaux inférieurs.' },
  adjustable: { label: 'Ajustable', hint: 'Le paramètre peut être adapté dans les bornes déclarées.' },
  additive: { label: 'Additive', hint: 'Les niveaux inférieurs ne peuvent qu’ajouter des exigences.' },
} as const;

export interface EffectiveRule { ref: RuleRef; rule: Rule; version: RuleVersion; overriddenBy?: RuleRef }
export interface RuleConflict { kind: 'imposed' | 'bounds' | 'additive' | 'competing'; message: string; rules: RuleRef[] }

/** Rules of a Blueprint version that apply to a target, with inheritance and conflicts (RG-05). */
export function resolveRules(s: AppState, v: BlueprintVersion | undefined, target: { productId?: ID; repoId?: ID; moduleId?: ID } = {}) {
  const entries: EffectiveRule[] = [];
  for (const ref of v?.rules ?? []) {
    const rule = get(s, 'rule', ref.ruleId);
    const version = rule?.versions.find((x) => x.number === ref.version);
    if (!rule || !version) continue;
    const sc = version.scope;
    const applies =
      sc.level === 'org' ||
      (sc.level === 'product' && (!target.productId || sc.productId === target.productId)) ||
      (sc.level === 'repo' && (!target.productId || productOfRepo(s, sc.repoId) === target.productId) && (!target.repoId || sc.repoId === target.repoId)) ||
      (sc.level === 'module' && (!target.repoId || sc.repoId === target.repoId) && (!target.moduleId || sc.moduleId === target.moduleId));
    if (applies) entries.push({ ref, rule, version });
  }
  const conflicts: RuleConflict[] = [];
  for (const child of entries) {
    if (!child.version.adapts) continue;
    const parent = entries.find((e) => e.rule.id === child.version.adapts);
    if (!parent) continue;
    const pv = parent.version;
    if (pv.policy === 'imposed') {
      conflicts.push({ kind: 'imposed', rules: [parent.ref, child.ref], message: `${child.rule.code} adapte ${parent.rule.code}, qui est imposée : l’adaptation n’est pas autorisée.` });
    } else if (pv.policy === 'additive') {
      conflicts.push({ kind: 'additive', rules: [parent.ref, child.ref], message: `${parent.rule.code} est additive : ${child.rule.code} doit ajouter une exigence, pas la remplacer.` });
    } else if (pv.parameter && child.version.parameter) {
      const val = child.version.parameter.value;
      if (val < pv.parameter.min || val > pv.parameter.max) {
        conflicts.push({ kind: 'bounds', rules: [parent.ref, child.ref], message: `${child.rule.code} fixe ${pv.parameter.name} à ${val} ${pv.parameter.unit}, hors des bornes ${pv.parameter.min}–${pv.parameter.max} de ${parent.rule.code}.` });
      } else parent.overriddenBy = child.ref;
    } else parent.overriddenBy = child.ref;
  }
  const groups = new Map<string, EffectiveRule[]>();
  entries.forEach((e) => e.version.conflictGroup && groups.set(e.version.conflictGroup, [...(groups.get(e.version.conflictGroup) ?? []), e]));
  groups.forEach((g, name) => {
    if (g.length > 1) conflicts.push({ kind: 'competing', rules: g.map((e) => e.ref), message: `Choix concurrents à arbitrer (${name}) : ${g.map((e) => e.rule.code).join(', ')}. Aucune règle ne l’emporte automatiquement.` });
  });
  return { rules: entries, conflicts };
}

export function productOfRepo(s: AppState, repoId?: ID): ID | undefined {
  return Object.values(s.db.product).find((p) => p.repos.some((r) => r.id === repoId))?.id;
}

export function projectRules(s: AppState, project: Project) {
  return resolveRules(s, bpVersion(s, project.orgId, project.blueprintVersion), { productId: project.productId });
}

/** Distinct approver is required when the project's profile handles personal data (RG-16). */
export function requiresDistinctApprover(s: AppState, projectId?: ID): boolean {
  const project = get(s, 'project', projectId);
  if (!project) return true;
  const f = fact(bpVersion(s, project.orgId, project.blueprintVersion), 'data.personal');
  return !f || f.value.toLowerCase() !== 'non';
}

/* ----------------------------------------------------------------- results and evidence */
export interface Freshness { state: 'current' | 'stale'; reasons: string[] }
export function resultFreshness(s: AppState, r: Result): Freshness {
  const reasons: string[] = [];
  const project = get(s, 'project', r.projectId);
  const control = get(s, 'control', r.controlId);
  const subj = r.inputs.subject;
  if (subj) {
    const d = get(s, 'deliverable', subj.deliverableId);
    if (d && d.current !== subj.version) reasons.push(`Le livrable « ${d.title} » a adopté la version ${d.current} (résultat obtenu sur la v${subj.version}).`);
  }
  if (control && r.inputs.controlVersion !== undefined && control.version !== r.inputs.controlVersion) {
    reasons.push(`La définition du contrôle est passée en v${control.version}.`);
  }
  if (project && project.blueprintVersion !== r.inputs.blueprintVersion) {
    const now = projectRules(s, project).rules;
    for (const used of r.inputs.rules) {
      const cur = now.find((e) => e.rule.id === used.ruleId);
      if (!cur) reasons.push(`La règle ${get(s, 'rule', used.ruleId)?.code ?? used.ruleId} ne s’applique plus au projet.`);
      else if (cur.ref.version !== used.version) reasons.push(`Le projet a adopté ${cur.rule.code} v${cur.ref.version} (résultat obtenu avec la v${used.version}).`);
    }
  }
  return { state: reasons.length ? 'stale' : 'current', reasons };
}

/** Latest result per (control, subject deliverable) — older results remain consultable. */
export function latestResults(s: AppState, projectId?: ID) {
  const byKey = new Map<string, Result>();
  list(s, 'result', s.session.orgId)
    .filter((r) => !projectId || r.projectId === projectId)
    .sort((a, b) => a.evaluatedAt - b.evaluatedAt || a.id.localeCompare(b.id))
    .forEach((r) => byKey.set(`${r.controlId}|${r.inputs.subject?.deliverableId ?? ''}`, r));
  return [...byKey.values()];
}

/* ----------------------------------------------------------------- approvals and exceptions */
export function effectiveExceptionStatus(s: AppState, e: RuleException) {
  if (e.status === 'approved' && e.expiresAt !== undefined && e.expiresAt <= nowOf(s)) return 'expired' as const;
  return e.status;
}
export function effectiveApprovalStatus(s: AppState, a: Approval) {
  if (a.status === 'approved' && a.expiresAt !== undefined && a.expiresAt <= nowOf(s)) return 'expired' as const;
  return a.status;
}
export function subjectVersion(s: AppState, ref: Ref): number | undefined {
  switch (ref.kind) {
    case 'deliverable': return get(s, 'deliverable', ref.id)?.current;
    case 'decision': return get(s, 'decision', ref.id)?.number;
    case 'quest': return questRevision(s, ref.id);
    case 'exception': return 1;
    case 'blueprint': return ref.version;
    default: return ref.version;
  }
}
/** A quest's revision changes whenever one of its deliverables adopts a new version (RG-15). */
export function questRevision(s: AppState, questId: ID): number {
  const q = get(s, 'quest', questId);
  if (!q) return 0;
  return q.deliverableIds.reduce((sum, id) => sum + (get(s, 'deliverable', id)?.current ?? 0), 0) + q.revision * 1000;
}
export interface ApprovalCheck { valid: boolean; reason: string }
export function approvalValidity(s: AppState, a: Approval): ApprovalCheck {
  const st = effectiveApprovalStatus(s, a);
  if (st === 'expired') return { valid: false, reason: 'Approbation expirée.' };
  if (st === 'revoked') return { valid: false, reason: 'Approbation révoquée.' };
  if (st === 'refused') return { valid: false, reason: 'Approbation refusée.' };
  if (st === 'expected') return { valid: false, reason: 'Approbation attendue.' };
  const current = subjectVersion(s, a.subject);
  if (current !== undefined && current !== a.subject.version) return { valid: false, reason: `Approbation donnée sur une version antérieure (v${a.subject.version}, actuelle v${current}).` };
  return { valid: true, reason: 'Approbation valide sur la version actuelle.' };
}
export const approvalsFor = (s: AppState, ref: Ref) =>
  list(s, 'approval', s.session.orgId).filter((a) => a.subject.kind === ref.kind && a.subject.id === ref.id).sort((a, b) => a.createdAt - b.createdAt);

/** Valid approved exception covering a rule for a project and an exact deliverable version (RG-25, RG-31). */
export function coveringException(s: AppState, projectId: ID, ruleIds: ID[], subject?: { deliverableId: ID; version: number }) {
  return list(s, 'exception', s.session.orgId).find((e) =>
    e.projectId === projectId && ruleIds.includes(e.ruleId) && effectiveExceptionStatus(s, e) === 'approved' &&
    (!e.subject || !subject || (e.subject.deliverableId === subject.deliverableId && e.subject.version === subject.version)));
}
export function ruleIsDerogable(s: AppState, project: Project, ruleId: ID): boolean {
  const eff = projectRules(s, project).rules.find((e) => e.rule.id === ruleId);
  return eff?.version.derogable ?? false;
}

/* ----------------------------------------------------------------- quests */
export interface ClosureItem { key: string; label: string; status: 'ok' | 'missing' | 'waived' | 'info'; detail: string; fix?: { label: string; to: Ref | string } }

export function questDeliverables(s: AppState, q: Quest): Deliverable[] {
  return q.deliverableIds.map((id) => get(s, 'deliverable', id)).filter((d): d is Deliverable => !!d);
}

/** Every condition checked before closing a quest (RG-21, RG-24, RG-25). */
export function closureReport(s: AppState, questId: ID): ClosureItem[] {
  const q = get(s, 'quest', questId);
  if (!q) return [];
  const project = get(s, 'project', q.projectId)!;
  const items: ClosureItem[] = [];
  items.push(q.ownerId
    ? { key: 'owner', label: 'Responsable désigné', status: 'ok', detail: s.users[q.ownerId]?.name ?? q.ownerId }
    : { key: 'owner', label: 'Responsable désigné', status: 'missing', detail: 'Aucun propriétaire.', fix: { label: 'Renseigner un responsable', to: { kind: 'quest', id: q.id } } });
  const openCriteria = q.criteria.filter((c) => c.required && !c.met);
  items.push({
    key: 'criteria', label: "Critères d’acceptation requis", status: openCriteria.length ? 'missing' : 'ok',
    detail: openCriteria.length ? `${openCriteria.length} critère(s) non satisfait(s) : ${openCriteria.map((c) => c.text).join(' ; ')}` : `${q.criteria.filter((c) => c.required).length} critère(s) satisfait(s).`,
    fix: openCriteria.length ? { label: 'Cocher les critères vérifiés', to: { kind: 'quest', id: q.id } } : undefined,
  });
  const tasks = list(s, 'task', q.orgId).filter((t) => t.questId === q.id);
  const openTasks = tasks.filter((t) => t.status !== 'done' && t.status !== 'cancelled');
  items.push({ key: 'tasks', label: 'Tâches terminées', status: openTasks.length ? 'missing' : 'ok', detail: openTasks.length ? `${openTasks.length} tâche(s) ouverte(s) : ${openTasks.map((t) => t.title).join(' ; ')}` : `${tasks.length} tâche(s) traitée(s).`, fix: openTasks.length ? { label: 'Traiter les tâches ou dépendances', to: { kind: 'quest', id: q.id } } : undefined });
  const dels = questDeliverables(s, q);
  for (const type of q.expectedDeliverables) {
    const d = dels.find((x) => x.type === type);
    const ok = d && (d.status === 'approved' || d.status === 'published');
    items.push({
      key: `deliverable:${type}`, label: `Livrable attendu : ${DELIVERABLE_TYPES[type].label}`, status: ok ? 'ok' : 'missing',
      detail: !d ? 'Aucun livrable rattaché.' : ok ? `${d.title} v${d.current} — ${stateDef('deliverable', d.status).label}` : `${d.title} v${d.current} — ${stateDef('deliverable', d.status).label}, approbation requise.`,
      fix: ok ? undefined : { label: d ? 'Faire approuver le livrable' : 'Fournir le livrable', to: d ? { kind: 'deliverable', id: d.id } : '/forge/studio' },
    });
  }
  const results = latestResults(s, q.projectId);
  for (const controlId of q.controlIds) {
    const control = get(s, 'control', controlId);
    if (!control) continue;
    const subjects = dels.filter((d) => control.appliesTo.includes(d.type));
    if (subjects.length === 0) {
      items.push({ key: `control:${control.id}`, label: `Contrôle ${control.code}`, status: control.blocking ? 'missing' : 'info', detail: 'Aucun livrable évaluable rattaché à la quête : le contrôle ne peut pas être exécuté.', fix: { label: 'Rattacher un livrable', to: { kind: 'quest', id: q.id } } });
      continue;
    }
    for (const d of subjects) items.push(controlItem(s, project, control, d, results));
  }
  if (q.needsHumanApproval) {
    const appr = approvalsFor(s, { kind: 'quest', id: q.id }).filter((a) => a.purpose === 'clôture');
    const valid = appr.find((a) => approvalValidity(s, a).valid);
    const last = appr.at(-1);
    items.push({
      key: 'approval', label: requiresDistinctApprover(s, q.projectId) ? 'Validation humaine par un approbateur distinct' : 'Validation humaine',
      status: valid ? 'ok' : 'missing',
      detail: valid ? `Approuvée par ${s.users[valid.decidedBy ?? '']?.name ?? '—'} sur la révision ${valid.subject.version}.` : last ? approvalValidity(s, last).reason : 'Aucune demande de validation.',
      fix: valid ? undefined : { label: last && effectiveApprovalStatus(s, last) === 'expected' ? 'Obtenir la validation' : 'Demander une validation', to: { kind: 'quest', id: q.id } },
    });
  }
  return items;
}

function controlItem(s: AppState, project: Project, control: ControlDef, d: Deliverable, results: Result[]): ClosureItem {
  const key = `control:${control.id}:${d.id}`;
  const label = `Contrôle ${control.code} sur « ${d.title} »`;
  const r = results.find((x) => x.controlId === control.id && x.inputs.subject?.deliverableId === d.id);
  const rerun = { label: 'Relancer le contrôle', to: `/tour/controles?control=${control.id}&deliverable=${d.id}` };
  const optional = (status: ClosureItem['status']) => (control.blocking ? status : 'info');
  if (!r) return { key, label, status: optional('missing'), detail: 'Jamais exécuté sur ce livrable : aucune preuve.', fix: rerun };
  const fresh = resultFreshness(s, r);
  const outcome = stateDef('result', r.outcome).label;
  if (fresh.state === 'stale') return { key, label, status: optional('missing'), detail: `Résultat ${outcome.toLowerCase()} périmé : ${fresh.reasons.join(' ')}`, fix: rerun };
  if (r.outcome === 'passed') return { key, label, status: 'ok', detail: `Réussi sur la v${r.inputs.subject?.version} (${fmtDate(r.evaluatedAt)}).` };
  if (r.outcome === 'not_applicable') return r.justification ? { key, label, status: 'ok', detail: `Non applicable : ${r.justification}` } : { key, label, status: optional('missing'), detail: 'Non applicable sans justification.', fix: rerun };
  if (r.outcome === 'failed') {
    const derogable = control.ruleIds.every((id) => ruleIsDerogable(s, project, id));
    const exc = derogable ? coveringException(s, project.id, control.ruleIds, r.inputs.subject) : undefined;
    if (exc) return { key, label, status: 'waived', detail: `Résultat toujours échoué ; garde levée par l’exception ${exc.id} approuvée jusqu’au ${fmtDate(exc.expiresAt)}.` };
    return {
      key, label, status: optional('missing'),
      detail: derogable ? 'Échoué. Corrigez puis relancez, ou demandez une exception pour cette version.' : 'Échoué. La règle associée est non dérogeable : seule une correction lève ce blocage.',
      fix: derogable ? { label: 'Voir le constat ou demander une exception', to: '/tour/constats' } : rerun,
    };
  }
  return { key, label, status: optional('missing'), detail: `${outcome} : ne vaut pas réussite. Relancez le contrôle.`, fix: rerun };
}

export const closureBlocked = (items: ClosureItem[]) => items.filter((i) => i.status === 'missing');

export function questProgress(s: AppState, q: Quest): { done: number; total: number; pct: number } {
  const items = closureReport(s, q.id).filter((i) => i.status !== 'info');
  const done = items.filter((i) => i.status === 'ok' || i.status === 'waived').length;
  return { done, total: items.length, pct: items.length ? Math.round((done / items.length) * 100) : 0 };
}

/** True when adding `from → dependsOn` would introduce a cycle (RG-23). */
export function wouldCycle(s: AppState, taskId: ID, dependsOn: ID): boolean {
  if (taskId === dependsOn) return true;
  const seen = new Set<ID>();
  const stack = [dependsOn];
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === taskId) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    stack.push(...(get(s, 'task', cur)?.dependsOn ?? []));
  }
  return false;
}

/* ----------------------------------------------------------------- documents and shares */
export function docUpdateReasons(s: AppState, d: Deliverable): string[] {
  const v = d.versions.find((x) => x.number === d.current);
  return (v?.describes ?? []).flatMap((ref) => {
    const cur = subjectVersion(s, ref);
    const label = objectLabel(s, ref);
    if (ref.kind === 'blueprint') {
      const pub = latestPublished(s, d.orgId);
      return pub && ref.version !== undefined && pub.number > ref.version ? [`Le Blueprint publié est passé en v${pub.number} (document rédigé sur la v${ref.version}).`] : [];
    }
    return cur !== undefined && ref.version !== undefined && cur > ref.version ? [`${label} est passé en v${cur} (document rédigé sur la v${ref.version}).`] : [];
  });
}
export function shareStatus(s: AppState, sh: Share): 'active' | 'expired' | 'revoked' {
  if (sh.status === 'revoked') return 'revoked';
  return sh.expiresAt <= nowOf(s) ? 'expired' : 'active';
}

/* ----------------------------------------------------------------- labels and relations */
export const DELIVERABLE_TYPES = {
  spec: { label: 'Spécification', doc: 'référence' },
  adr: { label: "Décision d’architecture (ADR)", doc: 'explication' },
  code: { label: 'Proposition de code', doc: null },
  tests: { label: 'Tests', doc: null },
  component: { label: 'Composant', doc: null },
  gallery: { label: 'Galerie de composants', doc: 'référence' },
  api: { label: "Référence d’API", doc: 'api' },
  doc: { label: 'Documentation', doc: 'guide' },
  changelog: { label: 'Changelog', doc: 'changelog' },
  roadmap: { label: 'Roadmap', doc: 'roadmap' },
  landing: { label: 'Landing page', doc: 'commercial' },
  presentation: { label: 'Présentation', doc: 'commercial' },
  video: { label: 'Storyboard vidéo', doc: 'commercial' },
} as const;

export const KIND_LABELS: Record<RefKind, string> = {
  org: 'Organisation', user: 'Personne', member: 'Membre', product: 'Produit', project: 'Projet', relation: 'Relation',
  blueprint: 'Blueprint', rule: 'Règle', applicability: 'Applicabilité', collection: 'Collection', pack: 'Pack', expert: 'Expertise',
  skill: 'Skill', council: 'Conseil', decision: 'Décision', quest: 'Quête', task: 'Tâche', deliverable: 'Livrable', control: 'Contrôle',
  run: 'Exécution', result: 'Résultat', evidence: 'Preuve', finding: 'Constat', approval: 'Approbation', exception: 'Exception',
  competitor: 'Concurrent', source: 'Source', signal: 'Signal', opportunity: 'Opportunité', share: 'Partage', integration: 'Intégration',
  review: 'Réexamen', event: 'Événement', reference: 'Référence',
};

export function objectLabel(s: AppState, ref: Ref): string {
  const v = ref.version !== undefined ? ` v${ref.version}` : '';
  switch (ref.kind) {
    case 'reference': return referenceById(s, ref.id)?.name ?? ref.id;
    case 'org': return s.orgs[ref.id]?.name ?? ref.id;
    case 'user': return s.users[ref.id]?.name ?? ref.id;
    case 'blueprint': return `${blueprintOf(s, s.session.orgId)?.name ?? 'Blueprint'}${v}`;
    case 'rule': { const r = get(s, 'rule', ref.id); return r ? `${r.code} ${latestRuleVersion(r).title}${v}` : ref.id; }
    case 'evidence': return `Preuve ${ref.id}`;
    case 'result': { const r = get(s, 'result', ref.id); return r ? `Résultat ${get(s, 'control', r.controlId)?.code ?? ''} (${stateDef('result', r.outcome).label})` : ref.id; }
    case 'approval': { const a = get(s, 'approval', ref.id); return a ? `Approbation ${a.purpose} — ${objectLabel(s, a.subject)}` : ref.id; }
    case 'exception': { const e = get(s, 'exception', ref.id); return e ? `Exception ${get(s, 'rule', e.ruleId)?.code ?? ''}` : ref.id; }
    case 'event': return get(s, 'event', ref.id)?.summary ?? ref.id;
    case 'member': { const m = get(s, 'member', ref.id); return m ? s.users[m.userId]?.name ?? ref.id : ref.id; }
    case 'review': return get(s, 'review', ref.id)?.reason ?? ref.id;
    case 'applicability': { const a = get(s, 'applicability', ref.id); return a ? `Applicabilité ${referenceById(s, a.refId)?.name ?? a.refId}` : ref.id; }
    default: {
      const e = get(s, ref.kind, ref.id) as { title?: string; name?: string } | undefined;
      return (e?.title ?? e?.name ?? ref.id) + v;
    }
  }
}

/** Outgoing relations of an object, used by the Chronicles trace and the "liens" panels. */
export function refsOf(s: AppState, ref: Ref): Ref[] {
  const r = (kind: RefKind, id?: ID | null, version?: number): Ref[] => (id ? [{ kind, id, version }] : []);
  switch (ref.kind) {
    case 'deliverable': { const d = get(s, 'deliverable', ref.id); if (!d) return []; return [...r('quest', d.questId), ...r('project', d.projectId), ...(d.versions.find((v) => v.number === d.current)?.describes ?? [])]; }
    case 'quest': { const q = get(s, 'quest', ref.id); if (!q) return []; return [...r('decision', q.decisionId), ...(q.originRef ? [q.originRef] : []), ...r('project', q.projectId), ...q.controlIds.flatMap((id) => r('control', id)), ...q.deliverableIds.flatMap((id) => r('deliverable', id))]; }
    case 'decision': { const d = get(s, 'decision', ref.id); if (!d) return []; return [...r('council', d.councilId), ...r('decision', d.revisionOf), ...r('blueprint', blueprintOf(s, d.orgId)?.id, d.considered.blueprintVersion), ...d.considered.rules.map((x) => ({ kind: 'rule' as const, id: x.ruleId, version: x.version })), ...d.questIds.flatMap((id) => r('quest', id))]; }
    case 'council': { const c = get(s, 'council', ref.id); if (!c) return []; return [...r('project', c.projectId), ...(c.origin ? [c.origin] : []), ...c.ruleIds.flatMap((id) => r('rule', id)), ...c.participantIds.flatMap((id) => r('expert', id)), ...c.documentIds.flatMap((id) => r('deliverable', id))]; }
    case 'result': { const x = get(s, 'result', ref.id); if (!x) return []; return [...r('run', x.runId), ...r('control', x.controlId), ...r('deliverable', x.inputs.subject?.deliverableId, x.inputs.subject?.version), ...x.inputs.rules.map((y) => ({ kind: 'rule' as const, id: y.ruleId, version: y.version }))]; }
    case 'evidence': { const x = get(s, 'evidence', ref.id); if (!x) return []; return [...r('result', x.resultId), ...r('run', x.runId), ...r('control', x.controlId), ...r('blueprint', blueprintOf(s, x.orgId)?.id, x.inputs.blueprintVersion)]; }
    case 'run': { const x = get(s, 'run', ref.id); if (!x) return []; return [...r('control', x.controlId), ...r('skill', x.skillId), ...r('quest', x.questId), ...r('run', x.previousRunId), ...r('deliverable', x.inputs.subject?.deliverableId ?? x.outputDeliverableId, x.inputs.subject?.version)]; }
    case 'finding': { const x = get(s, 'finding', ref.id); if (!x) return []; return [x.subject, ...r('rule', x.ruleId), ...r('result', x.resultId), ...r('quest', x.questId)]; }
    case 'approval': { const x = get(s, 'approval', ref.id); return x ? [x.subject] : []; }
    case 'exception': { const x = get(s, 'exception', ref.id); if (!x) return []; return [...r('rule', x.ruleId), ...r('project', x.projectId), ...r('deliverable', x.subject?.deliverableId, x.subject?.version)]; }
    case 'control': { const x = get(s, 'control', ref.id); return x ? x.ruleIds.flatMap((id) => r('rule', id)) : []; }
    case 'rule': { const x = get(s, 'rule', ref.id); return x ? latestRuleVersion(x).referenceIds.map((id) => ({ kind: 'reference' as const, id })) : []; }
    case 'share': { const x = get(s, 'share', ref.id); return x ? r('deliverable', x.deliverableId, x.version) : []; }
    case 'signal': { const x = get(s, 'signal', ref.id); if (!x) return []; return [...r('competitor', x.competitorId), ...r('source', x.sourceId), ...r('opportunity', x.opportunityId), ...r('council', x.councilId), ...r('quest', x.questId), ...x.projectIds.flatMap((id) => r('project', id))]; }
    case 'opportunity': { const x = get(s, 'opportunity', ref.id); if (!x) return []; return [...x.signalIds.flatMap((id) => r('signal', id)), ...r('council', x.councilId)]; }
    case 'project': { const x = get(s, 'project', ref.id); if (!x) return []; return [...r('product', x.productId), ...r('blueprint', blueprintOf(s, x.orgId)?.id, x.blueprintVersion), ...x.linkedProductIds.flatMap((id) => r('product', id))]; }
    case 'event': { const x = get(s, 'event', ref.id); return x ? [x.object, ...x.related] : []; }
    case 'review': { const x = get(s, 'review', ref.id); return x ? [x.subject, x.cause] : []; }
    case 'applicability': { const x = get(s, 'applicability', ref.id); return x ? [{ kind: 'reference', id: x.refId }, ...r('project', x.projectId)] : []; }
    default: return [];
  }
}

const incomingCache = new WeakMap<object, { orgId: ID; index: Map<string, Ref[]> }>();
const SCANNED: RefKind[] = ['deliverable', 'quest', 'decision', 'council', 'result', 'evidence', 'run', 'finding', 'approval', 'exception', 'share', 'signal', 'opportunity', 'review', 'applicability', 'control'];
/** Reverse relations, recomputed when the database object changes. */
export function incomingRefs(s: AppState, ref: Ref): Ref[] {
  const orgId = s.session.orgId;
  if (!orgId) return [];
  let cached = incomingCache.get(s.db);
  if (cached?.orgId !== orgId) {
    const index = new Map<string, Ref[]>();
    for (const kind of SCANNED) {
      for (const e of list(s, kind as 'quest', orgId)) {
        const from: Ref = { kind, id: e.id };
        for (const to of refsOf(s, from)) {
          const key = `${to.kind}:${to.id}`;
          index.set(key, [...(index.get(key) ?? []), from]);
        }
      }
    }
    cached = { orgId, index };
    incomingCache.set(s.db, cached);
  }
  return cached.index.get(`${ref.kind}:${ref.id}`) ?? [];
}

/** Breadth-first trace in both directions, used to rebuild the decision → evidence chain. */
export function lineage(s: AppState, start: Ref, depth = 4): { ref: Ref; distance: number; direction: 'amont' | 'aval' | 'origine' }[] {
  const out = new Map<string, { ref: Ref; distance: number; direction: 'amont' | 'aval' | 'origine' }>();
  out.set(`${start.kind}:${start.id}`, { ref: start, distance: 0, direction: 'origine' });
  for (const direction of ['amont', 'aval'] as const) {
    let frontier = [start];
    for (let dist = 1; dist <= depth && frontier.length; dist++) {
      const next: Ref[] = [];
      for (const cur of frontier) {
        const neighbours = direction === 'amont' ? refsOf(s, cur) : incomingRefs(s, cur);
        for (const n of neighbours) {
          if (n.kind === 'project' || n.kind === 'expert' || n.kind === 'event') continue;
          const key = `${n.kind}:${n.id}`;
          if (out.has(key)) continue;
          out.set(key, { ref: n, distance: dist, direction });
          next.push(n);
        }
      }
      frontier = next;
    }
  }
  return [...out.values()];
}

/* ----------------------------------------------------------------- kingdom dashboard */
export function kingdomStats(s: AppState) {
  const orgId = s.session.orgId;
  const projects = list(s, 'project', orgId);
  const active = new Set(projects.filter((p) => p.status === 'active').map((p) => p.id));
  const results = latestResults(s);
  const failed = results.filter((r) => r.outcome === 'failed' && get(s, 'control', r.controlId)?.blocking);
  const stale = results.filter((r) => resultFreshness(s, r).state === 'stale');
  const pendingDecisions = list(s, 'decision', orgId).filter((d) => d.status === 'review' || d.status === 'draft');
  const awaitingCouncils = list(s, 'council', orgId).filter((c) => c.status === 'awaiting');
  const blockedQuests = list(s, 'quest', orgId).filter((q) => q.status === 'blocked' && active.has(q.projectId));
  const pendingApprovals = list(s, 'approval', orgId).filter((a) => a.status === 'expected');
  const openFindings = list(s, 'finding', orgId).filter((f) => f.status === 'open' || f.status === 'in_progress');
  const reviews = list(s, 'review', orgId).filter((r) => r.status === 'open');
  const unknowns = unknownFacts(latestPublished(s, orgId));
  const recent = list(s, 'event', orgId).sort((a, b) => b.at - a.at).slice(0, 6);
  const expiring = list(s, 'exception', orgId).filter((e) => effectiveExceptionStatus(s, e) === 'expired' || (e.status === 'approved' && e.expiresAt && e.expiresAt - nowOf(s) < 7 * DAY));
  return { projects, failed, stale, pendingDecisions, awaitingCouncils, blockedQuests, pendingApprovals, openFindings, reviews, unknowns, recent, expiring };
}

export interface NextAction { text: string; to: Ref | string }
export function nextRecommendedAction(s: AppState): NextAction | null {
  const k = kingdomStats(s);
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : null;
  const mine = k.pendingApprovals.find((a) => a.approverId === me || (!a.approverId && a.authorId !== me));
  if (mine) return { text: `Examiner la demande d'approbation : ${objectLabel(s, mine.subject)}`, to: mine.subject };
  if (k.unknowns[0]) return { text: `Résoudre l'inconnue "${k.unknowns[0].label}"`, to: '/blueprint/assistant' };
  if (k.failed[0]) return { text: `Traiter l'échec du contrôle ${get(s, 'control', k.failed[0].controlId)?.code}`, to: '/tour/constats' };
  if (k.awaitingCouncils[0]) return { text: `Arbitrer le conseil « ${k.awaitingCouncils[0].title} »`, to: { kind: 'council', id: k.awaitingCouncils[0].id } };
  if (k.stale[0]) return { text: 'Relancer les contrôles dont la preuve est à réévaluer', to: '/tour/controles' };
  if (k.reviews[0]) return { text: `Réexaminer : ${k.reviews[0].reason}`, to: '/blueprint/impacts' };
  if (k.blockedQuests[0]) return { text: `Débloquer la quête « ${k.blockedQuests[0].title} »`, to: { kind: 'quest', id: k.blockedQuests[0].id } };
  return null;
}

export interface Notification { id: string; tone: Tone; text: string; to: Ref | string; at: number }
export function notifications(s: AppState): Notification[] {
  const orgId = s.session.orgId;
  const org = orgId ? s.orgs[orgId] : undefined;
  if (!org) return [];
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : null;
  const out: Notification[] = [];
  if (org.settings.notifications.approvals) {
    list(s, 'approval', orgId).filter((a) => a.status === 'expected' && (a.approverId ? a.approverId === me : a.authorId !== me))
      .forEach((a) => out.push({ id: `appr:${a.id}`, tone: 'info', text: `Approbation attendue : ${objectLabel(s, a.subject)}`, to: a.subject, at: a.createdAt }));
  }
  if (org.settings.notifications.controls) {
    latestResults(s).filter((r) => r.outcome === 'failed' || r.outcome === 'inconclusive')
      .forEach((r) => out.push({ id: `res:${r.id}`, tone: r.outcome === 'failed' ? 'danger' : 'warning', text: `Contrôle ${get(s, 'control', r.controlId)?.code} : ${stateDef('result', r.outcome).label.toLowerCase()}`, to: { kind: 'result', id: r.id }, at: r.evaluatedAt }));
    list(s, 'run', orgId).filter((r) => r.status === 'error')
      .forEach((r) => out.push({ id: `run:${r.id}`, tone: 'danger', text: `Erreur d'exécution : ${r.title}`, to: { kind: 'run', id: r.id }, at: r.endedAt ?? r.startedAt }));
  }
  if (org.settings.notifications.exceptions) {
    list(s, 'exception', orgId).filter((e) => effectiveExceptionStatus(s, e) === 'expired')
      .forEach((e) => out.push({ id: `exc:${e.id}:exp`, tone: 'warning', text: `Exception expirée : ${objectLabel(s, { kind: 'rule', id: e.ruleId })} — nouvel examen requis`, to: { kind: 'exception', id: e.id }, at: e.expiresAt ?? 0 }));
    list(s, 'review', orgId).filter((r) => r.status === 'open')
      .forEach((r) => out.push({ id: `rev:${r.id}`, tone: 'warning', text: `À réexaminer : ${r.reason}`, to: r.subject, at: r.createdAt }));
  }
  if (org.settings.notifications.watch) {
    list(s, 'signal', orgId).filter((x) => x.reevaluation === 'proposed')
      .forEach((x) => out.push({ id: `sig:${x.id}`, tone: 'ai', text: `Signal à évaluer : ${x.title}`, to: { kind: 'signal', id: x.id }, at: x.consultedAt }));
  }
  list(s, 'integration', orgId).filter((i) => i.status === 'error' || i.status === 'expired')
    .forEach((i) => out.push({ id: `int:${i.id}:${i.status}`, tone: 'warning', text: `Intégration ${i.name} : ${stateDef('integration', i.status).label.toLowerCase()}`, to: '/intendance/integrations', at: i.changedAt }));
  return out.sort((a, b) => b.at - a.at);
}

/* ----------------------------------------------------------------- formatting */
export function fmtDate(ms?: number, withTime = false): string {
  if (ms === undefined) return '—';
  return new Date(ms).toLocaleString('fr-FR', withTime ? { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: 'short', year: 'numeric' });
}
export function fmtRelative(ms: number, now: number): string {
  const diff = Math.round((ms - now) / DAY);
  if (diff === 0) return "aujourd’hui";
  if (diff === 1) return 'demain';
  if (diff === -1) return 'hier';
  return diff > 0 ? `dans ${diff} j` : `il y a ${-diff} j`;
}

/* ----------------------------------------------------------------- blueprint impacts */
export interface BlueprintImpacts {
  changedRules: { rule: Rule; from?: number; to?: number; change: 'ajoutée' | 'retirée' | 'modifiée' }[];
  changedFacts: { label: string; from: string; to: string; resolved: boolean }[];
  conflicts: RuleConflict[];
  projects: Project[];
  decisions: Decision[];
  quests: Quest[];
  controls: ControlDef[];
  staleResults: Result[];
  docs: Deliverable[];
}
/** What changes when moving from one Blueprint version to another (RG-06), optionally for one project. */
export function blueprintImpacts(s: AppState, from: BlueprintVersion | undefined, to: BlueprintVersion | undefined, projectId?: ID): BlueprintImpacts {
  const orgId = s.session.orgId;
  const empty: BlueprintImpacts = { changedRules: [], changedFacts: [], conflicts: [], projects: [], decisions: [], quests: [], controls: [], staleResults: [], docs: [] };
  if (!to) return empty;
  const fromRules = new Map((from?.rules ?? []).map((r) => [r.ruleId, r.version]));
  const toRules = new Map(to.rules.map((r) => [r.ruleId, r.version]));
  const changedRules: BlueprintImpacts['changedRules'] = [];
  toRules.forEach((v, id) => { const r = get(s, 'rule', id); if (!r) return; if (!fromRules.has(id)) changedRules.push({ rule: r, to: v, change: 'ajoutée' }); else if (fromRules.get(id) !== v) changedRules.push({ rule: r, from: fromRules.get(id), to: v, change: 'modifiée' }); });
  fromRules.forEach((v, id) => { const r = get(s, 'rule', id); if (r && !toRules.has(id)) changedRules.push({ rule: r, from: v, change: 'retirée' }); });
  const changedFacts = to.context.flatMap((f) => {
    const old = from?.context.find((x) => x.key === f.key);
    if (old && old.value === f.value && old.provenance === f.provenance) return [];
    return [{ label: f.label, from: old ? (old.provenance === 'unknown' ? 'inconnue' : old.value) : '—', to: f.provenance === 'unknown' ? 'inconnue' : f.value, resolved: old?.provenance === 'unknown' && f.provenance !== 'unknown' }];
  });
  const changedIds = new Set(changedRules.map((c) => c.rule.id));
  const projects = list(s, 'project', orgId).filter((p) => p.status === 'active' && (projectId ? p.id === projectId : p.blueprintVersion === from?.number));
  const pids = new Set(projects.map((p) => p.id));
  const controls = list(s, 'control', orgId).filter((c) => c.ruleIds.some((id) => changedIds.has(id)));
  const cids = new Set(controls.map((c) => c.id));
  return {
    changedRules,
    changedFacts,
    conflicts: resolveRules(s, to).conflicts,
    projects,
    decisions: list(s, 'decision', orgId).filter((d) => pids.has(d.projectId) && d.status === 'approved' && (changedFacts.length > 0 || d.considered.rules.some((r) => changedIds.has(r.ruleId)))),
    quests: list(s, 'quest', orgId).filter((q) => pids.has(q.projectId) && !['done', 'cancelled'].includes(q.status) && q.controlIds.some((c) => cids.has(c))),
    controls,
    staleResults: latestResults(s).filter((r) => pids.has(r.projectId) && r.inputs.rules.some((x) => changedIds.has(x.ruleId))),
    docs: list(s, 'deliverable', orgId).filter((d) => pids.has(d.projectId) && d.docCategory && d.versions.find((v) => v.number === d.current)?.describes.some((x) => x.kind === 'blueprint' && from && x.version === from.number)),
  };
}
