/**
 * Library (references, applicability, collections, packs, imports, update proposals)
 * and Guild (agent configuration) commands.
 */
import type { ImportRow, Reference } from '@/demo/adapters/catalogue';
import { command, emit, fail, insert, must, nextId, requireHuman, clone } from '../engine';
import { allReferences, openDraft, referenceById } from '../selectors';
import { createApproval } from './transitions';
import type { ApplicabilityStatus, ID } from '../types';

/* ---------------------------------------------------------------- references */

export const toggleFavoriteReference = command<{ refId: string }>({
  name: 'toggleFavoriteReference',
  run: (d, ctx, p) => {
    const f = (d.catalogue.favorites[ctx.orgId] ??= []);
    d.catalogue.favorites[ctx.orgId] = f.includes(p.refId) ? f.filter((x) => x !== p.refId) : [...f, p.refId];
  },
});

export const setApplicability = command<{ projectId: ID; refId: string; status: ApplicabilityStatus; reason: string }, ID>({
  name: 'setApplicability',
  capability: 'propose',
  project: (p) => p.projectId,
  guard: (s, _c, p) =>
    !referenceById(s, p.refId) ? 'Référence inconnue.' : p.reason.trim().length < 5 ? 'Indiquez le motif de cette qualification.' : null,
  run: (d, ctx, p) => {
    const existing = Object.values(d.db.applicability).find(
      (a) => a.orgId === ctx.orgId && a.projectId === p.projectId && a.refId === p.refId,
    );
    const human = ctx.actor.type === 'human';
    const authorId = human ? requireHuman(ctx) : `agent:${ctx.actor.type === 'agent' ? ctx.actor.expertId : ''}`;
    const id = existing?.id ?? nextId(d, 'app');
    insert(d, 'applicability', {
      id,
      orgId: ctx.orgId,
      projectId: p.projectId,
      refId: p.refId,
      status: p.status,
      reason: p.reason.trim(),
      authorId,
      validated: human,
      suggestedBy: human ? undefined : 'Agent',
      at: ctx.now,
    });
    emit(d, ctx, {
      action: 'applicability.set',
      summary: `Applicabilité de ${referenceById(d as never, p.refId)?.name} : ${p.status}${human ? '' : ' (proposition d’agent)'}`,
      object: { kind: 'applicability', id },
      projectId: p.projectId,
      justification: p.reason,
      related: [{ kind: 'reference', id: p.refId }],
    });
    return id;
  },
});

export const validateApplicability = command<{ id: ID }>({
  name: 'validateApplicability',
  capability: 'propose',
  humanOnly: true,
  project: (p, s) => s.db.applicability[p.id]?.projectId,
  guard: (s, _c, p) => (s.db.applicability[p.id]?.validated ? 'Déjà validée.' : null),
  run: (d, ctx, p) => {
    const a = must(d, 'applicability', p.id, ctx.orgId);
    a.validated = true;
    a.authorId = requireHuman(ctx);
    a.at = ctx.now;
    emit(d, ctx, {
      action: 'applicability.validated',
      summary: `Suggestion validée : ${referenceById(d as never, a.refId)?.name}`,
      object: { kind: 'applicability', id: a.id },
      projectId: a.projectId,
    });
  },
});

/** Links a reference to an existing rule of the open draft (one rule may cite several references). */
export const linkReferenceToRule = command<{ refId: string; ruleId: ID }>({
  name: 'linkReferenceToRule',
  capability: 'propose',
  guard: (s, ctx, p) => {
    const draft = openDraft(s, ctx.orgId);
    if (!draft || draft.status !== 'draft') return 'Préparez d’abord une nouvelle version du Blueprint : une version publiée est immuable.';
    if (!draft.rules.some((r) => r.ruleId === p.ruleId)) return 'La règle ne figure pas dans la version en préparation.';
    const ref = draft.rules.find((r) => r.ruleId === p.ruleId)!;
    return s.db.rule[p.ruleId].versions.find((v) => v.number === ref.version)?.referenceIds.includes(p.refId)
      ? 'Cette référence est déjà citée par la règle.'
      : null;
  },
  run: (d, ctx, p) => {
    const draft = openDraft(d as never, ctx.orgId)!;
    const rule = must(d, 'rule', p.ruleId, ctx.orgId);
    const ref = draft.rules.find((r) => r.ruleId === p.ruleId)!;
    const cur = rule.versions.find((v) => v.number === ref.version)!;
    if (cur.status === 'draft') cur.referenceIds.push(p.refId);
    else {
      const number = Math.max(...rule.versions.map((v) => v.number)) + 1;
      rule.versions.push({
        ...clone(cur),
        number,
        status: 'draft',
        referenceIds: [...cur.referenceIds, p.refId],
        authorId: requireHuman(ctx),
        createdAt: ctx.now,
        justification: `Ajout de la source ${p.refId}`,
      });
      // the draft Blueprint version is the only one modified; published versions keep their rule versions
      const bp = Object.values(d.db.blueprint).find((b) => b.orgId === ctx.orgId)!;
      bp.versions.find((v) => v.number === draft.number)!.rules.find((r) => r.ruleId === p.ruleId)!.version = number;
    }
    emit(d, ctx, {
      action: 'rule.reference',
      summary: `${rule.code} cite désormais ${referenceById(d as never, p.refId)?.name} (brouillon v${draft.number})`,
      object: { kind: 'rule', id: rule.id },
      related: [{ kind: 'reference', id: p.refId }],
    });
  },
});

export const editReference = command<{
  refId: string;
  patch: Partial<Pick<Reference, 'description' | 'whenToUse' | 'nature' | 'sources'>>;
  note: string;
}>({
  name: 'editReference',
  capability: 'configure_org',
  guard: (s, _c, p) => (!referenceById(s, p.refId) ? 'Référence inconnue.' : p.note.trim().length < 3 ? 'Décrivez la modification.' : null),
  run: (d, ctx, p) => {
    const cur = referenceById(d as never, p.refId)!;
    (d.catalogue.history[p.refId] ??= []).push({ at: ctx.now, authorId: requireHuman(ctx), data: clone(cur), note: p.note });
    const next = { ...cur, ...p.patch };
    d.catalogue.added = d.catalogue.added.filter((r) => r.id !== p.refId).concat(next);
    emit(d, ctx, {
      action: 'reference.edited',
      summary: `Fiche « ${cur.name} » modifiée (version précédente conservée)`,
      object: { kind: 'reference', id: p.refId },
      justification: p.note,
    });
  },
});

export const restoreReference = command<{ refId: string; index: number }>({
  name: 'restoreReference',
  capability: 'configure_org',
  guard: (s, _c, p) => (s.catalogue.history[p.refId]?.[p.index] ? null : 'Version introuvable.'),
  run: (d, ctx, p) => {
    const hist = d.catalogue.history[p.refId];
    const target = clone(hist[p.index].data);
    hist.push({
      at: ctx.now,
      authorId: requireHuman(ctx),
      data: clone(referenceById(d as never, p.refId)!),
      note: `Avant restauration de la version du ${new Date(hist[p.index].at).toLocaleDateString('fr-FR')}`,
    });
    d.catalogue.added = d.catalogue.added.filter((r) => r.id !== p.refId).concat(target);
    emit(d, ctx, {
      action: 'reference.restored',
      summary: `Fiche « ${target.name} » restaurée par une nouvelle version`,
      object: { kind: 'reference', id: p.refId },
    });
  },
});

/** Applies an import after preview: each row was explicitly marked add / update / skip (RG-41). */
export const applyCatalogueImport = command<{ rows: ImportRow[]; source: string }, { added: number; updated: number; skipped: number }>({
  name: 'applyCatalogueImport',
  capability: 'configure_org',
  guard: (_s, _c, p) => (p.rows.length === 0 ? 'Rien à importer.' : null),
  run: (d, ctx, p) => {
    const counts = { added: 0, updated: 0, skipped: 0 };
    const known = new Set(allReferences(d as never).map((r) => r.id));
    for (const row of p.rows) {
      if (row.decision === 'skip') {
        counts.skipped++;
        continue;
      }
      if (row.decision === 'update' && row.existing) {
        (d.catalogue.history[row.existing.id] ??= []).push({
          at: ctx.now,
          authorId: requireHuman(ctx),
          data: clone(referenceById(d as never, row.existing.id)!),
          note: `Avant import ${p.source}`,
        });
        d.catalogue.added = d.catalogue.added.filter((r) => r.id !== row.existing!.id).concat({ ...row.incoming, id: row.existing.id });
        counts.updated++;
      } else {
        let id = row.incoming.id;
        let n = 2;
        while (known.has(id)) id = `${row.incoming.id}-${n++}`;
        known.add(id);
        d.catalogue.added.push({ ...row.incoming, id });
        counts.added++;
      }
    }
    emit(d, ctx, {
      action: 'catalogue.imported',
      summary: `Import « ${p.source} » : ${counts.added} ajout(s), ${counts.updated} mise(s) à jour, ${counts.skipped} ignorée(s)`,
      object: { kind: 'org', id: ctx.orgId },
    });
    return counts;
  },
});

/** Simulated watch on references: produces a proposal, never a silent update (RG-37). */
export const proposeReferenceUpdate = command<{ refId: string; changes: Partial<Reference>; origin: string }, ID>({
  name: 'proposeReferenceUpdate',
  capability: 'propose',
  guard: (s, _c, p) =>
    s.catalogue.proposals.some((x) => x.refId === p.refId && x.status === 'proposed')
      ? 'Une proposition est déjà en attente pour cette référence.'
      : null,
  run: (d, ctx, p) => {
    const cur = referenceById(d as never, p.refId) ?? fail('Référence inconnue.');
    const id = nextId(d, 'rpr');
    d.catalogue.proposals.push({
      id,
      refId: p.refId,
      incoming: { ...cur, ...p.changes },
      changes: Object.keys(p.changes),
      status: 'proposed',
      at: ctx.now,
      origin: p.origin,
    });
    emit(d, ctx, {
      action: 'reference.update.proposed',
      summary: `Mise à jour proposée pour « ${cur.name} » (${p.origin})`,
      object: { kind: 'reference', id: p.refId },
      provenance: 'simulation',
    });
    return id;
  },
});

export const decideReferenceProposal = command<{ id: ID; adopt: boolean }>({
  name: 'decideReferenceProposal',
  capability: 'configure_org',
  humanOnly: true,
  guard: (s, _c, p) => (s.catalogue.proposals.find((x) => x.id === p.id)?.status === 'proposed' ? null : 'Proposition déjà traitée.'),
  run: (d, ctx, p) => {
    const prop = d.catalogue.proposals.find((x) => x.id === p.id)!;
    prop.status = p.adopt ? 'adopted' : 'dismissed';
    if (p.adopt) {
      (d.catalogue.history[prop.refId] ??= []).push({
        at: ctx.now,
        authorId: requireHuman(ctx),
        data: clone(referenceById(d as never, prop.refId)!),
        note: 'Avant adoption de la mise à jour',
      });
      d.catalogue.added = d.catalogue.added.filter((r) => r.id !== prop.refId).concat(clone(prop.incoming));
    }
    emit(d, ctx, {
      action: p.adopt ? 'reference.update.adopted' : 'reference.update.dismissed',
      summary: `Mise à jour de « ${prop.incoming.name} » ${p.adopt ? 'adoptée' : 'écartée'}`,
      object: { kind: 'reference', id: prop.refId },
    });
  },
});

/* ---------------------------------------------------------------- collections and packs */

export const saveCollection = command<{ id?: ID; name: string; description: string; refIds: string[] }, ID>({
  name: 'saveCollection',
  capability: 'propose',
  guard: (_s, _c, p) => (p.name.trim().length < 2 ? 'Nom trop court.' : null),
  run: (d, ctx, p) => {
    const id = p.id ?? nextId(d, 'col');
    insert(d, 'collection', { id, orgId: ctx.orgId, name: p.name.trim(), description: p.description, refIds: [...new Set(p.refIds)] });
    emit(d, ctx, {
      action: p.id ? 'collection.updated' : 'collection.created',
      summary: `Collection « ${p.name.trim()} » ${p.id ? 'modifiée' : 'créée'} (${p.refIds.length} référence(s))`,
      object: { kind: 'collection', id },
    });
    return id;
  },
});

export const toggleInCollection = command<{ collectionId: ID; refId: string }>({
  name: 'toggleInCollection',
  capability: 'propose',
  run: (d, ctx, p) => {
    const c = must(d, 'collection', p.collectionId, ctx.orgId);
    c.refIds = c.refIds.includes(p.refId) ? c.refIds.filter((x) => x !== p.refId) : [...c.refIds, p.refId];
  },
});

export const savePack = command<{ id?: ID; name: string; description: string; refIds: string[]; enabled: boolean }, ID>({
  name: 'savePack',
  capability: 'configure_org',
  guard: (s, _c, p) =>
    p.name.trim().length < 2
      ? 'Nom trop court.'
      : p.id && s.db.pack[p.id]?.origin === 'cli' && p.refIds.length !== s.db.pack[p.id].refIds.length
        ? 'Un pack issu du registre CLI n’est pas modifiable ici : dupliquez-le.'
        : null,
  run: (d, ctx, p) => {
    const id = p.id ?? nextId(d, 'pck');
    const prev = d.db.pack[id];
    insert(d, 'pack', {
      id,
      orgId: ctx.orgId,
      name: p.name.trim(),
      description: p.description,
      refIds: p.refIds,
      origin: prev?.origin ?? 'local',
      cliId: prev?.cliId,
      enabled: p.enabled,
    });
    emit(d, ctx, {
      action: 'pack.saved',
      summary: `Pack « ${p.name.trim()} » ${p.enabled ? 'activé' : 'désactivé'}`,
      object: { kind: 'pack', id },
    });
    return id;
  },
});

/* ---------------------------------------------------------------- guild */

export const proposeInstructions = command<{ expertId: ID; text: string }, number>({
  name: 'proposeInstructions',
  capability: (_p, s) => (s.session.actor.type === 'agent' ? 'propose' : 'configure_agents'),
  guard: (s, ctx, p) => {
    const e = s.db.expert[p.expertId];
    if (!e) return 'Expertise introuvable.';
    if (ctx.actor.type === 'agent' && ctx.actor.expertId !== p.expertId) return 'Un agent ne peut proposer d’évolution que pour lui-même.';
    if (e.instructions.some((i) => i.status === 'proposed')) return 'Une évolution est déjà en attente de décision.';
    return p.text.trim().length < 20 ? 'Les instructions doivent être explicites (20 caractères au moins).' : null;
  },
  run: (d, ctx, p) => {
    const e = must(d, 'expert', p.expertId, ctx.orgId);
    const number = Math.max(...e.instructions.map((i) => i.number)) + 1;
    const authorId = ctx.actor.type === 'human' ? ctx.actor.userId : `agent:${p.expertId}`;
    e.instructions.push({ number, text: p.text.trim(), status: 'proposed', authorId, at: ctx.now });
    const approval = createApprovalFor(d, ctx, e.id, number, e.approverId);
    emit(d, ctx, {
      action: 'expert.instructions.proposed',
      summary: `Instructions v${number} proposées pour ${e.name}`,
      object: { kind: 'expert', id: e.id, version: number },
      related: [{ kind: 'approval', id: approval }],
    });
    return number;
  },
});

function createApprovalFor(
  d: Parameters<typeof createApproval>[0],
  ctx: Parameters<typeof createApproval>[1],
  expertId: ID,
  version: number,
  approverId: ID,
): ID {
  // Agent-authored proposals are attributed to the expert's human owner for separation checks.
  const c = ctx.actor.type === 'human' ? ctx : { ...ctx, actor: { type: 'human' as const, userId: d.db.expert[expertId].humanOwnerId } };
  return createApproval(d, c, {
    subject: { kind: 'expert', id: expertId, version },
    purpose: 'instruction',
    approverId,
    requireDistinct: true,
  }).id;
}

export const restrictTools = command<{ expertId: ID; tools: string[] }>({
  name: 'restrictTools',
  capability: 'configure_agents',
  guard: (s, _c, p) => {
    const e = s.db.expert[p.expertId];
    if (!e) return 'Expertise introuvable.';
    const extra = p.tools.filter((t) => !e.toolsAvailable.includes(t));
    return extra.length ? `Outil non disponible pour cette expertise : ${extra.join(', ')}.` : null;
  },
  run: (d, ctx, p) => {
    const e = must(d, 'expert', p.expertId, ctx.orgId);
    const removed = e.toolsAllowed.filter((t) => !p.tools.includes(t));
    const added = p.tools.filter((t) => !e.toolsAllowed.includes(t));
    e.toolsAllowed = p.tools;
    emit(d, ctx, {
      action: 'expert.tools',
      summary:
        `Outils de ${e.name} : ${added.length ? `+${added.join(', +')}` : ''}${removed.length ? ` −${removed.join(', −')}` : ''}`.trim(),
      object: { kind: 'expert', id: e.id },
    });
  },
});

export const updateExpert = command<{
  expertId: ID;
  budget?: number;
  active?: boolean;
  memory?: string;
  humanOwnerId?: ID;
  approverId?: ID;
}>({
  name: 'updateExpert',
  capability: 'configure_agents',
  guard: (s, _c, p) => {
    const e = s.db.expert[p.expertId];
    if (!e) return 'Expertise introuvable.';
    const owner = p.humanOwnerId ?? e.humanOwnerId;
    const approver = p.approverId ?? e.approverId;
    return owner === approver
      ? 'Le responsable humain et l’approbateur doivent être deux personnes distinctes.'
      : p.budget !== undefined && p.budget < e.budget.used
        ? `Le budget ne peut pas être inférieur à la consommation (${e.budget.used}).`
        : null;
  },
  run: (d, ctx, p) => {
    const e = must(d, 'expert', p.expertId, ctx.orgId);
    if (p.budget !== undefined) e.budget.units = p.budget;
    if (p.active !== undefined) e.active = p.active;
    if (p.memory) e.memory.push(p.memory);
    if (p.humanOwnerId) e.humanOwnerId = p.humanOwnerId;
    if (p.approverId) e.approverId = p.approverId;
    emit(d, ctx, {
      action: 'expert.updated',
      summary: `${e.name} : ${Object.keys(p)
        .filter((k) => k !== 'expertId')
        .join(', ')} modifié(s)`,
      object: { kind: 'expert', id: e.id },
    });
  },
});
