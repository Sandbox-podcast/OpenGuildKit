/**
 * Main demonstration journey (brief §10) played through the domain commands only:
 * "Permettre à un administrateur d'exporter les données de ses clients."
 */
import { describe, expect, it } from 'vitest';
import { cmd } from '@/demo/domain/commands';
import { closureBlocked, closureReport, lineage, resultFreshness, shareStatus } from '@/demo/domain/selectors';
import type { AppState, DeliverableType } from '@/demo/domain/types';
import { agent, human, latest, nova, ok, refused, run, ticks } from './helpers';

const YANIS = human('u-yanis');
const INES = human('u-ines');
const SKILL: Record<string, string> = { spec: 'spec', component: 'ui', api: 'api', tests: 'tests', code: 'code', doc: 'doc' };

describe('parcours principal — export des données clients', () => {
  it('relie Blueprint, Conseil, décision, quête, livrables, contrôles, preuves, validation, partage et réexamen', () => {
    let s: AppState = nova();
    expect(s.session.projectId).toBe('prj-export');

    // 3–4. The unknown retention is identified, then resolved in a new Blueprint version.
    const v2 = s.db.blueprint['bp-nova'].versions.find((v) => v.number === 2)!;
    expect(v2.context.find((f) => f.key === 'export.retention')?.provenance).toBe('unknown');
    expect(refused(s, cmd.setFact, { version: 2, key: 'export.retention', value: '7 jours' })).toMatch(/immuable/);
    s = ok(s, cmd.setFact, { version: 3, key: 'export.retention', value: '7 jours' });
    expect(refused(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'publish', version: 3 })).toMatch(/Impossible depuis/);
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'submit', version: 3 });
    expect(refused(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'publish', version: 3 })).toMatch(/Conflits à arbitrer/);
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'reject', version: 3, reason: 'Arbitrer la stratégie de branches' });
    s = ok(s, cmd.arbitrateConflict, { version: 3, keepRuleId: 'rul-br-gh', dropRuleIds: ['rul-br-tbd'], reason: 'GitHub flow déjà pratiqué par toutes les équipes.' });
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'submit', version: 3 });
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'publish', version: 3 });
    s = ok(s, cmd.adoptBlueprint, { projectId: 'prj-export', version: 3, reason: 'Durée de disponibilité fixée.' });
    expect(s.db.project['prj-export'].blueprintVersion).toBe(3);

    // 5. A suggestion stays a proposal until a human validates it.
    expect(s.db.applicability['app-2'].validated).toBe(false);
    s = ok(s, cmd.validateApplicability, { id: 'app-2' });

    // 7–8. The council compares two options; disagreements are annotated.
    s = ok(s, cmd.transition, { kind: 'council', id: 'cns-export', action: 'launch' });
    expect(refused(s, cmd.transition, { kind: 'council', id: 'cns-export', action: 'arbitrate' })).toMatch(/Contributions en cours/);
    s = ticks(s, 6);
    const council = s.db.council['cns-export'];
    expect(council.contributions).toHaveLength(6);
    expect(council.options.length).toBeGreaterThanOrEqual(2);
    s = ok(s, cmd.annotateCouncil, { councilId: 'cns-export', text: 'Produit et Engineering divergent sur l’option A.', contributionIds: council.contributions.slice(0, 3).map((c) => c.id) });
    s = ok(s, cmd.requestClarification, { councilId: 'cns-export', expertId: 'exp-org-nova-privacy', question: 'Quelle durée retenir ?' });
    s = ok(s, cmd.transition, { kind: 'council', id: 'cns-export', action: 'arbitrate' });

    // 9. A human chooses and justifies; a distinct human approves.
    let decisionId: string;
    [s, decisionId] = run(s, cmd.proposeDecision, { councilId: 'cns-export', optionId: 'opt-b', justification: 'Couvre les grands comptes ; durée de 7 jours fixée.', ownerId: 'u-yanis' });
    s = ok(s, cmd.transition, { kind: 'decision', id: decisionId, action: 'submit', approverId: 'u-ines' });
    expect(refused(s, cmd.transition, { kind: 'decision', id: decisionId, action: 'approve' })).toMatch(/Séparation|assignée/);
    expect(refused(s, cmd.transition, { kind: 'decision', id: decisionId, action: 'approve' }, agent('security'))).toMatch(/humain/);
    s = ok(s, cmd.transition, { kind: 'decision', id: decisionId, action: 'approve' }, INES);
    expect(s.db.decision[decisionId].status).toBe('approved');
    expect(s.db.decision[decisionId].considered.blueprintVersion).toBe(3);

    // 10. Conversion is idempotent.
    let questIds: string[];
    [s, questIds] = run(s, cmd.convertDecision, { decisionId });
    expect(refused(s, cmd.convertDecision, { decisionId })).toMatch(/Déjà convertie/);
    const questId = questIds[0];
    expect(Object.values(s.db.quest).filter((q) => q.decisionId === decisionId)).toHaveLength(1);
    s = ok(s, cmd.transition, { kind: 'quest', id: questId, action: 'start' });

    // 11. The forge prepares every expected deliverable.
    for (const type of s.db.quest[questId].expectedDeliverables) s = ok(s, cmd.launchSkill, { skillId: `skl-${SKILL[type]}-org-nova`, questId, type: type as DeliverableType });
    s = ticks(s, 5);
    const del = (type: DeliverableType) => Object.values(s.db.deliverable).find((d) => d.questId === questId && d.type === type)!;
    expect(s.db.quest[questId].deliverableIds).toHaveLength(6);

    // 12–13. First verification reveals the isolation defect.
    s = ok(s, cmd.launchControl, { controlId: 'ctl-isolation', deliverableId: del('code').id, questId });
    s = ticks(s, 5);
    const failed = latest(s.db.result, (r) => r.controlId === 'ctl-isolation' && r.inputs.subject?.deliverableId === del('code').id)!;
    expect(failed.outcome).toBe('failed');
    const finding = latest(s.db.finding, (f) => f.resultId === failed.id)!;
    expect(finding.status).toBe('open');
    s = ok(s, cmd.correctiveQuest, { findingId: finding.id, existingQuestId: questId });
    expect(closureBlocked(closureReport(s, questId)).some((i) => i.key.startsWith('control:ctl-isolation'))).toBe(true);

    // 14. The correction creates a new version; the old evidence becomes stale.
    s = ok(s, cmd.launchSkill, { skillId: 'skl-code-org-nova', questId, type: 'code', variant: 'correctif' });
    s = ticks(s, 5);
    expect(del('code').current).toBe(2);
    expect(resultFreshness(s, s.db.result[failed.id]).state).toBe('stale');

    // 15. New executions produce new results and evidence.
    for (const [controlId, type] of [['ctl-isolation', 'code'], ['ctl-perm', 'code'], ['ctl-tests', 'tests']] as const) s = ok(s, cmd.launchControl, { controlId, deliverableId: del(type).id, questId });
    s = ticks(s, 5);
    expect(s.db.finding[finding.id].status).toBe('resolved');
    expect(s.db.result[failed.id].outcome).toBe('failed');

    // 16. Criteria, tasks, approvals by a distinct approver.
    for (const c of s.db.quest[questId].criteria) s = ok(s, cmd.setCriterion, { questId, criterionId: c.id, met: true });
    for (const t of Object.values(s.db.task).filter((x) => x.questId === questId)) {
      s = ok(s, cmd.transition, { kind: 'task', id: t.id, action: 'start' });
      s = ok(s, cmd.transition, { kind: 'task', id: t.id, action: 'finish' });
    }
    for (const id of s.db.quest[questId].deliverableIds) {
      s = ok(s, cmd.transition, { kind: 'deliverable', id, action: 'submit', approverId: 'u-ines' });
      s = ok(s, cmd.transition, { kind: 'deliverable', id, action: 'approve' }, INES);
    }
    s = ok(s, cmd.transition, { kind: 'quest', id: questId, action: 'submitReview' });
    expect(refused(s, cmd.transition, { kind: 'quest', id: questId, action: 'close' })).toMatch(/Validation humaine/);
    let approvalId: string;
    [s, approvalId] = run(s, cmd.requestApproval, { subject: { kind: 'quest', id: questId }, purpose: 'clôture', approverId: 'u-ines' });
    expect(refused(s, cmd.transition, { kind: 'approval', id: approvalId, action: 'approve' })).toMatch(/assignée|Séparation/);
    s = ok(s, cmd.transition, { kind: 'approval', id: approvalId, action: 'approve' }, INES);

    // 17. The quest closes; the approved documentation is published.
    s = ok(s, cmd.transition, { kind: 'quest', id: questId, action: 'close' }, YANIS);
    expect(s.db.quest[questId].status).toBe('done');
    s = ok(s, cmd.transition, { kind: 'deliverable', id: del('doc').id, action: 'publish' });
    expect(del('doc').status).toBe('published');

    // 18. Local share: authorised opening, refusal, revocation.
    let shareId: string;
    [s, shareId] = run(s, cmd.createShare, { deliverableId: del('doc').id, audience: 'Administrateurs pilotes', mode: 'lecture', days: 7 });
    const token = s.db.share[shareId].token;
    expect(run(s, cmd.openShare, { token, visitor: 'Administrateurs pilotes' })[1]).toBe('autorisé');
    expect(run(s, cmd.openShare, { token, visitor: 'Inconnu' })[1]).toBe('refusé');
    s = ok(s, cmd.transition, { kind: 'share', id: shareId, action: 'revoke' });
    expect(shareStatus(s, s.db.share[shareId])).toBe('revoked');
    expect(run(s, cmd.openShare, { token, visitor: 'Administrateurs pilotes' })[1]).toBe('révoqué');

    // 19. The chronicles rebuild the chain from the documentation.
    const chain = lineage(s, { kind: 'deliverable', id: del('doc').id }, 5).map((x) => x.ref.kind);
    expect(chain).toEqual(expect.arrayContaining(['quest', 'decision', 'council', 'blueprint', 'rule']));
    const codeChain = lineage(s, { kind: 'deliverable', id: del('code').id }, 3).map((x) => x.ref.kind);
    expect(codeChain).toEqual(expect.arrayContaining(['result', 'evidence', 'approval', 'run']));

    // 20. A later Blueprint evolution: published but not adopted, then adopted with re-examination.
    s = ok(s, cmd.startBlueprintDraft, { justification: 'Étendre l’isolation aux traitements asynchrones.' }, INES);
    s = ok(s, cmd.editRule, { version: 4, ruleId: 'rul-iso', patch: { statement: 'Toute lecture ou écriture de données métier, y compris dans les traitements asynchrones et les fichiers générés, est filtrée par client.', justification: 'Traitements asynchrones' } }, INES);
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'submit', version: 4 }, INES);
    s = ok(s, cmd.transition, { kind: 'blueprint', id: 'bp-nova', action: 'publish', version: 4 }, YANIS);
    const passed = latest(s.db.result, (r) => r.controlId === 'ctl-isolation' && r.outcome === 'passed' && r.projectId === 'prj-export')!;
    expect(resultFreshness(s, passed).state).toBe('current');
    s = ok(s, cmd.adoptBlueprint, { projectId: 'prj-export', version: 4, reason: 'Adopter l’isolation étendue.' });
    expect(resultFreshness(s, passed).state).toBe('stale');
    expect(Object.values(s.db.review).some((r) => r.subject.id === decisionId && r.status === 'open')).toBe(true);
    expect(s.db.decision[decisionId].status).toBe('approved');
  });
});
