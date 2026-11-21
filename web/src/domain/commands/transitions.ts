/**
 * Generic lifecycle transition. Allowed moves come from MACHINES; each (kind, action) may add
 * a guard (preconditions with an actionable reason) and an effect. Board drag-and-drop,
 * buttons, keyboard moves and the command palette all go through this single command.
 */
import type { Draft } from 'immer';
import { authorize } from '../permissions';
import { emit, fail, get, list, must, nextId, requireHuman, type Ctx } from '../engine';
import { findTransition, stateDef, type MachineKind } from '../machines';
import {
  approvalValidity, bpVersion, closureBlocked, closureReport, effectiveApprovalStatus, effectiveExceptionStatus, projectRules,
  requiresDistinctApprover, resolveRules, ruleIsDerogable, subjectVersion, unknownFacts,
} from '../selectors';
import type { AppState, Approval, ID, Ref } from '../types';
import { command } from '../engine';

export type TransitionKind = 'blueprint' | 'council' | 'decision' | 'quest' | 'task' | 'deliverable' | 'run' | 'approval' | 'exception' | 'share';
export interface TransitionPayload { kind: TransitionKind; id: ID; action: string; reason?: string; version?: number; approverId?: ID }

type S = AppState;
type D = Draft<AppState>;

/* ---------------------------------------------------------------- shared approval logic */

/** Why the current actor may not decide this approval (RG-14, RG-15, RG-16). */
export function approvalGuard(s: S, ctx: Ctx, a: Approval): string | null {
  if (ctx.actor.type !== 'human') return 'Une approbation revient à un humain identifié ; un agent ne peut pas approuver.';
  const userId = ctx.actor.userId;
  const cap = a.purpose === 'exception' ? 'approve_exception' : 'approve';
  const auth = authorize(s, ctx.actor, cap, { orgId: ctx.orgId, projectId: a.projectId });
  if (!auth.ok) return auth.reason!;
  const st = effectiveApprovalStatus(s, a);
  if (st !== 'expected') return `Cette demande est ${stateDef('approval', st).label.toLowerCase()}.`;
  if (a.approverId && a.approverId !== userId) return `Cette approbation est assignée à ${s.users[a.approverId]?.name ?? 'une autre personne'}.`;
  if (a.requireDistinct && a.authorId === userId) {
    return 'Séparation auteur-approbateur : vous avez demandé cette validation, une autre personne doit la donner. Changer de rôle ne lève pas cette règle.';
  }
  const current = subjectVersion(s, a.subject);
  if (current !== undefined && current !== a.subject.version) return `La demande porte sur la version ${a.subject.version} ; la version actuelle est ${current}. Une nouvelle demande est nécessaire.`;
  return null;
}

export function createApproval(d: D, ctx: Ctx, p: { subject: Ref & { version: number }; purpose: Approval['purpose']; projectId?: ID; approverId?: ID; requireDistinct?: boolean }): Approval {
  // Pending requests for an older version of the same subject are superseded.
  Object.values(d.db.approval).forEach((a) => {
    if (a.subject.kind === p.subject.kind && a.subject.id === p.subject.id && a.purpose === p.purpose && a.status === 'expected') a.status = 'revoked', a.reason = 'Remplacée par une nouvelle demande.';
  });
  const id = nextId(d, 'apr');
  const a: Approval = {
    id, orgId: ctx.orgId, projectId: p.projectId, subject: p.subject, purpose: p.purpose, authorId: requireHuman(ctx),
    approverId: p.approverId, requireDistinct: p.requireDistinct ?? requiresDistinctApprover(d as S, p.projectId), status: 'expected', createdAt: ctx.now,
  };
  d.db.approval[id] = a;
  emit(d, ctx, { action: 'approval.requested', summary: `Validation demandée (${p.purpose})${p.approverId ? ` à ${d.users[p.approverId]?.name}` : ''}`, object: { kind: 'approval', id }, projectId: p.projectId, related: [p.subject] });
  return a;
}

const pendingApproval = (s: S, subject: Ref, purpose: Approval['purpose']) =>
  list(s, 'approval', s.session.orgId).find((a) => a.subject.kind === subject.kind && a.subject.id === subject.id && a.purpose === purpose && effectiveApprovalStatus(s, a) === 'expected');

function decideApproval(d: D, ctx: Ctx, a: Approval, status: 'approved' | 'refused' | 'revoked', reason?: string) {
  const ap = d.db.approval[a.id];
  ap.status = status;
  ap.decidedBy = ctx.actor.type === 'human' ? ctx.actor.userId : undefined;
  ap.decidedAt = ctx.now;
  if (reason) ap.reason = reason;
}

/* ---------------------------------------------------------------- guards */

type GuardFn = (s: S, ctx: Ctx, p: TransitionPayload) => string | null;
type EffectFn = (d: D, ctx: Ctx, p: TransitionPayload, from: string) => void;

function questPrecondition(s: S, id: ID): string | null {
  const q = must(s, 'quest', id);
  const missing = [
    !q.ownerId && 'un responsable',
    !q.objective.trim() && 'un objectif',
    q.criteria.length === 0 && "au moins un critère d’acceptation",
    q.expectedDeliverables.length === 0 && 'au moins un livrable attendu',
  ].filter(Boolean);
  return missing.length ? `Avant de préparer la quête, renseignez ${missing.join(', ')}.` : null;
}

function openDependencies(s: S, taskId: ID) {
  const t = must(s, 'task', taskId);
  return t.dependsOn.map((id) => get(s, 'task', id)).filter((x) => x && x.status !== 'done' && x.status !== 'cancelled');
}

const GUARDS: Record<string, GuardFn> = {
  'blueprint.submit': (s, _c, p) => (bpVersion(s, s.session.orgId, p.version)?.status === 'draft' ? null : 'Seul un brouillon peut être soumis.'),
  'blueprint.publish': (s, ctx, p) => {
    const v = bpVersion(s, s.session.orgId, p.version);
    if (!v) return 'Version introuvable.';
    if (v.number > 1 && ctx.actor.type === 'human' && v.authorId === ctx.actor.userId) return 'Vous avez rédigé cette version : une autre personne doit la relire et la publier.';
    const { conflicts } = resolveRules(s, v);
    if (conflicts.length) return `Conflits à arbitrer avant publication : ${conflicts[0].message}`;
    return null;
  },
  'blueprint.archive': (s, _c, p) => {
    const users = list(s, 'project', s.session.orgId).filter((x) => x.status === 'active' && x.blueprintVersion === p.version);
    return users.length ? `Le projet « ${users[0].name} » suit encore cette version.` : null;
  },
  'council.launch': (s, _c, p) => {
    const c = must(s, 'council', p.id);
    if (!c.objective.trim()) return 'Renseignez un objectif.';
    if (!c.participantIds.length) return 'Ajoutez au moins une expertise.';
    return null;
  },
  'council.arbitrate': (s, _c, p) => {
    const c = must(s, 'council', p.id);
    const missing = c.participantIds.filter((e) => !c.contributions.some((x) => x.expertId === e));
    return missing.length ? `Contributions en cours : ${missing.length} expertise(s) n'ont pas encore répondu.` : null;
  },
  'decision.submit': (s, _c, p) => {
    const dec = must(s, 'decision', p.id);
    if (!dec.optionId && !dec.optionTitle) return 'Choisissez une option.';
    if (dec.justification.trim().length < 10) return 'Motivez la décision (10 caractères au moins).';
    return null;
  },
  'decision.approve': (s, ctx, p) => {
    const dec = must(s, 'decision', p.id);
    const a = pendingApproval(s, { kind: 'decision', id: dec.id }, 'décision');
    if (!a) return 'Aucune demande d’approbation en attente pour cette décision.';
    const g = approvalGuard(s, ctx, a);
    if (g) return g;
    const project = must(s, 'project', dec.projectId);
    if (dec.considered.blueprintVersion !== project.blueprintVersion) {
      return `La décision a été préparée sur le Blueprint v${dec.considered.blueprintVersion} ; le projet suit désormais la v${project.blueprintVersion}. Demandez une révision.`;
    }
    const council = get(s, 'council', dec.councilId);
    const unknown = unknownFacts(bpVersion(s, dec.orgId, dec.considered.blueprintVersion)).filter((f) => council?.requiredFacts.includes(f.key));
    if (unknown.length) return `Information inconnue requise : « ${unknown[0].label} ». Résolvez-la dans une nouvelle version du Blueprint avant d’approuver.`;
    return null;
  },
  'decision.refuse': (s, ctx, p) => { const a = pendingApproval(s, { kind: 'decision', id: p.id }, 'décision'); return a ? approvalGuard(s, ctx, a) : 'Aucune demande en attente.'; },
  'decision.requestRevision': (s, ctx, p) => { const a = pendingApproval(s, { kind: 'decision', id: p.id }, 'décision'); return a ? approvalGuard(s, ctx, a) : 'Aucune demande en attente.'; },
  'quest.prepare': (s, _c, p) => questPrecondition(s, p.id),
  'quest.start': (s, _c, p) => questPrecondition(s, p.id),
  'quest.unblock': (s, _c, p) => {
    const tasks = list(s, 'task', s.session.orgId).filter((t) => t.questId === p.id && t.status === 'blocked');
    return tasks.length ? `Débloquez d’abord la tâche « ${tasks[0].title} ».` : null;
  },
  'quest.submitReview': (s, _c, p) => {
    const blocked = list(s, 'task', s.session.orgId).filter((t) => t.questId === p.id && t.status === 'blocked');
    return blocked.length ? `La tâche « ${blocked[0].title} » est bloquée.` : null;
  },
  'quest.close': (s, _c, p) => {
    const missing = closureBlocked(closureReport(s, p.id));
    if (!missing.length) return null;
    const first = missing[0];
    return `Clôture impossible : ${first.label} — ${first.detail}${first.fix ? ` Action utile : ${first.fix.label}.` : ''}${missing.length > 1 ? ` (+${missing.length - 1} autre(s) condition(s))` : ''}`;
  },
  'task.start': (s, _c, p) => { const open = openDependencies(s, p.id); return open.length ? `Dépend de « ${open[0]!.title} », non terminée.` : null; },
  'task.finish': (s, _c, p) => { const open = openDependencies(s, p.id); return open.length ? `Dépend de « ${open[0]!.title} », non terminée.` : null; },
  'deliverable.submit': (s, _c, p) => {
    const dl = must(s, 'deliverable', p.id);
    return dl.versions.some((v) => v.number === dl.current) ? null : 'Aucune version adoptée à soumettre.';
  },
  'deliverable.approve': (s, ctx, p) => { const a = pendingApproval(s, { kind: 'deliverable', id: p.id }, 'livrable'); return a ? approvalGuard(s, ctx, a) : 'Aucune demande de revue en attente sur la version actuelle.'; },
  'deliverable.requestChanges': (s, ctx, p) => { const a = pendingApproval(s, { kind: 'deliverable', id: p.id }, 'livrable'); return a ? approvalGuard(s, ctx, a) : 'Aucune demande de revue en attente.'; },
  'deliverable.publish': (s, _c, p) => {
    const dl = must(s, 'deliverable', p.id);
    const ok = list(s, 'approval', s.session.orgId).some((a) => a.subject.kind === 'deliverable' && a.subject.id === dl.id && approvalValidity(s, a).valid);
    return ok ? null : 'Aucune approbation valide sur la version actuelle.';
  },
  'run.suspend': (s, _c, p) => (must(s, 'run', p.id).suspendable ? null : 'Cette exécution ne peut pas être suspendue : seule l’annulation est possible.'),
  'approval.approve': (s, ctx, p) => {
    const a = must(s, 'approval', p.id);
    const g = approvalGuard(s, ctx, a);
    if (g) return g;
    // Approving from the inbox applies the same business guards as approving the subject itself.
    if (a.subject.kind === 'decision') return GUARDS['decision.approve'](s, ctx, { kind: 'decision', id: a.subject.id, action: 'approve' });
    if (a.subject.kind === 'blueprint') return GUARDS['blueprint.publish'](s, ctx, { kind: 'blueprint', id: a.subject.id, action: 'publish', version: a.subject.version });
    return null;
  },
  'approval.refuse': (s, ctx, p) => approvalGuard(s, ctx, must(s, 'approval', p.id)),
  'approval.revoke': (_s, ctx) => (ctx.actor.type === 'human' ? null : 'Réservé à un humain.'),
  'exception.request': (s, _c, p) => {
    const e = must(s, 'exception', p.id);
    const missing = [
      !e.scope.trim() && 'le périmètre', !e.reason.trim() && 'le motif', !e.riskAccepted.trim() && 'le risque accepté',
      !e.compensatingMeasures.trim() && 'les mesures compensatoires', !e.ownerId && 'le propriétaire', !e.approverId && "l’approbateur", !e.expiresAt && "l’échéance",
    ].filter(Boolean);
    if (missing.length) return `Demande incomplète, elle reste en brouillon : renseignez ${missing.join(', ')}.`;
    const project = must(s, 'project', e.projectId);
    if (!ruleIsDerogable(s, project, e.ruleId)) return 'Cette règle est déclarée non dérogeable : aucune exception ne peut lever son blocage.';
    if (e.expiresAt! <= Date.now() + s.demo.timeOffsetMs) return "L’échéance est déjà dépassée.";
    return null;
  },
  'exception.approve': (s, ctx, p) => {
    const e = must(s, 'exception', p.id);
    if (ctx.actor.type !== 'human') return 'Réservé à un humain identifié.';
    if (e.authorId === ctx.actor.userId) return 'Vous avez rédigé cette demande : une autre personne doit l’approuver.';
    if (e.approverId && e.approverId !== ctx.actor.userId) return `Approbation assignée à ${s.users[e.approverId]?.name}.`;
    if (!ruleIsDerogable(s, must(s, 'project', e.projectId), e.ruleId)) return 'Règle non dérogeable.';
    return null;
  },
};

/* ---------------------------------------------------------------- effects */

const EFFECTS: Record<string, EffectFn> = {
  'blueprint.submit': (d, ctx, p) => {
    const bp = must(d, 'blueprint', p.id);
    const v = bp.versions.find((x) => x.number === p.version)!;
    v.submittedAt = ctx.now;
    createApproval(d, ctx, { subject: { kind: 'blueprint', id: bp.id, version: v.number }, purpose: 'blueprint', approverId: p.approverId, requireDistinct: v.number > 1 });
  },
  'blueprint.publish': (d, ctx, p) => {
    const bp = must(d, 'blueprint', p.id);
    const v = bp.versions.find((x) => x.number === p.version)!;
    v.publishedAt = ctx.now;
    v.reviewerId = requireHuman(ctx);
    publishRuleVersions(d, v.rules);
    const a = pendingApproval(d as S, { kind: 'blueprint', id: bp.id }, 'blueprint');
    if (a) decideApproval(d, ctx, a, 'approved');
  },
  'blueprint.reject': (d, ctx, p) => { const a = pendingApproval(d as S, { kind: 'blueprint', id: p.id }, 'blueprint'); if (a) decideApproval(d, ctx, a, 'refused', p.reason); },
  'council.cancel': (d, ctx, p) => {
    Object.values(d.db.decision).filter((x) => x.councilId === p.id && (x.status === 'draft' || x.status === 'review')).forEach((x) => { x.status = 'cancelled'; x.statusReason = 'Session annulée'; });
    d.db.council[p.id].statusReason = p.reason;
    void ctx;
  },
  'council.suspend': (d, _c, p) => { d.db.council[p.id].statusReason = p.reason; },
  'decision.submit': (d, ctx, p) => {
    const dec = d.db.decision[p.id];
    const project = must(d, 'project', dec.projectId);
    dec.considered = { blueprintVersion: project.blueprintVersion, rules: projectRules(d as S, project).rules.map((r) => r.ref) };
    createApproval(d, ctx, { subject: { kind: 'decision', id: dec.id, version: dec.number }, purpose: 'décision', projectId: dec.projectId, approverId: p.approverId });
  },
  'decision.approve': (d, ctx, p) => {
    const a = pendingApproval(d as S, { kind: 'decision', id: p.id }, 'décision')!;
    decideApproval(d, ctx, a, 'approved');
    onDecisionApproved(d, ctx, p.id);
  },
  'decision.refuse': (d, ctx, p) => {
    const a = pendingApproval(d as S, { kind: 'decision', id: p.id }, 'décision')!;
    decideApproval(d, ctx, a, 'refused', p.reason);
    d.db.decision[p.id].statusReason = p.reason;
  },
  'decision.requestRevision': (d, ctx, p) => {
    const a = pendingApproval(d as S, { kind: 'decision', id: p.id }, 'décision')!;
    decideApproval(d, ctx, a, 'refused', `Révision demandée : ${p.reason}`);
    d.db.decision[p.id].statusReason = p.reason;
  },
  'quest.block': (d, _c, p, from) => { const q = d.db.quest[p.id]; q.statusReason = p.reason; q.resumeTo = from as typeof q.status; },
  'quest.unblock': (d, _c, p) => { const q = d.db.quest[p.id]; q.status = q.resumeTo && q.resumeTo !== 'blocked' ? q.resumeTo : 'doing'; q.statusReason = undefined; },
  'quest.close': (d, ctx, p) => {
    const q = d.db.quest[p.id];
    q.closedAt = ctx.now;
    Object.values(d.db.finding).filter((f) => f.questId === q.id && f.status === 'in_progress').forEach((f) => { f.status = 'resolved'; });
  },
  'quest.reopen': (d, _c, p) => { const q = d.db.quest[p.id]; q.closedAt = undefined; q.revision += 1; q.statusReason = p.reason; },
  'quest.cancel': (d, _c, p) => { d.db.quest[p.id].statusReason = p.reason; },
  'task.block': (d, _c, p) => { d.db.task[p.id].statusReason = p.reason; },
  'task.unblock': (d, _c, p) => { d.db.task[p.id].statusReason = undefined; },
  'deliverable.submit': (d, ctx, p) => {
    const dl = d.db.deliverable[p.id];
    createApproval(d, ctx, { subject: { kind: 'deliverable', id: dl.id, version: dl.current }, purpose: 'livrable', projectId: dl.projectId, approverId: p.approverId });
  },
  'deliverable.approve': (d, ctx, p) => { decideApproval(d, ctx, pendingApproval(d as S, { kind: 'deliverable', id: p.id }, 'livrable')!, 'approved'); },
  'deliverable.requestChanges': (d, ctx, p) => { decideApproval(d, ctx, pendingApproval(d as S, { kind: 'deliverable', id: p.id }, 'livrable')!, 'refused', p.reason); },
  'run.cancel': (d, ctx, p) => {
    const r = d.db.run[p.id];
    r.endedAt = ctx.now;
    r.statusReason = p.reason;
    r.steps.forEach((st) => { if (st.status === 'pending' || st.status === 'running') st.status = 'skipped'; });
    r.log.push({ at: ctx.now, level: 'warn', text: `Exécution annulée : ${p.reason}. Aucune mise à jour ultérieure ne sera appliquée.` });
  },
  'run.suspend': (d, ctx, p) => { d.db.run[p.id].log.push({ at: ctx.now, level: 'info', text: 'Exécution suspendue.' }); },
  'run.resume': (d, ctx, p) => { d.db.run[p.id].log.push({ at: ctx.now, level: 'info', text: 'Exécution reprise.' }); },
  'approval.approve': (d, ctx, p) => { const a = d.db.approval[p.id]; decideApproval(d, ctx, a, 'approved'); onApprovalApproved(d, ctx, a); },
  'approval.refuse': (d, ctx, p) => { const a = d.db.approval[p.id]; decideApproval(d, ctx, a, 'refused', p.reason); onApprovalRefused(d, ctx, a, p.reason ?? ''); },
  'approval.revoke': (d, ctx, p) => {
    const a = d.db.approval[p.id];
    decideApproval(d, ctx, a, 'revoked', p.reason);
    flagReview(d, ctx, a.subject, { kind: 'approval', id: a.id }, `Approbation révoquée : ${p.reason}`, a.projectId);
  },
  'exception.approve': (d, ctx, p) => {
    const e = d.db.exception[p.id];
    e.decidedBy = requireHuman(ctx);
    Object.values(d.db.finding).filter((f) => f.projectId === e.projectId && f.ruleId === e.ruleId && f.status === 'open').forEach((f) => { f.status = 'waived'; });
  },
  'exception.refuse': (d, _c, p) => { d.db.exception[p.id].statusReason = p.reason; },
  'exception.revoke': (d, ctx, p) => {
    const e = d.db.exception[p.id];
    e.statusReason = p.reason;
    reopenAfterException(d, ctx, e.id, `Exception révoquée : ${p.reason}`);
  },
  'share.revoke': (d, ctx, p) => { void ctx; d.db.share[p.id].status = 'revoked'; },
};

/** Rule versions become published together with the Blueprint version that references them. */
function publishRuleVersions(d: D, refs: { ruleId: ID; version: number }[]) {
  refs.forEach((ref) => { const rv = d.db.rule[ref.ruleId]?.versions.find((x) => x.number === ref.version); if (rv) rv.status = 'published'; });
}

export function flagReview(d: D, ctx: Ctx, subject: Ref, cause: Ref, reason: string, projectId?: ID) {
  const exists = Object.values(d.db.review).some((r) => r.status === 'open' && r.subject.kind === subject.kind && r.subject.id === subject.id && r.cause.id === cause.id);
  if (exists) return;
  const id = nextId(d, 'rev');
  d.db.review[id] = { id, orgId: ctx.orgId, projectId, subject, cause, reason, status: 'open', createdAt: ctx.now };
}

/** Expired or revoked exceptions put the affected findings and quests back under review (RG-33). */
export function reopenAfterException(d: D, ctx: Ctx, exceptionId: ID, reason: string) {
  const e = d.db.exception[exceptionId];
  Object.values(d.db.finding).filter((f) => f.projectId === e.projectId && f.ruleId === e.ruleId && f.status === 'waived').forEach((f) => {
    f.status = 'open';
    flagReview(d, ctx, { kind: 'finding', id: f.id }, { kind: 'exception', id: e.id }, reason, e.projectId);
  });
  Object.values(d.db.quest).filter((q) => q.projectId === e.projectId && q.status !== 'done' && q.status !== 'cancelled')
    .filter((q) => q.controlIds.some((c) => d.db.control[c]?.ruleIds.includes(e.ruleId)))
    .forEach((q) => flagReview(d, ctx, { kind: 'quest', id: q.id }, { kind: 'exception', id: e.id }, reason, e.projectId));
}

function onDecisionApproved(d: D, ctx: Ctx, decisionId: ID) {
  const dec = d.db.decision[decisionId];
  dec.decidedAt = ctx.now;
  if (dec.councilId && d.db.council[dec.councilId]) d.db.council[dec.councilId].status = 'done';
  if (dec.revisionOf) {
    const old = d.db.decision[dec.revisionOf];
    if (old) {
      old.status = 'replaced';
      old.replacedBy = dec.id;
      emit(d, ctx, { action: 'decision.replaced', summary: `Décision « ${old.title} » v${old.number} remplacée par la v${dec.number}`, object: { kind: 'decision', id: old.id, version: old.number }, projectId: old.projectId, related: [{ kind: 'decision', id: dec.id }] });
    }
  }
}

function onApprovalApproved(d: D, ctx: Ctx, a: Approval) {
  const sub = a.subject;
  if (sub.kind === 'decision') { const dec = d.db.decision[sub.id]; if (dec?.status === 'review') { dec.status = 'approved'; onDecisionApproved(d, ctx, dec.id); } }
  if (sub.kind === 'deliverable') { const dl = d.db.deliverable[sub.id]; if (dl?.status === 'review') dl.status = 'approved'; }
  if (sub.kind === 'blueprint') {
    const v = d.db.blueprint[sub.id]?.versions.find((x) => x.number === sub.version);
    if (v?.status === 'review') { v.status = 'published'; v.publishedAt = ctx.now; v.reviewerId = requireHuman(ctx); publishRuleVersions(d, v.rules); }
  }
  if (sub.kind === 'expert') {
    const ex = d.db.expert[sub.id];
    const proposed = ex?.instructions.find((i) => i.number === sub.version);
    if (ex && proposed?.status === 'proposed') {
      ex.instructions.forEach((i) => { if (i.status === 'active') i.status = 'retired'; });
      proposed.status = 'active';
      proposed.decidedBy = requireHuman(ctx);
    }
  }
}

function onApprovalRefused(d: D, ctx: Ctx, a: Approval, reason: string) {
  const sub = a.subject;
  if (sub.kind === 'decision') { const dec = d.db.decision[sub.id]; if (dec?.status === 'review') { dec.status = 'refused'; dec.statusReason = reason; } }
  if (sub.kind === 'deliverable') { const dl = d.db.deliverable[sub.id]; if (dl?.status === 'review') dl.status = 'draft'; }
  if (sub.kind === 'blueprint') { const v = d.db.blueprint[sub.id]?.versions.find((x) => x.number === sub.version); if (v?.status === 'review') v.status = 'draft'; }
  if (sub.kind === 'expert') { const i = d.db.expert[sub.id]?.instructions.find((x) => x.number === sub.version); if (i?.status === 'proposed') { i.status = 'rejected'; i.decidedBy = requireHuman(ctx); } }
}

/* ---------------------------------------------------------------- command */

function currentState(s: S, p: TransitionPayload): string {
  switch (p.kind) {
    case 'blueprint': return bpVersion(s, s.session.orgId, p.version)?.status ?? fail('Version introuvable.');
    case 'exception': return effectiveExceptionStatus(s, must(s, 'exception', p.id));
    case 'approval': return effectiveApprovalStatus(s, must(s, 'approval', p.id));
    case 'share': { const sh = must(s, 'share', p.id); return sh.status === 'revoked' ? 'revoked' : sh.expiresAt <= Date.now() + s.demo.timeOffsetMs ? 'expired' : 'active'; }
    default: return (must(s, p.kind, p.id, s.session.orgId ?? undefined) as { status: string }).status;
  }
}

function projectOf(s: S, p: TransitionPayload): ID | undefined {
  if (p.kind === 'blueprint') return undefined;
  const e = get(s, p.kind, p.id) as { projectId?: ID; questId?: ID } | undefined;
  if (p.kind === 'task') return get(s, 'quest', (e as { questId: ID } | undefined)?.questId)?.projectId;
  if (p.kind === 'share') return get(s, 'deliverable', get(s, 'share', p.id)?.deliverableId)?.projectId;
  return e?.projectId;
}

export const transition = command<TransitionPayload, string>({
  name: 'transition',
  capability: (p) => findTransition(p.kind, p.action)?.capability ?? 'edit',
  project: (p, s) => projectOf(s, p),
  humanOnly: (p) => !!findTransition(p.kind, p.action)?.humanOnly,
  guard: (s, ctx, p) => {
    const def = findTransition(p.kind as MachineKind, p.action);
    if (!def) return `Action « ${p.action} » inconnue.`;
    const from = currentState(s, p);
    if (!def.from.includes(from)) return `Impossible depuis l’état « ${stateDef(p.kind as MachineKind, from).label} » : ${def.label.toLowerCase()} n’est possible que depuis ${def.from.map((f) => `« ${stateDef(p.kind as MachineKind, f).label} »`).join(', ')}.`;
    if (def.needsReason && !(p.reason ?? '').trim()) return 'Un motif est requis pour cette action.';
    return GUARDS[`${p.kind}.${p.action}`]?.(s, ctx, p) ?? null;
  },
  run: (d, ctx, p) => {
    const def = findTransition(p.kind, p.action)!;
    const from = currentState(d as S, p);
    if (p.kind === 'blueprint') {
      const v = must(d, 'blueprint', p.id).versions.find((x) => x.number === p.version)!;
      v.status = def.to as typeof v.status;
    } else if (p.kind !== 'share') {
      (must(d, p.kind, p.id) as { status: string }).status = def.to;
    }
    EFFECTS[`${p.kind}.${p.action}`]?.(d, ctx, p, from);
    const to = p.kind === 'blueprint' ? def.to : p.kind === 'share' ? 'revoked' : (get(d, p.kind, p.id) as { status: string }).status;
    const projectId = projectOf(d as S, p);
    emit(d, ctx, {
      action: `${p.kind}.${p.action}`,
      summary: `${def.label} — ${labelFor(d as S, p)} (${stateDef(p.kind as MachineKind, from).label} → ${stateDef(p.kind as MachineKind, to).label})`,
      object: { kind: p.kind, id: p.id, version: p.version },
      projectId,
      justification: p.reason,
    });
    return to;
  },
});

function labelFor(s: S, p: TransitionPayload): string {
  if (p.kind === 'blueprint') return `Blueprint v${p.version}`;
  const e = get(s, p.kind, p.id) as { title?: string; name?: string } | undefined;
  return e?.title ?? e?.name ?? p.id;
}
