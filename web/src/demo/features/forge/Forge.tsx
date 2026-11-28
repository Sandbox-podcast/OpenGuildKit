/** Forge: skills, execution queue and detail, deliverable studio, versions, updates and restoration (brief §5.8). */
import { useEffect, useMemo, useState } from 'react';
import { NotFound } from '@/demo/app/App';
import { dispatch, newOpId, useAppState } from '@/demo/app/store';
import { navigate, setQuery, useDirtyGuard, useRoute } from '@/shared/router';
import { cmd } from '@/demo/domain/commands';
import { list } from '@/demo/domain/engine';
import { stateDef } from '@/demo/domain/machines';
import { DELIVERABLE_TYPES, docUpdateReasons, fmtDate, lineage, objectLabel } from '@/demo/domain/selectors';
import type { Content, Deliverable, DeliverableType, ID, Run, Skill } from '@/demo/domain/types';
import { download, exportDeliverable, FORMAT_LABELS, formatsFor, type ExportFormat } from '@/demo/adapters/export';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Empty, KV, Notice, Panel, Select, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { CollectionBar, useCollection } from '@/demo/ui/collection';
import { Dialog } from '@/shared/ui/overlay';
import { ActorLabel, ApprovalList, CmdButton, Lifecycle, ObjectLink, Person, SimBadge, StatusBadge, Version } from '@/demo/ui/domain';
import { ContentPreview, DiffView, contentText } from '@/demo/ui/content';

const TABS = [
  { id: 'skills', label: 'Skills et outils', icon: 'anvil' as const }, { id: 'executions', label: 'Exécutions', icon: 'play' as const },
  { id: 'studio', label: 'Livrables', icon: 'scroll' as const }, { id: 'versions', label: 'Versions', icon: 'history' as const },
  { id: 'mises-a-jour', label: 'Mises à jour', icon: 'spark' as const },
];

export function ForgeSpace({ tab = 'studio' }: { tab?: string }) {
  const s = useAppState();
  const running = list(s, 'run', s.session.orgId).filter((r) => r.status === 'running' || r.status === 'suspended').length;
  const updates = list(s, 'skill', s.session.orgId).filter((k) => k.update && ['proposed', 'review'].includes(k.update.status)).length;
  return (
    <div className="stack">
      <Tabs label="Forge" value={tab} onChange={(t) => navigate(`/forge/${t}`)} tabs={TABS.map((t) => ({ ...t, count: t.id === 'executions' ? running : t.id === 'mises-a-jour' ? updates : undefined }))} />
      {tab === 'skills' && <Skills />}
      {tab === 'executions' && <Executions />}
      {tab === 'studio' && <Studio />}
      {tab === 'versions' && <RecentVersions />}
      {tab === 'mises-a-jour' && <Updates />}
    </div>
  );
}

/* ------------------------------------------------------------------ skills */
function Skills() {
  const s = useAppState();
  const route = useRoute();
  const skills = list(s, 'skill', s.session.orgId);
  const selected = route.query.get('skill');
  return (
    <div className="grid-auto">
      {skills.map((k) => <SkillCard key={k.id} k={k} open={selected === k.id} />)}
    </div>
  );
}

function SkillCard({ k, open }: { k: Skill; open: boolean }) {
  const s = useAppState();
  const cur = k.versions.find((v) => v.version === k.installed) ?? k.versions[0];
  const [params, setParams] = useState(k.params);
  const experts = list(s, 'expert', s.session.orgId).filter((e) => e.skillIds.includes(k.id));
  return (
    <article className={`card ${open ? 'selected' : ''}`} id={k.id}>
      <div className="row between"><h3>{k.name}</h3>{k.installed ? (k.active ? <Badge tone="success" icon="check">active</Badge> : <Badge tone="warning">installée, inactive</Badge>) : <Badge tone="muted">non installée</Badge>}</div>
      <p className="small muted">{k.summary}</p>
      <KV items={[['Origine', k.origin], ['Version', k.installed ? <Version n={k.installed} label="" /> : `disponible ${k.versions.at(-1)?.version}`], ['Licence', k.license], ['Dépendances', cur.dependencies.join(', ') || 'aucune'], ['Capacités', k.capabilities.join(', ')], ['Périmètre', k.scope], ['Produit', k.produces ? DELIVERABLE_TYPES[k.produces].label : '—'], ['Permissions', cur.permissions.join(' · ')], ['Utilisée par', experts.map((e) => e.name).join(', ') || '—']]} />
      <div className="row" style={{ marginTop: 8 }}>
        {!k.installed ? <CmdButton def={cmd.installSkill} payload={{ id: k.id }} size="small" variant="primary" success="Skill installée (inactive)">Installer</CmdButton>
          : <CmdButton def={cmd.setSkillActive} payload={{ id: k.id, active: !k.active }} size="small" success={k.active ? 'Skill désactivée' : 'Skill activée'}>{k.active ? 'Désactiver' : 'Activer'}</CmdButton>}
        {k.installed && <CmdButton def={cmd.checkSkillUpdate} payload={{ id: k.id }} size="small" icon="spark" success="Mise à jour proposée" showReason={false}>Vérifier les mises à jour</CmdButton>}
      </div>
      {Object.keys(k.params).length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="small">Paramètres</summary>
          {Object.entries(params).map(([key, val]) => <TextField key={key} label={key} value={val} onChange={(e) => setParams({ ...params, [key]: e.target.value })} />)}
          <CmdButton def={cmd.setSkillParams} payload={{ id: k.id, params }} size="small" success="Paramètres enregistrés">Enregistrer</CmdButton>
        </details>
      )}
      <details><summary className="small">Historique ({k.versions.length} version(s))</summary><ul className="bullets tiny">{k.versions.map((v) => <li key={v.version}>{v.version} — {v.changelog} ({fmtDate(v.publishedAt)})</li>)}</ul></details>
    </article>
  );
}

/* ------------------------------------------------------------------ executions */
const RunSteps = ({ r }: { r: Run }) => <div className="run-steps">{r.steps.map((st, i) => <span key={i} className={st.status}><Icon name={st.status === 'done' ? 'check' : st.status === 'error' ? 'warn' : st.status === 'skipped' ? 'ban' : st.status === 'running' ? 'play' : 'dot'} size={10} />{st.label}</span>)}</div>;

function Executions() {
  const s = useAppState();
  const runs = list(s, 'run', s.session.orgId).sort((a, b) => b.startedAt - a.startedAt);
  const filters = [
    { key: 'etat', label: 'État', options: Object.entries({ running: 'En cours', suspended: 'Suspendue', done: 'Terminée', error: 'Erreur', cancelled: 'Annulée' }).map(([value, label]) => ({ value, label })), test: (r: Run, v: string) => r.status === v },
    { key: 'type', label: 'Type', options: [{ value: 'control', label: 'Contrôle' }, { value: 'skill', label: 'Skill' }], test: (r: Run, v: string) => r.kind === v },
  ];
  const c = useCollection(runs, { text: (r) => r.title, filters });
  const org = s.orgs[s.session.orgId!];
  return (
    <Panel title="File d’exécution" actions={<><SimBadge label="Exécutions simulées" /><span className="small muted">Budget : {org.settings.budget.used}/{org.settings.budget.monthlyUnits} unités</span></>}>
      <CollectionBar c={c} filters={filters} total={runs.length} placeholder="Rechercher une exécution" />
      {c.items.length === 0 ? <Empty title="Aucune exécution" /> : (
        <table className="data responsive">
          <thead><tr><th>Exécution</th><th>État</th><th>Étapes</th><th>Tentative</th><th>Lancée</th><th>Actions</th></tr></thead>
          <tbody>{c.items.map((r) => (
            <tr key={r.id}>
              <td data-label="Exécution"><a href={`#/forge/executions/${r.id}`}>{r.title}</a><span className="tiny muted" style={{ display: 'block' }}>{s.db.project[r.projectId]?.name}</span></td>
              <td data-label="État"><StatusBadge kind="run" state={r.status} />{r.status === 'running' && <span className="anvil-work" style={{ marginLeft: 8 }} />}</td>
              <td data-label="Étapes">{r.stepIndex}/{r.steps.length}</td>
              <td data-label="Tentative">{r.attempt}</td>
              <td data-label="Lancée" className="small">{fmtDate(r.startedAt, true)}</td>
              <td data-label="Actions"><div className="row"><Lifecycle kind="run" id={r.id} state={r.status} compact />{['error', 'cancelled', 'done'].includes(r.status) && <CmdButton def={cmd.retryRun} payload={{ runId: r.id }} size="small" icon="replace" success="Nouvelle tentative lancée" showReason={false}>Relancer</CmdButton>}</div></td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </Panel>
  );
}

export function RunPage({ id }: { id: ID }) {
  const s = useAppState();
  const r = s.db.run[id];
  if (!r || r.orgId !== s.session.orgId) return <NotFound what="Exécution" />;
  const result = list(s, 'result', s.session.orgId).find((item) => item.id === r.resultId && item.runId === r.id);
  const evidence = list(s, 'evidence', s.session.orgId).filter((e) => e.runId === r.id);
  const next = list(s, 'run', s.session.orgId).filter((x) => x.previousRunId === r.id);
  return (
    <div className="stack">
      <Panel title={r.title} actions={<><SimBadge /><StatusBadge kind="run" state={r.status} /><Lifecycle kind="run" id={r.id} state={r.status} compact />{['error', 'cancelled', 'done'].includes(r.status) && <CmdButton def={cmd.retryRun} payload={{ runId: r.id }} size="small" icon="replace" success="Nouvelle tentative lancée" onDone={(nid) => navigate(`/forge/executions/${nid}`)}>Relancer</CmdButton>}</>}>
        {r.status === 'error' && <Notice tone="danger" title="Erreur technique">{r.statusReason} Aucun résultat de contrôle disponible.</Notice>}
        {r.status === 'cancelled' && <Notice tone="warn" title="Annulée :">{r.statusReason} Aucune mise à jour ultérieure ne sera appliquée.</Notice>}
        <RunSteps r={r} />
      </Panel>
      <div className="grid-2">
        <Panel title="Contexte et entrées">
          <KV items={[
            ['Projet', <ObjectLink to={{ kind: 'project', id: r.projectId }} />], ['Quête', r.questId ? <ObjectLink to={{ kind: 'quest', id: r.questId }} /> : '—'],
            ['Type', r.kind === 'control' ? `Contrôle ${s.db.control[r.controlId!]?.code}` : `Skill ${s.db.skill[r.skillId!]?.name}`],
            ['Objet évalué', r.inputs.subject ? <ObjectLink to={{ kind: 'deliverable', id: r.inputs.subject.deliverableId, version: r.inputs.subject.version }} /> : '—'],
            ['Blueprint', <Version n={r.inputs.blueprintVersion} />], ['Règles', r.inputs.rules.map((x) => `${s.db.rule[x.ruleId]?.code} v${x.version}`).join(', ') || '—'],
            ['Version du contrôle', r.inputs.controlVersion ?? '—'], ['Paramètres', Object.entries(r.inputs.params).map(([k, v]) => `${k} : ${v}`).join(' · ') || '—'],
            ['Lancée par', <ActorLabel actor={r.actor} />], ['Limites', `${r.costPerStep} unité(s) par étape ; ${r.suspendable ? 'suspension possible' : 'non suspendable'}`],
            ['Tentative', <>{r.attempt}{r.previousRunId && <> · précédente <ObjectLink to={{ kind: 'run', id: r.previousRunId }} /></>}{next.map((n) => <span key={n.id}> · suivante <ObjectLink to={{ kind: 'run', id: n.id }} /></span>)}</>],
          ]} />
        </Panel>
        <Panel title="Résultat et preuve">
          {!result ? <p className="small muted">{r.kind === 'skill' ? (r.outputDeliverableId ? <>Livrable produit : <ObjectLink to={{ kind: 'deliverable', id: r.outputDeliverableId }} /></> : 'Aucun livrable produit.') : 'Aucun résultat : l’exécution ne s’est pas terminée normalement.'}</p> : (
            <>
              <div className="row"><StatusBadge kind="result" state={result.outcome} /><a href={`#/tour/preuves?resultat=${result.id}`}>Voir le résultat</a></div>
              <p className="small">{result.observation}</p>
              {evidence.map((e) => <p key={e.id} className="small"><Icon name="shield" size={12} /> Preuve <code>{e.digest}</code> — {fmtDate(e.at, true)} · <a href={`#/tour/preuves?preuve=${e.id}`}>lire la preuve</a></p>)}
            </>
          )}
        </Panel>
      </div>
      <Panel title="Journal"><div className="log" role="log">{r.log.map((l, i) => <div key={i} className={`lvl-${l.level}`}><time>{new Date(l.at).toLocaleTimeString('fr-FR')}</time>{l.text}</div>)}</div></Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ studio */
function Studio() {
  const s = useAppState();
  const route = useRoute();
  const typeParam = route.query.get('type');
  const type = typeParam && Object.hasOwn(DELIVERABLE_TYPES, typeParam) ? typeParam as DeliverableType : null;
  const all = list(s, 'deliverable', s.session.orgId);
  const items = all.filter((d) => !type || d.type === type);
  const c = useCollection(items, { text: (d) => `${d.title} ${DELIVERABLE_TYPES[d.type].label}`, prefix: 's' });
  const creating = route.query.get('nouveau') === '1';
  const running = list(s, 'run', s.session.orgId).filter((r) => r.kind === 'skill' && r.status === 'running');
  return (
    <div className="stack">
      {running.length > 0 && <Notice tone="ai" icon="anvil">Préparation en cours : {running.map((r) => r.title).join(' · ')} <span className="anvil-work" /></Notice>}
      <Panel title="Livrables par type" actions={<CmdButton def={cmd.createDeliverable} payload={{ projectId: s.session.projectId ?? '', type: 'doc', title: 'xxxx' }} variant="primary" icon="plus" onRun={() => setQuery({ nouveau: '1' })}>Nouveau livrable</CmdButton>}>
        <div className="studio-types" style={{ marginBottom: 'var(--gap)' }}>
          {(Object.keys(DELIVERABLE_TYPES) as DeliverableType[]).map((t) => {
            const n = all.filter((d) => d.type === t).length;
            return <button key={t} className={`card ${type === t ? 'selected' : ''}`} aria-pressed={type === t} onClick={() => setQuery({ type: type === t ? null : t })}><strong className="small">{DELIVERABLE_TYPES[t].label}</strong><span className="tiny muted" style={{ display: 'block' }}>{n} {n === 1 ? 'livrable' : 'livrables'}</span></button>;
          })}
        </div>
        <CollectionBar c={c} total={items.length} placeholder="Rechercher un livrable" />
        {c.items.length === 0 ? <Empty title={items.length ? 'Aucun résultat' : type ? 'Aucun livrable de ce type' : 'Aucun livrable'} /> : (
          <table className="data responsive"><thead><tr><th>Livrable</th><th>Type</th><th>État</th><th>Version</th><th>Quête</th><th>Mise à jour</th></tr></thead>
            <tbody>{[...c.items].sort((a, b) => b.createdAt - a.createdAt).map((d) => (
              <tr key={d.id}><td data-label="Livrable"><a href={`#/forge/livrables/${d.id}`}>{d.title}</a>{d.versions.some((v) => v.proposal) && <Badge tone="info" icon="spark">proposition</Badge>}{docUpdateReasons(s, d).length > 0 && <Badge tone="warning" icon="stale">à actualiser</Badge>}</td><td data-label="Type">{DELIVERABLE_TYPES[d.type].label}</td><td data-label="État"><StatusBadge kind="deliverable" state={d.status} /></td><td data-label="Version"><Version n={d.current} /></td><td data-label="Quête">{d.questId ? <ObjectLink to={{ kind: 'quest', id: d.questId }} /> : '—'}</td><td data-label="Mise à jour" className="small">{fmtDate(d.versions.at(-1)?.createdAt)}</td></tr>
            ))}</tbody></table>
        )}
      </Panel>
      <NewDeliverable key={s.session.orgId} open={creating} onClose={() => setQuery({ nouveau: null })} defaultType={type ?? 'doc'} />
    </div>
  );
}

function NewDeliverable({ open, onClose, defaultType }: { open: boolean; onClose: () => void; defaultType: DeliverableType }) {
  const s = useAppState();
  const projects = list(s, 'project', s.session.orgId).filter((p) => p.status === 'active');
  const [v, setV] = useState({ projectId: s.session.projectId ?? projects[0]?.id ?? '', questId: '', type: defaultType, title: '' });
  const [opId] = useState(newOpId);
  useEffect(() => { setV((x) => ({ ...x, type: defaultType })); }, [defaultType]);
  return (
    <Dialog open={open} onClose={onClose} title="Nouveau livrable" footer={<><Button onClick={onClose}>Annuler</Button><Button variant="primary" onClick={() => { const out = dispatch(cmd.createDeliverable, { projectId: v.projectId, questId: v.questId || undefined, type: v.type, title: v.title }, { opId, success: 'Livrable créé (brouillon v1)' }); if (out.ok) { onClose(); navigate(`/forge/livrables/${out.value}`); } }}>Créer</Button></>}>
      <div className="stack">
        <Select label="Type" value={v.type} onChange={(e) => setV({ ...v, type: e.target.value as DeliverableType })} options={(Object.keys(DELIVERABLE_TYPES) as DeliverableType[]).map((t) => ({ value: t, label: DELIVERABLE_TYPES[t].label }))} />
        <TextField label="Titre" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
        <Select label="Projet" value={v.projectId} onChange={(e) => setV({ ...v, projectId: e.target.value })} options={projects.map((p) => ({ value: p.id, label: p.name }))} />
        <Select label="Quête (facultatif)" value={v.questId} placeholder="Aucune" onChange={(e) => setV({ ...v, questId: e.target.value })} options={list(s, 'quest', s.session.orgId).filter((q) => q.projectId === v.projectId).map((q) => ({ value: q.id, label: q.title }))} />
        <p className="small muted">Le livrable commence par un modèle modifiable.</p>
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ deliverable page */
export function DeliverablePage({ id }: { id: ID }) {
  const s = useAppState();
  const route = useRoute();
  const d = s.db.deliverable[id];
  const tab = route.query.get('onglet') ?? 'apercu';
  if (!d || d.orgId !== s.session.orgId) return <NotFound what="Livrable" />;
  const cur = d.versions.find((v) => v.number === d.current)!;
  const proposals = d.versions.filter((v) => v.proposal);
  const reasons = docUpdateReasons(s, d);
  return (
    <div className="stack">
      <Panel title={d.title} actions={<>{cur.simulated && <SimBadge />}<Version n={d.current} /><Lifecycle kind="deliverable" id={d.id} state={d.status} /></>}>
        <div className="row small"><Badge tone="info">{DELIVERABLE_TYPES[d.type].label}</Badge><span>Projet <ObjectLink bare to={{ kind: 'project', id: d.projectId }} /></span>{d.questId && <span>· quête <ObjectLink bare to={{ kind: 'quest', id: d.questId }} /></span>}<span>· responsable <Person id={d.ownerId} /></span>{d.docCategory && <span>· documentation : {d.docCategory}</span>}</div>
        {proposals.length > 0 && <Notice tone="ai" title={`Proposition v${proposals.at(-1)!.number} en attente.`}>La version {d.current} reste en vigueur tant que la proposition n’est pas adoptée. <a href={`#/forge/livrables/${d.id}?onglet=versions`}>Comparer et décider</a></Notice>}
        {reasons.length > 0 && <Notice tone="warn" title="À actualiser :">{reasons.join(' ')}</Notice>}
        <div className="row"><CmdButton def={cmd.regenerateDeliverable} payload={{ id: d.id }} size="small" variant="ai" icon="spark" success={(n) => `Proposition v${n} créée (simulation)`}>Régénérer (proposition)</CmdButton></div>
      </Panel>
      <Tabs label="Livrable" value={tab} onChange={(t) => setQuery({ onglet: t })} tabs={[{ id: 'apercu', label: 'Aperçu', icon: 'eye' }, { id: 'editer', label: 'Modifier', icon: 'edit' }, { id: 'versions', label: 'Versions', icon: 'history', count: proposals.length }, { id: 'validation', label: 'Revue et validation', icon: 'shield' }, { id: 'liens', label: 'Liens et traçabilité', icon: 'link' }, { id: 'export', label: 'Export', icon: 'download' }]} />
      {tab === 'apercu' && <Panel title={`Aperçu v${d.current}`}><ContentPreview content={cur.content} title={d.title} /></Panel>}
      {tab === 'editer' && <Editor d={d} />}
      {tab === 'versions' && <VersionsTab d={d} />}
      {tab === 'validation' && <Panel title="Revue et validation"><p className="small muted">Chaque approbation porte sur une version du livrable.</p><ApprovalList subject={{ kind: 'deliverable', id: d.id }} /></Panel>}
      {tab === 'liens' && <LinksTab d={d} />}
      {tab === 'export' && <ExportTab d={d} />}
    </div>
  );
}

function Editor({ d }: { d: Deliverable }) {
  const cur = d.versions.find((v) => v.number === d.current)!;
  const initial = cur.content.kind === 'markdown' ? cur.content.body : cur.content.kind === 'api' ? cur.content.spec : JSON.stringify(cur.content, null, 2);
  const [text, setText] = useState(initial);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  useDirtyGuard(`deliverable:${d.id}`, text !== initial);
  const parse = (): Content | null => {
    if (cur.content.kind === 'markdown') return { kind: 'markdown', body: text };
    if (cur.content.kind === 'api') return { kind: 'api', spec: text };
    try {
      const parsed = JSON.parse(text) as Content;
      if (parsed.kind !== cur.content.kind) { setError(`Le contenu doit rester de nature « ${cur.content.kind} ».`); return null; }
      return parsed;
    } catch (e) { setError(`JSON invalide : ${(e as Error).message}`); return null; }
  };
  const content = useMemo(() => { try { return cur.content.kind === 'markdown' ? { kind: 'markdown', body: text } as Content : cur.content.kind === 'api' ? { kind: 'api', spec: text } as Content : JSON.parse(text) as Content; } catch { return null; } }, [text, cur.content.kind]);
  return (
    <div className="grid-2">
      <Panel title="Modifier">
        {d.status !== 'draft' && <Notice tone="info">Ce livrable est {stateDef('deliverable', d.status).label.toLowerCase()} : votre modification créera une proposition, sans remplacer la version en vigueur.</Notice>}
        <TextArea label={cur.content.kind === 'markdown' ? 'Contenu (Markdown)' : cur.content.kind === 'api' ? 'Spécification OpenAPI (YAML)' : `Contenu structuré (${cur.content.kind}, JSON)`} className="code-area" value={text} onChange={(e) => { setText(e.target.value); setError(null); }} error={error} />
        <TextField label="Note de version" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="row"><Button onClick={() => setText(initial)} disabled={text === initial}>Annuler les modifications</Button>
          <Button variant="primary" onClick={() => { const c = parse(); if (!c) return; const out = dispatch(cmd.editDeliverable, { id: d.id, content: c, note }, { success: (n) => `Version ${n} enregistrée` }); if (out.ok) setNote(''); }}>Enregistrer une nouvelle version</Button></div>
      </Panel>
      <Panel title="Aperçu en direct">{content ? <ContentPreview content={content} title={d.title} /> : <p className="small muted">Contenu non valide.</p>}</Panel>
    </div>
  );
}

function VersionsTab({ d }: { d: Deliverable }) {
  const [a, setA] = useState(String(Math.max(1, d.current - 1)));
  const [b, setB] = useState(String(d.versions.at(-1)!.number));
  const va = d.versions.find((v) => v.number === Number(a));
  const vb = d.versions.find((v) => v.number === Number(b));
  return (
    <div className="stack">
      <Panel title="Historique des versions">
        <table className="data responsive"><thead><tr><th>Version</th><th>Note</th><th>Auteur</th><th>Date</th><th>Statut</th><th>Actions</th></tr></thead>
          <tbody>{[...d.versions].reverse().map((v) => (
            <tr key={v.number}>
              <td data-label="Version"><Version n={v.number} />{v.simulated && <SimBadge />}</td><td data-label="Note" className="small">{v.note}</td>
              <td data-label="Auteur">{v.authorId ? <Person id={v.authorId} /> : 'Système de démonstration'}</td><td data-label="Date" className="small">{fmtDate(v.createdAt, true)}</td>
              <td data-label="Statut">{v.number === d.current ? <Badge tone="success" icon="check">en vigueur</Badge> : v.proposal ? <Badge tone="info" icon="spark">proposition</Badge> : <Badge tone="muted">historique</Badge>}</td>
              <td data-label="Actions"><div className="row">
                {v.proposal && <><CmdButton def={cmd.adoptDeliverableVersion} payload={{ id: d.id, version: v.number }} size="small" variant="primary" success={`v${v.number} adoptée`}>Adopter</CmdButton><CmdButton def={cmd.dismissProposal} payload={{ id: d.id, version: v.number }} size="small" success="Proposition écartée">Écarter</CmdButton></>}
                {!v.proposal && v.number !== d.current && <CmdButton def={cmd.restoreDeliverableVersion} payload={{ id: d.id, version: v.number, reason: '' }} size="small" icon="replace" success="Restauration par une nouvelle version" confirm={{ title: `Restaurer la v${v.number}`, message: <p>Une nouvelle version reprendra ce contenu ; l’historique est conservé.</p>, needsReason: true, label: 'Restaurer' }}>Restaurer</CmdButton>}
              </div></td>
            </tr>
          ))}</tbody></table>
      </Panel>
      <Panel title="Comparer les versions">
        <div className="row"><Select label="Version de départ" value={a} onChange={(e) => setA(e.target.value)} options={d.versions.map((v) => ({ value: String(v.number), label: `v${v.number}` }))} /><Select label="Version à comparer" value={b} onChange={(e) => setB(e.target.value)} options={d.versions.map((v) => ({ value: String(v.number), label: `v${v.number}` }))} /></div>
        {va && vb && <DiffView before={contentText(va.content)} after={contentText(vb.content)} labels={[`v${a}`, `v${b}`]} />}
      </Panel>
    </div>
  );
}

function LinksTab({ d }: { d: Deliverable }) {
  const s = useAppState();
  const cur = d.versions.find((v) => v.number === d.current)!;
  const chain = lineage(s, { kind: 'deliverable', id: d.id }, 4).filter((x) => x.distance > 0);
  return (
    <div className="grid-2">
      <Panel title="Versions décrites">{cur.describes.length ? <ul className="plain">{cur.describes.map((r) => <li key={`${r.kind}${r.id}`}><ObjectLink to={r} /></li>)}</ul> : <p className="small muted">Aucune source déclarée.</p>}</Panel>
      <Panel title="Chaîne de traçabilité" actions={<a href={`#/chroniques/trace?kind=deliverable&id=${d.id}`} className="small">Ouvrir dans les Chroniques</a>}>
        <ul className="plain stack tight">{chain.slice(0, 18).map((x) => <li key={`${x.ref.kind}${x.ref.id}`} className="small"><Badge tone={x.direction === 'amont' ? 'info' : 'ai'}>{x.direction}</Badge> <ObjectLink to={x.ref} /></li>)}</ul>
        <p className="tiny muted">{objectLabel(s, { kind: 'deliverable', id: d.id })}</p>
      </Panel>
    </div>
  );
}

function ExportTab({ d }: { d: Deliverable }) {
  const cur = d.versions.find((v) => v.number === d.current)!;
  const formats = formatsFor(cur.content);
  const run = (f: ExportFormat) => {
    const out = dispatch(cmd.recordExport, { what: `${d.title} v${d.current}`, format: FORMAT_LABELS[f], count: 1, object: { kind: 'deliverable', id: d.id, version: d.current } }, {});
    if (!out.ok) return;
    const file = exportDeliverable(d, cur, f);
    download(file.filename, file.mime, file.text);
  };
  return (
    <Panel title="Exporter la version en vigueur">
      <p className="small muted">Formats réellement produits pour ce type de contenu. Aucun PDF, PPTX ou MP4 n’est proposé car la démonstration ne les génère pas. {cur.simulated ? 'Le fichier indique que le contenu est simulé.' : ''}</p>
      <div className="row">{formats.map((f) => <CmdButton key={f} def={cmd.recordExport} payload={{ what: d.title, format: f, count: 1 }} icon="download" onRun={() => run(f)}>{FORMAT_LABELS[f]}</CmdButton>)}</div>
      {d.docCategory && <p className="small" style={{ marginTop: 8 }}>Pour partager ce document avec une audience fictive : <a href={`#/documentation/partages?doc=${d.id}`}>Documentation › Partages</a></p>}
    </Panel>
  );
}

/* ------------------------------------------------------------------ versions and updates */
function RecentVersions() {
  const s = useAppState();
  const rows = list(s, 'deliverable', s.session.orgId).flatMap((d) => d.versions.map((v) => ({ d, v }))).sort((a, b) => b.v.createdAt - a.v.createdAt).slice(0, 40);
  const [sel, setSel] = useState<string | null>(null);
  const chosen = rows.find((r) => `${r.d.id}:${r.v.number}` === sel);
  const prev = chosen ? chosen.d.versions.filter((v) => v.number < chosen.v.number).at(-1) : undefined;
  return (
    <div className="grid-2">
      <Panel title="Versions récentes">
        <ul className="plain stack tight">{rows.map(({ d, v }) => (
          <li key={`${d.id}:${v.number}`}><button className={`card ${sel === `${d.id}:${v.number}` ? 'selected' : ''}`} onClick={() => setSel(`${d.id}:${v.number}`)}>
            <div className="row between"><strong className="small">{d.title}</strong><span className="row"><Version n={v.number} />{v.proposal && <Badge tone="info">proposition</Badge>}{v.simulated && <SimBadge />}</span></div>
            <span className="tiny muted">{v.note} · {fmtDate(v.createdAt, true)}</span>
          </button></li>
        ))}</ul>
      </Panel>
      <Panel title="Différences avec la version précédente">
        {!chosen ? <p className="small muted">Sélectionnez une version.</p> : !prev ? <p className="small muted">Première version : aucune version précédente.</p> : <><a href={`#/forge/livrables/${chosen.d.id}?onglet=versions`} className="small">Ouvrir le livrable</a><DiffView before={contentText(prev.content)} after={contentText(chosen.v.content)} labels={[`v${prev.number}`, `v${chosen.v.number}`]} /></>}
      </Panel>
    </div>
  );
}

function Updates() {
  const s = useAppState();
  const skills = list(s, 'skill', s.session.orgId).filter((k) => k.update || k.previous);
  const [reason, setReason] = useState('');
  if (!skills.length) return <Empty title="Aucune mise à jour proposée">Utilisez « Vérifier les mises à jour » dans le catalogue des skills.</Empty>;
  return (
    <div className="stack">
      {skills.map((k) => {
        const cur = k.versions.find((v) => v.version === k.installed)!;
        const next = k.update ? k.versions.find((v) => v.version === k.update!.version) : undefined;
        const added = next ? next.permissions.filter((p) => !cur.permissions.includes(p)) : [];
        return (
          <Panel key={k.id} title={`${k.name} : ${k.installed}${next ? ` → ${next.version}` : ''}`} actions={k.update && <StatusBadge kind="skillUpdate" state={k.update.status} />}>
            {next && (
              <>
                <p className="small">{next.changelog}</p>
                {added.length > 0 && <Notice tone="danger" title="Changement de permission :">{added.join(', ')}. L’adoption doit être examinée ; si elle est faite par la personne qui l’a examinée, une autre personne doit adopter.</Notice>}
                <DiffView before={`Permissions :\n${cur.permissions.join('\n')}\nDépendances :\n${cur.dependencies.join('\n') || 'aucune'}`} after={`Permissions :\n${next.permissions.join('\n')}\nDépendances :\n${next.dependencies.join('\n') || 'aucune'}`} labels={[cur.version, next.version]} />
                <p className="tiny muted">Impacts : {list(s, 'expert', s.session.orgId).filter((e) => e.skillIds.includes(k.id)).map((e) => e.name).join(', ') || 'aucune expertise'} utilise(nt) cette skill. {k.update?.reviewerId && <>Examinée par <Person id={k.update.reviewerId} />.</>}</p>
                {k.update && ['proposed', 'review'].includes(k.update.status) && (
                  <div className="row">
                    <CmdButton def={cmd.decideSkillUpdate} payload={{ id: k.id, action: 'review' }} size="small" icon="eye" success="Mise à jour en revue">Passer en revue</CmdButton>
                    <CmdButton def={cmd.decideSkillUpdate} payload={{ id: k.id, action: 'adopt' }} size="small" variant="primary" success="Mise à jour adoptée">Adopter</CmdButton>
                    <TextField label="Motif pour écarter" value={reason} onChange={(e) => setReason(e.target.value)} />
                    <CmdButton def={cmd.decideSkillUpdate} payload={{ id: k.id, action: 'dismiss', reason }} size="small" variant="danger" success="Mise à jour écartée">Écarter</CmdButton>
                  </div>
                )}
              </>
            )}
            {k.previous && <div className="row" style={{ marginTop: 8 }}><span className="small muted">Version précédente conservée : {k.previous}</span><CmdButton def={cmd.decideSkillUpdate} payload={{ id: k.id, action: 'restore' }} size="small" icon="replace" success="Version précédente restaurée">Restaurer {k.previous}</CmdButton></div>}
          </Panel>
        );
      })}
    </div>
  );
}
