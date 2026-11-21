/** Documentation: tree, categories, versions, "à actualiser", regeneration and local demo sharing (brief §5.11). */
import { useState } from 'react';
import { dispatch, useAppState } from '@/app/store';
import { navigate, setQuery, useRoute } from '@/app/router';
import { Brand } from '@/app/Brand';
import { cmd } from '@/domain/commands';
import { list, nowOf } from '@/domain/engine';
import { docUpdateReasons, fmtDate, fmtRelative, shareStatus } from '@/domain/selectors';
import type { Deliverable, DocCategory, ID } from '@/domain/types';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Empty, KV, Notice, Panel, Select, Tabs, TextField } from '@/shared/ui/core';
import { CmdButton, Lifecycle, ObjectLink, Person, SimBadge, StatusBadge, Version } from '@/shared/ui/domain';
import { ContentPreview, DiffView, contentText } from '@/shared/ui/content';
import { norm } from '@/app/search';

const CATEGORIES: { id: DocCategory; label: string }[] = [
  { id: 'tutoriel', label: 'Tutoriels' }, { id: 'guide', label: 'Guides' }, { id: 'référence', label: 'Référence technique' }, { id: 'explication', label: 'Explications' },
  { id: 'api', label: 'API' }, { id: 'changelog', label: 'Changelog' }, { id: 'roadmap', label: 'Roadmap' }, { id: 'commercial', label: 'Documents commerciaux' },
];

export function DocsSpace({ tab = 'espace' }: { tab?: string }) {
  const s = useAppState();
  const docs = list(s, 'deliverable', s.session.orgId).filter((d) => d.docCategory);
  const toUpdate = docs.filter((d) => docUpdateReasons(s, d).length).length;
  const shares = list(s, 'share', s.session.orgId).filter((x) => shareStatus(s, x) === 'active').length;
  return (
    <div className="stack">
      <Tabs label="Documentation" value={tab} onChange={(t) => navigate(`/documentation/${t}`)} tabs={[{ id: 'espace', label: 'Espace documentaire', icon: 'scroll', count: toUpdate }, { id: 'partages', label: 'Partages de démonstration', icon: 'link', count: shares }]} />
      {tab === 'partages' ? <Shares /> : <Space docs={docs} />}
    </div>
  );
}

function Space({ docs }: { docs: Deliverable[] }) {
  const s = useAppState();
  const route = useRoute();
  const cat = route.query.get('categorie') ?? '';
  const sel = route.query.get('doc');
  const etat = route.query.get('etat') ?? '';
  const q = route.query.get('q') ?? '';
  const filtered = docs.filter((d) => (!cat || d.docCategory === cat) && (!q || norm(`${d.title} ${contentText(d.versions.find((v) => v.number === d.current)!.content)}`).includes(norm(q)))
    && (!etat || (etat === 'brouillons' ? ['draft', 'review'].includes(d.status) : etat === 'approuves' ? ['approved', 'published'].includes(d.status) : docUpdateReasons(s, d).length > 0)));
  const tree = new Map<string, Deliverable[]>();
  filtered.forEach((d) => { const root = (d.docPath ?? 'Divers').split('/')[0]; tree.set(root, [...(tree.get(root) ?? []), d]); });
  const doc = sel ? s.db.deliverable[sel] : filtered[0];
  return (
    <div className="library-layout">
      <aside className="panel facets open" aria-label="Arborescence">
        <div className="field"><label htmlFor="doc-q" className="sr-only">Rechercher</label><input id="doc-q" type="search" placeholder="Rechercher un document" defaultValue={q} onChange={(e) => setQuery({ q: e.target.value })} /></div>
        <div className="facet" style={{ marginTop: 8 }}>
          <button aria-pressed={!cat} onClick={() => setQuery({ categorie: null })}><span>Toutes les catégories</span><span>{docs.length}</span></button>
          {CATEGORIES.map((c) => <button key={c.id} aria-pressed={cat === c.id} onClick={() => setQuery({ categorie: cat === c.id ? null : c.id })}><span>{c.label}</span><span>{docs.filter((d) => d.docCategory === c.id).length}</span></button>)}
        </div>
        <div className="seg" role="group" aria-label="État" style={{ marginTop: 8, flexWrap: 'wrap' }}>
          {[['', 'Tous'], ['brouillons', 'Brouillons'], ['approuves', 'Approuvés'], ['actualiser', 'À actualiser']].map(([k, l]) => <button key={k} aria-pressed={etat === k} onClick={() => setQuery({ etat: k || null })}>{l}</button>)}
        </div>
        <nav aria-label="Documents" style={{ marginTop: 10 }}>
          {[...tree.entries()].map(([root, items]) => (
            <details key={root} open>
              <summary className="small" style={{ fontWeight: 600, cursor: 'pointer' }}><Icon name="archive" size={12} /> {root}</summary>
              <ul className="plain">{items.map((d) => <li key={d.id}><a href={`#/documentation/espace?doc=${d.id}${cat ? `&categorie=${cat}` : ''}`} aria-current={doc?.id === d.id ? 'page' : undefined} className="nav-item" style={{ padding: '4px 8px' }}><Icon name="scroll" size={12} /><span className="small">{(d.docPath ?? d.title).split('/').slice(1).join(' / ') || d.title}</span>{docUpdateReasons(s, d).length > 0 && <Icon name="stale" size={12} label="à actualiser" />}</a></li>)}</ul>
            </details>
          ))}
          {tree.size === 0 && <p className="small muted">Aucun document.</p>}
        </nav>
      </aside>
      {doc ? <DocView d={doc} /> : <Empty title="Aucun document">Les livrables documentaires (guides, références, commerciaux…) apparaissent ici.</Empty>}
    </div>
  );
}

function DocView({ d }: { d: Deliverable }) {
  const s = useAppState();
  const [compare, setCompare] = useState(false);
  const cur = d.versions.find((v) => v.number === d.current)!;
  const reasons = docUpdateReasons(s, d);
  const prev = d.versions.filter((v) => v.number < d.current && !v.proposal).at(-1);
  const proposal = d.versions.find((v) => v.proposal);
  return (
    <div className="stack">
      <Panel title={d.title} actions={<>{cur.simulated && <SimBadge />}<Version n={d.current} /><Lifecycle kind="deliverable" id={d.id} state={d.status} compact /></>}>
        <div className="row small"><StatusBadge kind="deliverable" state={d.status} />{reasons.length > 0 && <Badge tone="warning" icon="stale">À actualiser</Badge>}<span>Catégorie : {CATEGORIES.find((c) => c.id === d.docCategory)?.label}</span></div>
        <KV items={[['Propriétaire', <Person id={d.ownerId} />], ['Audience', d.audience ?? '—'], ['Versions décrites', cur.describes.map((r) => <span key={r.id + r.version} style={{ marginRight: 8 }}><ObjectLink to={r} /></span>)], ['Objets liés', <>{d.questId && <ObjectLink to={{ kind: 'quest', id: d.questId }} />} <ObjectLink to={{ kind: 'project', id: d.projectId }} /></>], ['Dernière modification', fmtDate(cur.createdAt, true)]]} />
        {reasons.length > 0 && <Notice tone="warn" title="À actualiser :">{reasons.join(' ')} Une régénération crée une proposition ; les versions et validations précédentes sont conservées.</Notice>}
        {proposal && <Notice tone="ai">Proposition v{proposal.number} en attente. <a href={`#/forge/livrables/${d.id}?onglet=versions`}>Adopter ou écarter</a></Notice>}
        <div className="row">
          <CmdButton def={cmd.regenerateDeliverable} payload={{ id: d.id }} size="small" icon="spark" variant="ai" success={(n) => `Proposition v${n} créée`}>Régénérer (proposition)</CmdButton>
          {prev && <Button size="small" icon="history" onClick={() => setCompare((c) => !c)}>{compare ? 'Masquer la comparaison' : `Comparer avec la v${prev.number}`}</Button>}
          <a className="btn small" href={`#/forge/livrables/${d.id}?onglet=editer`}><Icon name="edit" size={14} /> Modifier</a>
          <a className="btn small" href={`#/documentation/partages?doc=${d.id}`}><Icon name="link" size={14} /> Partager</a>
        </div>
      </Panel>
      {compare && prev && <Panel title={`v${prev.number} → v${d.current}`}><DiffView before={contentText(prev.content)} after={contentText(cur.content)} labels={[`v${prev.number}`, `v${d.current}`]} /></Panel>}
      <Panel title={`Contenu v${d.current}`}><ContentPreview content={cur.content} title={d.title} /></Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ shares */
function Shares() {
  const s = useAppState();
  const route = useRoute();
  const docs = list(s, 'deliverable', s.session.orgId).filter((d) => d.docCategory);
  const shares = list(s, 'share', s.session.orgId).sort((a, b) => b.createdAt - a.createdAt);
  const [v, setV] = useState({ deliverableId: route.query.get('doc') ?? docs.find((d) => ['approved', 'published'].includes(d.status))?.id ?? '', audience: 'Administrateurs clients (fictifs)', mode: 'lecture' as 'lecture' | 'contribution', days: 7 });
  const [visitor, setVisitor] = useState<Record<ID, string>>({});
  return (
    <div className="stack">
      <Notice tone="warn" title="Liens de démonstration locaux.">Un lien local ne constitue pas un espace privé sécurisé ni un partage livré à un client. Aucun courriel n’est envoyé ; l’ouverture est simulée dans ce navigateur.</Notice>
      <Panel title="Créer un partage">
        <div className="form-grid">
          <Select label="Document (version approuvée ou publiée)" value={v.deliverableId} onChange={(e) => setV({ ...v, deliverableId: e.target.value })} options={docs.map((d) => ({ value: d.id, label: `${d.title} — v${d.current} (${d.status})` }))} />
          <TextField label="Audience fictive" value={v.audience} onChange={(e) => setV({ ...v, audience: e.target.value })} />
          <Select label="Droit" value={v.mode} onChange={(e) => setV({ ...v, mode: e.target.value as 'lecture' })} options={[{ value: 'lecture', label: 'Lecture' }, { value: 'contribution', label: 'Contribution' }]} />
          <TextField label="Durée (jours)" type="number" min={1} max={90} value={v.days} onChange={(e) => setV({ ...v, days: Number(e.target.value) })} />
        </div>
        <CmdButton def={cmd.createShare} payload={v} variant="primary" icon="link" success="Lien de démonstration créé">Créer le lien</CmdButton>
      </Panel>
      <Panel title={`Partages (${shares.length})`}>
        {shares.length === 0 ? <Empty title="Aucun partage" /> : shares.map((sh) => {
          const st = shareStatus(s, sh);
          const d = s.db.deliverable[sh.deliverableId];
          return (
            <div key={sh.id} className="card" style={{ margin: 3 }}>
              <div className="row between"><strong>{d?.title} <Version n={sh.version} /></strong><span className="row"><StatusBadge kind="share" state={st} /><Lifecycle kind="share" id={sh.id} state={st} compact /></span></div>
              <p className="small" style={{ margin: '4px 0' }}>Audience : {sh.audience} · {sh.mode} · expire {fmtRelative(sh.expiresAt, nowOf(s))} ({fmtDate(sh.expiresAt, true)}) · lien local <code>#/partage/{sh.token}</code></p>
              <div className="row">
                <TextField label="Simuler une ouverture par" value={visitor[sh.id] ?? sh.audience} onChange={(e) => setVisitor({ ...visitor, [sh.id]: e.target.value })} hint="Une personne hors de l’audience est refusée." />
                <CmdButton def={cmd.openShare} payload={{ token: sh.token, visitor: visitor[sh.id] ?? sh.audience }} size="small" icon="eye" success={(o) => `Ouverture simulée : accès ${o}`}>Simuler l’ouverture</CmdButton>
                <a className="btn small" href={`#/partage/${sh.token}`} target="_blank" rel="noopener"><Icon name="external" size={12} /> Ouvrir la vue destinataire</a>
                {st === 'active' && <CmdButton def={cmd.demoExpire} payload={{ kind: 'share', id: sh.id }} size="small" variant="ghost" icon="stale" success="Expiration simulée">Simuler l’expiration</CmdButton>}
              </div>
              {sh.accessLog.length > 0 && <ul className="plain tiny" style={{ marginTop: 6 }}>{[...sh.accessLog].reverse().map((l, i) => <li key={i}>{fmtDate(l.at, true)} — {l.visitor} : <Badge tone={l.outcome === 'autorisé' ? 'success' : 'danger'}>{l.outcome}</Badge></li>)}</ul>}
            </div>
          );
        })}
      </Panel>
    </div>
  );
}

/** Recipient view of a local demo link: authorised, refused, expired or revoked. */
export function SharePage({ token }: { token: string }) {
  const s = useAppState();
  const sh = Object.values(s.db.share).find((x) => x.token === token);
  const [visitor, setVisitor] = useState('');
  const [outcome, setOutcome] = useState<string | null>(null);
  const d = sh ? s.db.deliverable[sh.deliverableId] : undefined;
  const version = d?.versions.find((v) => v.number === sh?.version);
  return (
    <div className="share-page stack">
      <div className="row between"><Brand /><SimBadge label="Lien de démonstration local" /></div>
      {!sh ? <Notice tone="danger" title="Lien introuvable.">Ce lien n’existe pas dans ce navigateur. Les liens de démonstration ne sont pas transmis à un serveur.</Notice> : (
        <>
          <Panel title="Accès au document partagé">
            <p className="small muted">Simulation de la page qu’ouvrirait un destinataire. Indiquez qui ouvre le lien.</p>
            <div className="row"><div className="grow"><TextField label="Vous êtes" value={visitor} onChange={(e) => setVisitor(e.target.value)} placeholder={sh.audience} /></div>
              <Button variant="primary" onClick={() => { const out = dispatch(cmd.openShare, { token, visitor }, {}); if (out.ok) setOutcome(out.value as string); }}>Ouvrir</Button></div>
          </Panel>
          {outcome === 'autorisé' && d && version && <Panel title={`${d.title} — v${version.number} (${sh.mode})`}><ContentPreview content={version.content} title={d.title} /></Panel>}
          {outcome === 'refusé' && <Notice tone="danger" title="Accès refusé.">Ce lien est réservé à l’audience « {sh.audience} ».</Notice>}
          {outcome === 'expiré' && <Notice tone="warn" title="Lien expiré.">Le lien a expiré le {fmtDate(sh.expiresAt, true)}. Demandez un nouveau partage au propriétaire du document.</Notice>}
          {outcome === 'révoqué' && <Notice tone="warn" title="Lien révoqué.">Le propriétaire a révoqué ce partage.</Notice>}
        </>
      )}
      <a href="#/documentation/partages" className="small">← Retour à l’application</a>
    </div>
  );
}
