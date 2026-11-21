/**
 * Watchtower (findings, exceptions, qualifications), Observatory (watch), documentation
 * sharing and Chronicles (exports, compensations), plus the periodic `tick`.
 */
import { services } from '@/adapters/services';
import { command, DAY, emit, fail, insert, list, must, nextId, requireHuman, type Ctx, clone } from '../engine';
import { effectiveExceptionStatus, effectiveApprovalStatus, resultFreshness, shareStatus } from '../selectors';
import { advanceRun } from './forge';
import { produceContribution } from './work';
import { flagReview, reopenAfterException } from './transitions';
import type { AppState, ID, Ref, RuleException, SignalType } from '../types';
import type { Draft } from 'immer';

type D = Draft<AppState>;

/* ---------------------------------------------------------------- findings */

export const assignFinding = command<{ id: ID; ownerId: ID }>({
  name: 'assignFinding',
  capability: 'edit',
  project: (p, s) => s.db.finding[p.id]?.projectId,
  run: (d, ctx, p) => {
    const f = must(d, 'finding', p.id, ctx.orgId);
    f.ownerId = p.ownerId;
    if (f.status === 'open') f.status = 'in_progress';
    emit(d, ctx, { action: 'finding.assigned', summary: `Constat « ${f.title} » assigné à ${d.users[p.ownerId]?.name}`, object: { kind: 'finding', id: f.id }, projectId: f.projectId });
  },
});

/** Creates the corrective quest once; a second click links to the existing one (RG-20, RG-42). */
export const correctiveQuest = command<{ findingId: ID; existingQuestId?: ID }, ID>({
  name: 'correctiveQuest',
  capability: 'edit',
  project: (p, s) => s.db.finding[p.findingId]?.projectId,
  guard: (s, _c, p) => {
    const f = s.db.finding[p.findingId];
    if (!f) return 'Constat introuvable.';
    if (f.questId && !p.existingQuestId) return `Une quête corrective existe déjà : ${s.db.quest[f.questId]?.title}.`;
    if (p.existingQuestId && ['done', 'cancelled'].includes(s.db.quest[p.existingQuestId]?.status ?? '')) return 'Quête close : rouvrez-la ou créez une correction.';
    return null;
  },
  run: (d, ctx, p) => {
    const f = must(d, 'finding', p.findingId, ctx.orgId);
    let questId = p.existingQuestId;
    if (!questId) {
      questId = nextId(d, 'qst');
      const dl = d.db.deliverable[f.subject.id];
      insert(d, 'quest', {
        id: questId, orgId: ctx.orgId, projectId: f.projectId, title: `Corriger : ${f.title}`, objective: f.remediation, type: f.category === 'sécurité' ? 'sécurité' : 'correction',
        origin: 'finding', originRef: { kind: 'finding', id: f.id }, ownerId: f.ownerId, priority: f.severity === 'critique' ? 'P1' : 'P2', status: 'todo',
        criteria: [{ id: nextId(d, 'crt'), text: `Le contrôle ${d.db.control[f.source]?.code ?? ''} réussit sur une nouvelle version`, required: true, met: false }],
        expectedDeliverables: dl ? [dl.type] : [], deliverableIds: dl ? [dl.id] : [], controlIds: d.db.control[f.source] ? [f.source] : [], needsHumanApproval: true,
        comments: [], order: 0, createdAt: ctx.now, revision: 0,
      });
      emit(d, ctx, { action: 'quest.created', summary: `Quête corrective créée depuis le constat « ${f.title} »`, object: { kind: 'quest', id: questId }, projectId: f.projectId, related: [{ kind: 'finding', id: f.id }] });
    } else {
      emit(d, ctx, { action: 'finding.linked', summary: `Constat « ${f.title} » rattaché à la quête « ${d.db.quest[questId]?.title} »`, object: { kind: 'finding', id: f.id }, projectId: f.projectId, related: [{ kind: 'quest', id: questId }] });
    }
    f.questId = questId;
    if (f.status === 'open') f.status = 'in_progress';
    return questId;
  },
});

/** "Non applicable" always carries a human justification (RG-27). */
export const markNotApplicable = command<{ controlId: ID; deliverableId: ID; justification: string }, ID>({
  name: 'markNotApplicable',
  capability: 'run_controls',
  project: (p, s) => s.db.deliverable[p.deliverableId]?.projectId,
  humanOnly: true,
  guard: (_s, _c, p) => (p.justification.trim().length < 15 ? 'Une justification d’au moins 15 caractères est obligatoire.' : null),
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.deliverableId, ctx.orgId);
    const c = must(d, 'control', p.controlId, ctx.orgId);
    const project = d.db.project[dl.projectId];
    const runId = nextId(d, 'run');
    const inputs = { blueprintVersion: project.blueprintVersion, rules: [], controlVersion: c.version, subject: { deliverableId: dl.id, version: dl.current }, params: { qualification: 'humaine' } };
    insert(d, 'run', { id: runId, orgId: ctx.orgId, projectId: dl.projectId, kind: 'control', controlId: c.id, title: `${c.code} — qualification « non applicable »`, inputs, steps: [{ label: 'Qualification humaine', status: 'done' }], stepIndex: 1, status: 'done', log: [{ at: ctx.now, level: 'info', text: `Non applicable : ${p.justification}` }], attempt: 1, startedAt: ctx.now, endedAt: ctx.now, costPerStep: 0, actor: ctx.actor, suspendable: false, plannedFailure: null });
    const id = nextId(d, 'res');
    insert(d, 'result', { id, orgId: ctx.orgId, projectId: dl.projectId, runId, controlId: c.id, outcome: 'not_applicable', observation: 'Qualifié non applicable par une personne.', justification: p.justification.trim(), inputs, evaluatedAt: ctx.now, simulated: true });
    emit(d, ctx, { action: 'result.not_applicable', summary: `${c.code} qualifié non applicable sur « ${dl.title} »`, object: { kind: 'result', id }, projectId: dl.projectId, justification: p.justification });
    return id;
  },
});

/* ---------------------------------------------------------------- exceptions */

export type ExceptionInput = Pick<RuleException, 'projectId' | 'ruleId' | 'scope' | 'reason' | 'riskAccepted' | 'compensatingMeasures' | 'ownerId' | 'approverId' | 'expiresAt' | 'subject'>;

export const saveException = command<ExceptionInput & { id?: ID }, ID>({
  name: 'saveException',
  capability: 'request_exception',
  project: (p) => p.projectId,
  guard: (s, _c, p) => (p.id && s.db.exception[p.id]?.status !== 'draft' ? 'Seul un brouillon est modifiable.' : !s.db.rule[p.ruleId] ? 'Choisissez la règle concernée.' : null),
  run: (d, ctx, p) => {
    const id = p.id ?? nextId(d, 'exc');
    const prev = d.db.exception[id];
    insert(d, 'exception', { ...p, id, orgId: ctx.orgId, status: 'draft', authorId: prev?.authorId ?? requireHuman(ctx), createdAt: prev?.createdAt ?? ctx.now });
    if (!prev) emit(d, ctx, { action: 'exception.draft', summary: `Demande d’exception préparée pour ${d.db.rule[p.ruleId].code}`, object: { kind: 'exception', id }, projectId: p.projectId });
    return id;
  },
});

/* ---------------------------------------------------------------- observatory */

export const collectSignals = command<Record<string, never>, number>({
  name: 'collectSignals',
  capability: 'propose',
  guard: (s, ctx) => (!s.orgs[ctx.orgId]?.settings.watch.enabled ? 'La veille simulée est désactivée dans les paramètres.' : s.orgs[ctx.orgId].settings.watch.cursor >= services.watch.feed.length ? 'Aucun nouveau signal dans le scénario de démonstration.' : null),
  run: (d, ctx) => {
    const org = d.orgs[ctx.orgId];
    const t = services.watch.feed[org.settings.watch.cursor];
    org.settings.watch.cursor += 1;
    const competitorId = Object.values(d.db.competitor).find((c) => c.orgId === ctx.orgId && c.name === t.competitor)?.id;
    let source = Object.values(d.db.source).find((x) => x.orgId === ctx.orgId && x.name === t.source);
    if (!source) {
      source = insert(d, 'source', { id: nextId(d, 'src'), orgId: ctx.orgId, name: t.source, url: 'https://example.invalid/veille-fictive', type: 'Page publique fictive', fictional: true, active: true });
    }
    const id = nextId(d, 'sig');
    const { competitor: _c, source: _s, daysAgo, projects, ...rest } = t;
    insert(d, 'signal', { ...clone(rest), id, orgId: ctx.orgId, competitorId, sourceId: source.id, publishedAt: ctx.now - daysAgo * DAY, consultedAt: ctx.now, projectIds: projects.filter((x) => d.db.project[x]?.orgId === ctx.orgId), notes: [], favorite: false, reevaluation: 'proposed', fictional: true });
    emit(d, ctx, { action: 'signal.collected', summary: `Nouveau signal (fictif) : ${t.title} — réévaluation proposée, la roadmap n’est pas modifiée`, object: { kind: 'signal', id }, provenance: 'simulation' });
    return 1;
  },
});

export const updateSignal = command<{ id: ID; note?: string; favorite?: boolean; relevance?: { level: 'faible' | 'moyenne' | 'forte'; reason: string }; projectIds?: ID[] }>({
  name: 'updateSignal',
  capability: 'propose',
  guard: (_s, _c, p) => (p.relevance && p.relevance.reason.trim().length < 5 ? 'Expliquez le niveau de pertinence.' : null),
  run: (d, ctx, p) => {
    const sig = must(d, 'signal', p.id, ctx.orgId);
    const authorId = ctx.actor.type === 'human' ? ctx.actor.userId : 'agent';
    if (p.note) sig.notes.push({ id: nextId(d, 'nte'), authorId, text: p.note, at: ctx.now });
    if (p.favorite !== undefined) sig.favorite = p.favorite;
    if (p.projectIds) sig.projectIds = p.projectIds;
    if (p.relevance) { sig.relevance = { level: p.relevance.level, reasons: [p.relevance.reason, ...sig.relevance.reasons].slice(0, 4) }; sig.reevaluation = 'done'; }
    if (p.note || p.relevance) emit(d, ctx, { action: p.relevance ? 'signal.reevaluated' : 'signal.annotated', summary: p.relevance ? `Signal réévalué (${p.relevance.level}) : ${sig.title}` : `Note ajoutée au signal « ${sig.title} »`, object: { kind: 'signal', id: sig.id }, justification: p.relevance?.reason });
  },
});

export const saveOpportunity = command<{ id?: ID; title: string; description: string; signalIds: ID[]; status?: 'open' | 'council' | 'retained' | 'dismissed' }, ID>({
  name: 'saveOpportunity',
  capability: 'propose',
  guard: (_s, _c, p) => (p.title.trim().length < 4 ? 'Titre trop court.' : null),
  run: (d, ctx, p) => {
    const id = p.id ?? nextId(d, 'opp');
    const prev = d.db.opportunity[id];
    insert(d, 'opportunity', { id, orgId: ctx.orgId, title: p.title.trim(), description: p.description, signalIds: p.signalIds, status: p.status ?? prev?.status ?? 'open', councilId: prev?.councilId, createdAt: prev?.createdAt ?? ctx.now });
    p.signalIds.forEach((sid) => { if (d.db.signal[sid]) d.db.signal[sid].opportunityId = id; });
    emit(d, ctx, { action: prev ? 'opportunity.updated' : 'opportunity.created', summary: `Opportunité « ${p.title.trim()} » ${prev ? 'modifiée' : 'créée'}`, object: { kind: 'opportunity', id }, related: p.signalIds.map((x) => ({ kind: 'signal' as const, id: x })) });
    return id;
  },
});

export const saveCompetitor = command<{ id?: ID; name: string; kind: 'direct' | 'indirect'; description: string; strengths: string[]; weaknesses: string[]; favorite?: boolean }, ID>({
  name: 'saveCompetitor',
  capability: 'propose',
  guard: (_s, _c, p) => (p.name.trim().length < 2 ? 'Nom trop court.' : null),
  run: (d, ctx, p) => {
    const id = p.id ?? nextId(d, 'cmp');
    insert(d, 'competitor', { id, orgId: ctx.orgId, name: p.name.trim(), kind: p.kind, description: p.description, strengths: p.strengths, weaknesses: p.weaknesses, favorite: p.favorite ?? d.db.competitor[id]?.favorite ?? false, fictional: true });
    emit(d, ctx, { action: 'competitor.saved', summary: `Concurrent fictif « ${p.name.trim()} » enregistré`, object: { kind: 'competitor', id } });
    return id;
  },
});

export const saveSource = command<{ id?: ID; name: string; url: string; type: string; active: boolean }, ID>({
  name: 'saveSource',
  capability: 'configure_org',
  guard: (_s, _c, p) => { try { const u = new URL(p.url); return ['http:', 'https:'].includes(u.protocol) ? null : 'Seules les adresses http(s) sont acceptées.'; } catch { return 'Adresse invalide.'; } },
  run: (d, ctx, p) => {
    const id = p.id ?? nextId(d, 'src');
    insert(d, 'source', { id, orgId: ctx.orgId, name: p.name.trim(), url: p.url, type: p.type, active: p.active, fictional: true });
    emit(d, ctx, { action: 'source.saved', summary: `Source de veille « ${p.name.trim()} » ${p.active ? 'active' : 'inactive'} (simulation, aucune collecte réelle)`, object: { kind: 'source', id } });
    return id;
  },
});

/* ---------------------------------------------------------------- sharing */

const token = (d: D) => `demo-${(d.seq * 7919 + 104729).toString(36)}`;

export const createShare = command<{ deliverableId: ID; audience: string; mode: 'lecture' | 'contribution'; days: number }, ID>({
  name: 'createShare',
  capability: 'share',
  project: (p, s) => s.db.deliverable[p.deliverableId]?.projectId,
  guard: (s, _c, p) => {
    const dl = s.db.deliverable[p.deliverableId];
    if (!dl) return 'Document introuvable.';
    if (!['approved', 'published'].includes(dl.status)) return 'Seule une version approuvée ou publiée peut être partagée.';
    if (!p.audience.trim()) return 'Choisissez une audience.';
    return p.days < 1 || p.days > 90 ? 'Durée entre 1 et 90 jours.' : null;
  },
  run: (d, ctx, p) => {
    const dl = must(d, 'deliverable', p.deliverableId, ctx.orgId);
    const id = nextId(d, 'shr');
    insert(d, 'share', { id, orgId: ctx.orgId, deliverableId: dl.id, version: dl.current, audience: p.audience.trim(), mode: p.mode, expiresAt: ctx.now + p.days * DAY, status: 'active', token: token(d), createdBy: requireHuman(ctx), createdAt: ctx.now, accessLog: [] });
    emit(d, ctx, { action: 'share.created', summary: `Lien de démonstration local créé pour « ${dl.title} » v${dl.current} (${p.audience.trim()}, ${p.mode}, ${p.days} j) — aucun courriel envoyé`, object: { kind: 'share', id }, projectId: dl.projectId, provenance: 'démo' });
    return id;
  },
});

/** Simulates someone opening a local demo link; logs authorised, refused, expired or revoked access (RG-38). */
export const openShare = command<{ token: string; visitor: string }, 'autorisé' | 'refusé' | 'expiré' | 'révoqué'>({
  name: 'openShare',
  global: true,
  guard: (s, _c, p) => (Object.values(s.db.share).some((x) => x.token === p.token) ? null : 'Lien introuvable.'),
  run: (d, ctx, p) => {
    const sh = Object.values(d.db.share).find((x) => x.token === p.token)!;
    const st = shareStatus(d as AppState, sh);
    const outcome = st === 'revoked' ? 'révoqué' : st === 'expired' ? 'expiré' : sh.audience.toLowerCase().includes(p.visitor.trim().toLowerCase()) && p.visitor.trim() ? 'autorisé' : 'refusé';
    sh.accessLog.push({ at: ctx.now, visitor: p.visitor.trim() || 'anonyme', outcome });
    emit(d, { ...ctx, orgId: sh.orgId, actor: { type: 'system' } }, { action: `share.open.${outcome}`, summary: `Ouverture simulée du lien par « ${p.visitor.trim() || 'anonyme'} » : accès ${outcome}`, object: { kind: 'share', id: sh.id }, provenance: 'démo' });
    return outcome;
  },
});

/* ---------------------------------------------------------------- chronicles */

export const recordExport = command<{ what: string; format: string; count: number; object?: Ref }>({
  name: 'recordExport',
  capability: 'export',
  run: (d, ctx, p) => {
    emit(d, ctx, { action: 'export', summary: `Export ${p.format} : ${p.what} (${p.count} élément(s))`, object: p.object ?? { kind: 'org', id: ctx.orgId } });
  },
});

/** Compensating event: undo by a new event and, when supported, a new version (RG-39). */
export const compensateEvent = command<{ eventId: ID; reason: string }, string>({
  name: 'compensateEvent',
  capability: 'edit',
  project: (p, s) => s.db.event[p.eventId]?.projectId,
  humanOnly: true,
  guard: (s, _c, p) => {
    const e = s.db.event[p.eventId];
    if (!e) return 'Événement introuvable.';
    if (Object.values(s.db.event).some((x) => x.compensates === e.id)) return 'Cet événement a déjà été compensé.';
    if (!COMPENSABLE.includes(e.action)) return `Les événements « ${e.action} » ne se compensent pas automatiquement : utilisez la transition ou la version appropriée.`;
    return p.reason.trim().length < 5 ? 'Motivez la compensation.' : null;
  },
  run: (d, ctx, p) => {
    const e = d.db.event[p.eventId];
    let effect = '';
    if (e.action === 'deliverable.version' || e.action === 'deliverable.adopted') {
      const dl = must(d, 'deliverable', e.object.id);
      const prev = dl.versions.filter((v) => v.number < (e.object.version ?? 0) && !v.proposal).at(-1) ?? fail('Aucune version antérieure.');
      const number = Math.max(...dl.versions.map((v) => v.number)) + 1;
      dl.versions.push({ ...clone(prev), number, createdAt: ctx.now, authorId: requireHuman(ctx), authorKind: 'human', note: `Compensation de la v${e.object.version} : ${p.reason}`, proposal: false });
      dl.current = number;
      dl.status = 'draft';
      effect = `nouvelle version ${number} reprenant la v${prev.number}`;
    } else if (e.action === 'project.archived') {
      const pr = must(d, 'project', e.object.id);
      pr.status = 'active';
      effect = 'projet restauré';
    } else if (e.action === 'project.restored') {
      const pr = must(d, 'project', e.object.id);
      pr.status = 'archived';
      effect = 'projet de nouveau archivé';
    } else if (e.action === 'applicability.set' || e.action === 'quest.criterion') {
      effect = 'annulation consignée sans effet automatique';
    }
    emit(d, ctx, { action: 'compensation', summary: `Compensation de « ${e.summary} » : ${effect}`, object: e.object, projectId: e.projectId, justification: p.reason, compensates: e.id });
    return effect;
  },
});
export const COMPENSABLE = ['deliverable.version', 'deliverable.adopted', 'project.archived', 'project.restored', 'applicability.set', 'quest.criterion'];

/* ---------------------------------------------------------------- tick */

/** Expired exceptions and approvals: status recorded once, affected objects put under review (RG-33). */
function syncExpirations(d: D, ctx: Ctx) {
  const s = d as AppState;
  Object.values(d.db.exception).filter((e) => e.orgId === ctx.orgId && e.status === 'approved' && effectiveExceptionStatus(s, e) === 'expired').forEach((e) => {
    e.status = 'expired';
    emit(d, { ...ctx, actor: { type: 'system' } }, { action: 'exception.expired', summary: `Exception expirée : ${d.db.rule[e.ruleId]?.code} sur ${d.db.project[e.projectId]?.name} — les nouvelles actions concernées attendent un nouvel examen`, object: { kind: 'exception', id: e.id }, projectId: e.projectId });
    reopenAfterException(d, ctx, e.id, `Exception ${e.id} expirée`);
  });
  Object.values(d.db.approval).filter((a) => a.orgId === ctx.orgId && a.status === 'approved' && effectiveApprovalStatus(s, a) === 'expired').forEach((a) => {
    a.status = 'expired';
    flagReview(d, ctx, a.subject, { kind: 'approval', id: a.id }, 'Approbation expirée', a.projectId);
  });
}

/** Periodic system step: advances executions, council contributions and demo connections. */
export const tick = command<Record<string, never>, boolean>({
  name: 'tick',
  run: (d, ctx) => {
    const sys = { ...ctx, actor: { type: 'system' as const } };
    let changed = false;
    list(d as AppState, 'run', ctx.orgId).filter((r) => r.status === 'running').forEach((r) => { advanceRun(d, ctx, r.id); changed = true; });
    list(d as AppState, 'council', ctx.orgId).filter((c) => c.status === 'running').forEach((c) => { changed = produceContribution(d, ctx, c.id) || changed; });
    list(d as AppState, 'integration', ctx.orgId).filter((i) => i.status === 'connecting').forEach((i) => {
      const failNext = d.demo.nextFailure === 'tool-error';
      i.status = failNext ? 'error' : 'available';
      i.changedAt = ctx.now;
      if (failNext) d.demo.nextFailure = null;
      emit(d, sys, { action: `integration.${i.status}`, summary: `${i.name} : ${failNext ? 'erreur simulée pendant la connexion' : 'disponible en simulation'}`, object: { kind: 'integration', id: i.id }, provenance: 'démo' });
      changed = true;
    });
    syncExpirations(d, ctx);
    return changed;
  },
});

export const hasActiveWork = (s: AppState) =>
  list(s, 'run', s.session.orgId).some((r) => r.status === 'running') ||
  list(s, 'council', s.session.orgId).some((c) => c.status === 'running' && c.participantIds.some((e) => !c.contributions.some((x) => x.expertId === e))) ||
  list(s, 'integration', s.session.orgId).some((i) => i.status === 'connecting') ||
  list(s, 'exception', s.session.orgId).some((e) => e.status === 'approved' && effectiveExceptionStatus(s, e) === 'expired');

export const staleOf = (s: AppState, resultId: ID) => resultFreshness(s, must(s, 'result', resultId));
export type { SignalType };
