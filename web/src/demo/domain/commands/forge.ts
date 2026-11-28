/**
 * Forge: skills, executions (controls and skills) and the deliverable studio.
 * Executions advance through `tick` one step at a time; the state is the source of truth,
 * so a reload resumes them and a cancelled execution never completes later (RG-26, RG-30).
 */
import type { Draft } from 'immer';
import { services } from '@/demo/adapters/services';
import { command, emit, fail, get, insert, list, must, nextId, requireHuman, type Ctx, clone } from '../engine';
import { blueprintOf, bpVersion, DELIVERABLE_TYPES, fact, projectRules } from '../selectors';
import type { AppState, Content, Deliverable, DeliverableType, DocCategory, ID, Ref, Run } from '../types';

type D = Draft<AppState>;

/* ---------------------------------------------------------------- skills */

export const installSkill = command<{ id: ID; version?: string }>({
  name: 'installSkill',
  capability: 'configure_agents',
  guard: (s, _c, p) => (s.db.skill[p.id]?.installed ? 'Déjà installée.' : null),
  run: (d, ctx, p) => {
    const sk = must(d, 'skill', p.id, ctx.orgId);
    sk.installed = p.version ?? sk.versions[0].version;
    sk.active = false;
    emit(d, ctx, { action: 'skill.installed', summary: `Skill « ${sk.name} » ${sk.installed} installée (inactive tant qu’elle n’est pas activée)`, object: { kind: 'skill', id: sk.id } });
  },
});

export const setSkillActive = command<{ id: ID; active: boolean }>({
  name: 'setSkillActive',
  capability: 'configure_agents',
  guard: (s, _c, p) => (!s.db.skill[p.id]?.installed ? 'Installez la skill avant de l’activer.' : s.db.skill[p.id].active === p.active ? 'Aucun changement.' : null),
  run: (d, ctx, p) => {
    const sk = must(d, 'skill', p.id, ctx.orgId);
    sk.active = p.active;
    emit(d, ctx, { action: p.active ? 'skill.activated' : 'skill.deactivated', summary: `Skill « ${sk.name} » ${p.active ? 'activée' : 'désactivée'}`, object: { kind: 'skill', id: sk.id } });
  },
});

export const setSkillParams = command<{ id: ID; params: Record<string, string> }>({
  name: 'setSkillParams',
  capability: 'configure_agents',
  run: (d, ctx, p) => {
    const sk = must(d, 'skill', p.id, ctx.orgId);
    sk.params = { ...sk.params, ...p.params };
    emit(d, ctx, { action: 'skill.params', summary: `Paramètres de « ${sk.name} » modifiés`, object: { kind: 'skill', id: sk.id } });
  },
});

/** Simulated discovery of a new version: a proposal with its differences, never an automatic update (RG-37). */
export const checkSkillUpdate = command<{ id: ID }>({
  name: 'checkSkillUpdate',
  capability: 'propose',
  guard: (s, _c, p) => {
    const sk = s.db.skill[p.id];
    if (!sk?.installed) return 'Skill non installée.';
    if (sk.update && ['proposed', 'review'].includes(sk.update.status)) return 'Une mise à jour est déjà en attente.';
    const idx = sk.versions.findIndex((v) => v.version === sk.installed);
    return idx === sk.versions.length - 1 ? 'Aucune version plus récente dans le catalogue de démonstration.' : null;
  },
  run: (d, ctx, p) => {
    const sk = must(d, 'skill', p.id, ctx.orgId);
    const next = sk.versions[sk.versions.findIndex((v) => v.version === sk.installed) + 1];
    sk.update = { version: next.version, status: 'proposed', at: ctx.now };
    emit(d, ctx, { action: 'skill.update.proposed', summary: `Mise à jour ${next.version} proposée pour « ${sk.name} »`, object: { kind: 'skill', id: sk.id }, provenance: 'simulation' });
  },
});

export const decideSkillUpdate = command<{ id: ID; action: 'review' | 'adopt' | 'dismiss' | 'restore'; reason?: string }>({
  name: 'decideSkillUpdate',
  capability: (p) => (p.action === 'review' ? 'propose' : 'configure_agents'),
  humanOnly: true,
  guard: (s, ctx, p) => {
    const sk = s.db.skill[p.id];
    if (!sk) return 'Skill introuvable.';
    if (p.action === 'restore') return sk.previous ? null : 'Aucune version précédente à restaurer.';
    if (!sk.update) return 'Aucune mise à jour proposée.';
    if (p.action === 'review') return sk.update.status === 'proposed' ? null : 'Déjà en revue ou traitée.';
    if (sk.update.status !== 'review') return 'Passez d’abord la mise à jour en revue pour examiner ses changements.';
    if (p.action === 'adopt' && sk.update.reviewerId === (ctx.actor.type === 'human' ? ctx.actor.userId : '')) {
      const cur = sk.versions.find((v) => v.version === sk.installed)!;
      const next = sk.versions.find((v) => v.version === sk.update!.version)!;
      if (next.permissions.some((x) => !cur.permissions.includes(x))) return 'Cette mise à jour ajoute une permission : une autre personne que celle qui l’a examinée doit l’adopter.';
    }
    return p.action === 'dismiss' && !(p.reason ?? '').trim() ? 'Indiquez pourquoi la mise à jour est écartée.' : null;
  },
  run: (d, ctx, p) => {
    const sk = must(d, 'skill', p.id, ctx.orgId);
    const who = requireHuman(ctx);
    if (p.action === 'review') { sk.update!.status = 'review'; sk.update!.reviewerId = who; }
    if (p.action === 'adopt') { sk.previous = sk.installed ?? undefined; sk.installed = sk.update!.version; sk.update!.status = 'adopted'; }
    if (p.action === 'dismiss') sk.update!.status = 'dismissed';
    if (p.action === 'restore') { const cur = sk.installed; sk.installed = sk.previous!; sk.previous = cur ?? undefined; }
    const label = { review: 'mise en revue', adopt: 'adoptée', dismiss: 'écartée', restore: 'version précédente restaurée' }[p.action];
    emit(d, ctx, { action: `skill.update.${p.action}`, summary: `« ${sk.name} » : ${label} (${sk.installed})`, object: { kind: 'skill', id: sk.id }, justification: p.reason });
  },
});

/* ---------------------------------------------------------------- executions */

function inputsFor(s: AppState, projectId: ID, ruleIds: ID[]) {
  const project = must(s, 'project', projectId);
  const eff = projectRules(s, project).rules;
  return { blueprintVersion: project.blueprintVersion, rules: eff.filter((e) => ruleIds.includes(e.rule.id)).map((e) => e.ref) };
}

function newRun(d: D, ctx: Ctx, base: Omit<Run, 'id' | 'orgId' | 'status' | 'stepIndex' | 'log' | 'startedAt' | 'actor' | 'plannedFailure' | 'attempt'> & { attempt?: number }): ID {
  const id = nextId(d, 'run');
  const failure = d.demo.nextFailure;
  d.demo.nextFailure = null;
  insert(d, 'run', { ...base, id, orgId: ctx.orgId, status: 'running', stepIndex: 0, attempt: base.attempt ?? 1, plannedFailure: failure, startedAt: ctx.now, actor: ctx.actor, log: [{ at: ctx.now, level: 'info', text: `Exécution lancée (tentative ${base.attempt ?? 1}). Résultat simulé par l’adaptateur de démonstration.` }] });
  emit(d, ctx, { action: 'run.started', summary: `Exécution lancée : ${base.title}`, object: { kind: 'run', id }, projectId: base.projectId, provenance: 'simulation', related: base.inputs.subject ? [{ kind: 'deliverable', id: base.inputs.subject.deliverableId, version: base.inputs.subject.version }] : [] });
  return id;
}

export const launchControl = command<{ controlId: ID; deliverableId: ID; questId?: ID }, ID>({
  name: 'launchControl',
  capability: 'run_controls',
  project: (p, s) => s.db.deliverable[p.deliverableId]?.projectId,
  guard: (s, ctx, p) => {
    const c = s.db.control[p.controlId];
    const dl = s.db.deliverable[p.deliverableId];
    if (!c || !dl) return 'Contrôle ou livrable introuvable.';
    if (!c.appliesTo.includes(dl.type)) return `Le contrôle ${c.code} ne s’applique pas à un livrable de type ${DELIVERABLE_TYPES[dl.type].label}.`;
    const dup = list(s, 'run', ctx.orgId).find((r) => r.controlId === c.id && r.inputs.subject?.deliverableId === dl.id && r.inputs.subject.version === dl.current && ['running', 'pending', 'suspended'].includes(r.status));
    return dup ? `Une exécution de ${c.code} est déjà en cours sur cette version (${dup.id}).` : null;
  },
  run: (d, ctx, p) => {
    const c = must(d, 'control', p.controlId, ctx.orgId);
    const dl = must(d, 'deliverable', p.deliverableId, ctx.orgId);
    return newRun(d, ctx, {
      projectId: dl.projectId, kind: 'control', controlId: c.id, questId: p.questId ?? dl.questId, title: `${c.code} — ${dl.title} v${dl.current}`,
      inputs: { ...inputsFor(d as AppState, dl.projectId, c.ruleIds), controlVersion: c.version, subject: { deliverableId: dl.id, version: dl.current }, params: { stratégie: services.controls.strategyLabels[c.strategy] ?? c.strategy } },
      steps: services.controls.steps.map((label) => ({ label, status: 'pending' as const })), costPerStep: 2, suspendable: true,
    });
  },
});

export const launchSkill = command<{ skillId: ID; questId: ID; type?: DeliverableType; variant?: 'initial' | 'correctif' }, ID>({
  name: 'launchSkill',
  capability: 'propose',
  project: (p, s) => s.db.quest[p.questId]?.projectId,
  guard: (s, ctx, p) => {
    const sk = s.db.skill[p.skillId];
    const q = s.db.quest[p.questId];
    if (!sk || !q) return 'Skill ou quête introuvable.';
    if (!sk.installed) return `La skill « ${sk.name} » n’est pas installée.`;
    if (!sk.active) return `La skill « ${sk.name} » est installée mais inactive : activez-la dans la Forge.`;
    if (['done', 'cancelled'].includes(q.status)) return 'Quête close.';
    if (ctx.actor.type === 'agent') {
      const ex = s.db.expert[ctx.actor.expertId];
      if (!ex?.skillIds.includes(sk.id)) return `${ex?.name ?? 'Cet agent'} n’est pas autorisé à utiliser cette skill.`;
    }
    const busy = list(s, 'run', ctx.orgId).find((r) => r.skillId === sk.id && r.questId === q.id && ['running', 'pending', 'suspended'].includes(r.status));
    return busy ? 'Une génération est déjà en cours pour cette quête.' : null;
  },
  run: (d, ctx, p) => {
    const sk = must(d, 'skill', p.skillId, ctx.orgId);
    const q = must(d, 'quest', p.questId, ctx.orgId);
    const type = p.type ?? sk.produces ?? fail('Type de livrable non précisé.');
    return newRun(d, ctx, {
      projectId: q.projectId, kind: 'skill', skillId: sk.id, questId: q.id, title: `${sk.name} — ${DELIVERABLE_TYPES[type].label} pour « ${q.title} »`,
      inputs: { ...inputsFor(d as AppState, q.projectId, []), params: { type, variante: p.variant ?? 'initial', version: sk.installed ?? '' } },
      steps: services.controls.skillSteps.map((label) => ({ label, status: 'pending' as const })), costPerStep: 3, suspendable: false,
    });
  },
});

export const retryRun = command<{ runId: ID }, ID>({
  name: 'retryRun',
  capability: 'run_controls',
  project: (p, s) => s.db.run[p.runId]?.projectId,
  guard: (s, ctx, p) => {
    const r = s.db.run[p.runId];
    if (!r) return 'Exécution introuvable.';
    if (!['error', 'cancelled', 'done'].includes(r.status)) return 'Seule une exécution terminée, annulée ou en erreur peut être relancée.';
    return list(s, 'run', ctx.orgId).some((x) => x.previousRunId === r.id && ['running', 'pending', 'suspended'].includes(x.status)) ? 'Une relance est déjà en cours.' : null;
  },
  run: (d, ctx, p) => {
    const r = must(d, 'run', p.runId, ctx.orgId);
    const base = { projectId: r.projectId, kind: r.kind, controlId: r.controlId, skillId: r.skillId, questId: r.questId, steps: r.steps.map((st) => ({ label: st.label, status: 'pending' as const })), costPerStep: r.costPerStep, suspendable: r.suspendable, previousRunId: r.id, attempt: r.attempt + 1 };
    if (r.kind === 'control') {
      const c = must(d, 'control', r.controlId);
      const dl = must(d, 'deliverable', r.inputs.subject?.deliverableId);
      return newRun(d, ctx, { ...base, title: `${c.code} — ${dl.title} v${dl.current}`, inputs: { ...inputsFor(d as AppState, r.projectId, c.ruleIds), controlVersion: c.version, subject: { deliverableId: dl.id, version: dl.current }, params: r.inputs.params } });
    }
    return newRun(d, ctx, { ...base, title: r.title, inputs: { ...inputsFor(d as AppState, r.projectId, []), params: r.inputs.params } });
  },
});

/** Advances one running execution by one step. Never touches a cancelled or suspended run. */
export function advanceRun(d: D, ctx: Ctx, runId: ID) {
  const r = d.db.run[runId];
  if (!r || r.status !== 'running') return;
  const org = d.orgs[r.orgId];
  const sys = { ...ctx, actor: { type: 'system' as const }, orgId: r.orgId };
  if (org.settings.budget.used + r.costPerStep > org.settings.budget.monthlyUnits) {
    r.status = 'error';
    r.statusReason = `Budget de simulation atteint (${org.settings.budget.used}/${org.settings.budget.monthlyUnits} unités).`;
    r.endedAt = ctx.now;
    r.steps[r.stepIndex].status = 'error';
    r.log.push({ at: ctx.now, level: 'error', text: `Interrompue : ${r.statusReason} Augmentez le budget dans l’Intendance puis relancez.` });
    emit(d, sys, { action: 'run.budget', summary: `Exécution interrompue par la limite de budget : ${r.title}`, object: { kind: 'run', id: r.id }, projectId: r.projectId, provenance: 'simulation' });
    return;
  }
  org.settings.budget.used += r.costPerStep;
  const step = r.steps[r.stepIndex];
  step.status = 'running';
  if (r.plannedFailure === 'tool-error' && r.stepIndex === 2) {
    step.status = 'error';
    r.status = 'error';
    r.statusReason = services.controls.toolError;
    r.endedAt = ctx.now;
    r.log.push({ at: ctx.now, level: 'error', text: services.controls.toolError });
    emit(d, sys, { action: 'run.error', summary: `Erreur technique (simulée) : ${r.title}`, object: { kind: 'run', id: r.id }, projectId: r.projectId, provenance: 'simulation' });
    return;
  }
  step.status = 'done';
  r.log.push({ at: ctx.now, level: 'info', text: `${step.label} — terminé.` });
  r.stepIndex += 1;
  if (r.stepIndex < r.steps.length) return;
  r.status = 'done';
  r.endedAt = ctx.now;
  if (r.kind === 'control') finalizeControl(d, sys, r);
  else finalizeSkill(d, sys, r);
}

function finalizeControl(d: D, ctx: Ctx, r: Run) {
  const control = d.db.control[r.controlId!];
  const subject = r.inputs.subject!;
  const dl = d.db.deliverable[subject.deliverableId];
  const content = dl?.versions.find((v) => v.number === subject.version)?.content;
  const ev = r.plannedFailure === 'inconclusive'
    ? { outcome: 'inconclusive' as const, observation: 'Résultat non concluant injecté depuis les paramètres de démonstration : la vérification n’a pas pu trancher.' }
    : services.controls.evaluate(control.strategy, content);
  const resultId = nextId(d, 'res');
  insert(d, 'result', { id: resultId, orgId: r.orgId, projectId: r.projectId, runId: r.id, controlId: control.id, outcome: ev.outcome, observation: ev.observation, justification: ev.outcome === 'not_applicable' ? ev.observation : undefined, inputs: clone(r.inputs), evaluatedAt: ctx.now, simulated: true });
  r.resultId = resultId;
  const evidenceId = nextId(d, 'prv');
  const excerpt = JSON.stringify({ contrôle: control.code, version: control.version, livrable: `${dl?.title} v${subject.version}`, blueprint: `v${r.inputs.blueprintVersion}`, règles: r.inputs.rules, résultat: ev.outcome, observation: ev.observation }, null, 2);
  insert(d, 'evidence', { id: evidenceId, orgId: r.orgId, projectId: r.projectId, resultId, runId: r.id, controlId: control.id, inputs: clone(r.inputs), at: ctx.now, actor: r.actor, provenance: 'Adaptateur de contrôle de démonstration', digest: services.controls.digest(excerpt), excerpt, simulated: true });
  r.log.push({ at: ctx.now, level: ev.outcome === 'failed' ? 'error' : ev.outcome === 'passed' ? 'info' : 'warn', text: `Résultat : ${ev.outcome} — ${ev.observation}` });
  emit(d, ctx, { action: `result.${ev.outcome}`, summary: `${control.code} sur « ${dl?.title} » v${subject.version} : ${{ passed: 'réussi', failed: 'échoué', inconclusive: 'non concluant', not_applicable: 'non applicable', not_evaluated: 'non évalué' }[ev.outcome]}`, object: { kind: 'result', id: resultId }, projectId: r.projectId, provenance: 'simulation', related: [{ kind: 'evidence', id: evidenceId }, { kind: 'deliverable', id: subject.deliverableId, version: subject.version }] });
  const open = Object.values(d.db.finding).filter((f) => f.orgId === r.orgId && f.subject.kind === 'deliverable' && f.subject.id === subject.deliverableId && f.source === control.id && f.status !== 'resolved');
  if (ev.outcome === 'failed' && 'finding' in ev && ev.finding) {
    if (open.length) open.forEach((f) => { f.resultId = resultId; f.runId = r.id; f.observation = ev.observation; });
    else {
      const id = nextId(d, 'cst');
      insert(d, 'finding', { id, orgId: r.orgId, projectId: r.projectId, severity: ev.finding.severity, category: control.category, title: ev.finding.title, subject: { kind: 'deliverable', id: subject.deliverableId, version: subject.version }, ruleId: control.ruleIds[0], resultId, runId: r.id, observation: ev.observation, source: control.id, ownerId: undefined, status: 'open', remediation: ev.finding.remediation, createdAt: ctx.now });
      emit(d, ctx, { action: 'finding.created', summary: `Constat ouvert : ${ev.finding.title}`, object: { kind: 'finding', id }, projectId: r.projectId, provenance: 'simulation', related: [{ kind: 'result', id: resultId }] });
    }
  }
  if (ev.outcome === 'passed') open.filter((f) => f.status !== 'waived').forEach((f) => {
    f.status = 'resolved';
    emit(d, ctx, { action: 'finding.resolved', summary: `Constat résolu par la v${subject.version} : ${f.title}`, object: { kind: 'finding', id: f.id }, projectId: r.projectId, provenance: 'simulation', related: [{ kind: 'result', id: resultId }] });
  });
}

function scenarioOf(d: D, questId?: ID): 'export' | 'vuln' | 'generic' {
  const q = get(d as AppState, 'quest', questId);
  const council = get(d as AppState, 'council', get(d as AppState, 'decision', q?.decisionId)?.councilId);
  if (council?.scenario === 'vulnerabilite' || /csv|vuln/i.test(q?.title ?? '')) return 'vuln';
  return council?.scenario === 'export-donnees' || /export/i.test(q?.title ?? '') ? 'export' : 'generic';
}

function finalizeSkill(d: D, ctx: Ctx, r: Run) {
  const q = d.db.quest[r.questId!];
  const project = d.db.project[r.projectId];
  const type = r.inputs.params.type as DeliverableType;
  const retention = fact(bpVersion(d as AppState, r.orgId, project.blueprintVersion), 'export.retention');
  const gen = services.generator.generate(type, {
    projectName: project.name, productName: d.db.product[project.productId]?.name ?? '', questTitle: q.title, objective: q.objective,
    criteria: q.criteria.map((c) => c.text), retentionDays: retention && retention.provenance !== 'unknown' ? retention.value.replace(/\D+/g, '') || retention.value : undefined,
    variant: (r.inputs.params.variante as 'initial' | 'correctif') ?? 'initial', scenario: scenarioOf(d, q.id),
  });
  const describes: Ref[] = [{ kind: 'blueprint', id: blueprintOf(d as AppState, r.orgId)!.id, version: project.blueprintVersion }];
  const api = q.deliverableIds.map((id) => d.db.deliverable[id]).find((x) => x?.type === 'api');
  if (type === 'doc' && api) describes.push({ kind: 'deliverable', id: api.id, version: api.current });
  const author = r.actor.type === 'agent' ? r.actor.expertId : null;
  const existing = q.deliverableIds.map((id) => d.db.deliverable[id]).find((x) => x?.type === type && x.status !== 'archived');
  const actor = { ...ctx, actor: r.actor };
  if (existing) {
    const id = addVersion(d, actor, existing, gen.content, r.inputs.params.variante === 'correctif' ? 'Correctif généré' : 'Nouvelle génération', describes, author, true);
    r.outputDeliverableId = existing.id;
    r.log.push({ at: ctx.now, level: 'info', text: `Version ${id} ajoutée à « ${existing.title} ».` });
    return;
  }
  const id = nextId(d, 'dlv');
  const doc = DELIVERABLE_TYPES[type].doc as DocCategory | null;
  insert(d, 'deliverable', { id, orgId: r.orgId, projectId: r.projectId, questId: q.id, type, title: gen.title, status: 'draft', current: 1, ownerId: q.ownerId ?? project.ownerId ?? '', docCategory: doc ?? undefined, docPath: doc ? `${project.name}/${gen.title}` : undefined, audience: doc ? (type === 'landing' || type === 'presentation' ? 'Prospects' : 'Administrateurs clients') : undefined, createdAt: ctx.now,
    versions: [{ number: 1, content: gen.content, authorId: author, authorKind: author ? 'agent' : 'system', createdAt: ctx.now, note: 'Première génération', simulated: true, proposal: false, describes }] });
  q.deliverableIds.push(id);
  r.outputDeliverableId = id;
  r.log.push({ at: ctx.now, level: 'info', text: `Livrable « ${gen.title} » créé (v1, brouillon).` });
  emit(d, actor, { action: 'deliverable.generated', summary: `Livrable généré : « ${gen.title} » (simulation)`, object: { kind: 'deliverable', id, version: 1 }, projectId: r.projectId, provenance: 'simulation', related: [{ kind: 'quest', id: q.id }, { kind: 'run', id: r.id }] });
}

/**
 * Adds a version. On a draft deliverable it is adopted at once; on a deliverable under review,
 * approved or published it stays a proposal until someone adopts it (RG-34).
 */
function addVersion(d: D, ctx: Ctx, dl: Deliverable, content: Content, note: string, describes: Ref[], authorId: ID | null, simulated: boolean): number {
  const number = Math.max(...dl.versions.map((v) => v.number)) + 1;
  const adopt = dl.status === 'draft';
  dl.versions.push({ number, content, authorId, authorKind: authorId ? (d.users[authorId] ? 'human' : 'agent') : 'system', createdAt: ctx.now, note, simulated, proposal: !adopt, describes });
  if (adopt) dl.current = number;
  emit(d, ctx, { action: adopt ? 'deliverable.version' : 'deliverable.proposal', summary: adopt ? `« ${dl.title} » passe en v${number} (${note})` : `Proposition v${number} pour « ${dl.title} » : la v${dl.current} ${dl.status === 'published' ? 'publiée' : 'approuvée'} reste en vigueur`, object: { kind: 'deliverable', id: dl.id, version: number }, projectId: dl.projectId, provenance: simulated ? 'simulation' : 'local' });
  return number;
}

/* ---------------------------------------------------------------- deliverables */

export const createDeliverable = command<{ projectId: ID; questId?: ID; type: DeliverableType; title: string; docCategory?: DocCategory; docPath?: string; audience?: string; content?: Content }, ID>({
  name: 'createDeliverable',
  capability: 'edit',
  project: (p) => p.projectId,
  guard: (_s, _c, p) => (p.title.trim().length < 3 ? 'Titre trop court.' : null),
  run: (d, ctx, p) => {
    const project = must(d, 'project', p.projectId, ctx.orgId);
    const q = get(d as AppState, 'quest', p.questId);
    const content = p.content ?? services.generator.generate(p.type, { projectName: project.name, productName: d.db.product[project.productId]?.name ?? '', questTitle: q?.title ?? p.title, objective: q?.objective ?? p.title, criteria: q?.criteria.map((c) => c.text) ?? [], variant: 'initial', scenario: 'generic' }).content;
    const id = nextId(d, 'dlv');
    const doc = p.docCategory ?? (DELIVERABLE_TYPES[p.type].doc as DocCategory | null) ?? undefined;
    insert(d, 'deliverable', { id, orgId: ctx.orgId, projectId: p.projectId, questId: p.questId, type: p.type, title: p.title.trim(), status: 'draft', current: 1, ownerId: requireHuman(ctx), docCategory: doc, docPath: doc ? p.docPath ?? `${project.name}/${p.title.trim()}` : undefined, audience: p.audience, createdAt: ctx.now,
      versions: [{ number: 1, content, authorId: requireHuman(ctx), authorKind: 'human', createdAt: ctx.now, note: 'Création', simulated: false, proposal: false, describes: [{ kind: 'blueprint', id: blueprintOf(d as AppState, ctx.orgId)!.id, version: project.blueprintVersion }] }] });
    if (q) d.db.quest[q.id].deliverableIds.push(id);
    emit(d, ctx, { action: 'deliverable.created', summary: `Livrable « ${p.title.trim()} » créé`, object: { kind: 'deliverable', id, version: 1 }, projectId: p.projectId, related: q ? [{ kind: 'quest', id: q.id }] : [] });
    return id;
  },
});

export const editDeliverable = command<{ id: ID; content: Content; note: string }, number>({
  name: 'editDeliverable',
  capability: 'edit',
  project: (p, s) => s.db.deliverable[p.id]?.projectId,
  guard: (s, _c, p) => {
    const dl = s.db.deliverable[p.id];
    if (!dl) return 'Livrable introuvable.';
    if (dl.status === 'archived' || dl.status === 'replaced') return 'Livrable archivé ou remplacé : restaurez-le pour le modifier.';
    const cur = dl.versions.find((v) => v.number === dl.current);
    if (JSON.stringify(cur?.content) === JSON.stringify(p.content)) return 'Aucune modification à enregistrer.';
    return p.note.trim().length < 3 ? 'Décrivez la modification (note de version).' : null;
  },
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.id, ctx.orgId);
    const cur = dl.versions.find((v) => v.number === dl.current)!;
    return addVersion(d, ctx, dl, p.content, p.note.trim(), cur.describes, requireHuman(ctx), false);
  },
});

/** Explicit adoption of a proposal: becomes current and goes back to draft for a new review. */
export const adoptDeliverableVersion = command<{ id: ID; version: number }>({
  name: 'adoptDeliverableVersion',
  capability: 'edit',
  project: (p, s) => s.db.deliverable[p.id]?.projectId,
  humanOnly: true,
  guard: (s, _c, p) => {
    const dl = s.db.deliverable[p.id];
    const v = dl?.versions.find((x) => x.number === p.version);
    return !v ? 'Version introuvable.' : !v.proposal ? 'Cette version n’est pas une proposition en attente.' : null;
  },
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.id, ctx.orgId);
    const from = dl.current;
    dl.versions.find((x) => x.number === p.version)!.proposal = false;
    dl.current = p.version;
    dl.status = 'draft';
    emit(d, ctx, { action: 'deliverable.adopted', summary: `« ${dl.title} » adopte la v${p.version} (au lieu de v${from}) : nouvelle revue nécessaire, les preuves de la v${from} deviennent à réévaluer`, object: { kind: 'deliverable', id: dl.id, version: p.version }, projectId: dl.projectId });
  },
});

export const restoreDeliverableVersion = command<{ id: ID; version: number; reason: string }, number>({
  name: 'restoreDeliverableVersion',
  capability: 'edit',
  project: (p, s) => s.db.deliverable[p.id]?.projectId,
  guard: (s, _c, p) => (!s.db.deliverable[p.id]?.versions.some((v) => v.number === p.version) ? 'Version introuvable.' : s.db.deliverable[p.id].current === p.version ? 'C’est déjà la version en vigueur.' : p.reason.trim().length < 3 ? 'Indiquez le motif de la restauration.' : null),
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.id, ctx.orgId);
    if (dl.status === 'archived') dl.status = 'draft';
    const old = dl.versions.find((v) => v.number === p.version)!;
    return addVersion(d, ctx, dl, clone(old.content), `Restauration de la v${p.version} : ${p.reason}`, old.describes, requireHuman(ctx), false);
  },
});

export const regenerateDeliverable = command<{ id: ID }, number>({
  name: 'regenerateDeliverable',
  capability: 'propose',
  project: (p, s) => s.db.deliverable[p.id]?.projectId,
  guard: (s, _c, p) => (s.db.deliverable[p.id] ? (s.db.deliverable[p.id].versions.some((v) => v.proposal) ? 'Une proposition attend déjà d’être adoptée ou écartée.' : null) : 'Livrable introuvable.'),
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.id, ctx.orgId);
    const project = d.db.project[dl.projectId];
    const q = get(d as AppState, 'quest', dl.questId);
    const retention = fact(bpVersion(d as AppState, ctx.orgId, project.blueprintVersion), 'export.retention');
    const gen = services.generator.generate(dl.type, { projectName: project.name, productName: d.db.product[project.productId]?.name ?? '', questTitle: q?.title ?? dl.title, objective: q?.objective ?? dl.title, criteria: q?.criteria.map((c) => c.text) ?? [], retentionDays: retention && retention.provenance !== 'unknown' ? retention.value.replace(/\D+/g, '') : undefined, variant: 'correctif', scenario: scenarioOf(d, dl.questId) });
    const cur = dl.versions.find((v) => v.number === dl.current)!;
    const describes = cur.describes.map((ref) => ref.kind === 'blueprint' ? { ...ref, version: project.blueprintVersion } : ref.kind === 'deliverable' ? { ...ref, version: d.db.deliverable[ref.id]?.current ?? ref.version } : ref);
    const number = Math.max(...dl.versions.map((v) => v.number)) + 1;
    dl.versions.push({ number, content: gen.content, authorId: null, authorKind: 'system', createdAt: ctx.now, note: 'Régénération à partir des sources actuelles', simulated: true, proposal: true, describes });
    emit(d, ctx, { action: 'deliverable.regenerated', summary: `Régénération proposée pour « ${dl.title} » (v${number}), les versions précédentes et leurs validations sont conservées`, object: { kind: 'deliverable', id: dl.id, version: number }, projectId: dl.projectId, provenance: 'simulation' });
    return number;
  },
});

export const dismissProposal = command<{ id: ID; version: number }>({
  name: 'dismissProposal',
  capability: 'edit',
  project: (p, s) => s.db.deliverable[p.id]?.projectId,
  guard: (s, _c, p) => (s.db.deliverable[p.id]?.versions.find((v) => v.number === p.version)?.proposal ? null : 'Pas une proposition.'),
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.id, ctx.orgId);
    const v = dl.versions.find((x) => x.number === p.version)!;
    v.proposal = false;
    v.note = `${v.note} — écartée`;
    emit(d, ctx, { action: 'deliverable.proposal.dismissed', summary: `Proposition v${p.version} de « ${dl.title} » écartée (conservée dans l’historique)`, object: { kind: 'deliverable', id: dl.id, version: p.version }, projectId: dl.projectId });
  },
});

export const setDocMeta = command<{ id: ID; docCategory?: DocCategory; docPath?: string; audience?: string; ownerId?: ID }>({
  name: 'setDocMeta',
  capability: 'edit',
  project: (p, s) => s.db.deliverable[p.id]?.projectId,
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.id, ctx.orgId);
    Object.assign(dl, Object.fromEntries(Object.entries({ docCategory: p.docCategory, docPath: p.docPath, audience: p.audience, ownerId: p.ownerId }).filter(([, v]) => v !== undefined)));
    emit(d, ctx, { action: 'deliverable.meta', summary: `Classement documentaire de « ${dl.title} » modifié`, object: { kind: 'deliverable', id: dl.id }, projectId: dl.projectId });
  },
});
