/**
 * Workspace commands: organisations, onboarding, projects, products, relations, members,
 * settings, integrations, preferences and the explicit demo controls.
 */
import type { Draft } from 'immer';
import { EXPERT_SEEDS } from '@/demo/fixtures/experts';
import { CONTROL_SEEDS, controlFromSeed, SKILL_SEEDS, skillFromSeed } from '@/demo/fixtures/seeds';
import { services } from '@/demo/adapters/services';
import { answersToFacts, EXPERT_LABEL_TO_KEY, suggestReferences } from '../questionnaire';
import { command, DAY, emit, fail, insert, list, must, nextId, requireHuman, type Ctx, clone } from '../engine';
import { blueprintOf, latestPublished } from '../selectors';
import type { RoleId } from '../permissions';
import type { Actor, AppState, Expert, ID, Integration, OnboardingState, Org, Preferences, Product, Relation, RuleVersion } from '../types';

type D = Draft<AppState>;

export const DEFAULT_SETTINGS: Org['settings'] = {
  retentionDays: 365,
  budget: { monthlyUnits: 400, used: 0 },
  watch: { enabled: true, cadence: 'hebdomadaire', topics: ['Export de données', 'CRM', 'Conformité'], cursor: 0 },
  notifications: { approvals: true, controls: true, exceptions: true, watch: true },
  demoModel: 'Modèle de démonstration déterministe (aucun appel externe)',
};

export const INTEGRATIONS: Omit<Integration, 'id' | 'orgId' | 'changedAt'>[] = [
  {
    name: 'Forge de code (type GitHub)',
    category: 'Dépôts',
    status: 'not_configured',
    detail: 'Lecture des dépôts et propositions de diff simulées.',
  },
  { name: 'Suivi de tickets (type Jira)', category: 'Travail', status: 'not_configured', detail: 'Synchronisation des quêtes simulée.' },
  {
    name: 'Messagerie d’équipe (type Slack)',
    category: 'Communication',
    status: 'not_configured',
    detail: 'Notifications simulées, aucun message envoyé.',
  },
  { name: 'Outil de design (type Figma)', category: 'Design', status: 'not_configured', detail: 'Lecture de maquettes simulée.' },
  { name: 'Wiki (type Notion)', category: 'Documentation', status: 'not_configured', detail: 'Publication documentaire simulée.' },
  {
    name: 'Fournisseur de modèles IA',
    category: 'Agents',
    status: 'not_configured',
    detail: 'Les agents utilisent le modèle de démonstration déterministe.',
  },
];

export function seedExperts(d: D, ctx: Ctx, orgId: ID, ownerId: ID, approverId: ID, keys?: string[]) {
  for (const e of EXPERT_SEEDS) {
    const id = `exp-${orgId}-${e.key}`;
    const expert: Expert = {
      id,
      orgId,
      key: e.key,
      name: e.name,
      classTitle: e.classTitle,
      domain: e.domain,
      specialty: e.specialty,
      capabilities: e.capabilities,
      sources: e.sources,
      methods: e.methods,
      skillIds: SKILL_SEEDS.filter((sk) => sk.experts.includes(e.key)).map((sk) => `skl-${sk.key}-${orgId}`),
      toolsAvailable: e.tools,
      toolsAllowed: e.allowed,
      contextAccess: e.context,
      memory: [],
      limits: e.limits,
      budget: { units: e.budget, used: 0 },
      humanOwnerId: ownerId,
      creatorId: ownerId,
      approverId,
      instructions: [{ number: 1, text: e.instructions, status: 'active', authorId: ownerId, at: ctx.now, decidedBy: approverId }],
      boardId: e.boardId,
      active: !keys || keys.includes(e.key),
    };
    insert(d, 'expert', expert);
  }
}

function seedIntegrations(d: D, ctx: Ctx, orgId: ID) {
  INTEGRATIONS.forEach((i, n) => insert(d, 'integration', { ...i, id: `int-${orgId}-${n}`, orgId, changedAt: ctx.now }));
}

const BLANK_USERS = [
  { id: 'u-alex', name: 'Alex Morin', title: 'Fondateur·rice (identité de démonstration)', portrait: 'human-1', role: 'owner' as RoleId },
  {
    id: 'u-sam',
    name: 'Sam Leroy',
    title: 'Responsable sécurité (identité de démonstration)',
    portrait: 'human-2',
    role: 'admin' as RoleId,
  },
  { id: 'u-noa', name: 'Noa Petit', title: 'Lecteur·rice (identité de démonstration)', portrait: 'human-3', role: 'reader' as RoleId },
];

/* ---------------------------------------------------------------- organisations */

export const createBlankOrg = command<{ name: string }, ID>({
  name: 'createBlankOrg',
  global: true,
  guard: (_s, _c, p) => (p.name.trim().length < 2 ? 'Donnez un nom d’au moins deux caractères.' : null),
  run: (d, ctx, p) => {
    const orgId = nextId(d, 'org');
    const c = { ...ctx, orgId };
    BLANK_USERS.forEach((u) => {
      d.users[u.id] ??= { id: u.id, name: u.name, title: u.title, portrait: u.portrait };
    });
    d.orgs[orgId] = {
      id: orgId,
      name: p.name.trim(),
      activity: '',
      kind: 'blank',
      createdAt: ctx.now,
      settings: clone(DEFAULT_SETTINGS),
      onboarding: {
        status: 'draft',
        mode: 'new',
        step: 0,
        answers: { 'org.name': { value: p.name.trim(), unknown: false } },
        updatedAt: ctx.now,
      },
    };
    BLANK_USERS.forEach((u) => insert(d, 'member', { id: nextId(d, 'mbr'), orgId, userId: u.id, role: u.role, since: ctx.now }));
    insert(d, 'blueprint', { id: `bp-${orgId}`, orgId, name: `Blueprint ${p.name.trim()}`, versions: [] });
    seedIntegrations(d, c, orgId);
    d.session = { orgId, actor: { type: 'human', userId: 'u-alex' }, projectId: null };
    emit(
      d,
      { ...c, actor: d.session.actor },
      { action: 'org.created', summary: `Organisation « ${p.name.trim()} » créée`, object: { kind: 'org', id: orgId } },
    );
    return orgId;
  },
});

export const switchOrg = command<{ orgId: ID }>({
  name: 'switchOrg',
  global: true,
  guard: (s, _c, p) => (s.orgs[p.orgId] ? null : 'Organisation introuvable.'),
  run: (d, _c, p) => {
    const member = Object.values(d.db.member).find((m) => m.orgId === p.orgId && (m.role === 'maintainer' || m.role === 'owner'));
    const keep =
      d.session.actor.type === 'human' &&
      Object.values(d.db.member).some((m) => m.orgId === p.orgId && m.userId === (d.session.actor as { userId: ID }).userId);
    d.session = { orgId: p.orgId, actor: keep ? d.session.actor : { type: 'human', userId: member?.userId ?? '' }, projectId: null };
  },
});

export const setActor = command<{ actor: Actor }>({
  name: 'setActor',
  guard: (s, ctx, p) => {
    if (p.actor.type === 'human' && !list(s, 'member', ctx.orgId).some((m) => m.userId === (p.actor as { userId: ID }).userId))
      return 'Cette identité n’est pas membre de l’organisation.';
    if (p.actor.type === 'agent' && s.db.expert[p.actor.expertId]?.orgId !== ctx.orgId) return 'Agent inconnu.';
    return null;
  },
  run: (d, _c, p) => {
    d.session.actor = p.actor;
  },
});

export const setProjectContext = command<{ projectId: ID | null }>({
  name: 'setProjectContext',
  run: (d, ctx, p) => {
    if (p.projectId) must(d, 'project', p.projectId, ctx.orgId);
    d.session.projectId = p.projectId;
  },
});

/* ---------------------------------------------------------------- onboarding */

export const updateOnboarding = command<Partial<Pick<OnboardingState, 'step' | 'mode'>> & { answers?: OnboardingState['answers'] }>({
  name: 'updateOnboarding',
  capability: 'configure_org',
  guard: (s, ctx) =>
    s.orgs[ctx.orgId]?.onboarding.status === 'done'
      ? 'Le questionnaire initial est déjà conclu ; modifiez le Blueprint pour faire évoluer le profil.'
      : null,
  run: (d, ctx, p) => {
    const o = d.orgs[ctx.orgId].onboarding;
    if (p.step !== undefined) o.step = p.step;
    if (p.mode) o.mode = p.mode;
    if (p.answers) Object.assign(o.answers, p.answers);
    o.updatedAt = ctx.now;
    if (p.answers?.['org.name']?.value) d.orgs[ctx.orgId].name = p.answers['org.name'].value;
    if (p.answers?.['org.activity']?.value) d.orgs[ctx.orgId].activity = p.answers['org.activity'].value;
  },
});

export const analyzeRepository = command<{ address: string }, string>({
  name: 'analyzeRepository',
  capability: 'configure_org',
  run: (d, ctx, p) => {
    const res = services.repository.analyze(p.address);
    d.orgs[ctx.orgId].onboarding.analysis = {
      scenario: res.scenario,
      target: p.address,
      at: ctx.now,
      observations: res.observations.map((o, i) => ({ ...o, id: `obs-${i + 1}` })),
    };
    emit(d, ctx, {
      action: 'repo.analyzed',
      summary: res.scenario ? `Analyse simulée du dépôt ${p.address}` : `Aucune analyse : ${p.address} hors scénario`,
      object: { kind: 'org', id: ctx.orgId },
      provenance: 'simulation',
    });
    return res.message;
  },
});

export const editObservation = command<{ id: string; corrected?: string; dismissed?: boolean }>({
  name: 'editObservation',
  capability: 'configure_org',
  run: (d, ctx, p) => {
    const ob = d.orgs[ctx.orgId].onboarding.analysis?.observations.find((o) => o.id === p.id) ?? fail('Observation introuvable.');
    if (p.corrected !== undefined) ob.corrected = p.corrected.trim() || undefined;
    if (p.dismissed !== undefined) ob.dismissed = p.dismissed;
  },
});

/** Publishes the first Blueprint version from the questionnaire (brief §5.1). */
export const publishFirstBlueprint = command<{ acceptedRefIds: string[] }, number>({
  name: 'publishFirstBlueprint',
  capability: 'publish',
  humanOnly: true,
  guard: (s, ctx) => {
    const o = s.orgs[ctx.orgId]?.onboarding;
    if (!o) return 'Organisation introuvable.';
    if (o.status === 'done') return 'Le premier Blueprint est déjà publié.';
    const missing = ['org.name', 'org.activity', 'product.name'].filter((k) => !o.answers[k]?.value?.trim());
    return missing.length ? 'Renseignez le nom, l’activité et le produit principal avant de publier.' : null;
  },
  run: (d, ctx, p) => {
    const userId = requireHuman(ctx);
    const org = d.orgs[ctx.orgId];
    const o = org.onboarding;
    const facts = answersToFacts(o as OnboardingState);
    const suggestions = suggestReferences(facts).filter((sug) => p.acceptedRefIds.includes(sug.refId));
    const productId = nextId(d, 'prd');
    const product: Product = {
      id: productId,
      orgId: org.id,
      name: o.answers['product.name'].value,
      description: o.answers['users']?.value ? `Pour ${o.answers['users'].value}` : 'Produit principal',
      ownerId: userId,
      color: '#69C4D4',
      stack: (o.answers['stack']?.value ?? '').split(', ').filter(Boolean),
      repos: o.analysis?.scenario
        ? [
            {
              id: nextId(d, 'repo'),
              name: o.analysis.target.replace('demo://depots/', ''),
              language: o.analysis.observations[0]?.value ?? '',
              modules: [],
            },
          ]
        : [],
      territory: 0,
    };
    insert(d, 'product', product);
    const ruleRefs = suggestions
      .filter((sug) => sug.rule)
      .map((sug) => {
        const rule = sug.rule!;
        const id = nextId(d, 'rul');
        const version: RuleVersion = {
          number: 1,
          status: 'published',
          title: rule.title,
          statement: rule.statement,
          referenceIds: [sug.refId],
          scope: { level: 'org' },
          ownerId: userId,
          criticality: rule.criticality,
          blocking: rule.blocking,
          derogable: rule.criticality !== 'critique',
          policy: rule.criticality === 'critique' ? 'imposed' : 'additive',
          expectedControlIds: [],
          authorId: userId,
          justification: sug.reason,
          createdAt: ctx.now,
        };
        insert(d, 'rule', { id, orgId: org.id, code: rule.code, versions: [version] });
        return { ruleId: id, version: 1 };
      });
    const ruleIdByCode = Object.fromEntries(
      Object.values(d.db.rule)
        .filter((r) => r.orgId === org.id)
        .map((r) => [r.code, r.id]),
    );
    SKILL_SEEDS.forEach((sk) => insert(d, 'skill', skillFromSeed(sk, org.id, ctx.now)));
    CONTROL_SEEDS.forEach((c) => insert(d, 'control', controlFromSeed(c, `${c.key}-${org.id}`, org.id, ruleIdByCode)));
    const bp = must(d, 'blueprint', blueprintOf(d as AppState, org.id)?.id);
    bp.versions.push({
      number: 1,
      status: 'published',
      context: facts,
      rules: ruleRefs,
      exclusions: [],
      authorId: userId,
      justification: 'Profil initial issu du questionnaire.',
      createdAt: ctx.now,
      publishedAt: ctx.now,
      reviewerId: userId,
    });
    const projectId = nextId(d, 'prj');
    insert(d, 'project', {
      id: projectId,
      orgId: org.id,
      productId,
      name: `${product.name} — socle`,
      summary: 'Projet créé avec le premier Blueprint.',
      ownerId: userId,
      status: 'active',
      blueprintVersion: 1,
      linkedProductIds: [],
      environments: (o.answers['environments']?.value ?? '').split(', ').filter(Boolean),
      storage: [o.answers['storage']?.value ?? ''].filter(Boolean),
      dataSensitivity: o.answers['data.personal']?.value ?? 'Inconnue',
      createdAt: ctx.now,
    });
    for (const sug of suggestReferences(facts)) {
      const accepted = p.acceptedRefIds.includes(sug.refId);
      insert(d, 'applicability', {
        id: nextId(d, 'app'),
        orgId: org.id,
        projectId,
        refId: sug.refId,
        status: accepted ? sug.status : 'to_clarify',
        reason: sug.reason,
        authorId: userId,
        validated: accepted,
        suggestedBy: 'Questionnaire initial',
        at: ctx.now,
      });
    }
    const admin = Object.values(d.db.member).find((m) => m.orgId === org.id && m.role === 'admin')?.userId ?? userId;
    const keys = (o.answers['experts']?.value ?? '')
      .split(', ')
      .map((l) => EXPERT_LABEL_TO_KEY[l])
      .filter(Boolean);
    seedExperts(d, ctx, org.id, userId, admin, keys.length ? keys : undefined);
    o.status = 'done';
    o.updatedAt = ctx.now;
    d.session.projectId = projectId;
    emit(d, ctx, {
      action: 'blueprint.published',
      summary: `Premier Blueprint publié (v1) : ${facts.filter((f) => f.provenance === 'unknown').length} inconnue(s) à traiter, ${ruleRefs.length} règle(s)`,
      object: { kind: 'blueprint', id: bp.id, version: 1 },
      related: [{ kind: 'project', id: projectId }],
    });
    return 1;
  },
});

/* ---------------------------------------------------------------- projects and products */

export interface ProjectInput {
  name: string;
  summary: string;
  productId: ID;
  ownerId?: ID;
  environments: string[];
  storage: string[];
  dataSensitivity: string;
  linkedProductIds: ID[];
}

function projectProblems(s: AppState, ctx: Ctx, p: ProjectInput): string | null {
  if (p.name.trim().length < 3) return 'Le nom doit compter au moins trois caractères.';
  if (!p.ownerId) return 'Un projet actif doit avoir un responsable humain.';
  if (!list(s, 'member', ctx.orgId).some((m) => m.userId === p.ownerId)) return 'Le responsable doit être membre de l’organisation.';
  if (!s.db.product[p.productId] || s.db.product[p.productId].orgId !== ctx.orgId)
    return 'Choisissez un produit principal de cette organisation.';
  return null;
}

export const createProject = command<ProjectInput, ID>({
  name: 'createProject',
  capability: 'edit',
  guard: (s, ctx, p) => projectProblems(s, ctx, p) ?? (latestPublished(s, ctx.orgId) ? null : 'Publiez d’abord un Blueprint.'),
  run: (d, ctx, p) => {
    const id = nextId(d, 'prj');
    const bpv = latestPublished(d as AppState, ctx.orgId)!.number;
    insert(d, 'project', {
      id,
      orgId: ctx.orgId,
      productId: p.productId,
      name: p.name.trim(),
      summary: p.summary.trim(),
      ownerId: p.ownerId,
      status: 'active',
      blueprintVersion: bpv,
      linkedProductIds: p.linkedProductIds,
      environments: p.environments,
      storage: p.storage,
      dataSensitivity: p.dataSensitivity,
      createdAt: ctx.now,
    });
    emit(d, ctx, {
      action: 'project.created',
      summary: `Projet « ${p.name.trim()} » créé (Blueprint v${bpv})`,
      object: { kind: 'project', id },
      projectId: id,
    });
    return id;
  },
});

export const updateProject = command<ProjectInput & { id: ID }>({
  name: 'updateProject',
  capability: 'edit',
  project: (p) => p.id,
  guard: (s, ctx, p) => projectProblems(s, ctx, p),
  run: (d, ctx, p) => {
    const pr = must(d, 'project', p.id, ctx.orgId);
    Object.assign(pr, {
      name: p.name.trim(),
      summary: p.summary.trim(),
      productId: p.productId,
      ownerId: p.ownerId,
      environments: p.environments,
      storage: p.storage,
      dataSensitivity: p.dataSensitivity,
      linkedProductIds: p.linkedProductIds,
    });
    emit(d, ctx, {
      action: 'project.updated',
      summary: `Projet « ${pr.name} » modifié`,
      object: { kind: 'project', id: pr.id },
      projectId: pr.id,
    });
  },
});

export const archiveProject = command<{ id: ID; reason: string }>({
  name: 'archiveProject',
  capability: 'archive',
  project: (p) => p.id,
  guard: (s, _c, p) =>
    s.db.project[p.id]?.status === 'archived' ? 'Déjà archivé.' : !p.reason.trim() ? 'Indiquez le motif de l’archivage.' : null,
  run: (d, ctx, p) => {
    const pr = must(d, 'project', p.id, ctx.orgId);
    pr.status = 'archived';
    pr.statusReason = p.reason;
    emit(d, ctx, {
      action: 'project.archived',
      summary: `Projet « ${pr.name} » archivé`,
      object: { kind: 'project', id: pr.id },
      projectId: pr.id,
      justification: p.reason,
    });
  },
});

export const restoreProject = command<{ id: ID }>({
  name: 'restoreProject',
  capability: 'archive',
  project: (p) => p.id,
  guard: (s, ctx, p) => {
    const pr = s.db.project[p.id];
    if (pr?.status !== 'archived') return 'Ce projet n’est pas archivé.';
    return pr.ownerId && list(s, 'member', ctx.orgId).some((m) => m.userId === pr.ownerId)
      ? null
      : 'Désignez d’abord un responsable membre de l’organisation.';
  },
  run: (d, ctx, p) => {
    const pr = must(d, 'project', p.id, ctx.orgId);
    pr.status = 'active';
    pr.statusReason = undefined;
    emit(d, ctx, {
      action: 'project.restored',
      summary: `Projet « ${pr.name} » restauré`,
      object: { kind: 'project', id: pr.id },
      projectId: pr.id,
    });
  },
});

export const toggleFavoriteProject = command<{ id: ID }>({
  name: 'toggleFavoriteProject',
  run: (d, _c, p) => {
    const f = d.prefs.favoriteProjects;
    d.prefs.favoriteProjects = f.includes(p.id) ? f.filter((x) => x !== p.id) : [...f, p.id];
  },
});

export const saveProduct = command<
  { id?: ID; name: string; description: string; ownerId: ID; stack: string[]; repos: Product['repos']; color: string },
  ID
>({
  name: 'saveProduct',
  capability: 'edit',
  guard: (_s, _c, p) => (p.name.trim().length < 2 ? 'Nom de produit trop court.' : !p.ownerId ? 'Un produit a un responsable.' : null),
  run: (d, ctx, p) => {
    if (p.id) {
      const pr = must(d, 'product', p.id, ctx.orgId);
      Object.assign(pr, {
        name: p.name.trim(),
        description: p.description,
        ownerId: p.ownerId,
        stack: p.stack,
        repos: p.repos,
        color: p.color,
      });
      emit(d, ctx, { action: 'product.updated', summary: `Produit « ${pr.name} » modifié`, object: { kind: 'product', id: pr.id } });
      return pr.id;
    }
    const id = nextId(d, 'prd');
    insert(d, 'product', {
      id,
      orgId: ctx.orgId,
      name: p.name.trim(),
      description: p.description,
      ownerId: p.ownerId,
      color: p.color,
      stack: p.stack,
      repos: p.repos,
      territory: list(d as AppState, 'product', ctx.orgId).length,
    });
    emit(d, ctx, { action: 'product.created', summary: `Produit « ${p.name.trim()} » créé`, object: { kind: 'product', id } });
    return id;
  },
});

export const addRelation = command<Omit<Relation, 'id' | 'orgId'>, ID>({
  name: 'addRelation',
  capability: 'edit',
  guard: (s, ctx, p) =>
    p.fromProductId === p.toProductId
      ? 'Une relation relie deux produits distincts.'
      : list(s, 'relation', ctx.orgId).some(
            (r) => r.fromProductId === p.fromProductId && r.toProductId === p.toProductId && r.kind === p.kind,
          )
        ? 'Cette relation existe déjà.'
        : null,
  run: (d, ctx, p) => {
    const id = nextId(d, 'rel');
    insert(d, 'relation', { id, orgId: ctx.orgId, ...p });
    emit(d, ctx, {
      action: 'relation.created',
      summary: `Relation « ${d.db.product[p.fromProductId]?.name} ${p.kind} ${d.db.product[p.toProductId]?.name} » ajoutée`,
      object: { kind: 'relation', id },
      related: [
        { kind: 'product', id: p.fromProductId },
        { kind: 'product', id: p.toProductId },
      ],
    });
    return id;
  },
});

export const removeRelation = command<{ id: ID; reason: string }>({
  name: 'removeRelation',
  capability: 'edit',
  guard: (_s, _c, p) => (p.reason.trim() ? null : 'Indiquez le motif.'),
  run: (d, ctx, p) => {
    const r = must(d, 'relation', p.id, ctx.orgId);
    delete d.db.relation[p.id];
    emit(d, ctx, {
      action: 'relation.removed',
      summary: `Relation entre ${d.db.product[r.fromProductId]?.name} et ${d.db.product[r.toProductId]?.name} retirée`,
      object: { kind: 'relation', id: p.id },
      justification: p.reason,
    });
  },
});

/* ---------------------------------------------------------------- members and settings */

export const addMember = command<{ name: string; title: string; role: RoleId; projectId?: ID }, ID>({
  name: 'addMember',
  capability: 'manage_members',
  guard: (_s, _c, p) => (p.name.trim().length < 3 ? 'Nom trop court.' : null),
  run: (d, ctx, p) => {
    const userId = nextId(d, 'usr');
    d.users[userId] = {
      id: userId,
      name: p.name.trim(),
      title: `${p.title.trim() || 'Membre'} (identité fictive)`,
      portrait: `human-${(d.seq % 6) + 1}`,
    };
    const id = nextId(d, 'mbr');
    insert(d, 'member', { id, orgId: ctx.orgId, userId, role: p.role, projectId: p.projectId, since: ctx.now });
    emit(d, ctx, {
      action: 'member.added',
      summary: `${p.name.trim()} ajouté·e comme ${p.role} (aucune invitation envoyée)`,
      object: { kind: 'member', id },
    });
    return userId;
  },
});

export const changeRole = command<{ memberId: ID; role: RoleId; projectId?: ID | null }>({
  name: 'changeRole',
  capability: 'manage_members',
  guard: (s, ctx, p) => {
    const m = s.db.member[p.memberId];
    if (!m || m.orgId !== ctx.orgId) return 'Membre introuvable.';
    const owners = list(s, 'member', ctx.orgId).filter((x) => x.role === 'owner');
    if (m.role === 'owner' && p.role !== 'owner' && owners.length === 1) return 'L’organisation doit garder au moins un propriétaire.';
    return null;
  },
  run: (d, ctx, p) => {
    const m = must(d, 'member', p.memberId, ctx.orgId);
    const before = m.role;
    m.role = p.role;
    if (p.projectId !== undefined) m.projectId = p.projectId ?? undefined;
    emit(d, ctx, {
      action: 'member.role',
      summary: `Rôle de ${d.users[m.userId]?.name} : ${before} → ${p.role}`,
      object: { kind: 'member', id: m.id },
    });
  },
});

export const removeMember = command<{ memberId: ID; reason: string }>({
  name: 'removeMember',
  capability: 'manage_members',
  guard: (s, ctx, p) => {
    const m = s.db.member[p.memberId];
    if (!m) return 'Membre introuvable.';
    if (list(s, 'project', ctx.orgId).some((x) => x.status === 'active' && x.ownerId === m.userId))
      return 'Ce membre est responsable d’un projet actif : désignez d’abord un autre responsable.';
    if (m.role === 'owner' && list(s, 'member', ctx.orgId).filter((x) => x.role === 'owner').length === 1) return 'Dernier propriétaire.';
    return p.reason.trim() ? null : 'Indiquez le motif.';
  },
  run: (d, ctx, p) => {
    const m = must(d, 'member', p.memberId, ctx.orgId);
    delete d.db.member[p.memberId];
    emit(d, ctx, {
      action: 'member.removed',
      summary: `${d.users[m.userId]?.name} retiré·e de l'organisation`,
      object: { kind: 'member', id: p.memberId },
      justification: p.reason,
    });
  },
});

export const updateSettings = command<{ patch: Partial<Omit<Org['settings'], 'budget'>> & { monthlyUnits?: number } }>({
  name: 'updateSettings',
  capability: 'configure_org',
  guard: (_s, _c, p) =>
    p.patch.retentionDays !== undefined && (p.patch.retentionDays < 30 || p.patch.retentionDays > 3650)
      ? 'La conservation doit être comprise entre 30 et 3650 jours.'
      : p.patch.monthlyUnits !== undefined && p.patch.monthlyUnits < 0
        ? 'Budget invalide.'
        : null,
  run: (d, ctx, p) => {
    const st = d.orgs[ctx.orgId].settings;
    const { monthlyUnits, ...rest } = p.patch;
    Object.assign(st, rest);
    if (monthlyUnits !== undefined) st.budget.monthlyUnits = monthlyUnits;
    emit(d, ctx, {
      action: 'settings.updated',
      summary: `Paramètres modifiés : ${Object.keys(p.patch).join(', ')}`,
      object: { kind: 'org', id: ctx.orgId },
    });
  },
});

/* ---------------------------------------------------------------- integrations (demo) */

export const setIntegration = command<{
  id: ID;
  action: 'connect' | 'disconnect' | 'retry' | 'simulate-error' | 'simulate-expiry';
  account?: string;
}>({
  name: 'setIntegration',
  capability: 'configure_org',
  guard: (s, _c, p) => {
    const i = s.db.integration[p.id];
    if (!i) return 'Intégration introuvable.';
    if (p.action === 'connect' && !['not_configured', 'disconnected'].includes(i.status)) return 'Déjà configurée.';
    if (p.action === 'retry' && !['error', 'expired'].includes(i.status)) return 'Rien à réessayer.';
    if (p.action === 'connect' && !(p.account ?? '').trim()) return 'Renseignez un identifiant fictif (aucun compte réel n’est contacté).';
    return null;
  },
  run: (d, ctx, p) => {
    const i = must(d, 'integration', p.id, ctx.orgId);
    const next = {
      connect: 'connecting',
      retry: 'connecting',
      disconnect: 'disconnected',
      'simulate-error': 'error',
      'simulate-expiry': 'expired',
    } as const;
    i.status = next[p.action];
    i.changedAt = ctx.now;
    if (p.account) i.account = p.account.trim();
    emit(d, ctx, {
      action: `integration.${p.action}`,
      summary: `${i.name} : ${p.action === 'connect' ? 'connexion de démonstration lancée' : p.action}`,
      object: { kind: 'integration', id: i.id },
      provenance: 'démo',
    });
  },
});

/* ---------------------------------------------------------------- preferences, drafts and demo */

export const setPreference = command<Partial<Preferences>>({
  name: 'setPreference',
  global: true,
  run: (d, _c, p) => {
    Object.assign(d.prefs, p);
  },
});

export const markNotificationsRead = command<{ ids: string[] }>({
  name: 'markNotificationsRead',
  run: (d, _c, p) => {
    d.prefs.readNotifications = [...new Set([...d.prefs.readNotifications, ...p.ids])].slice(-500);
  },
});

export const saveDraft = command<{ key: string; value: unknown }>({
  name: 'saveDraft',
  global: true,
  run: (d, _c, p) => {
    if (p.value === undefined) delete d.drafts[p.key];
    else d.drafts[p.key] = p.value as never;
  },
});

export const demoAdvanceTime = command<{ days: number }>({
  name: 'demoAdvanceTime',
  global: true,
  run: (d, ctx, p) => {
    d.demo.timeOffsetMs += p.days * DAY;
    if (ctx.orgId)
      emit(
        d,
        { ...ctx, actor: { type: 'system' } },
        {
          action: 'demo.time',
          summary: `Démonstration : horloge avancée de ${p.days} jour(s)`,
          object: { kind: 'org', id: ctx.orgId },
          provenance: 'démo',
        },
      );
  },
});

export const demoInjectFailure = command<{ kind: 'tool-error' | 'inconclusive' | null }>({
  name: 'demoInjectFailure',
  run: (d, ctx, p) => {
    d.demo.nextFailure = p.kind;
    emit(
      d,
      { ...ctx, actor: { type: 'system' } },
      {
        action: 'demo.failure',
        summary: p.kind
          ? `Démonstration : la prochaine exécution produira « ${p.kind === 'tool-error' ? 'erreur d’outil' : 'résultat non concluant'} »`
          : 'Démonstration : injection d’échec retirée',
        object: { kind: 'org', id: ctx.orgId },
        provenance: 'démo',
      },
    );
  },
});

export const demoExpire = command<{ kind: 'exception' | 'share' | 'approval'; id: ID }>({
  name: 'demoExpire',
  run: (d, ctx, p) => {
    const e = must(d, p.kind, p.id, ctx.orgId) as { expiresAt?: number };
    e.expiresAt = ctx.now - 1000;
    emit(
      d,
      { ...ctx, actor: { type: 'system' } },
      {
        action: 'demo.expire',
        summary: `Démonstration : expiration simulée (${p.kind} ${p.id})`,
        object: { kind: p.kind, id: p.id },
        provenance: 'démo',
      },
    );
  },
});
