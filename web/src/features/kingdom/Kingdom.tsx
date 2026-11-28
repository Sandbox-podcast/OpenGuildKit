/** Royaume: map, dashboard, projects (map and list) and the project sheet (brief §5.2). */
import { useEffect, useMemo, useState } from 'react';
import { NotFound } from '@/app/App';
import { dispatch, newOpId, useAppState } from '@/app/store';
import { navigate, routeOf, setQuery, useDirtyGuard, useRoute } from '@/app/router';
import { PLACES, placeCounts } from '@/app/places';
import { cmd } from '@/domain/commands';
import { list } from '@/domain/engine';
import { authorize } from '@/domain/permissions';
import {
  DELIVERABLE_TYPES, LEVELS, POLICIES, fmtDate, kingdomStats, latestResults, nextRecommendedAction, projectRules, questProgress, resultFreshness,
} from '@/domain/selectors';
import type { ID, Project, Relation } from '@/domain/types';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Empty, KV, Notice, Panel, Progress, Segmented, Select, Stat, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { CollectionBar, useCollection } from '@/shared/ui/collection';
import { Dialog } from '@/shared/ui/overlay';
import { ActorLabel, CmdButton, ObjectLink, Person, StatusBadge, Version } from '@/shared/ui/domain';
import { KingdomMap } from './KingdomMap';

/* ------------------------------------------------------------------ kingdom */
export function Kingdom() {
  const s = useAppState();
  const [selected, setSelected] = useState<string | null>(null);
  const [alt, setAlt] = useState(() => window.matchMedia('(max-width: 700px)').matches);
  const focus = s.prefs.mode === 'focus';
  return (
    <div className="stack">
      <ResumeWork />
      {!focus && (
        <div className="kingdom-layout">
          <Panel className="map-panel" title="Carte du Royaume" actions={<Segmented label="Présentation de la carte" value={alt ? 'list' : 'map'} onChange={(v) => setAlt(v === 'list')} options={[{ value: 'map', label: 'Carte', icon: 'map' }, { value: 'list', label: 'Liste', icon: 'list' }]} />}>
            {alt ? <PlacesList /> : <><KingdomMap selected={selected} onSelect={setSelected} /><p className="tiny muted map-help">Les bâtiments ouvrent les espaces. Sélectionnez un territoire pour voir ses projets.</p></>}
          </Panel>
          <SelectionPanel selected={selected} />
        </div>
      )}
      <Dashboard />
    </div>
  );
}

function ResumeWork() {
  const s = useAppState();
  const project = s.session.projectId ? s.db.project[s.session.projectId] : undefined;
  const editable = s.session.orgId && authorize(s, s.session.actor, 'edit', { orgId: s.session.orgId, projectId: project?.id }).ok;
  const next = editable ? nextRecommendedAction(s) : null;
  const projectPath = project ? `#/projets/${project.id}` : '#/royaume/projets';
  const href = next ? `#${typeof next.to === 'string' ? next.to : routeOf(next.to)}` : projectPath;
  return (
    <section className="resume-work" aria-labelledby="resume-title">
      <div className="resume-primary">
        <h2 id="resume-title"><Icon name="flag" size={16} /> À reprendre</h2>
        <a className="resume-action" href={href}>{next?.text ?? (project ? 'Consulter le projet actif' : 'Consulter les projets')} <Icon name="chevron" size={13} /></a>
      </div>
      <div className="resume-project">
        <span className="tiny muted">Projet actif</span>
        {project ? <><a href={`#/projets/${project.id}`}>{project.name}</a><span className="tiny muted">Responsable <Person id={project.ownerId} /></span></> : <a href="#/royaume/projets">Voir les projets</a>}
        {project && s.prefs.mode === 'focus' && <a className="resume-all-projects" href="#/royaume/projets">Tous les projets <Icon name="chevron" size={12} /></a>}
      </div>
    </section>
  );
}

function PlacesList() {
  const s = useAppState();
  const counts = placeCounts(s);
  return (
    <ul className="plain places-list">
      {PLACES.map((p) => {
        const c = counts[p.key];
        return (
          <li key={p.key}>
            <a className="card place-card" href={`#${p.route}`}>
              <Icon name={p.icon} size={20} />
              <span className="grow"><strong className="pixel-font">{p.name}</strong><span className="tiny muted" style={{ display: 'block' }}>{p.role}</span></span>
              {c && <Badge tone={c.tone === 'danger' ? 'danger' : c.tone === 'warning' ? 'warning' : 'info'}>{c.n} {c.label}</Badge>}
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function SelectionPanel({ selected }: { selected: string | null }) {
  const s = useAppState();
  const product = selected ? s.db.product[selected] : undefined;
  if (!product || product.orgId !== s.session.orgId) {
    return <Panel className="selection-panel" title="Suivi de l'organisation"><KingdomCounters /><a className="btn small" href="#/royaume/projets"><Icon name="list" size={14} /> Tous les projets</a></Panel>;
  }
  const projects = list(s, 'project', s.session.orgId).filter((p) => p.productId === product.id);
  const rels = list(s, 'relation', s.session.orgId).filter((r) => r.fromProductId === product.id || r.toProductId === product.id);
  return (
      <Panel className="selection-panel" title={<span className="row"><span className="swatch" style={{ background: product.color }} />{product.name}</span>}>
        <p className="muted">{product.description}</p>
        <KV items={[['Responsable', <Person id={product.ownerId} />], ['Stack', product.stack.join(', ')], ['Dépôts', product.repos.map((r) => r.name).join(', ') || '—']]} />
        <h3 style={{ marginTop: 12 }}>Projets</h3>
        <ul className="plain stack tight">{projects.map((p) => <li key={p.id}><a className="card" href={`#/projets/${p.id}`}><div className="row between"><strong>{p.name}</strong><StatusBadge kind="project" state={p.status} /></div><span className="tiny muted">{p.summary}</span></a></li>)}</ul>
        <h3 style={{ marginTop: 12 }}>Relations</h3>
        <RelationsList rels={rels} />
      </Panel>
  );
}

function KingdomCounters() {
  const s = useAppState();
  const k = kingdomStats(s);
  return (
    <div className="grid-2" style={{ gap: 10 }}>
      <Stat value={k.projects.filter((p) => p.status === 'active').length} label="projets actifs" />
      <Stat value={k.pendingApprovals.length} label={k.pendingApprovals.length === 1 ? 'validation attendue' : 'validations attendues'} tone="info" />
      <Stat value={k.failed.length} label={k.failed.length === 1 ? 'contrôle bloquant échoué' : 'contrôles bloquants échoués'} tone={k.failed.length ? 'danger' : undefined} />
      <Stat value={k.stale.length} label={k.stale.length === 1 ? 'preuve à réévaluer' : 'preuves à réévaluer'} tone={k.stale.length ? 'warning' : undefined} />
    </div>
  );
}

export function RelationsList({ rels }: { rels: Relation[] }) {
  const s = useAppState();
  if (!rels.length) return <p className="small muted">Aucune relation déclarée.</p>;
  return (
    <ul className="plain stack tight">
      {rels.map((r) => <li key={r.id} className="small"><strong>{s.db.product[r.fromProductId]?.name}</strong> <Badge tone="info">{r.kind}</Badge> <strong>{s.db.product[r.toProductId]?.name}</strong><span className="muted"> — {r.note}</span></li>)}
    </ul>
  );
}

function Dashboard() {
  const s = useAppState();
  const k = useMemo(() => kingdomStats(s), [s]);
  const box = (title: string, icon: Parameters<typeof Icon>[0]['name'], count: number, children: React.ReactNode, tone?: 'danger' | 'warn' | 'ai') => (
    <Panel tone={count && tone ? tone : undefined} title={<span className="row"><Icon name={icon} size={16} />{title} <span className={`badge count ${tone === 'danger' && count ? 'danger' : ''}`}>{count}</span></span>}>
      {count === 0 ? <p className="small muted">Rien à signaler.</p> : children}
    </Panel>
  );
  return (
    <section aria-label="Tableau de bord" className="stack">
      <div className="grid-3">
        {box('Décisions en attente', 'council', k.pendingDecisions.length + k.awaitingCouncils.length, <ul className="plain stack tight">{k.awaitingCouncils.map((c) => <li key={c.id}><ObjectLink to={{ kind: 'council', id: c.id }} /> <StatusBadge kind="council" state={c.status} /></li>)}{k.pendingDecisions.map((d) => <li key={d.id}><ObjectLink to={{ kind: 'decision', id: d.id }} /> <StatusBadge kind="decision" state={d.status} /></li>)}</ul>, 'ai')}
        {box('Quêtes bloquées', 'lock', k.blockedQuests.length, <ul className="plain stack tight">{k.blockedQuests.map((q) => <li key={q.id}><ObjectLink to={{ kind: 'quest', id: q.id }} /><span className="tiny muted" style={{ display: 'block' }}>{q.statusReason}</span></li>)}</ul>, 'danger')}
        {box('Contrôles bloquants échoués', 'cross', k.failed.length, <ul className="plain stack tight">{k.failed.map((r) => <li key={r.id}><ObjectLink to={{ kind: 'result', id: r.id }} /><span className="tiny muted" style={{ display: 'block' }}>{s.db.project[r.projectId]?.name}</span></li>)}</ul>, 'danger')}
        {box('Preuves à réévaluer', 'stale', k.stale.length, <ul className="plain stack tight">{k.stale.map((r) => <li key={r.id}><ObjectLink to={{ kind: 'result', id: r.id }} /><span className="tiny muted" style={{ display: 'block' }}>{resultFreshness(s, r).reasons[0]}</span></li>)}</ul>, 'warn')}
        {box('Validations attendues', 'clock', k.pendingApprovals.length, <ul className="plain stack tight">{k.pendingApprovals.map((a) => <li key={a.id}><ObjectLink to={a.subject} /><span className="tiny muted" style={{ display: 'block' }}>{a.purpose} · {a.approverId ? `assignée à ${s.users[a.approverId]?.name}` : 'toute personne habilitée'}</span></li>)}</ul>)}
        {box('Exceptions à échéance', 'shield', k.expiring.length, <ul className="plain stack tight">{k.expiring.map((e) => <li key={e.id}><ObjectLink to={{ kind: 'exception', id: e.id }} /><span className="tiny muted" style={{ display: 'block' }}>échéance {fmtDate(e.expiresAt)}</span></li>)}</ul>, 'warn')}
      </div>
      <Panel title="Dernières modifications" actions={<a href="#/chroniques" className="small">Toutes les chroniques</a>}>
        <ul className="plain timeline">
          {k.recent.map((e) => <li key={e.id}><span className="tiny muted">{fmtDate(e.at, true)}</span> <ActorLabel actor={e.actor} /> <span>{e.summary}</span> {e.provenance !== 'local' && <Badge tone="ai" icon="dice">{e.provenance}</Badge>}</li>)}
        </ul>
      </Panel>
    </section>
  );
}

/* ------------------------------------------------------------------ projects */
export function ProjectsView() {
  const s = useAppState();
  const route = useRoute();
  const view = route.query.get('vue') ?? 'liste';
  const showMap = s.prefs.mode === 'explorer';
  const projects = list(s, 'project', s.session.orgId);
  const products = list(s, 'product', s.session.orgId);
  const filters = [
    { key: 'produit', label: 'Produit', options: products.map((p) => ({ value: p.id, label: p.name })), test: (p: Project, v: string) => p.productId === v },
    { key: 'etat', label: 'État', options: [{ value: 'active', label: 'Actifs' }, { value: 'archived', label: 'Archivés' }], test: (p: Project, v: string) => p.status === v },
    { key: 'favoris', label: 'Favoris', options: [{ value: 'oui', label: 'Favoris seulement' }], test: (p: Project) => s.prefs.favoriteProjects.includes(p.id) },
  ];
  const sorts = [{ key: 'nom', label: 'Nom', compare: (a: Project, b: Project) => a.name.localeCompare(b.name) }, { key: 'recent', label: 'Plus récents', compare: (a: Project, b: Project) => b.createdAt - a.createdAt }];
  const c = useCollection(projects, { text: (p) => `${p.name} ${p.summary} ${s.db.product[p.productId]?.name}`, filters, sorts });
  const [form, setForm] = useState<Project | 'new' | null>(route.query.get('nouveau') ? 'new' : null);
  const canEdit = authorize(s, s.session.actor, 'edit', { orgId: s.session.orgId! });
  return (
    <Panel title="Projets" actions={<>
      {showMap && <Segmented label="Vue" value={view} onChange={(v) => setQuery({ vue: v })} options={[{ value: 'liste', label: 'Liste', icon: 'list' }, { value: 'carte', label: 'Carte', icon: 'map' }]} />}
      <span className="btn-wrap"><Button variant="primary" icon="plus" disabled={!canEdit.ok} title={canEdit.reason} onClick={() => setForm('new')}>Nouveau projet</Button>{!canEdit.ok && <span className="why">{canEdit.reason}</span>}</span>
    </>}>
      <CollectionBar c={c} filters={filters} sorts={sorts} total={projects.length} placeholder="Rechercher un projet" />
      {showMap && view === 'carte' ? <KingdomMap selected={null} onSelect={(k) => setQuery({ produit: k, vue: 'liste' })} /> : (
        c.items.length === 0 ? <Empty title="Aucun projet ne correspond">Modifiez la recherche ou les filtres, ou créez un projet.</Empty> : (
          <div className="grid-auto">
            {c.items.map((p) => {
              const prod = s.db.product[p.productId];
              const quests = list(s, 'quest', s.session.orgId).filter((q) => q.projectId === p.id);
              const fav = s.prefs.favoriteProjects.includes(p.id);
              return (
                <article key={p.id} className="card project-card" style={{ borderTop: `4px solid ${prod?.color}` }}>
                  <div className="row between">
                    <a href={`#/projets/${p.id}`}><h3>{p.name}</h3></a>
                    <button className="btn ghost icon small" aria-pressed={fav} aria-label={fav ? 'Retirer des favoris' : 'Ajouter aux favoris'} onClick={() => dispatch(cmd.toggleFavoriteProject, { id: p.id }, { silent: true })}><Icon name="star" size={14} className={fav ? 'fav-on' : ''} /></button>
                  </div>
                  <p className="small muted">{p.summary}</p>
                  <div className="row small"><StatusBadge kind="project" state={p.status} /><span>{prod?.name}</span><Version n={p.blueprintVersion} label="Blueprint v" /></div>
                  <div className="row small" style={{ marginTop: 6 }}><Person id={p.ownerId} /> <span className="muted">· {quests.length} quête(s)</span></div>
                </article>
              );
            })}
          </div>
        )
      )}
      <ProjectForm open={!!form} project={form === 'new' ? undefined : form ?? undefined} onClose={() => { setForm(null); setQuery({ nouveau: null }); }} />
    </Panel>
  );
}

function ProjectForm({ open, project, onClose }: { open: boolean; project?: Project; onClose: () => void }) {
  const s = useAppState();
  const draftKey = `project-form:${project?.id ?? 'new'}`;
  const blank = { name: '', summary: '', productId: list(s, 'product', s.session.orgId)[0]?.id ?? '', ownerId: s.session.actor.type === 'human' ? s.session.actor.userId : '', environments: 'Développement, Recette, Production', storage: 'PostgreSQL', dataSensitivity: 'Données personnelles', linked: [] as string[] };
  const initial = project ? { name: project.name, summary: project.summary, productId: project.productId, ownerId: project.ownerId ?? '', environments: project.environments.join(', '), storage: project.storage.join(', '), dataSensitivity: project.dataSensitivity, linked: project.linkedProductIds } : blank;
  const [v, setV] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [opId] = useState(newOpId);
  useEffect(() => { if (open) { setV((s.drafts[draftKey] as typeof initial) ?? initial); setError(null); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps -- INTENTIONAL(#522): the form resets when it opens, not when its initial values change
  const dirty = open && JSON.stringify(v) !== JSON.stringify(initial);
  useDirtyGuard(draftKey, dirty);
  const members = [...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))];
  const submit = () => {
    const payload = { name: v.name, summary: v.summary, productId: v.productId, ownerId: v.ownerId || undefined, environments: v.environments.split(',').map((x) => x.trim()).filter(Boolean), storage: v.storage.split(',').map((x) => x.trim()).filter(Boolean), dataSensitivity: v.dataSensitivity, linkedProductIds: v.linked };
    const out = project ? dispatch(cmd.updateProject, { ...payload, id: project.id }, { silent: true, success: 'Projet modifié' }) : dispatch(cmd.createProject, payload, { silent: true, opId, success: 'Projet créé' });
    if (!out.ok) { setError(out.reason); return; }
    dispatch(cmd.saveDraft, { key: draftKey, value: undefined }, { silent: true });
    onClose();
    if (!project && out.value) navigate(`/projets/${out.value}`);
  };
  return (
    <Dialog open={open} onClose={() => { if (dirty) dispatch(cmd.saveDraft, { key: draftKey, value: v }, { silent: true }); onClose(); }} title={project ? `Modifier « ${project.name} »` : 'Nouveau projet'} footer={<>
      <span className="small muted grow">{dirty ? 'Brouillon conservé si vous fermez.' : ''}</span>
      <Button onClick={onClose}>Annuler</Button><Button variant="primary" onClick={submit}>{project ? 'Enregistrer' : 'Créer le projet'}</Button>
    </>}>
      {error && <Notice tone="danger">{error}</Notice>}
      <div className="form-grid">
        <TextField className="full" label="Nom" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} error={error && /nom/i.test(error) ? error : null} />
        <TextArea className="full" label="Synthèse" value={v.summary} onChange={(e) => setV({ ...v, summary: e.target.value })} />
        <Select label="Produit principal" value={v.productId} onChange={(e) => setV({ ...v, productId: e.target.value })} options={list(s, 'product', s.session.orgId).map((p) => ({ value: p.id, label: p.name }))} />
        <Select label="Responsable humain" value={v.ownerId} onChange={(e) => setV({ ...v, ownerId: e.target.value })} placeholder="Choisir…" error={error && /responsable/i.test(error) ? error : null} options={members.map((id) => ({ value: id, label: s.users[id]?.name ?? id }))} />
        <TextField label="Environnements" hint="Séparés par des virgules" value={v.environments} onChange={(e) => setV({ ...v, environments: e.target.value })} />
        <TextField label="Stockage" value={v.storage} onChange={(e) => setV({ ...v, storage: e.target.value })} />
        <TextField className="full" label="Sensibilité des données" value={v.dataSensitivity} onChange={(e) => setV({ ...v, dataSensitivity: e.target.value })} />
        <fieldset className="full field" style={{ border: 0, padding: 0 }}>
          <legend className="label">Autres produits concernés</legend>
          <div className="choice-group">{list(s, 'product', s.session.orgId).filter((p) => p.id !== v.productId).map((p) => (
            <label className="choice" key={p.id}><input type="checkbox" checked={v.linked.includes(p.id)} onChange={(e) => setV({ ...v, linked: e.target.checked ? [...v.linked, p.id] : v.linked.filter((x) => x !== p.id) })} /><span>{p.name}</span></label>
          ))}</div>
        </fieldset>
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ project sheet */
const PROJECT_TABS = [
  { id: 'synthese', label: 'Synthèse' }, { id: 'produit', label: 'Produit et dépôts' }, { id: 'technique', label: 'Stack et données' },
  { id: 'architecture', label: 'Architecture' }, { id: 'regles', label: 'Blueprint et règles' }, { id: 'travail', label: 'Quêtes et décisions' },
  { id: 'livrables', label: 'Livrables et documentation' }, { id: 'controles', label: 'Contrôles et risques' }, { id: 'activite', label: 'Activité et versions' },
];

export function ProjectSheet({ id }: { id?: ID }) {
  const s = useAppState();
  const route = useRoute();
  const tab = route.query.get('onglet') ?? 'synthese';
  const [edit, setEdit] = useState(false);
  const p = id ? s.db.project[id] : undefined;
  if (!p || p.orgId !== s.session.orgId) return <NotFound what="Projet" />;
  const prod = s.db.product[p.productId];
  const orgId = s.session.orgId;
  const quests = list(s, 'quest', orgId).filter((q) => q.projectId === p.id);
  const completed = quests.filter((q) => q.status === 'done').length;
  const blocked = quests.filter((q) => q.status === 'blocked').length;
  const workSummary = [quests.length, completed ? `${completed} ${completed === 1 ? 'terminée' : 'terminées'}` : '', blocked ? `${blocked} ${blocked === 1 ? 'bloquée' : 'bloquées'}` : ''].filter((item) => item !== '').join(' · ');
  const decisions = list(s, 'decision', orgId).filter((d) => d.projectId === p.id);
  const councils = list(s, 'council', orgId).filter((c) => c.projectId === p.id);
  const deliverables = list(s, 'deliverable', orgId).filter((d) => d.projectId === p.id);
  const results = latestResults(s, p.id);
  const findings = list(s, 'finding', orgId).filter((f) => f.projectId === p.id);
  const events = list(s, 'event', orgId).filter((e) => e.projectId === p.id).sort((a, b) => b.at - a.at);
  const rules = projectRules(s, p);
  const rels = list(s, 'relation', orgId).filter((r) => r.fromProductId === p.productId || r.toProductId === p.productId);
  return (
    <div className="stack">
      <Panel title="Projet" actions={<>
        <StatusBadge kind="project" state={p.status} />
        <Button size="small" icon="star" aria-pressed={s.prefs.favoriteProjects.includes(p.id)} onClick={() => dispatch(cmd.toggleFavoriteProject, { id: p.id }, { silent: true })}>{s.prefs.favoriteProjects.includes(p.id) ? 'Favori' : 'Ajouter aux favoris'}</Button>
        {s.session.projectId !== p.id && <Button size="small" icon="flag" onClick={() => dispatch(cmd.setProjectContext, { projectId: p.id }, { success: 'Projet de travail sélectionné' })}>Travailler sur ce projet</Button>}
        <CmdButton def={cmd.updateProject} payload={{ id: p.id, name: p.name, summary: p.summary, productId: p.productId, ownerId: p.ownerId, environments: p.environments, storage: p.storage, dataSensitivity: p.dataSensitivity, linkedProductIds: p.linkedProductIds }} size="small" icon="edit" showReason={false} onRun={() => setEdit(true)}>Modifier</CmdButton>
        {p.status === 'active'
          ? <CmdButton def={cmd.archiveProject} payload={{ id: p.id, reason: '' }} size="small" icon="archive" variant="danger" success="Projet archivé" confirm={{ title: `Archiver « ${p.name} »`, message: <p>Le projet reste consultable avec tout son historique ; aucune nouvelle opération ne sera acceptée.</p>, needsReason: true, danger: true, label: 'Archiver' }}>Archiver</CmdButton>
          : <CmdButton def={cmd.restoreProject} payload={{ id: p.id }} size="small" icon="replace" success="Projet restauré">Restaurer</CmdButton>}
      </>}>
        {p.status === 'archived' && <Notice tone="warn" title="Projet archivé.">{p.statusReason} Il reste consultable ; les nouvelles opérations sont refusées.</Notice>}
        <p className="muted">{p.summary}</p>
        <div className="row project-context">
          <span className="small muted">Responsable <Person id={p.ownerId} showRole /></span>
          <a className="btn small" href={`#/projets/${p.id}?onglet=regles`}>Consulter les règles</a>
          <a className="btn small" href={`#/projets/${p.id}?onglet=travail`}>Voir les quêtes et décisions</a>
        </div>
      </Panel>
      <Tabs label="Fiche projet" tabs={PROJECT_TABS} value={tab} onChange={(t) => setQuery({ onglet: t })} />
      {tab === 'synthese' && (
        <div className="grid-2">
          <Panel title="Synthèse">
            <KV items={[['Produit principal', prod?.name], ['Blueprint suivi', <a href={`#/projets/${p.id}?onglet=regles`}><Version n={p.blueprintVersion} label="v" /></a>], ['Créé le', fmtDate(p.createdAt)], ['Données', p.dataSensitivity]]} />
          </Panel>
          <Panel title="État du travail">
            <KV items={[['Quêtes', workSummary], ['Décisions', decisions.length], ['Livrables', deliverables.length], ['Contrôles échoués', results.filter((r) => r.outcome === 'failed').length], ['Constats ouverts', findings.filter((f) => f.status === 'open').length]]} />
          </Panel>
        </div>
      )}
      {tab === 'produit' && (
        <Panel title={`Produit ${prod?.name}`}>
          <p className="muted">{prod?.description}</p>
          <table className="data"><thead><tr><th>Dépôt</th><th>Langage</th><th>Modules</th></tr></thead><tbody>{prod?.repos.map((r) => <tr key={r.id}><td className="mono">{r.name}</td><td>{r.language}</td><td>{r.modules.map((m) => m.name).join(', ')}</td></tr>)}</tbody></table>
          <h3 style={{ marginTop: 12 }}>Autres produits concernés</h3>
          {p.linkedProductIds.length ? <ul className="bullets">{p.linkedProductIds.map((x) => <li key={x}>{s.db.product[x]?.name}</li>)}</ul> : <p className="small muted">Aucun.</p>}
        </Panel>
      )}
      {tab === 'technique' && <Panel title="Stack, environnements et stockage"><KV items={[['Stack', prod?.stack.join(', ')], ['Environnements', p.environments.join(', ')], ['Stockage', p.storage.join(', ')], ['Sensibilité des données', p.dataSensitivity]]} /></Panel>}
      {tab === 'architecture' && <ArchitectureTab productId={p.productId} rels={rels} />}
      {tab === 'regles' && (
        <Panel title={`Règles actives (Blueprint v${p.blueprintVersion})`} actions={<a className="small" href="#/blueprint/impacts">Voir les impacts d’une autre version</a>}>
          {rules.conflicts.map((c) => <Notice key={c.message} tone="warn">{c.message}</Notice>)}
          <table className="data responsive"><thead><tr><th>Règle</th><th>Niveau</th><th>Politique</th><th>Criticité</th><th>Version</th></tr></thead>
            <tbody>{rules.rules.map((e) => <tr key={e.rule.id}><td data-label="Règle"><a href={`#/blueprint/structure?regle=${e.rule.id}`}><strong>{e.rule.code}</strong></a> {e.version.title}{e.overriddenBy && <span className="tiny muted" style={{ display: 'block' }}>Adaptée par {s.db.rule[e.overriddenBy.ruleId]?.code}</span>}</td><td data-label="Niveau">{LEVELS[e.version.scope.level].label}</td><td data-label="Politique">{POLICIES[e.version.policy].label}</td><td data-label="Criticité">{e.version.criticality}{e.version.blocking && <Badge tone="danger" icon="lock">bloquante</Badge>}</td><td data-label="Version"><Version n={e.ref.version} /></td></tr>)}</tbody></table>
        </Panel>
      )}
      {tab === 'travail' && (
        <div className="grid-2">
          <Panel title="Quêtes">{quests.length === 0 ? <Empty title="Aucune quête">Créez une quête ou convertissez une décision.</Empty> : <ul className="plain stack tight">{quests.map((q) => { const pr = questProgress(s, q); return <li key={q.id}><a className="card" href={`#/quetes/${q.id}`}><div className="row between"><strong>{q.title}</strong><StatusBadge kind="quest" state={q.status} /></div><Progress value={pr.pct} label={`Avancement de ${q.title}`} /><span className="tiny muted">{pr.done}/{pr.total} conditions — indicatif</span></a></li>; })}</ul>}</Panel>
          <Panel title="Conseils et décisions">
            <ul className="plain stack tight">{councils.map((c) => <li key={c.id}><ObjectLink to={{ kind: 'council', id: c.id }} /> <StatusBadge kind="council" state={c.status} /></li>)}{decisions.map((d) => <li key={d.id}><ObjectLink to={{ kind: 'decision', id: d.id }} /> <StatusBadge kind="decision" state={d.status} /></li>)}</ul>
            {!councils.length && !decisions.length && <p className="small muted">Aucune session ni décision.</p>}
          </Panel>
        </div>
      )}
      {tab === 'livrables' && (
        <Panel title="Livrables et documentation">
          {deliverables.length === 0 ? <Empty title="Aucun livrable" /> : <table className="data responsive"><thead><tr><th>Livrable</th><th>Type</th><th>État</th><th>Version</th></tr></thead><tbody>{deliverables.map((d) => <tr key={d.id}><td data-label="Livrable"><a href={`#/forge/livrables/${d.id}`}>{d.title}</a></td><td data-label="Type">{DELIVERABLE_TYPES[d.type].label}</td><td data-label="État"><StatusBadge kind="deliverable" state={d.status} /></td><td data-label="Version"><Version n={d.current} /></td></tr>)}</tbody></table>}
        </Panel>
      )}
      {tab === 'controles' && (
        <div className="grid-2">
          <Panel title="Derniers résultats de contrôle">{results.length === 0 ? <p className="small muted">Aucun contrôle exécuté.</p> : <ul className="plain stack tight">{results.map((r) => <li key={r.id} className="row"><StatusBadge kind="result" state={r.outcome} /><StatusBadge kind="freshness" state={resultFreshness(s, r).state} /><ObjectLink to={{ kind: 'result', id: r.id }} /></li>)}</ul>}</Panel>
          <Panel title="Constats et risques">{findings.length === 0 ? <p className="small muted">Aucun constat.</p> : <ul className="plain stack tight">{findings.map((f) => <li key={f.id} className="row"><StatusBadge kind="finding" state={f.status} /><Badge tone={f.severity === 'critique' || f.severity === 'haute' ? 'danger' : 'warning'}>{f.severity}</Badge><ObjectLink to={{ kind: 'finding', id: f.id }} /></li>)}</ul>}</Panel>
        </div>
      )}
      {tab === 'activite' && (
        <Panel title="Activité et versions">
          <ul className="plain timeline">{events.map((e) => <li key={e.id}><span className="tiny muted">{fmtDate(e.at, true)}</span> <ActorLabel actor={e.actor} /> {e.summary} {e.justification && <span className="tiny muted">— {e.justification}</span>}</li>)}</ul>
        </Panel>
      )}
      <ProjectForm open={edit} project={p} onClose={() => setEdit(false)} />
    </div>
  );
}

function ArchitectureTab({ productId, rels }: { productId: ID; rels: Relation[] }) {
  const s = useAppState();
  const products = list(s, 'product', s.session.orgId);
  const [form, setForm] = useState({ toProductId: products.find((p) => p.id !== productId)?.id ?? '', kind: 'appelle' as Relation['kind'], note: '' });
  return (
    <div className="grid-2">
      <Panel title="Relations d’architecture">
        <p className="small muted">Les relations entre applications sont des objets du modèle ; elles ne fusionnent ni les droits ni les profils.</p>
        <ArchitectureDiagram productId={productId} rels={rels} />
        <ul className="plain stack tight">
          {rels.map((r) => (
            <li key={r.id} className="row between">
              <span className="small"><strong>{s.db.product[r.fromProductId]?.name}</strong> {r.kind} <strong>{s.db.product[r.toProductId]?.name}</strong> — {r.note}</span>
              <CmdButton def={cmd.removeRelation} payload={{ id: r.id, reason: '' }} size="small" variant="ghost" icon="trash" showReason={false} confirm={{ title: 'Retirer la relation', needsReason: true, danger: true, label: 'Retirer' }}>Retirer</CmdButton>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="Déclarer une relation">
        <div className="stack">
          <Select label="Produit lié" value={form.toProductId} onChange={(e) => setForm({ ...form, toProductId: e.target.value })} options={products.filter((p) => p.id !== productId).map((p) => ({ value: p.id, label: p.name }))} />
          <Select label="Nature" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Relation['kind'] })} options={['appelle', 'dépend de', 'partage des données', 'intègre'].map((x) => ({ value: x, label: x }))} />
          <TextField label="Précision" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          <CmdButton def={cmd.addRelation} payload={{ fromProductId: productId, ...form }} variant="primary" icon="link" success="Relation ajoutée">Ajouter la relation</CmdButton>
        </div>
      </Panel>
    </div>
  );
}

function ArchitectureDiagram({ productId, rels }: { productId: ID; rels: Relation[] }) {
  const s = useAppState();
  const ids = [...new Set([productId, ...rels.flatMap((r) => [r.fromProductId, r.toProductId])])];
  const pos = (i: number) => (i === 0 ? { x: 200, y: 110 } : { x: 200 + Math.cos((i / (ids.length - 1)) * Math.PI * 2) * 150, y: 110 + Math.sin((i / (ids.length - 1)) * Math.PI * 2) * 80 });
  return (
    <svg viewBox="0 0 400 220" className="arch-svg" role="img" aria-label={`Relations de ${s.db.product[productId]?.name} : ${rels.map((r) => `${s.db.product[r.fromProductId]?.name} ${r.kind} ${s.db.product[r.toProductId]?.name}`).join(' ; ')}`}>
      {rels.map((r) => { const a = pos(ids.indexOf(r.fromProductId)); const b = pos(ids.indexOf(r.toProductId)); return <g key={r.id}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#565e7e" strokeWidth="2" strokeDasharray={r.kind === 'partage des données' ? '4 3' : undefined} /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} fill="#b9bdc9" fontSize="10" textAnchor="middle">{r.kind}</text></g>; })}
      {ids.map((id, i) => { const p = pos(i); const prd = s.db.product[id]; return <g key={id}><rect x={p.x - 58} y={p.y - 14} width="116" height="28" fill="#222840" stroke={prd?.color} strokeWidth="3" /><text x={p.x} y={p.y + 4} fill="#f3f0e8" fontSize="12" textAnchor="middle">{prd?.name}</text></g>; })}
    </svg>
  );
}
