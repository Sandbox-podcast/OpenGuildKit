/**
 * Blueprint commands. A published version is immutable (RG-04): every change goes through
 * a new draft version, its review and its publication. Projects follow an explicit version and
 * adopt a new one only after seeing its impacts (RG-06).
 */
import type { Draft } from 'immer';
import { command, emit, fail, insert, list, must, nextId, requireHuman, type Ctx, clone } from '../engine';
import { blueprintImpacts, blueprintOf, bpVersion, latestPublished, openDraft } from '../selectors';
import { flagReview } from './transitions';
import type { AppState, ContextFact, ID, Provenance, RuleScope, RuleVersion } from '../types';

type D = Draft<AppState>;

function draftVersion(d: D | AppState, ctx: Ctx, n: number) {
  const v = bpVersion(d as AppState, ctx.orgId, n) ?? fail('Version introuvable.');
  if (v.status !== 'draft') fail(`La version ${n} est ${v.status === 'published' ? 'publiée et donc immuable' : 'en revue'} : préparez une nouvelle version.`);
  return v;
}
const isDraft = (s: AppState, ctx: Ctx, n: number) => {
  const v = bpVersion(s, ctx.orgId, n);
  return !v ? 'Version introuvable.' : v.status !== 'draft' ? (v.status === 'published' ? 'Version publiée : elle est immuable. Préparez une nouvelle version.' : 'Version en revue : renvoyez-la en brouillon pour la modifier.') : null;
};

export const startBlueprintDraft = command<{ justification: string }, number>({
  name: 'startBlueprintDraft',
  capability: 'propose',
  guard: (s, ctx, p) => (openDraft(s, ctx.orgId) ? `La version ${openDraft(s, ctx.orgId)!.number} est déjà en préparation.` : !latestPublished(s, ctx.orgId) ? 'Aucune version publiée à faire évoluer.' : p.justification.trim().length < 5 ? 'Expliquez la raison de cette évolution.' : null),
  run: (d, ctx, p) => {
    const bp = must(d, 'blueprint', blueprintOf(d as AppState, ctx.orgId)?.id);
    const base = latestPublished(d as AppState, ctx.orgId)!;
    const number = Math.max(...bp.versions.map((v) => v.number)) + 1;
    bp.versions.push({ ...clone(base), number, status: 'draft', authorId: requireHuman(ctx), justification: p.justification, basedOn: base.number, createdAt: ctx.now, submittedAt: undefined, publishedAt: undefined, reviewerId: undefined });
    emit(d, ctx, { action: 'blueprint.draft', summary: `Nouvelle version ${number} du Blueprint en préparation (basée sur la v${base.number})`, object: { kind: 'blueprint', id: bp.id, version: number }, justification: p.justification });
    return number;
  },
});

export const setFact = command<{ version: number; key: string; value: string; provenance?: Provenance; label?: string; section?: string; note?: string }>({
  name: 'setFact',
  capability: 'propose',
  guard: (s, ctx, p) => isDraft(s, ctx, p.version) ?? (p.provenance !== 'unknown' && !p.value.trim() ? 'Renseignez une valeur ou marquez l’information comme inconnue.' : null),
  run: (d, ctx, p) => {
    const v = draftVersion(d, ctx, p.version);
    let f = v.context.find((x) => x.key === p.key);
    const was = f?.provenance;
    if (!f) {
      f = { key: p.key, section: p.section ?? 'Contexte', label: p.label ?? p.key, value: '', provenance: 'declared' } as ContextFact;
      v.context.push(f);
    }
    f.value = p.provenance === 'unknown' ? '' : p.value.trim();
    f.provenance = p.provenance ?? 'declared';
    f.source = p.note ?? (was === 'unknown' ? 'Inconnue résolue' : 'Déclaré dans le Blueprint');
    f.confirmedBy = undefined;
    emit(d, ctx, { action: was === 'unknown' && f.provenance === 'declared' ? 'blueprint.unknown.resolved' : 'blueprint.fact', summary: was === 'unknown' && f.provenance === 'declared' ? `Inconnue résolue : ${f.label} = ${f.value}` : `Contexte modifié : ${f.label}`, object: { kind: 'blueprint', id: blueprintOf(d as AppState, ctx.orgId)!.id, version: p.version } });
  },
});

export const confirmInferred = command<{ version: number; key: string }>({
  name: 'confirmInferred',
  capability: 'propose',
  humanOnly: true,
  guard: (s, ctx, p) => isDraft(s, ctx, p.version) ?? (bpVersion(s, ctx.orgId, p.version)?.context.find((f) => f.key === p.key)?.provenance === 'inferred' ? null : 'Seule une valeur inférée peut être confirmée.'),
  run: (d, ctx, p) => {
    const f = draftVersion(d, ctx, p.version).context.find((x) => x.key === p.key)!;
    f.confirmedBy = requireHuman(ctx);
    emit(d, ctx, { action: 'blueprint.inferred.confirmed', summary: `Valeur inférée confirmée : ${f.label}`, object: { kind: 'blueprint', id: blueprintOf(d as AppState, ctx.orgId)!.id, version: p.version } });
  },
});

export interface RuleInput {
  code: string; title: string; statement: string; referenceIds: string[]; scope: RuleScope; ownerId: ID;
  criticality: RuleVersion['criticality']; blocking: boolean; derogable: boolean; policy: RuleVersion['policy'];
  parameter?: RuleVersion['parameter']; expectedControlIds: ID[]; justification: string; conflictGroup?: string;
}
const ruleProblems = (p: RuleInput) =>
  !/^[A-Z0-9-]{3,20}$/.test(p.code) ? 'Code de règle attendu en majuscules (ex. SEC-ISO-02).'
    : p.title.trim().length < 4 ? 'Titre trop court.'
      : p.statement.trim().length < 15 ? 'La formulation doit être vérifiable (15 caractères au moins).'
        : !p.ownerId ? 'Une règle a un propriétaire.'
          : p.policy === 'adjustable' && !p.parameter ? 'Une règle ajustable déclare son paramètre et ses bornes.'
            : p.parameter && (p.parameter.min > p.parameter.max || p.parameter.value < p.parameter.min || p.parameter.value > p.parameter.max) ? 'Valeur du paramètre hors de ses bornes.' : null;

/** Adds a new rule (draft v1) to the draft Blueprint version. */
export const addRule = command<{ version: number; rule: RuleInput; adapts?: ID }, ID>({
  name: 'addRule',
  capability: 'propose',
  guard: (s, ctx, p) => isDraft(s, ctx, p.version) ?? ruleProblems(p.rule) ?? (list(s, 'rule', ctx.orgId).some((r) => r.code === p.rule.code) ? `Le code ${p.rule.code} existe déjà.` : null) ?? adaptationProblem(s, ctx, p),
  run: (d, ctx, p) => {
    const v = draftVersion(d, ctx, p.version);
    const id = nextId(d, 'rul');
    const { justification, ...rest } = p.rule;
    insert(d, 'rule', { id, orgId: ctx.orgId, code: p.rule.code, versions: [{ ...rest, number: 1, status: 'draft', adapts: p.adapts, authorId: requireHuman(ctx), justification, createdAt: ctx.now }] });
    v.rules.push({ ruleId: id, version: 1 });
    emit(d, ctx, { action: p.adapts ? 'rule.adapted' : 'rule.created', summary: `${p.adapts ? 'Adaptation proposée' : 'Règle ajoutée'} : ${p.rule.code} ${p.rule.title} (brouillon v${p.version})`, object: { kind: 'rule', id, version: 1 }, justification, related: p.adapts ? [{ kind: 'rule', id: p.adapts }] : [] });
    return id;
  },
});

/** Inheritance check for adaptations (RG-05): forbidden adaptations are refused with their reason. */
function adaptationProblem(s: AppState, ctx: Ctx, p: { version: number; rule: RuleInput; adapts?: ID }): string | null {
  if (!p.adapts) return null;
  const v = bpVersion(s, ctx.orgId, p.version)!;
  const ref = v.rules.find((r) => r.ruleId === p.adapts);
  const parentRule = s.db.rule[p.adapts];
  const parent = parentRule?.versions.find((x) => x.number === ref?.version);
  if (!parent || !parentRule) return 'Règle parente absente de cette version du Blueprint.';
  const rank = { org: 0, product: 1, repo: 2, module: 3 };
  if (rank[p.rule.scope.level] <= rank[parent.scope.level]) return 'Une adaptation s’applique à un niveau inférieur à celui de la règle parente.';
  if (parent.policy === 'imposed') return `${parentRule.code} est imposée : aucune adaptation n’est autorisée aux niveaux inférieurs. Demandez une exception si la situation l’exige.`;
  if (parent.policy === 'additive') return `${parentRule.code} est additive : ajoutez une règle complémentaire au lieu de la remplacer.`;
  if (parent.parameter) {
    const val = p.rule.parameter?.value;
    if (val === undefined) return `Indiquez la nouvelle valeur de « ${parent.parameter.name} ».`;
    if (val < parent.parameter.min || val > parent.parameter.max) return `Valeur ${val} ${parent.parameter.unit} hors des bornes autorisées par ${parentRule.code} (${parent.parameter.min}–${parent.parameter.max}).`;
  }
  return null;
}

/** Edits a rule: creates its next draft version, referenced by the draft Blueprint version. */
export const editRule = command<{ version: number; ruleId: ID; patch: Partial<RuleInput> }>({
  name: 'editRule',
  capability: 'propose',
  guard: (s, ctx, p) => {
    const bad = isDraft(s, ctx, p.version);
    if (bad) return bad;
    const rule = s.db.rule[p.ruleId];
    if (!rule) return 'Règle introuvable.';
    const ref = bpVersion(s, ctx.orgId, p.version)!.rules.find((r) => r.ruleId === p.ruleId);
    if (!ref) return 'Cette règle ne figure pas dans la version en préparation.';
    const cur = rule.versions.find((v) => v.number === ref.version)!;
    return ruleProblems({ ...cur, code: rule.code, ...p.patch } as RuleInput);
  },
  run: (d, ctx, p) => {
    const v = draftVersion(d, ctx, p.version);
    const rule = must(d, 'rule', p.ruleId, ctx.orgId);
    const ref = v.rules.find((r) => r.ruleId === p.ruleId)!;
    const cur = rule.versions.find((x) => x.number === ref.version)!;
    const { code: _code, ...patch } = p.patch;
    if (cur.status === 'draft') {
      Object.assign(cur, patch);
    } else {
      const number = Math.max(...rule.versions.map((x) => x.number)) + 1;
      rule.versions.push({ ...clone(cur), ...patch, number, status: 'draft', authorId: requireHuman(ctx), createdAt: ctx.now });
      ref.version = number;
    }
    emit(d, ctx, { action: 'rule.edited', summary: `Règle ${rule.code} modifiée dans le brouillon v${p.version} (v${ref.version})`, object: { kind: 'rule', id: rule.id, version: ref.version }, justification: p.patch.justification });
  },
});

export const removeRuleFromDraft = command<{ version: number; ruleId: ID; reason: string }>({
  name: 'removeRuleFromDraft',
  capability: 'propose',
  guard: (s, ctx, p) => isDraft(s, ctx, p.version) ?? (p.reason.trim().length < 5 ? 'Justifiez le retrait de la règle.' : null),
  run: (d, ctx, p) => {
    const v = draftVersion(d, ctx, p.version);
    v.rules = v.rules.filter((r) => r.ruleId !== p.ruleId);
    const rule = must(d, 'rule', p.ruleId);
    emit(d, ctx, { action: 'rule.removed', summary: `Règle ${rule.code} retirée du brouillon v${p.version}`, object: { kind: 'rule', id: rule.id }, justification: p.reason });
  },
});

/** Arbitration of competing rules: keeps one, removes the others with a recorded reason. */
export const arbitrateConflict = command<{ version: number; keepRuleId: ID; dropRuleIds: ID[]; reason: string }>({
  name: 'arbitrateConflict',
  capability: 'publish',
  humanOnly: true,
  guard: (s, ctx, p) => isDraft(s, ctx, p.version) ?? (p.reason.trim().length < 5 ? 'Motivez l’arbitrage.' : null),
  run: (d, ctx, p) => {
    const v = draftVersion(d, ctx, p.version);
    v.rules = v.rules.filter((r) => !p.dropRuleIds.includes(r.ruleId));
    const kept = d.db.rule[p.keepRuleId];
    const keptRef = v.rules.find((r) => r.ruleId === p.keepRuleId);
    const kv = kept?.versions.find((x) => x.number === keptRef?.version);
    if (kv?.status === 'draft') kv.conflictGroup = undefined;
    else if (kept && keptRef) {
      const number = Math.max(...kept.versions.map((x) => x.number)) + 1;
      kept.versions.push({ ...clone(kv!), number, status: 'draft', conflictGroup: undefined, createdAt: ctx.now, authorId: requireHuman(ctx), justification: p.reason });
      keptRef.version = number;
    }
    emit(d, ctx, { action: 'rule.arbitrated', summary: `Arbitrage : ${kept?.code} retenue, ${p.dropRuleIds.map((id) => d.db.rule[id]?.code).join(', ')} écartée(s)`, object: { kind: 'rule', id: p.keepRuleId }, justification: p.reason, related: p.dropRuleIds.map((id) => ({ kind: 'rule', id })) });
  },
});

export const excludeReference = command<{ version: number; refId: string; reason: string }>({
  name: 'excludeReference',
  capability: 'propose',
  guard: (s, ctx, p) => isDraft(s, ctx, p.version) ?? (p.reason.trim().length < 10 ? 'Justifiez l’exclusion (10 caractères au moins).' : null),
  run: (d, ctx, p) => {
    const v = draftVersion(d, ctx, p.version);
    v.exclusions = v.exclusions.filter((e) => e.refId !== p.refId).concat({ refId: p.refId, reason: p.reason, authorId: requireHuman(ctx), at: ctx.now });
    emit(d, ctx, { action: 'blueprint.exclusion', summary: `Exclusion justifiée : ${p.refId}`, object: { kind: 'reference', id: p.refId }, justification: p.reason });
  },
});

/** A project adopts another published version after seeing its impacts (RG-06, RG-29). */
export const adoptBlueprint = command<{ projectId: ID; version: number; reason: string }>({
  name: 'adoptBlueprint',
  capability: 'publish',
  project: (p) => p.projectId,
  humanOnly: true,
  guard: (s, ctx, p) => {
    const pr = s.db.project[p.projectId];
    const v = bpVersion(s, ctx.orgId, p.version);
    if (!pr) return 'Projet introuvable.';
    if (!v || v.status !== 'published') return 'Seule une version publiée peut être adoptée.';
    if (pr.blueprintVersion === p.version) return 'Le projet suit déjà cette version.';
    return p.reason.trim().length < 5 ? 'Motivez l’adoption.' : null;
  },
  run: (d, ctx, p) => {
    const pr = must(d, 'project', p.projectId, ctx.orgId);
    const s = d as AppState;
    const impacts = blueprintImpacts(s, bpVersion(s, ctx.orgId, pr.blueprintVersion), bpVersion(s, ctx.orgId, p.version), pr.id);
    const from = pr.blueprintVersion;
    pr.blueprintVersion = p.version;
    const cause = { kind: 'blueprint' as const, id: blueprintOf(s, ctx.orgId)!.id, version: p.version };
    impacts.decisions.forEach((dec) => flagReview(d, ctx, { kind: 'decision', id: dec.id }, cause, `Décision prise sur le Blueprint v${dec.considered.blueprintVersion}, le projet adopte la v${p.version}`, pr.id));
    impacts.quests.forEach((q) => flagReview(d, ctx, { kind: 'quest', id: q.id }, cause, `Quête ouverte : règles modifiées par la v${p.version}`, pr.id));
    emit(d, ctx, {
      action: 'blueprint.adopted', projectId: pr.id, object: cause, justification: p.reason,
      summary: `« ${pr.name} » adopte le Blueprint v${p.version} (au lieu de v${from}) : ${impacts.changedRules.length} règle(s) modifiée(s), ${impacts.staleResults.length} résultat(s) à réévaluer, ${impacts.decisions.length + impacts.quests.length} objet(s) à réexaminer`,
      related: [{ kind: 'project', id: pr.id }],
    });
  },
});

export const resolveReview = command<{ id: ID; note: string }>({
  name: 'resolveReview',
  capability: 'edit',
  project: (p, s) => s.db.review[p.id]?.projectId,
  guard: (_s, _c, p) => (p.note.trim().length < 3 ? 'Indiquez la conclusion du réexamen.' : null),
  run: (d, ctx, p) => {
    const r = must(d, 'review', p.id, ctx.orgId);
    r.status = 'done';
    r.doneBy = requireHuman(ctx);
    emit(d, ctx, { action: 'review.done', summary: `Réexamen conclu : ${r.reason}`, object: r.subject, projectId: r.projectId, justification: p.note, related: [{ kind: 'review', id: r.id }] });
  },
});
