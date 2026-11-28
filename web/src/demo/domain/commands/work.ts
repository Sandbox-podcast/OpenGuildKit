/**
 * Council, decisions and quests (RG-17 to RG-25).
 */
import { services } from '@/demo/adapters/services';
import { command, emit, fail, insert, list, must, nextId, requireHuman, type Ctx, clone } from '../engine';
import { questRevision, requiresDistinctApprover, wouldCycle } from '../selectors';
import { createApproval } from './transitions';
import type { AppState, Council, DeliverableType, ID, Quest, QuestPlan, QuestType, Ref } from '../types';
import type { Draft } from 'immer';

type D = Draft<AppState>;

/* ---------------------------------------------------------------- council */

export interface CouncilInput {
  projectId: ID; title: string; objective: string; scenario: string | null; context: string; constraints: string[];
  ruleIds: ID[]; participantIds: ID[]; documentIds: ID[]; ownerId: ID; origin?: Ref;
}

export const createCouncil = command<CouncilInput, ID>({
  name: 'createCouncil',
  capability: 'propose',
  project: (p) => p.projectId,
  guard: (s, ctx, p) => {
    if (p.title.trim().length < 4) return 'Donnez un titre à la session.';
    if (p.objective.trim().length < 10) return 'Décrivez l’objectif (10 caractères au moins).';
    if (!p.ownerId) return 'Désignez le responsable humain de la session.';
    const inactive = p.participantIds.filter((id) => !s.db.expert[id]?.active || s.db.expert[id].orgId !== ctx.orgId);
    return inactive.length ? 'Une expertise sélectionnée est inactive ou hors de l’organisation.' : null;
  },
  run: (d, ctx, p) => {
    const id = nextId(d, 'cns');
    const project = must(d, 'project', p.projectId, ctx.orgId);
    const scenario = p.scenario ? services.agents.scenarios[p.scenario] : undefined;
    const council: Council = {
      id, orgId: ctx.orgId, projectId: p.projectId, title: p.title.trim(), objective: p.objective.trim(), scenario: p.scenario,
      context: p.context, documentIds: p.documentIds, constraints: p.constraints, ruleIds: p.ruleIds, participantIds: [...new Set(p.participantIds)],
      ownerId: p.ownerId, status: 'prepared', blueprintVersion: project.blueprintVersion, requiredFacts: scenario?.requiredFacts ?? [],
      contributions: [], options: clone(scenario?.options ?? []), annotations: [], clarifications: [], origin: p.origin, createdAt: ctx.now,
    };
    insert(d, 'council', council);
    emit(d, ctx, { action: 'council.prepared', summary: `Session du Conseil préparée : « ${council.title} »${p.scenario ? '' : ' (hors scénario de simulation)'}`, object: { kind: 'council', id }, projectId: p.projectId, related: p.origin ? [p.origin] : [] });
    return id;
  },
});

export const updateCouncil = command<{ id: ID; patch: Partial<Pick<Council, 'title' | 'objective' | 'context' | 'constraints' | 'ruleIds' | 'participantIds' | 'documentIds' | 'ownerId'>> }>({
  name: 'updateCouncil',
  capability: 'propose',
  project: (p, s) => s.db.council[p.id]?.projectId,
  guard: (s, _c, p) => (s.db.council[p.id]?.status === 'prepared' ? null : 'Seule une session préparée peut être modifiée ; invitez une expertise ou annotez en cours de session.'),
  run: (d, ctx, p) => { Object.assign(must(d, 'council', p.id, ctx.orgId), p.patch); },
});

export const inviteExpert = command<{ councilId: ID; expertId: ID }>({
  name: 'inviteExpert',
  capability: 'propose',
  project: (p, s) => s.db.council[p.councilId]?.projectId,
  guard: (s, _c, p) => {
    const c = s.db.council[p.councilId];
    if (!c || !['prepared', 'running', 'suspended'].includes(c.status)) return 'La session n’accepte plus de participants.';
    if (c.participantIds.includes(p.expertId)) return 'Cette expertise participe déjà.';
    return s.db.expert[p.expertId]?.active ? null : 'Expertise inactive.';
  },
  run: (d, ctx, p) => {
    const c = must(d, 'council', p.councilId, ctx.orgId);
    c.participantIds.push(p.expertId);
    emit(d, ctx, { action: 'council.invite', summary: `${d.db.expert[p.expertId].name} invité·e au Conseil « ${c.title} »`, object: { kind: 'council', id: c.id }, projectId: c.projectId, related: [{ kind: 'expert', id: p.expertId }] });
  },
});

/** Produces the next pending contribution (one per tick) so opinions appear one after another. */
export function produceContribution(d: D, ctx: Ctx, councilId: ID): boolean {
  const c = d.db.council[councilId];
  if (!c || c.status !== 'running') return false;
  const expertId = c.participantIds.find((e) => !c.contributions.some((x) => x.expertId === e));
  if (!expertId) return false;
  const e = d.db.expert[expertId];
  const cost = 10;
  if (e.budget.used + cost > e.budget.units) {
    c.contributions.push({ id: nextId(d, 'ctb'), expertId, at: ctx.now, round: 1, facts: [], hypotheses: [], questions: [], risks: [], recommendation: `Budget de l’agent atteint (${e.budget.used}/${e.budget.units} unités) : aucune contribution produite.`, reservation: 'Interruption par limite de budget.', sourceRefIds: [], stances: {}, limited: true, simulated: true });
    emit(d, { ...ctx, actor: { type: 'agent', expertId } }, { action: 'council.budget', summary: `${e.name} : budget atteint, contribution non produite`, object: { kind: 'council', id: c.id }, projectId: c.projectId, provenance: 'simulation' });
    return true;
  }
  e.budget.used += cost;
  const t = services.agents.contribution(c.scenario, e.key, e.name);
  c.contributions.push({ id: nextId(d, 'ctb'), expertId, at: ctx.now, round: 1, facts: t.facts, hypotheses: t.hypotheses, questions: t.questions, risks: t.risks, recommendation: t.recommendation, reservation: t.reservation, deliverable: t.deliverable, sourceRefIds: t.sources, stances: t.stances, limited: t.limited, simulated: true });
  emit(d, { ...ctx, actor: { type: 'agent', expertId } }, { action: 'council.contribution', summary: `Avis de ${e.name} versé au Conseil « ${c.title} »${t.limited ? ' (contribution limitée)' : ''}`, object: { kind: 'council', id: c.id }, projectId: c.projectId, provenance: 'simulation' });
  return true;
}

export const requestClarification = command<{ councilId: ID; expertId: ID; question: string }>({
  name: 'requestClarification',
  capability: 'propose',
  project: (p, s) => s.db.council[p.councilId]?.projectId,
  guard: (s, _c, p) => {
    const c = s.db.council[p.councilId];
    if (!c || !['running', 'awaiting'].includes(c.status)) return 'Clarifications possibles pendant la session ou l’arbitrage.';
    if (!c.participantIds.includes(p.expertId)) return 'Cette expertise ne participe pas.';
    return p.question.trim().length < 5 ? 'Formulez la question.' : null;
  },
  run: (d, ctx, p) => {
    const c = must(d, 'council', p.councilId, ctx.orgId);
    const e = d.db.expert[p.expertId];
    c.clarifications.push({ id: nextId(d, 'clr'), expertId: p.expertId, question: p.question.trim(), answer: services.agents.clarification(c.scenario, e.key, p.question), at: ctx.now });
    emit(d, ctx, { action: 'council.clarification', summary: `Clarification demandée à ${e.name}`, object: { kind: 'council', id: c.id }, projectId: c.projectId, provenance: 'simulation' });
  },
});

export const annotateCouncil = command<{ councilId: ID; text: string; contributionIds: ID[]; optionId?: ID }>({
  name: 'annotateCouncil',
  capability: 'propose',
  project: (p, s) => s.db.council[p.councilId]?.projectId,
  guard: (_s, _c, p) => (p.text.trim().length < 3 ? 'Écrivez l’annotation.' : null),
  run: (d, ctx, p) => {
    const c = must(d, 'council', p.councilId, ctx.orgId);
    c.annotations.push({ id: nextId(d, 'ann'), text: p.text.trim(), authorId: requireHuman(ctx), contributionIds: p.contributionIds, optionId: p.optionId, at: ctx.now });
    emit(d, ctx, { action: 'council.annotation', summary: `Désaccord annoté dans « ${c.title} »`, object: { kind: 'council', id: c.id }, projectId: c.projectId });
  },
});

/* ---------------------------------------------------------------- decisions */

export const proposeDecision = command<{ councilId: ID; optionId: ID; justification: string; ownerId: ID }, ID>({
  name: 'proposeDecision',
  capability: 'propose',
  project: (p, s) => s.db.council[p.councilId]?.projectId,
  humanOnly: true,
  guard: (s, ctx, p) => {
    const c = s.db.council[p.councilId];
    if (!c || c.status !== 'awaiting') return 'La session doit être en attente d’arbitrage.';
    if (!c.options.some((o) => o.id === p.optionId)) return 'Option inconnue.';
    if (list(s, 'decision', ctx.orgId).some((x) => x.councilId === c.id && ['draft', 'review', 'approved'].includes(x.status))) return 'Une décision est déjà en cours ou approuvée pour cette session : révisez-la plutôt.';
    if (p.justification.trim().length < 10) return 'Motivez l’option choisie.';
    return p.ownerId ? null : 'Désignez le responsable de la décision.';
  },
  run: (d, ctx, p) => {
    const c = must(d, 'council', p.councilId, ctx.orgId);
    const option = c.options.find((o) => o.id === p.optionId)!;
    const id = nextId(d, 'dec');
    const project = must(d, 'project', c.projectId);
    const plan = c.scenario ? services.agents.scenarios[c.scenario]?.quests[p.optionId] ?? [] : [];
    insert(d, 'decision', {
      id, orgId: ctx.orgId, projectId: c.projectId, councilId: c.id, title: c.title, number: 1, status: 'draft', optionId: option.id, optionTitle: option.title,
      justification: p.justification.trim(), ownerId: p.ownerId, authorId: requireHuman(ctx), considered: { blueprintVersion: project.blueprintVersion, rules: [] },
      questIds: [], questPlan: plan.length ? clone(plan) : [defaultPlan(c.title, c.objective)], createdAt: ctx.now,
    });
    emit(d, ctx, { action: 'decision.proposed', summary: `Décision proposée : « ${option.title} » pour « ${c.title} »`, object: { kind: 'decision', id, version: 1 }, projectId: c.projectId, justification: p.justification, related: [{ kind: 'council', id: c.id }] });
    return id;
  },
});

const defaultPlan = (title: string, objective: string): QuestPlan => ({ title, objective, type: 'fonctionnalité', criteria: ['Objectif atteint et vérifié'], deliverables: ['spec'], controlIds: [], tasks: ['Préciser le besoin'] });

/** Revising an approved decision creates a new version; the old one is replaced only after approval (RG-19). */
export const reviseDecision = command<{ decisionId: ID; justification: string; optionId?: ID }, ID>({
  name: 'reviseDecision',
  capability: 'propose',
  project: (p, s) => s.db.decision[p.decisionId]?.projectId,
  humanOnly: true,
  guard: (s, ctx, p) => {
    const dec = s.db.decision[p.decisionId];
    if (!dec || dec.status !== 'approved') return 'Seule une décision approuvée peut être révisée.';
    if (list(s, 'decision', ctx.orgId).some((x) => x.revisionOf === dec.id && ['draft', 'review'].includes(x.status))) return 'Une révision est déjà en cours.';
    return p.justification.trim().length < 10 ? 'Motivez la révision.' : null;
  },
  run: (d, ctx, p) => {
    const old = must(d, 'decision', p.decisionId, ctx.orgId);
    const council = d.db.council[old.councilId ?? ''];
    const option = council?.options.find((o) => o.id === (p.optionId ?? old.optionId));
    const id = nextId(d, 'dec');
    insert(d, 'decision', { ...clone(old), id, number: old.number + 1, revisionOf: old.id, replacedBy: undefined, status: 'draft', statusReason: undefined, optionId: option?.id ?? old.optionId, optionTitle: option?.title ?? old.optionTitle, justification: p.justification.trim(), authorId: requireHuman(ctx), questIds: [], createdAt: ctx.now, decidedAt: undefined });
    emit(d, ctx, { action: 'decision.revision', summary: `Révision v${old.number + 1} proposée pour « ${old.title} » (la v${old.number} reste en vigueur jusqu’à approbation)`, object: { kind: 'decision', id, version: old.number + 1 }, projectId: old.projectId, related: [{ kind: 'decision', id: old.id }] });
    return id;
  },
});

export const editDecision = command<{ id: ID; justification?: string; ownerId?: ID; optionId?: ID }>({
  name: 'editDecision',
  capability: 'propose',
  project: (p, s) => s.db.decision[p.id]?.projectId,
  guard: (s, _c, p) => (s.db.decision[p.id]?.status === 'draft' ? null : 'Seul un brouillon de décision est modifiable : demandez une révision.'),
  run: (d, ctx, p) => {
    const dec = must(d, 'decision', p.id, ctx.orgId);
    if (p.justification !== undefined) dec.justification = p.justification;
    if (p.ownerId) dec.ownerId = p.ownerId;
    if (p.optionId) {
      const c = d.db.council[dec.councilId ?? ''];
      const o = c?.options.find((x) => x.id === p.optionId) ?? fail('Option inconnue.');
      dec.optionId = o.id;
      dec.optionTitle = o.title;
      const plan = c.scenario ? services.agents.scenarios[c.scenario]?.quests[o.id] : undefined;
      if (plan?.length) dec.questPlan = clone(plan);
    }
  },
});

/** Idempotent conversion of an approved decision into quests (RG-20). */
export const convertDecision = command<{ decisionId: ID; confirmExtra?: boolean }, ID[]>({
  name: 'convertDecision',
  capability: 'edit',
  project: (p, s) => s.db.decision[p.decisionId]?.projectId,
  guard: (s, _c, p) => {
    const dec = s.db.decision[p.decisionId];
    if (!dec) return 'Décision introuvable.';
    if (dec.status !== 'approved') return 'Seule une décision approuvée peut devenir une quête.';
    if (dec.questIds.length && !p.confirmExtra) return `Déjà convertie en ${dec.questIds.length} quête(s). Confirmez explicitement pour créer une quête supplémentaire.`;
    return null;
  },
  run: (d, ctx, p) => {
    const dec = must(d, 'decision', p.decisionId, ctx.orgId);
    const base = dec.questPlan[0] ?? defaultPlan(dec.title, dec.justification);
    const plans = p.confirmExtra && dec.questIds.length ? [{ ...base, title: `${base.title} (complément)` }] : dec.questPlan.length ? dec.questPlan : [base];
    const ids = plans.map((plan) => createQuestFromPlan(d, ctx, dec.projectId, plan, { decisionId: dec.id, origin: 'decision', originRef: { kind: 'decision', id: dec.id, version: dec.number }, ownerId: dec.ownerId }));
    dec.questIds.push(...ids);
    emit(d, ctx, { action: 'decision.converted', summary: `Décision « ${dec.title} » convertie en ${ids.length} quête(s)`, object: { kind: 'decision', id: dec.id, version: dec.number }, projectId: dec.projectId, related: ids.map((id) => ({ kind: 'quest' as const, id })) });
    return ids;
  },
});

function createQuestFromPlan(d: D, ctx: Ctx, projectId: ID, plan: QuestPlan, extra: Partial<Quest>): ID {
  const id = nextId(d, 'qst');
  const order = list(d as AppState, 'quest', ctx.orgId).length;
  insert(d, 'quest', {
    id, orgId: ctx.orgId, projectId, title: plan.title, objective: plan.objective, type: plan.type, origin: 'direct', priority: 'P2', status: 'todo',
    criteria: plan.criteria.map((text) => ({ id: nextId(d, 'crt'), text, required: true, met: false })), expectedDeliverables: plan.deliverables, deliverableIds: [],
    controlIds: plan.controlIds.map((c) => controlIdFor(d, ctx, c)).filter(Boolean) as ID[], needsHumanApproval: requiresDistinctApprover(d as AppState, projectId),
    comments: [], order, createdAt: ctx.now, revision: 0, ...extra,
  });
  plan.tasks.forEach((title, i) => insert(d, 'task', { id: nextId(d, 'tsk'), orgId: ctx.orgId, questId: id, title, status: 'todo', dependsOn: [], order: i }));
  emit(d, ctx, { action: 'quest.created', summary: `Quête « ${plan.title} » créée${extra.decisionId ? ' depuis une décision' : ''}`, object: { kind: 'quest', id }, projectId, related: extra.originRef ? [extra.originRef] : [] });
  return id;
}

/** Plans name controls by their code key (ctl-isolation…); each organisation has its own control ids. */
function controlIdFor(d: D, ctx: Ctx, key: string): ID | undefined {
  return Object.values(d.db.control).find((c) => c.orgId === ctx.orgId && (c.id === key || c.id === `${key}-${ctx.orgId}`))?.id;
}

/* ---------------------------------------------------------------- quests */

export interface QuestInput {
  projectId: ID; title: string; objective: string; type: QuestType; ownerId?: ID; priority: Quest['priority']; due?: string;
  criteria: string[]; expectedDeliverables: DeliverableType[]; controlIds: ID[]; needsHumanApproval?: boolean; originRef?: Ref; origin?: Quest['origin'];
}

export const createQuest = command<QuestInput, ID>({
  name: 'createQuest',
  capability: 'edit',
  project: (p) => p.projectId,
  guard: (_s, _c, p) => (p.title.trim().length < 4 ? 'Titre trop court (4 caractères au moins).' : p.objective.trim().length < 10 ? 'Décrivez l’objectif métier.' : null),
  run: (d, ctx, p) => {
    const id = nextId(d, 'qst');
    insert(d, 'quest', {
      id, orgId: ctx.orgId, projectId: p.projectId, title: p.title.trim(), objective: p.objective.trim(), type: p.type, origin: p.origin ?? 'direct', originRef: p.originRef,
      ownerId: p.ownerId, priority: p.priority, due: p.due, status: 'todo', criteria: p.criteria.filter((c) => c.trim()).map((text) => ({ id: nextId(d, 'crt'), text: text.trim(), required: true, met: false })),
      expectedDeliverables: p.expectedDeliverables, deliverableIds: [], controlIds: p.controlIds, needsHumanApproval: p.needsHumanApproval ?? requiresDistinctApprover(d as AppState, p.projectId),
      comments: [], order: list(d as AppState, 'quest', ctx.orgId).length, createdAt: ctx.now, revision: 0,
    });
    emit(d, ctx, { action: 'quest.created', summary: `Quête « ${p.title.trim()} » créée (${p.origin === 'finding' ? 'depuis un constat' : p.origin === 'signal' ? 'depuis un signal' : 'création directe'})`, object: { kind: 'quest', id }, projectId: p.projectId, related: p.originRef ? [p.originRef] : [] });
    return id;
  },
});

export const updateQuest = command<{ id: ID; patch: Partial<Pick<Quest, 'title' | 'objective' | 'type' | 'ownerId' | 'priority' | 'due' | 'expectedDeliverables' | 'controlIds' | 'needsHumanApproval' | 'order'>> }>({
  name: 'updateQuest',
  capability: 'edit',
  project: (p, s) => s.db.quest[p.id]?.projectId,
  guard: (s, _c, p) => {
    const q = s.db.quest[p.id];
    if (!q) return 'Quête introuvable.';
    if (q.status === 'done' || q.status === 'cancelled') return 'Quête close : rouvrez-la pour la modifier.';
    if (p.patch.needsHumanApproval === false && requiresDistinctApprover(s, q.projectId)) return 'Le profil du projet exige une validation humaine distincte : elle ne peut pas être retirée.';
    return p.patch.title !== undefined && p.patch.title.trim().length < 4 ? 'Titre trop court.' : null;
  },
  run: (d, ctx, p) => {
    const q = must(d, 'quest', p.id, ctx.orgId);
    Object.assign(q, p.patch);
    const fields = Object.keys(p.patch).join(', ');
    if (fields !== 'order') emit(d, ctx, { action: 'quest.updated', summary: `Quête « ${q.title} » modifiée (${fields})`, object: { kind: 'quest', id: q.id }, projectId: q.projectId });
  },
});

export const setCriterion = command<{ questId: ID; criterionId?: ID; text?: string; met?: boolean; remove?: boolean }>({
  name: 'setCriterion',
  capability: 'edit',
  project: (p, s) => s.db.quest[p.questId]?.projectId,
  guard: (s, _c, p) => (['done', 'cancelled'].includes(s.db.quest[p.questId]?.status ?? '') ? 'Quête close.' : p.text !== undefined && !p.criterionId && p.text.trim().length < 5 ? 'Critère trop court.' : null),
  run: (d, ctx, p) => {
    const q = must(d, 'quest', p.questId, ctx.orgId);
    if (!p.criterionId) { q.criteria.push({ id: nextId(d, 'crt'), text: p.text!.trim(), required: true, met: false }); return; }
    const c = q.criteria.find((x) => x.id === p.criterionId) ?? fail('Critère introuvable.');
    if (p.remove) q.criteria = q.criteria.filter((x) => x.id !== c.id);
    if (p.met !== undefined) {
      c.met = p.met;
      emit(d, ctx, { action: 'quest.criterion', summary: `Critère ${p.met ? 'satisfait' : 'rouvert'} : ${c.text}`, object: { kind: 'quest', id: q.id }, projectId: q.projectId });
    }
  },
});

export const addTasks = command<{ questId: ID; titles: string[]; assigneeId?: ID }, ID[]>({
  name: 'addTasks',
  capability: 'edit',
  project: (p, s) => s.db.quest[p.questId]?.projectId,
  guard: (s, _c, p) => (['done', 'cancelled'].includes(s.db.quest[p.questId]?.status ?? '') ? 'Quête close : rouvrez-la.' : p.titles.filter((t) => t.trim()).length === 0 ? 'Saisissez au moins une tâche.' : null),
  run: (d, ctx, p) => {
    const q = must(d, 'quest', p.questId, ctx.orgId);
    const start = list(d as AppState, 'task', ctx.orgId).filter((t) => t.questId === q.id).length;
    const ids = p.titles.filter((t) => t.trim()).map((title, i) => insert(d, 'task', { id: nextId(d, 'tsk'), orgId: ctx.orgId, questId: q.id, title: title.trim(), status: 'todo', assigneeId: p.assigneeId, dependsOn: [], order: start + i }).id);
    emit(d, ctx, { action: 'quest.decomposed', summary: `${ids.length} tâche(s) ajoutée(s) à « ${q.title} »`, object: { kind: 'quest', id: q.id }, projectId: q.projectId });
    return ids;
  },
});

export const updateTask = command<{ id: ID; title?: string; assigneeId?: ID | null; order?: number }>({
  name: 'updateTask',
  capability: 'edit',
  project: (p, s) => s.db.quest[s.db.task[p.id]?.questId ?? '']?.projectId,
  run: (d, ctx, p) => {
    const t = must(d, 'task', p.id, ctx.orgId);
    if (p.title !== undefined) t.title = p.title.trim() || t.title;
    if (p.assigneeId !== undefined) t.assigneeId = p.assigneeId ?? undefined;
    if (p.order !== undefined) t.order = p.order;
  },
});

/** Blocking dependencies between tasks form an acyclic graph (RG-23). */
export const setDependency = command<{ taskId: ID; dependsOn: ID; add: boolean }>({
  name: 'setDependency',
  capability: 'edit',
  project: (p, s) => s.db.quest[s.db.task[p.taskId]?.questId ?? '']?.projectId,
  guard: (s, _c, p) => {
    if (!p.add) return null;
    if (p.taskId === p.dependsOn) return 'Une tâche ne peut pas dépendre d’elle-même.';
    if (!s.db.task[p.dependsOn]) return 'Tâche introuvable.';
    if (s.db.task[p.taskId]?.dependsOn.includes(p.dependsOn)) return 'Dépendance déjà présente.';
    return wouldCycle(s, p.taskId, p.dependsOn) ? `Refusé : « ${s.db.task[p.dependsOn].title} » dépend déjà, directement ou non, de « ${s.db.task[p.taskId].title} ». Cette dépendance créerait un cycle.` : null;
  },
  run: (d, ctx, p) => {
    const t = must(d, 'task', p.taskId, ctx.orgId);
    t.dependsOn = p.add ? [...t.dependsOn, p.dependsOn] : t.dependsOn.filter((x) => x !== p.dependsOn);
    emit(d, ctx, { action: 'task.dependency', summary: `« ${t.title} » ${p.add ? 'dépend désormais de' : 'ne dépend plus de'} « ${d.db.task[p.dependsOn]?.title} »`, object: { kind: 'task', id: t.id }, projectId: d.db.quest[t.questId]?.projectId });
  },
});

export const addComment = command<{ questId: ID; text: string }>({
  name: 'addComment',
  capability: 'propose',
  project: (p, s) => s.db.quest[p.questId]?.projectId,
  guard: (_s, _c, p) => (p.text.trim().length < 2 ? 'Commentaire vide.' : null),
  run: (d, ctx, p) => {
    const q = must(d, 'quest', p.questId, ctx.orgId);
    const authorId = ctx.actor.type === 'human' ? ctx.actor.userId : `agent:${ctx.actor.type === 'agent' ? ctx.actor.expertId : 'system'}`;
    q.comments.push({ id: nextId(d, 'cmt'), authorId, text: p.text.trim(), at: ctx.now });
    emit(d, ctx, { action: 'quest.comment', summary: `Commentaire sur « ${q.title} »`, object: { kind: 'quest', id: q.id }, projectId: q.projectId });
  },
});

export const linkToQuest = command<{ questId: ID; kind: 'deliverable' | 'control'; id: ID; link: boolean }>({
  name: 'linkToQuest',
  capability: 'edit',
  project: (p, s) => s.db.quest[p.questId]?.projectId,
  guard: (s, _c, p) => {
    const q = s.db.quest[p.questId];
    if (!q) return 'Quête introuvable.';
    if (q.status === 'done' || q.status === 'cancelled') return 'Quête close : rouvrez-la.';
    if (p.kind === 'deliverable' && s.db.deliverable[p.id]?.projectId !== q.projectId) return 'Le livrable appartient à un autre projet.';
    return null;
  },
  run: (d, ctx, p) => {
    const q = must(d, 'quest', p.questId, ctx.orgId);
    const key = p.kind === 'deliverable' ? 'deliverableIds' : 'controlIds';
    q[key] = p.link ? [...new Set([...q[key], p.id])] : q[key].filter((x) => x !== p.id);
    if (p.kind === 'deliverable' && p.link) d.db.deliverable[p.id].questId = q.id;
    emit(d, ctx, { action: `quest.${p.kind}.${p.link ? 'linked' : 'unlinked'}`, summary: `${p.kind === 'deliverable' ? 'Livrable' : 'Contrôle'} ${p.link ? 'rattaché à' : 'détaché de'} « ${q.title} »`, object: { kind: 'quest', id: q.id }, projectId: q.projectId, related: [{ kind: p.kind, id: p.id }] });
  },
});

export const requestApproval = command<{ subject: Ref; purpose: 'clôture' | 'livrable' | 'revue'; approverId?: ID }, ID>({
  name: 'requestApproval',
  capability: 'propose',
  project: (p, s) => (s.db[p.subject.kind as 'quest']?.[p.subject.id] as { projectId?: ID } | undefined)?.projectId,
  humanOnly: true,
  guard: (s, ctx, p) => {
    if (p.approverId && ctx.actor.type === 'human' && p.approverId === ctx.actor.userId && requiresDistinctApprover(s, (s.db[p.subject.kind as 'quest']?.[p.subject.id] as { projectId?: ID } | undefined)?.projectId)) return 'Choisissez un approbateur distinct de vous : le profil exige deux identités.';
    if (p.subject.kind === 'quest' && s.db.quest[p.subject.id]?.status !== 'review') return 'Mettez d’abord la quête en revue.';
    return null;
  },
  run: (d, ctx, p) => {
    const projectId = (d.db[p.subject.kind as 'quest']?.[p.subject.id] as { projectId?: ID } | undefined)?.projectId;
    const version = p.subject.kind === 'quest' ? questRevision(d as AppState, p.subject.id) : p.subject.kind === 'deliverable' ? d.db.deliverable[p.subject.id].current : p.subject.version ?? 1;
    return createApproval(d, ctx, { subject: { ...p.subject, version }, purpose: p.purpose, projectId, approverId: p.approverId }).id;
  },
});
