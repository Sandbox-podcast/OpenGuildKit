/** Watchtower: findings, controls table, run comparison, evidence, exceptions and human reviews (brief §5.9). */
import { useState } from 'react';
import { NotFound } from '@/app/App';
import { dispatch, newOpId, useAppState } from '@/app/store';
import { navigate, setQuery, useRoute } from '@/app/router';
import { cmd } from '@/domain/commands';
import { DAY, list, nowOf } from '@/domain/engine';
import { stateDef } from '@/domain/machines';
import { approvalValidity, effectiveApprovalStatus, effectiveExceptionStatus, fmtDate, fmtRelative, latestResults, objectLabel, resultFreshness, ruleIsDerogable } from '@/domain/selectors';
import type { ControlCategory, Finding, ID, Result, RuleException } from '@/domain/types';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Checkbox, Empty, KV, Notice, Panel, Select, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { CollectionBar, groupBy, useCollection } from '@/shared/ui/collection';
import { ActorLabel, CmdButton, Freshness, Lifecycle, ObjectLink, Person, SimBadge, StatusBadge, Version } from '@/shared/ui/domain';
import { DiffView } from '@/shared/ui/content';

const CATEGORIES: ControlCategory[] = ['qualité', 'tests', 'sécurité', 'dépendances', 'accès', 'performance', 'fiabilité'];

export function WatchtowerSpace({ tab = 'constats', id }: { tab?: string; id?: ID }) {
  const s = useAppState();
  const open = list(s, 'finding', s.session.orgId).filter((f) => f.status === 'open').length;
  const reviews = list(s, 'approval', s.session.orgId).filter((a) => effectiveApprovalStatus(s, a) === 'expected').length;
  const stale = latestResults(s).filter((r) => resultFreshness(s, r).state === 'stale').length;
  return (
    <div className="stack">
      <Tabs label="Tour de guet" value={tab} onChange={(t) => navigate(`/tour/${t}`)} tabs={[
        { id: 'constats', label: 'Constats', icon: 'warn', count: open }, { id: 'controles', label: 'Contrôles', icon: 'tower', count: stale },
        { id: 'preuves', label: 'Preuves', icon: 'shield' }, { id: 'exceptions', label: 'Exceptions', icon: 'flag' }, { id: 'revues', label: 'Revues humaines', icon: 'eye', count: reviews },
      ]} />
      {tab === 'constats' && (id ? <FindingSheet id={id} /> : <Findings />)}
      {tab === 'controles' && <Controls />}
      {tab === 'preuves' && <EvidenceView />}
      {tab === 'exceptions' && (id ? <ExceptionSheet id={id} /> : <Exceptions />)}
      {tab === 'revues' && <Reviews />}
    </div>
  );
}

/* ------------------------------------------------------------------ findings */
const SEV_TONE = { critique: 'danger', haute: 'danger', moyenne: 'warning', basse: 'neutral' } as const;

function Findings() {
  const s = useAppState();
  const route = useRoute();
  const findings = list(s, 'finding', s.session.orgId).sort((a, b) => b.createdAt - a.createdAt);
  const filters = [
    { key: 'gravite', label: 'Gravité', options: ['critique', 'haute', 'moyenne', 'basse'].map((x) => ({ value: x, label: x })), test: (f: Finding, v: string) => f.severity === v },
    { key: 'categorie', label: 'Catégorie', options: CATEGORIES.map((x) => ({ value: x, label: x })), test: (f: Finding, v: string) => f.category === v },
    { key: 'projet', label: 'Projet', options: list(s, 'project', s.session.orgId).map((p) => ({ value: p.id, label: p.name })), test: (f: Finding, v: string) => f.projectId === v },
    { key: 'statut', label: 'Statut', options: ['open', 'in_progress', 'resolved', 'waived'].map((x) => ({ value: x, label: stateDef('finding', x).label })), test: (f: Finding, v: string) => f.status === v },
  ];
  const c = useCollection(findings, { text: (f) => `${f.title} ${f.observation} ${f.remediation}`, filters });
  const group = route.query.get('groupe') ?? 'projet';
  const groups = groupBy(c.items, (f) => group === 'categorie' ? f.category : group === 'gravite' ? f.severity : s.db.project[f.projectId]?.name ?? '—');
  return (
    <Panel title="Constats">
      <CollectionBar c={c} filters={filters} total={findings.length} placeholder="Rechercher un constat">
        <Select label={<span className="sr-only">Regrouper</span>} value={group} onChange={(e) => setQuery({ groupe: e.target.value })} options={[{ value: 'projet', label: 'Regrouper par projet' }, { value: 'categorie', label: 'Par catégorie' }, { value: 'gravite', label: 'Par gravité' }]} />
      </CollectionBar>
      {c.items.length === 0 ? <Empty title="Aucun constat">Les constats apparaissent lorsqu’un contrôle échoue.</Empty> : groups.map(([g, items]) => (
        <section key={g}>
          <h3>{g} <span className="badge count">{items.length}</span></h3>
          <table className="data responsive"><thead><tr><th>Constat</th><th>Gravité</th><th>Catégorie</th><th>Objet</th><th>Statut</th><th>Propriétaire</th></tr></thead>
            <tbody>{items.map((f) => <tr key={f.id}><td data-label="Constat"><a href={`#/tour/constats/${f.id}`}>{f.title}</a></td><td data-label="Gravité"><Badge tone={SEV_TONE[f.severity]} icon="warn">{f.severity}</Badge></td><td data-label="Catégorie">{f.category}</td><td data-label="Objet"><ObjectLink to={f.subject} /></td><td data-label="Statut"><StatusBadge kind="finding" state={f.status} /></td><td data-label="Propriétaire"><Person id={f.ownerId} /></td></tr>)}</tbody></table>
        </section>
      ))}
    </Panel>
  );
}

function FindingSheet({ id }: { id: ID }) {
  const s = useAppState();
  const f = s.db.finding[id];
  const [owner, setOwner] = useState('');
  const [quest, setQuest] = useState('');
  if (!f || f.orgId !== s.session.orgId) return <NotFound what="Constat" />;
  const result = f.resultId ? s.db.result[f.resultId] : undefined;
  const control = s.db.control[f.source];
  const dl = s.db.deliverable[f.subject.id];
  const project = s.db.project[f.projectId];
  const derogable = f.ruleId && project ? ruleIsDerogable(s, project, f.ruleId) : false;
  const members = [...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))];
  return (
    <div className="stack">
      <a href="#/tour/constats" className="small">← Tous les constats</a>
      <Panel title={f.title} actions={<><Badge tone={SEV_TONE[f.severity]} icon="warn">{f.severity}</Badge><StatusBadge kind="finding" state={f.status} />{result && <SimBadge />}</>}>
        <KV items={[
          ['Catégorie', f.category], ['Projet', <ObjectLink to={{ kind: 'project', id: f.projectId }} />], ['Objet affecté', <ObjectLink to={f.subject} />],
          ['Version', <Version n={f.subject.version} />], ['Règle', f.ruleId ? <ObjectLink to={{ kind: 'rule', id: f.ruleId }} /> : '—'], ['Source', control ? `${control.code} — ${control.name}` : f.source],
          ['Observation', f.observation], ['Propriétaire', <Person id={f.ownerId} />], ['Remédiation proposée', f.remediation], ['Quête', f.questId ? <ObjectLink to={{ kind: 'quest', id: f.questId }} /> : '—'],
          ['Résultat', result ? <span className="row"><StatusBadge kind="result" state={result.outcome} /><Freshness result={result} /><a href={`#/tour/preuves?resultat=${result.id}`}>preuve</a></span> : '—'], ['Ouvert le', fmtDate(f.createdAt, true)],
        ]} />
      </Panel>
      <div className="grid-2">
        <Panel title="Traiter">
          <div className="row"><Select label="Assigner à" value={owner} placeholder="Choisir…" onChange={(e) => setOwner(e.target.value)} options={members.map((m) => ({ value: m, label: s.users[m]?.name ?? m }))} /><CmdButton def={cmd.assignFinding} payload={{ id: f.id, ownerId: owner }} size="small" success="Constat assigné">Assigner</CmdButton></div>
          <h3 style={{ marginTop: 10 }}>Correction</h3>
          <CmdButton def={cmd.correctiveQuest} payload={{ findingId: f.id }} variant="primary" icon="quest" success="Quête corrective créée" onDone={(qid) => navigate(`/quetes/${qid}`)}>Créer une quête corrective</CmdButton>
          <div className="row" style={{ marginTop: 6 }}><Select label="Ou rattacher à une quête existante" value={quest} placeholder="Choisir…" onChange={(e) => setQuest(e.target.value)} options={list(s, 'quest', s.session.orgId).filter((q) => q.projectId === f.projectId && !['done', 'cancelled'].includes(q.status)).map((q) => ({ value: q.id, label: q.title }))} /><CmdButton def={cmd.correctiveQuest} payload={{ findingId: f.id, existingQuestId: quest }} size="small" success="Constat rattaché">Rattacher</CmdButton></div>
          {dl && f.questId && <div style={{ marginTop: 10 }}><CmdButton def={cmd.launchSkill} payload={{ skillId: `skl-${dl.type === 'component' ? 'ui' : dl.type}-${s.session.orgId}`, questId: f.questId, type: dl.type, variant: 'correctif' }} variant="ai" icon="anvil" success="Correctif en préparation (simulation) : une nouvelle version du livrable sera produite">Proposer un correctif (simulation)</CmdButton></div>}
          {control && dl && <div style={{ marginTop: 10 }}><CmdButton def={cmd.launchControl} payload={{ controlId: control.id, deliverableId: dl.id, questId: f.questId }} icon="play" success="Contrôle relancé sur la version en vigueur">Relancer {control.code} sur la v{dl.current}</CmdButton></div>}
        </Panel>
        <Panel title="Dérogation">
          {derogable ? <><p className="small muted">La règle est dérogeable : une exception approuvée, applicable à cette version et non expirée peut lever la garde. Le résultat du contrôle restera « échoué ».</p><a className="btn" href={`#/tour/exceptions?nouvelle=1&regle=${f.ruleId}&projet=${f.projectId}&livrable=${f.subject.id}&version=${f.subject.version ?? ''}`}><Icon name="flag" size={14} /> Demander une dérogation</a></>
            : <Notice tone="danger">La règle {s.db.rule[f.ruleId ?? '']?.code} est non dérogeable : seule une correction lève ce blocage.</Notice>}
        </Panel>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ controls */
function Controls() {
  const s = useAppState();
  const route = useRoute();
  const cat = route.query.get('categorie') ?? '';
  const proj = route.query.get('projet') ?? '';
  const focusControl = route.query.get('control');
  const focusDeliverable = route.query.get('deliverable');
  const controls = list(s, 'control', s.session.orgId).filter((c) => !cat || c.category === cat);
  const results = latestResults(s);
  const rows = controls.flatMap((c) => list(s, 'deliverable', s.session.orgId).filter((d) => c.appliesTo.includes(d.type) && (!proj || d.projectId === proj) && s.db.project[d.projectId]?.status === 'active' && (results.some((r) => r.controlId === c.id && r.inputs.subject?.deliverableId === d.id) || list(s, 'quest', s.session.orgId).some((q) => q.controlIds.includes(c.id) && q.deliverableIds.includes(d.id)))).map((d) => ({ c, d, r: results.find((r) => r.controlId === c.id && r.inputs.subject?.deliverableId === d.id) })));
  const [compare, setCompare] = useState<{ c: ID; d: ID } | null>(focusControl && focusDeliverable ? { c: focusControl, d: focusDeliverable } : null);
  const errors = list(s, 'run', s.session.orgId).filter((r) => r.kind === 'control' && r.status === 'error');
  const counts = CATEGORIES.map((k) => ({ k, total: rows.filter((x) => x.c.category === k).length, failed: rows.filter((x) => x.c.category === k && x.r?.outcome === 'failed').length }));
  return (
    <div className="stack">
      <div className="row">
        <div className="seg" role="group" aria-label="Catégorie" style={{ flexWrap: 'wrap' }}>{[['', 'Toutes'], ...CATEGORIES.map((k) => [k, k])].map(([k, l]) => <button key={k} aria-pressed={cat === k} onClick={() => setQuery({ categorie: k || null })} style={{ textTransform: 'capitalize' }}>{l}</button>)}</div>
        <Select label={<span className="sr-only">Projet</span>} value={proj} placeholder="Tous les projets" onChange={(e) => setQuery({ projet: e.target.value })} options={list(s, 'project', s.session.orgId).map((p) => ({ value: p.id, label: p.name }))} />
      </div>
      <Panel title="Indicateurs par périmètre">
        <p className="small muted">Chaque indicateur porte sur des contrôles et des objets précis. Aucun pourcentage global ne prétend démontrer la conformité à une norme.</p>
        <div className="row">{counts.filter((x) => x.total).map(({ k, total, failed }) => <span key={k} className="chip">{k[0].toLocaleUpperCase('fr-FR') + k.slice(1)} · {total} {total === 1 ? 'contrôle' : 'contrôles'}, {failed} {failed > 1 ? 'échecs' : 'échec'}</span>)}</div>
      </Panel>
      {errors.length > 0 && <Notice tone="danger" title="Erreurs techniques (récupérables) :">{errors.map((r) => <span key={r.id} style={{ display: 'block' }}><a href={`#/forge/executions/${r.id}`}>{r.title}</a> — {r.statusReason}</span>)}</Notice>}
      <Panel title="Tableau des contrôles" actions={<SimBadge label="Exécutions simulées" />}>
        <div className="table-wrap">
          <table className="data responsive">
            <thead><tr><th>Contrôle</th><th>Objet</th><th>Exécuté</th><th>Sur la version</th><th>Résultat</th><th>Validité du résultat</th><th>Preuve</th><th>Actions</th></tr></thead>
            <tbody>{rows.map(({ c, d, r }) => {
              const ev = r ? list(s, 'evidence', s.session.orgId).find((e) => e.resultId === r.id) : undefined;
              const running = list(s, 'run', s.session.orgId).find((x) => x.controlId === c.id && x.inputs.subject?.deliverableId === d.id && x.status === 'running');
              return (
                <tr key={`${c.id}${d.id}`} className={focusControl === c.id && focusDeliverable === d.id ? 'selected' : ''}>
                  <td data-label="Contrôle"><strong>{c.code}</strong> {c.name}{c.blocking && <Badge tone="danger" icon="lock">bloquant</Badge>}<span className="tiny muted" style={{ display: 'block', textTransform: 'capitalize' }}>{c.category}</span></td>
                  <td data-label="Objet"><ObjectLink to={{ kind: 'deliverable', id: d.id }} /><span className="tiny muted" style={{ display: 'block' }}>{s.db.project[d.projectId]?.name}</span></td>
                  <td data-label="Exécuté" className="small">{r ? fmtDate(r.evaluatedAt, true) : '—'}</td>
                  <td data-label="Sur la version">{r?.inputs.subject ? <><Version n={r.inputs.subject.version} /> <span className="tiny muted">(en vigueur : v{d.current})</span></> : '—'}</td>
                  <td data-label="Résultat">{running ? <Badge tone="ai" icon="play">en cours</Badge> : r ? <StatusBadge kind="result" state={r.outcome} /> : <StatusBadge kind="result" state="not_evaluated" />}</td>
                  <td data-label="Validité du résultat">{r ? <Freshness result={r} /> : '—'}</td>
                  <td data-label="Preuve">{ev ? <a href={`#/tour/preuves?preuve=${ev.id}`} className="mono small">{ev.digest}</a> : '—'}</td>
                  <td data-label="Actions"><div className="row">
                    <CmdButton def={cmd.launchControl} payload={{ controlId: c.id, deliverableId: d.id }} size="small" icon="play" success="Contrôle lancé" showReason={false}>{r ? 'Relancer' : 'Lancer'}</CmdButton>
                    <Button size="small" variant="ghost" onClick={() => setCompare({ c: c.id, d: d.id })}>Historique</Button>
                  </div></td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
        {rows.length === 0 && <Empty title="Aucun contrôle à afficher" />}
      </Panel>
      {compare && <RunComparison controlId={compare.c} deliverableId={compare.d} onClose={() => setCompare(null)} />}
      <NotApplicable />
    </div>
  );
}

function RunComparison({ controlId, deliverableId, onClose }: { controlId: ID; deliverableId: ID; onClose: () => void }) {
  const s = useAppState();
  const results = list(s, 'result', s.session.orgId).filter((r) => r.controlId === controlId && r.inputs.subject?.deliverableId === deliverableId).sort((a, b) => b.evaluatedAt - a.evaluatedAt);
  const [a, setA] = useState(results[1]?.id ?? '');
  const [b, setB] = useState(results[0]?.id ?? '');
  const control = s.db.control[controlId];
  const deliverable = s.db.deliverable[deliverableId];
  if (control?.orgId !== s.session.orgId || deliverable?.orgId !== s.session.orgId) return null;
  const txt = (r?: Result) => r ? `Résultat : ${r.outcome}\nVersion évaluée : v${r.inputs.subject?.version}\nBlueprint : v${r.inputs.blueprintVersion}\nRègles : ${r.inputs.rules.map((x) => `${s.db.rule[x.ruleId]?.code} v${x.version}`).join(', ')}\nObservation : ${r.observation}` : '';
  return (
    <Panel title={`Historique et comparaison — ${control.code} sur ${deliverable.title}`} actions={<Button size="small" variant="ghost" icon="close" onClick={onClose}>Fermer</Button>}>
      <ul className="plain stack tight">{results.map((r) => <li key={r.id} className="row small"><StatusBadge kind="result" state={r.outcome} /><Freshness result={r} /><Version n={r.inputs.subject?.version} /><span>{fmtDate(r.evaluatedAt, true)}</span><a href={`#/forge/executions/${r.runId}`}>exécution</a></li>)}</ul>
      {results.length >= 2 && <>
        <div className="row"><Select label="Exécution A" value={a} onChange={(e) => setA(e.target.value)} options={results.map((r) => ({ value: r.id, label: `${fmtDate(r.evaluatedAt, true)} — ${r.outcome}` }))} /><Select label="Exécution B" value={b} onChange={(e) => setB(e.target.value)} options={results.map((r) => ({ value: r.id, label: `${fmtDate(r.evaluatedAt, true)} — ${r.outcome}` }))} /></div>
        <DiffView before={txt(results.find((r) => r.id === a))} after={txt(results.find((r) => r.id === b))} labels={['A', 'B']} />
      </>}
    </Panel>
  );
}

function NotApplicable() {
  const s = useAppState();
  const [c, setC] = useState('');
  const [d, setD] = useState('');
  const [j, setJ] = useState('');
  const control = s.db.control[c];
  return (
    <Panel title="Qualifier « non applicable »">
      <p className="small muted">Un contrôle non applicable comporte toujours une justification humaine ; il n’est jamais déduit automatiquement.</p>
      <div className="form-grid">
        <Select label="Contrôle" value={c} placeholder="Choisir…" onChange={(e) => setC(e.target.value)} options={list(s, 'control', s.session.orgId).map((x) => ({ value: x.id, label: `${x.code} — ${x.name}` }))} />
        <Select label="Livrable" value={d} placeholder="Choisir…" onChange={(e) => setD(e.target.value)} options={list(s, 'deliverable', s.session.orgId).filter((x) => !control || control.appliesTo.includes(x.type)).map((x) => ({ value: x.id, label: x.title }))} />
        <TextArea className="full" label="Justification" value={j} onChange={(e) => setJ(e.target.value)} />
      </div>
      <CmdButton def={cmd.markNotApplicable} payload={{ controlId: c, deliverableId: d, justification: j }} size="small" success="Qualification enregistrée">Enregistrer</CmdButton>
    </Panel>
  );
}

/* ------------------------------------------------------------------ evidence */
function EvidenceView() {
  const s = useAppState();
  const route = useRoute();
  const all = list(s, 'evidence', s.session.orgId).sort((a, b) => b.at - a.at);
  const proofId = route.query.get('preuve');
  const resultId = route.query.get('resultat');
  const ev = proofId ? all.find((e) => e.id === proofId) : resultId ? all.find((e) => e.resultId === resultId) : all[0];
  const linkedResult = ev ? s.db.result[ev.resultId] : undefined;
  const result = linkedResult?.orgId === s.session.orgId ? linkedResult : undefined;
  const freshness = result && resultFreshness(s, result);
  const inventory = (
    <Panel key="inventory" title={`Preuves (${all.length})`}>
      <ul className="plain stack tight">{all.map((e) => {
        const r = s.db.result[e.resultId];
        const selected = e.id === ev?.id;
        return (
          <li key={e.id}>
            <a className={`card ${selected ? 'selected' : ''}`} href={`#/tour/preuves?preuve=${e.id}`} aria-current={selected ? 'true' : undefined}>
              <div className="row between"><span className="mono small">{e.digest}</span><span className="row">{r && <StatusBadge kind="result" state={r.outcome} />}{r && <Freshness result={r} />}</span></div>
              <span className="small">{s.db.control[e.controlId]?.code} — {objectLabel(s, { kind: 'deliverable', id: e.inputs.subject?.deliverableId ?? '' })} v{e.inputs.subject?.version}</span>
              <span className="tiny muted" style={{ display: 'block' }}>{fmtDate(e.at, true)}</span>
            </a>
          </li>
        );
      })}</ul>
    </Panel>
  );
  const detail = ev && result ? (
    <Panel key="detail" title="Lecture de la preuve" actions={<SimBadge label="Preuve simulée" />}>
      {freshness?.state === 'stale' && <Notice tone="warn" title="À réévaluer :">{freshness.reasons.join(' ')} Cette preuve ne débloque pas la version en vigueur.</Notice>}
      <Notice tone="ai">Preuve produite par l’adaptateur de démonstration. Elle n’a pas de valeur d’attestation et le journal local n’est pas inviolable.</Notice>
      <KV items={[
        ['Exécution', <ObjectLink bare to={{ kind: 'run', id: ev.runId }} />], ['Résultat', <span className="row"><StatusBadge kind="result" state={result.outcome} /><Freshness result={result} /></span>],
        ['Objet évalué', <ObjectLink bare to={{ kind: 'deliverable', id: ev.inputs.subject?.deliverableId ?? '', version: ev.inputs.subject?.version }} />], ['Version évaluée', <Version n={ev.inputs.subject?.version} />],
        ['Profil (Blueprint)', <Version n={ev.inputs.blueprintVersion} />], ['Règles', ev.inputs.rules.map((x) => <span key={x.ruleId} style={{ display: 'block' }}><ObjectLink bare to={{ kind: 'rule', id: x.ruleId, version: x.version }} /></span>)],
        ['Contrôle', `${s.db.control[ev.controlId]?.code} v${ev.inputs.controlVersion}`], ['Date', fmtDate(ev.at, true)], ['Acteur', <ActorLabel actor={ev.actor} />], ['Provenance', ev.provenance], ['Empreinte', <code>{ev.digest}</code>],
      ]} />
      <h3 style={{ marginTop: 10 }}>Observation</h3><p>{result.observation}</p>
      <h3>Extrait</h3><pre className="code"><code>{ev.excerpt}</code></pre>
    </Panel>
  ) : (
    <Panel key="detail" title="Lecture de la preuve">
      <p className="muted">{proofId || resultId ? 'Preuve introuvable dans cette organisation.' : 'Aucune preuve disponible.'}</p>
    </Panel>
  );
  return (
    <div className="grid-2">
      {proofId || resultId ? [detail, inventory] : [inventory, detail]}
    </div>
  );
}

/* ------------------------------------------------------------------ exceptions */
function Exceptions() {
  const s = useAppState();
  const route = useRoute();
  const all = list(s, 'exception', s.session.orgId).sort((a, b) => b.createdAt - a.createdAt);
  const creating = route.query.get('nouvelle') === '1';
  return (
    <div className="stack">
      {creating && <ExceptionForm />}
      <Panel title="Exceptions" actions={!creating && <Button variant="primary" icon="plus" onClick={() => setQuery({ nouvelle: '1' })}>Nouvelle demande</Button>}>
        {all.length === 0 ? <Empty title="Aucune exception" /> : (
          <table className="data responsive"><thead><tr><th>Règle</th><th>Projet</th><th>Périmètre</th><th>État</th><th>Échéance</th><th>Approbateur</th></tr></thead>
            <tbody>{all.map((e) => { const st = effectiveExceptionStatus(s, e); return <tr key={e.id}><td data-label="Règle"><a href={`#/tour/exceptions/${e.id}`}>{s.db.rule[e.ruleId]?.code}</a></td><td data-label="Projet">{s.db.project[e.projectId]?.name}</td><td data-label="Périmètre" className="small">{e.scope}</td><td data-label="État"><StatusBadge kind="exception" state={st} /></td><td data-label="Échéance" className="small">{e.expiresAt ? `${fmtDate(e.expiresAt)} (${fmtRelative(e.expiresAt, nowOf(s))})` : '—'}</td><td data-label="Approbateur"><Person id={e.approverId} /></td></tr>; })}</tbody></table>
        )}
      </Panel>
    </div>
  );
}

function ExceptionForm({ existing }: { existing?: RuleException }) {
  const s = useAppState();
  const route = useRoute();
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : undefined;
  const [opId] = useState(newOpId);
  const deliverableId = existing?.subject?.deliverableId ?? route.query.get('livrable') ?? '';
  const dl = list(s, 'deliverable', s.session.orgId).find((d) => d.id === deliverableId);
  const [v, setV] = useState({
    projectId: existing?.projectId ?? route.query.get('projet') ?? s.session.projectId ?? '', ruleId: existing?.ruleId ?? route.query.get('regle') ?? '', scope: existing?.scope ?? '', reason: existing?.reason ?? '',
    riskAccepted: existing?.riskAccepted ?? '', compensatingMeasures: existing?.compensatingMeasures ?? '', ownerId: existing?.ownerId ?? me, approverId: existing?.approverId ?? '',
    days: existing?.expiresAt ? Math.max(1, Math.round((existing.expiresAt - nowOf(s)) / DAY)) : 14, bindVersion: !!dl,
  });
  const members = [...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))];
  const save = () => {
    const out = dispatch(cmd.saveException, { id: existing?.id, projectId: v.projectId, ruleId: v.ruleId, scope: v.scope, reason: v.reason, riskAccepted: v.riskAccepted, compensatingMeasures: v.compensatingMeasures, ownerId: v.ownerId, approverId: v.approverId || undefined, expiresAt: nowOf(s) + v.days * DAY, subject: v.bindVersion && dl ? { deliverableId: dl.id, version: existing?.subject?.version ?? dl.current } : undefined }, { opId: existing ? undefined : opId, success: 'Brouillon d’exception enregistré' });
    if (out.ok && !existing) { setQuery({ nouvelle: null }); navigate(`/tour/exceptions/${out.value}`); }
  };
  return (
    <Panel title={existing ? 'Compléter la demande' : 'Nouvelle demande d’exception'}>
      <p className="small muted">Une demande incomplète reste en brouillon. Une exception interne n’annule pas une obligation externe ; une règle non dérogeable reste bloquante.</p>
      <div className="form-grid">
        <Select label="Projet" value={v.projectId} onChange={(e) => setV({ ...v, projectId: e.target.value })} options={list(s, 'project', s.session.orgId).map((p) => ({ value: p.id, label: p.name }))} />
        <Select label="Règle" value={v.ruleId} placeholder="Choisir…" onChange={(e) => setV({ ...v, ruleId: e.target.value })} options={list(s, 'rule', s.session.orgId).map((r) => ({ value: r.id, label: `${r.code} ${r.versions.at(-1)?.title}${r.versions.at(-1)?.derogable ? '' : ' (non dérogeable)'}` }))} />
        <TextField className="full" label="Périmètre" value={v.scope} onChange={(e) => setV({ ...v, scope: e.target.value })} />
        {dl && <Checkbox label={`Limiter à « ${dl.title} » v${existing?.subject?.version ?? dl.current}`} checked={v.bindVersion} onChange={(e) => setV({ ...v, bindVersion: e.target.checked })} />}
        <TextArea className="full" label="Motif" value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />
        <TextArea label="Risque accepté" value={v.riskAccepted} onChange={(e) => setV({ ...v, riskAccepted: e.target.value })} />
        <TextArea label="Mesures compensatoires" value={v.compensatingMeasures} onChange={(e) => setV({ ...v, compensatingMeasures: e.target.value })} />
        <Select label="Propriétaire" value={v.ownerId ?? ''} placeholder="Choisir…" onChange={(e) => setV({ ...v, ownerId: e.target.value })} options={members.map((m) => ({ value: m, label: s.users[m]?.name ?? m }))} />
        <Select label="Approbateur" value={v.approverId} placeholder="Choisir…" onChange={(e) => setV({ ...v, approverId: e.target.value })} options={members.filter((m) => m !== me).map((m) => ({ value: m, label: s.users[m]?.name ?? m }))} />
        <TextField label="Échéance (jours)" type="number" min={1} value={v.days} onChange={(e) => setV({ ...v, days: Number(e.target.value) })} />
      </div>
      <div className="row end"><Button onClick={() => setQuery({ nouvelle: null })}>Fermer</Button><CmdButton def={cmd.saveException} payload={{ projectId: v.projectId, ruleId: v.ruleId, scope: '', reason: '', riskAccepted: '', compensatingMeasures: '' }} variant="primary" onRun={save}>Enregistrer le brouillon</CmdButton></div>
    </Panel>
  );
}

function ExceptionSheet({ id }: { id: ID }) {
  const s = useAppState();
  const e = s.db.exception[id];
  if (!e || e.orgId !== s.session.orgId) return <NotFound what="Exception" />;
  const st = effectiveExceptionStatus(s, e);
  const findings = list(s, 'finding', s.session.orgId).filter((f) => f.projectId === e.projectId && f.ruleId === e.ruleId);
  return (
    <div className="stack">
      <a href="#/tour/exceptions" className="small">← Toutes les exceptions</a>
      <Panel title={`Exception ${s.db.rule[e.ruleId]?.code} — ${s.db.project[e.projectId]?.name}`} actions={<Lifecycle kind="exception" id={e.id} state={st} />}>
        {st === 'expired' && <Notice tone="warn" title="Exception expirée.">Les nouvelles actions concernées attendent un nouvel examen ; l’historique n’est pas réécrit.</Notice>}
        <KV items={[['Règle', <ObjectLink to={{ kind: 'rule', id: e.ruleId }} />], ['Périmètre', e.scope], ['Version concernée', e.subject ? <ObjectLink to={{ kind: 'deliverable', id: e.subject.deliverableId, version: e.subject.version }} /> : 'Toutes versions du projet'], ['Motif', e.reason], ['Risque accepté', e.riskAccepted || '—'], ['Mesures compensatoires', e.compensatingMeasures || '—'], ['Propriétaire', <Person id={e.ownerId} />], ['Approbateur', <Person id={e.approverId} />], ['Demandée par', <Person id={e.authorId} />], ['Décidée par', <Person id={e.decidedBy} />], ['Échéance', e.expiresAt ? `${fmtDate(e.expiresAt, true)} (${fmtRelative(e.expiresAt, nowOf(s))})` : '—'], ['Motif de décision', e.statusReason ?? '—']]} />
      </Panel>
      {e.status === 'draft' && <ExceptionForm existing={e} />}
      <Panel title="Constats concernés">{findings.length ? <ul className="plain stack tight">{findings.map((f) => <li key={f.id} className="row"><StatusBadge kind="finding" state={f.status} /><ObjectLink to={{ kind: 'finding', id: f.id }} /></li>)}</ul> : <p className="small muted">Aucun.</p>}</Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ reviews */
function Reviews() {
  const s = useAppState();
  const all = list(s, 'approval', s.session.orgId).sort((a, b) => b.createdAt - a.createdAt);
  const expected = all.filter((a) => effectiveApprovalStatus(s, a) === 'expected');
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : null;
  return (
    <div className="stack">
      <Panel title={`Revues humaines en attente (${expected.length})`}>
        <p className="small muted">Chaque approbation porte sur une version et un périmètre déterminés. La séparation auteur-approbateur dépend des identités, pas des rôles. Dans OpenGuildKit, une personne approuve ou refuse dans son propre terminal : chaque bouton montre la commande, puis la démo peut simuler sa saisie. Personne simulée : {me ? s.users[me]?.name : 'un agent ou le système'}.</p>
        {expected.length === 0 ? <Empty title="Aucune revue en attente" /> : (
          <ul className="plain stack tight">
            {expected.map((a) => (
              <li key={a.id} className="card">
                <div className="row between">
                  <span><strong>{objectLabel(s, a.subject)}</strong> <span className="small muted">({a.purpose}, version {a.subject.version})</span></span>
                  <span className="tiny muted">{fmtDate(a.createdAt, true)}</span>
                </div>
                <div className="row small"><span className="muted">Demandée par</span><Person id={a.authorId} /><span className="muted">· assignée à</span>{a.approverId ? <Person id={a.approverId} /> : 'toute personne habilitée'}{a.requireDistinct && <Badge tone="info" icon="shield">deux identités</Badge>}<ObjectLink to={a.subject}>ouvrir</ObjectLink></div>
                <div style={{ marginTop: 6 }}><Lifecycle kind="approval" id={a.id} state="expected" compact /></div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="Historique des validations">
        <table className="data responsive"><thead><tr><th>Objet</th><th>Motif</th><th>État</th><th>Validité</th><th>Décidée par</th><th>Date</th></tr></thead>
          <tbody>{all.filter((a) => effectiveApprovalStatus(s, a) !== 'expected').map((a) => { const st = effectiveApprovalStatus(s, a); const val = approvalValidity(s, a); return <tr key={a.id}><td data-label="Objet"><ObjectLink to={a.subject} /></td><td data-label="Motif">{a.purpose}</td><td data-label="État"><StatusBadge kind="approval" state={st} /></td><td data-label="Validité" className="small">{st === 'approved' ? (val.valid ? 'valide' : val.reason) : a.reason ?? '—'}</td><td data-label="Décidée par"><Person id={a.decidedBy} /></td><td data-label="Date" className="small">{fmtDate(a.decidedAt, true)}</td></tr>; })}</tbody></table>
      </Panel>
    </div>
  );
}

