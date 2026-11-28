/** Sensitive business rules (brief §12.1), each tested independently of the screens. */
import { describe, expect, it } from 'vitest';
import catalogue from '@/demo/fixtures/catalogue.json';
import { previewCatalogueImport, type Reference } from '@/demo/adapters/catalogue';
import { COUNCIL_SCENARIOS } from '@/demo/adapters/simulation/council';
import { EXPERT_SEEDS } from '@/demo/fixtures/experts';
import { backupOf, loadWorkspace, previewBackup, saveWorkspace, type KeyValueStore } from '@/demo/adapters/storage';
import { check } from '@/demo/domain/engine';
import { cmd } from '@/demo/domain/commands';
import { emptyState } from '@/demo/domain/state';
import { allReferences, closureBlocked, closureReport, effectiveExceptionStatus, resolveRules, resultFreshness, shareStatus } from '@/demo/domain/selectors';
import { agent, human, nova, ok, refused, run, ticks } from './helpers';

const YANIS = human('u-yanis');
const INES = human('u-ines');
const LEA = human('u-lea');

describe('organisation et Blueprint', () => {
  it('une nouvelle organisation atteint un premier Blueprint publié, avec ses inconnues', () => {
    let s = emptyState();
    s = ok(s, cmd.createBlankOrg, { name: 'Atelier Orion' });
    const unknown = { value: '', unknown: true };
    s = ok(s, cmd.updateOnboarding, { mode: 'existing', answers: { 'org.activity': { value: 'Éditeur SaaS B2B', unknown: false }, 'product.name': { value: 'Orion Desk', unknown: false }, 'data.personal': unknown, tenancy: { value: 'Oui, multi-clients', unknown: false } } });
    let message: string;
    [s, message] = run(s, cmd.analyzeRepository, { address: 'https://exemple.test/depot-inconnu' });
    expect(message).toMatch(/Aucune analyse/);
    expect(s.orgs[s.session.orgId!].onboarding.analysis?.observations).toHaveLength(0);
    s = ok(s, cmd.analyzeRepository, { address: 'demo://depots/crm-api' });
    s = ok(s, cmd.editObservation, { id: 'obs-2', corrected: 'fastify 4' });
    s = ok(s, cmd.publishFirstBlueprint, { acceptedRefIds: ['owasp-application-security-verification-standard-5-0-0', 'code-review'] });
    const bp = Object.values(s.db.blueprint).find((b) => b.orgId === s.session.orgId)!;
    expect(bp.versions[0].status).toBe('published');
    const facts = bp.versions[0].context;
    expect(facts.find((f) => f.key === 'data.personal')?.provenance).toBe('unknown');
    expect(facts.find((f) => f.label === 'Framework HTTP')?.provenance).toBe('declared');
    expect(facts.filter((f) => f.provenance === 'inferred').length).toBeGreaterThan(0);
    expect(Object.values(s.db.project).filter((p) => p.orgId === s.session.orgId)).toHaveLength(1);
    expect(refused(s, cmd.publishFirstBlueprint, { acceptedRefIds: [] })).toMatch(/déjà publié/);
  });

  it('changer d’organisation ne montre pas les données de la précédente (RG-01)', () => {
    let s = nova();
    s = ok(s, cmd.createBlankOrg, { name: 'Atelier Orion' });
    expect(refused(s, cmd.transition, { kind: 'quest', id: 'qst-portal', action: 'cancel', reason: 'test' })).toMatch(/autre organisation|Objet introuvable|n’appartient/);
  });

  it('une version publiée n’est jamais modifiée en place (RG-04)', () => {
    const s = nova();
    expect(refused(s, cmd.setFact, { version: 2, key: 'export.retention', value: '7 jours' })).toMatch(/immuable/);
    expect(refused(s, cmd.editRule, { version: 1, ruleId: 'rul-iso', patch: { title: 'Modifié' } })).toMatch(/immuable/);
  });

  it('l’héritage bloque les adaptations interdites et expose les conflits (RG-05)', () => {
    const s = nova();
    const base = { statement: 'Formulation vérifiable de la règle adaptée.', referenceIds: [], ownerId: 'u-yanis', criticality: 'moyenne' as const, blocking: false, derogable: true, policy: 'additive' as const, expectedControlIds: [], justification: 'test' };
    expect(refused(s, cmd.addRule, { version: 3, adapts: 'rul-iso', rule: { ...base, code: 'SEC-ISO-01B', title: 'Isolation assouplie', scope: { level: 'product', productId: 'prd-atlas' } } })).toMatch(/imposée/);
    expect(refused(s, cmd.addRule, { version: 3, adapts: 'rul-perf', rule: { ...base, code: 'PERF-01B', title: 'Budget assoupli', scope: { level: 'repo', repoId: 'repo-atlas-api' }, policy: 'adjustable', parameter: { name: 'p95', unit: 'ms', value: 1500, min: 200, max: 2000 } } })).toMatch(/hors des bornes/);
    const s2 = ok(s, cmd.addRule, { version: 3, adapts: 'rul-perf', rule: { ...base, code: 'PERF-01W', title: 'Budget du module web', scope: { level: 'repo', repoId: 'repo-atlas-web' }, policy: 'adjustable', parameter: { name: 'p95', unit: 'ms', value: 700, min: 200, max: 1000 } } });
    const v3 = s2.db.blueprint['bp-nova'].versions.find((v) => v.number === 3)!;
    const { conflicts } = resolveRules(s2, v3);
    expect(conflicts.map((c) => c.kind)).toEqual(['competing']);
  });
});

describe('identités, rôles et approbations', () => {
  it('un lecteur ne peut modifier une règle, par aucun chemin (RG-12)', () => {
    const s = nova();
    const reason = refused(s, cmd.editRule, { version: 3, ruleId: 'rul-iso', patch: { title: 'Nouveau titre' } }, LEA);
    expect(reason).toMatch(/Lecteur/);
    expect(refused(s, cmd.startBlueprintDraft, { justification: 'Je veux modifier' }, LEA)).toBeTruthy();
    expect(check({ ...s, session: { ...s.session, actor: LEA } }, cmd.setFact, { version: 3, key: 'x', value: 'y' }).ok).toBe(false);
  });

  it('un agent ne peut ni approuver, ni élargir ses outils, ni valider sa propre évolution (RG-13, RG-14)', () => {
    const s = nova();
    expect(refused(s, cmd.transition, { kind: 'approval', id: 'apr-instr', action: 'approve' }, agent('product'))).toMatch(/humain/);
    expect(refused(s, cmd.restrictTools, { expertId: 'exp-org-nova-engineering', tools: ['Écriture dans le dépôt'] }, agent('engineering'))).toMatch(/agent IA/);
    const s2 = ok(nova(), cmd.proposeInstructions, { expertId: 'exp-org-nova-security', text: 'Je souhaite aussi pouvoir approuver les exceptions de sécurité.' }, agent('security'));
    const appr = Object.values(s2.db.approval).find((a) => a.subject.id === 'exp-org-nova-security')!;
    expect(refused(s2, cmd.transition, { kind: 'approval', id: appr.id, action: 'approve' }, agent('security'))).toMatch(/humain/);
  });

  it('un auteur ne peut s’auto-approuver, même après un changement de rôle (RG-16)', () => {
    const THEO = human('u-theo');
    let s = nova();
    let approvalId: string;
    s = ok(s, cmd.transition, { kind: 'deliverable', id: 'dlv-billing-code', action: 'submit' }, THEO);
    approvalId = Object.values(s.db.approval).find((a) => a.subject.id === 'dlv-billing-code')!.id;
    expect(refused(s, cmd.transition, { kind: 'approval', id: approvalId, action: 'approve' }, THEO)).toMatch(/Contributeur/);
    s = ok(s, cmd.changeRole, { memberId: 'mbr-nova-3', role: 'admin' }, INES);
    expect(refused(s, cmd.transition, { kind: 'approval', id: approvalId, action: 'approve' }, THEO)).toMatch(/Séparation/);
    s = ok(s, cmd.transition, { kind: 'approval', id: approvalId, action: 'approve' }, YANIS);
    expect(s.db.deliverable['dlv-billing-code'].status).toBe('approved');
  });

  it('une approbation sur une ancienne version ne débloque pas la nouvelle (RG-15)', () => {
    let s = nova();
    s = ok(s, cmd.editDeliverable, { id: 'dlv-ds-tokens', content: { kind: 'markdown', body: 'nouveau' }, note: 'Refonte' }, human('u-theo'));
    const res = s.db.result['res-ds1'];
    expect(resultFreshness(s, res).state).toBe('stale');
    expect(closureReport(s, 'qst-ds').find((i) => i.key.startsWith('control:'))?.status).toBe('missing');
  });
});

describe('conseil, décisions et quêtes', () => {
  it('l’arbitrage est bloqué tant qu’une inconnue requise n’est pas résolue (RG-03)', () => {
    let s = nova();
    s = ticks(ok(s, cmd.transition, { kind: 'council', id: 'cns-export', action: 'launch' }), 6);
    s = ok(s, cmd.transition, { kind: 'council', id: 'cns-export', action: 'arbitrate' });
    let id: string;
    [s, id] = run(s, cmd.proposeDecision, { councilId: 'cns-export', optionId: 'opt-a', justification: 'Livrer vite une première valeur.', ownerId: 'u-yanis' });
    s = ok(s, cmd.transition, { kind: 'decision', id, action: 'submit' });
    expect(refused(s, cmd.transition, { kind: 'decision', id, action: 'approve' }, INES)).toMatch(/inconnue requise/);
  });

  it('une décision convertie deux fois par accident ne crée pas de doublon (RG-20)', () => {
    let s = nova();
    let ids: string[];
    const count = Object.keys(s.db.quest).length;
    expect(refused(s, cmd.convertDecision, { decisionId: 'dec-audit' })).toMatch(/Déjà convertie/);
    expect(Object.keys(s.db.quest).length).toBe(count);
    [s, ids] = run(s, cmd.convertDecision, { decisionId: 'dec-audit', confirmExtra: true });
    expect(ids).toHaveLength(1);
  });

  it('une dépendance cyclique entre tâches est refusée (RG-23)', () => {
    const s = nova();
    expect(refused(s, cmd.setDependency, { taskId: 'tsk-r1', dependsOn: 'tsk-r3', add: true })).toMatch(/cycle/);
    expect(refused(s, cmd.setDependency, { taskId: 'tsk-r1', dependsOn: 'tsk-r1', add: true })).toMatch(/elle-même/);
    expect(refused(s, cmd.transition, { kind: 'task', id: 'tsk-r2', action: 'start' })).toMatch(/Dépend de/);
  });

  it('une quête avec un contrôle bloquant échoué ne peut être clôturée (RG-25)', () => {
    let s = nova();
    expect(s.db.run['run-b1'].status).toBe('error');
    s = ok(s, cmd.retryRun, { runId: 'run-b1' }, human('u-theo'));
    s = ticks(s, 5);
    const res = Object.values(s.db.result).find((r) => r.controlId === 'ctl-deps')!;
    expect(res.outcome).toBe('failed');
    expect(closureBlocked(closureReport(s, 'qst-billing-exports')).some((i) => i.key.startsWith('control:ctl-deps'))).toBe(true);
  });

  it('une exception valide lève la garde d’une exigence dérogeable sans transformer l’échec en réussite (RG-25)', () => {
    let s = nova();
    const item = closureReport(s, 'qst-portal').find((i) => i.key.startsWith('control:ctl-a11y'))!;
    expect(item.status).toBe('waived');
    expect(s.db.result['res-p1'].outcome).toBe('failed');
    s = ok(s, cmd.transition, { kind: 'approval', id: 'apr-close-portal', action: 'approve' }, INES);
    s = ok(s, cmd.transition, { kind: 'quest', id: 'qst-portal', action: 'close' }, human('u-camille'));
    expect(s.db.quest['qst-portal'].status).toBe('done');
    expect(s.db.result['res-p1'].outcome).toBe('failed');
  });

  it('une exception expirée ne reste pas active et remet les actions en examen (RG-33)', () => {
    let s = nova();
    s = ok(s, cmd.demoAdvanceTime, { days: 4 });
    expect(effectiveExceptionStatus(s, s.db.exception['exc-portal'])).toBe('expired');
    s = ticks(s, 1);
    expect(s.db.exception['exc-portal'].status).toBe('expired');
    expect(s.db.finding['cst-portal'].status).toBe('open');
    expect(Object.values(s.db.review).some((r) => r.subject.id === 'qst-portal')).toBe(true);
    s = ok(s, cmd.transition, { kind: 'approval', id: 'apr-close-portal', action: 'approve' }, INES);
    expect(refused(s, cmd.transition, { kind: 'quest', id: 'qst-portal', action: 'close' }, human('u-camille'))).toMatch(/CTL-A11Y/);
  });

  it('une exception sur une règle non dérogeable reste impossible et une demande incomplète reste en brouillon (RG-31, RG-32)', () => {
    let s = nova();
    expect(refused(s, cmd.transition, { kind: 'exception', id: 'exc-billing-draft', action: 'request' }, human('u-theo'))).toMatch(/incomplète/);
    let id: string;
    [s, id] = run(s, cmd.saveException, { projectId: 'prj-export', ruleId: 'rul-iso', scope: 'Export', reason: 'Délai', riskAccepted: 'Fuite', compensatingMeasures: 'Aucune', ownerId: 'u-yanis', approverId: 'u-ines', expiresAt: Date.now() + 86_400_000 * 10 });
    expect(refused(s, cmd.transition, { kind: 'exception', id, action: 'request' })).toMatch(/non dérogeable/);
  });
});

describe('exécutions, preuves et versions', () => {
  it('une erreur technique n’apparaît jamais comme une réussite (RG-27)', () => {
    let s = nova();
    s = ok(s, cmd.demoInjectFailure, { kind: 'tool-error' });
    let runId: string;
    [s, runId] = run(s, cmd.launchControl, { controlId: 'ctl-isolation', deliverableId: 'dlv-audit-code' });
    s = ticks(s, 6);
    expect(s.db.run[runId].status).toBe('error');
    expect(s.db.run[runId].resultId).toBeUndefined();
    expect(Object.values(s.db.result).filter((r) => r.runId === runId)).toHaveLength(0);
  });

  it('annuler une exécution empêche sa finalisation tardive ; la relance crée une tentative liée (RG-30)', () => {
    let s = nova();
    let runId: string;
    [s, runId] = run(s, cmd.launchControl, { controlId: 'ctl-isolation', deliverableId: 'dlv-audit-code' });
    s = ticks(s, 1);
    s = ok(s, cmd.transition, { kind: 'run', id: runId, action: 'cancel', reason: 'Lancée par erreur' });
    s = ticks(s, 8);
    expect(s.db.run[runId].status).toBe('cancelled');
    expect(Object.values(s.db.result).filter((r) => r.runId === runId)).toHaveLength(0);
    let retry: string;
    [s, retry] = run(s, cmd.retryRun, { runId });
    expect(s.db.run[retry].previousRunId).toBe(runId);
    expect(s.db.run[retry].attempt).toBe(2);
  });

  it('le budget atteint interrompt la simulation avec un motif', () => {
    let s = nova();
    s = ok(s, cmd.updateSettings, { patch: { monthlyUnits: 183 } }, INES);
    let runId: string;
    [s, runId] = run(s, cmd.launchControl, { controlId: 'ctl-isolation', deliverableId: 'dlv-audit-code' });
    s = ticks(s, 4);
    expect(s.db.run[runId].status).toBe('error');
    expect(s.db.run[runId].statusReason).toMatch(/Budget/);
  });

  it('une version de règle publiée mais non adoptée ne périme pas les résultats du projet (RG-29)', () => {
    let s = nova();
    s = ok(s, cmd.setFact, { version: 3, key: 'export.retention', value: '7 jours' });
    s = ok(s, cmd.arbitrateConflict, { version: 3, keepRuleId: 'rul-br-gh', dropRuleIds: ['rul-br-tbd'], reason: 'GitHub flow retenu.' });
    s = ok(s, cmd.editRule, { version: 3, ruleId: 'rul-iso', patch: { statement: 'Version étendue de la règle d’isolation entre clients.' } });
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'submit', version: 3 });
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'publish', version: 3 });
    expect(s.db.rule['rul-iso'].versions.find((v) => v.number === 2)?.status).toBe('published');
    expect(resultFreshness(s, s.db.result['res-run-a2']).state).toBe('current');
    s = ok(s, cmd.adoptBlueprint, { projectId: 'prj-audit', version: 3, reason: 'Adoption' });
    expect(resultFreshness(s, s.db.result['res-run-a2']).state).toBe('stale');
  });

  it('modifier un livrable approuvé crée une proposition, jamais un remplacement silencieux (RG-34)', () => {
    let s = nova();
    s = ok(s, cmd.editDeliverable, { id: 'dlv-audit-doc', content: { kind: 'markdown', body: '# Guide modifié' }, note: 'Reformulation' }, human('u-camille'));
    const d = s.db.deliverable['dlv-audit-doc'];
    expect(d.current).toBe(2);
    expect(d.versions.at(-1)?.proposal).toBe(true);
    expect(d.status).toBe('published');
  });

  it('les partages locaux respectent expiration et révocation (RG-38)', () => {
    let s = nova();
    expect(shareStatus(s, s.db.share['shr-portal'])).toBe('expired');
    expect(run(s, cmd.openShare, { token: 'demo-portal-tuto', visitor: 'Clients pilotes' })[1]).toBe('expiré');
    expect(run(s, cmd.openShare, { token: 'demo-audit-guide', visitor: 'Clients grands comptes' })[1]).toBe('autorisé');
    s = ok(s, cmd.transition, { kind: 'share', id: 'shr-audit', action: 'revoke' }, human('u-camille'));
    expect(run(s, cmd.openShare, { token: 'demo-audit-guide', visitor: 'Clients grands comptes' })[1]).toBe('révoqué');
  });
});

describe('stockage, imports et catalogue', () => {
  const memoryStore = (): KeyValueStore => { const m = new Map<string, string>(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v), removeItem: (k) => void m.delete(k) }; };

  it('recharger conserve les données attendues', () => {
    const store = memoryStore();
    const s = ok(nova(), cmd.addComment, { questId: 'qst-ds', text: 'Commentaire à conserver' });
    expect(saveWorkspace(s, store).ok).toBe(true);
    const loaded = loadWorkspace(store);
    expect(loaded.problem).toBeUndefined();
    expect(loaded.state.db.quest['qst-ds'].comments.at(-1)?.text).toBe('Commentaire à conserver');
  });

  it('un import invalide n’altère pas les données existantes (RG-41)', () => {
    const s = nova();
    const before = JSON.stringify(s);
    expect(previewBackup('{pas du json', s).ok).toBe(false);
    const broken = JSON.parse(backupOf(s));
    broken.state.db.quest['qst-ds'].projectId = 'prj-inexistant';
    const preview = previewBackup(JSON.stringify(broken), s);
    expect(preview.ok).toBe(false);
    expect(preview.errors[0]).toMatch(/projet absent/);
    expect(JSON.stringify(s)).toBe(before);
  });

  it('une sauvegarde illisible est conservée à part et l’espace repart vide', () => {
    const store = memoryStore();
    store.setItem('open-guild-kit.demo', '{"state": 42}');
    const loaded = loadWorkspace(store);
    expect(loaded.problem).toMatch(/illisible/);
    expect(store.getItem('open-guild-kit.demo.illisible')).toBe('{"state": 42}');
  });

  it('le compteur de la Bibliothèque correspond aux 395 fiches importées', () => {
    const s = nova();
    expect((catalogue as { references: unknown[] }).references).toHaveLength(395);
    expect(allReferences(s)).toHaveLength(395);
    expect(new Set(allReferences(s).map((r) => r.id)).size).toBe(395);
  });

  it('l’import de catalogue rapproche les doublons et refuse les URL dangereuses', () => {
    const refs = allReferences(nova());
    const md = `# Test\n\n## 1. Code et collaboration — 2 références\n\n### Divers (2)\n\n| Référence | Nature | Description | Quand l’utiliser | Sources |\n| --- | --- | --- | --- | --- |\n| **Semantic Versioning** | convention | Description modifiée. | Toujours. | [Source 1: SemVer](https://semver.org/) |\n| **Nouvelle pratique** | pratique | Une nouveauté. | Parfois. | [Source 1: Piège](javascript:alert(1)) |\n`;
    const preview = previewCatalogueImport(md, refs);
    expect(preview.rows.find((r) => r.incoming.name === 'Semantic Versioning')?.decision).toBe('update');
    expect(preview.rows.find((r) => r.incoming.name === 'Nouvelle pratique')?.incoming.sources).toHaveLength(0);
    expect(preview.errors.some((e) => /source/.test(e.message))).toBe(true);
  });

  it('toutes les références citées par les scénarios existent dans le catalogue', () => {
    const ids = new Set(allReferences(nova()).map((r) => r.id));
    const cited = [
      ...EXPERT_SEEDS.flatMap((e) => e.sources),
      ...Object.values(COUNCIL_SCENARIOS).flatMap((sc) => Object.values(sc.contributions).flatMap((c) => c!.sources)),
      ...Object.values(nova().db.rule).flatMap((r) => r.versions.flatMap((v) => v.referenceIds)),
      ...Object.values(nova().db.collection).flatMap((c) => c.refIds),
    ];
    expect(cited.filter((id) => !ids.has(id))).toEqual([]);
  });
});

export type { Reference };
