/** Observatory: fictional competitors, sources, signals, trends, comparisons, opportunities and watch settings (brief §5.10). */
import { useState } from 'react';
import { NotFound } from '@/demo/app/App';
import { dispatch, useAppState } from '@/demo/app/store';
import { navigate } from '@/shared/router';
import { cmd } from '@/demo/domain/commands';
import { list } from '@/demo/domain/engine';
import { fmtDate } from '@/demo/domain/selectors';
import type { Competitor, ID, Signal, SignalType } from '@/demo/domain/types';
import { download, toYaml } from '@/demo/adapters/export';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Checkbox, Empty, KV, Notice, Panel, Select, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { CollectionBar, useCollection } from '@/demo/ui/collection';
import { CmdButton, ObjectLink, Person, SimBadge } from '@/demo/ui/domain';

const TYPES: SignalType[] = ['fonctionnalité', 'annonce', 'financement', 'site', 'communication', 'marché', 'écosystème'];
const LEVEL = { faible: 'neutral', moyenne: 'warning', forte: 'danger' } as const;
const Fictif = () => <Badge tone="ai" icon="dice">fictif</Badge>;

export function ObservatorySpace({ tab = 'signaux', id }: { tab?: string; id?: ID }) {
  const s = useAppState();
  const pending = list(s, 'signal', s.session.orgId).filter((x) => x.reevaluation === 'proposed').length;
  return (
    <div className="stack">
      <Tabs label="Observatoire" value={tab} onChange={(t) => navigate(`/observatoire/${t}`)} tabs={[
        { id: 'signaux', label: 'Signaux', icon: 'telescope', count: pending }, { id: 'concurrents', label: 'Concurrents', icon: 'flag' }, { id: 'sources', label: 'Sources', icon: 'link' },
        { id: 'tendances', label: 'Tendances', icon: 'grid' }, { id: 'comparaison', label: 'Comparaison', icon: 'list' }, { id: 'opportunites', label: 'Opportunités', icon: 'star' }, { id: 'parametres', label: 'Paramètres de veille', icon: 'settings' },
      ]} />
      <Notice tone="ai">Toutes les sociétés, sources et informations de l’Observatoire sont fictives et étiquetées comme telles, y compris dans les exports. Une nouvelle information propose une réévaluation : elle ne modifie jamais seule la roadmap.</Notice>
      {tab === 'signaux' && (id ? <SignalSheet id={id} /> : <Signals />)}
      {tab === 'concurrents' && <Competitors />}
      {tab === 'sources' && <Sources />}
      {tab === 'tendances' && <Trends />}
      {tab === 'comparaison' && <Comparison />}
      {tab === 'opportunites' && <Opportunities />}
      {tab === 'parametres' && <WatchSettings />}
    </div>
  );
}

function Signals() {
  const s = useAppState();
  const signals = list(s, 'signal', s.session.orgId).sort((a, b) => b.publishedAt - a.publishedAt);
  const filters = [
    { key: 'type', label: 'Type', options: TYPES.map((t) => ({ value: t, label: t })), test: (x: Signal, v: string) => x.type === v },
    { key: 'pertinence', label: 'Pertinence', options: ['faible', 'moyenne', 'forte'].map((t) => ({ value: t, label: t })), test: (x: Signal, v: string) => x.relevance.level === v },
    { key: 'concurrent', label: 'Concurrent', options: list(s, 'competitor', s.session.orgId).map((c) => ({ value: c.id, label: c.name })), test: (x: Signal, v: string) => x.competitorId === v },
    { key: 'favoris', label: 'Favoris', options: [{ value: 'oui', label: 'Favoris' }], test: (x: Signal) => x.favorite },
  ];
  const c = useCollection(signals, { text: (x) => `${x.title} ${x.context} ${x.facts.join(' ')}`, filters });
  const exportAll = () => {
    const out = dispatch(cmd.recordExport, { what: 'Signaux de veille (fictifs)', format: 'YAML', count: signals.length }, {});
    if (out.ok) download('signaux-fictifs.yaml', 'application/yaml', `# Exemples fictifs — Open Guild Kit, démonstration interactive\n${toYaml(signals.map((x) => ({ titre: x.title, fictif: true, type: x.type, source: s.db.source[x.sourceId]?.name, publie: new Date(x.publishedAt).toISOString().slice(0, 10), consulte: new Date(x.consultedAt).toISOString().slice(0, 10), faits: x.facts, interpretations: x.interpretations, hypotheses: x.hypotheses, recommandations: x.recommendations, pertinence: x.relevance })))}\n`);
  };
  return (
    <Panel title="Signaux" actions={<><CmdButton def={cmd.collectSignals} payload={{}} icon="telescope" variant="ai" success="Collecte simulée : nouveau signal à évaluer">Lancer une collecte (simulation)</CmdButton><CmdButton def={cmd.recordExport} payload={{ what: 'signaux', format: 'YAML', count: 0 }} icon="download" onRun={exportAll}>Exporter</CmdButton></>}>
      <CollectionBar c={c} filters={filters} total={signals.length} placeholder="Rechercher un signal" />
      {c.items.length === 0 ? <Empty title="Aucun signal" /> : (
        <ul className="plain stack tight">
          {c.items.map((x) => (
            <li key={x.id}><a className="card" href={`#/observatoire/signaux/${x.id}`}>
              <div className="row between"><strong>{x.title}</strong><span className="row"><Fictif />{x.reevaluation === 'proposed' && <Badge tone="info" icon="spark">à évaluer</Badge>}<Badge tone={LEVEL[x.relevance.level]}>pertinence {x.relevance.level}</Badge>{x.favorite && <Icon name="star" size={12} className="fav-on" label="favori" />}</span></div>
              <span className="small muted">{x.type} · {s.db.competitor[x.competitorId ?? '']?.name ?? 'écosystème'} · publié le {fmtDate(x.publishedAt)} · consulté le {fmtDate(x.consultedAt)}</span>
            </a></li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function SignalSheet({ id }: { id: ID }) {
  const s = useAppState();
  const x = s.db.signal[id];
  const [note, setNote] = useState('');
  const [level, setLevel] = useState<Signal['relevance']['level']>(x?.relevance.level ?? 'moyenne');
  const [reason, setReason] = useState('');
  const [opp, setOpp] = useState('');
  if (!x || x.orgId !== s.session.orgId) return <NotFound what="Signal" />;
  const src = s.db.source[x.sourceId];
  const section = (title: string, icon: Parameters<typeof Icon>[0]['name'], items: string[], tone?: 'ai') => <Panel title={<span className="row"><Icon name={icon} size={14} />{title}</span>} tone={tone}>{items.length ? <ul className="bullets">{items.map((t) => <li key={t}>{t}</li>)}</ul> : <p className="small muted">Aucun élément.</p>}</Panel>;
  return (
    <div className="stack">
      <a href="#/observatoire/signaux" className="small">← Tous les signaux</a>
      <Panel title={x.title} actions={<><Fictif /><SimBadge label="Veille simulée" /><Button size="small" icon="star" aria-pressed={x.favorite} onClick={() => dispatch(cmd.updateSignal, { id: x.id, favorite: !x.favorite }, { silent: true })}>{x.favorite ? 'Favori' : 'Favori ?'}</Button></>}>
        <KV items={[['Provenance', <>{src?.name} <span className="tiny muted">({src?.url}, adresse fictive non consultée)</span></>], ['Concurrent', x.competitorId ? s.db.competitor[x.competitorId]?.name : 'Écosystème'], ['Type', x.type], ['Publié le', fmtDate(x.publishedAt)], ['Consulté le', fmtDate(x.consultedAt, true)], ['Contexte', x.context], ['Projets potentiellement concernés', x.projectIds.map((p) => <ObjectLink key={p} to={{ kind: 'project', id: p }} />)], ['Opportunité', x.opportunityId ? <ObjectLink to={{ kind: 'opportunity', id: x.opportunityId }} /> : '—']]} />
      </Panel>
      <div className="grid-2">
        {section('Faits observés', 'eye', x.facts)}
        {section('Interprétations', 'question', x.interpretations)}
        {section('Hypothèses', 'question', x.hypotheses)}
        {section('Recommandations', 'spark', x.recommendations, 'ai')}
      </div>
      <div className="grid-2">
        <Panel title={`Pertinence : ${x.relevance.level}`}>
          <p className="small muted">Pourquoi :</p><ul className="bullets small">{x.relevance.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          {x.reevaluation === 'proposed' && <Notice tone="info">Réévaluation proposée : qualifiez la pertinence ; la roadmap n’est pas modifiée automatiquement.</Notice>}
          <div className="row"><Select label="Niveau" value={level} onChange={(e) => setLevel(e.target.value as typeof level)} options={['faible', 'moyenne', 'forte'].map((l) => ({ value: l, label: l }))} /><div className="grow"><TextField label="Explication" value={reason} onChange={(e) => setReason(e.target.value)} /></div></div>
          <CmdButton def={cmd.updateSignal} payload={{ id: x.id, relevance: { level, reason } }} size="small" success="Signal réévalué">Réévaluer</CmdButton>
        </Panel>
        <Panel title="Exploiter le signal">
          <div className="row"><Select label="Rattacher à une opportunité" value={opp} placeholder="Choisir…" onChange={(e) => setOpp(e.target.value)} options={list(s, 'opportunity', s.session.orgId).map((o) => ({ value: o.id, label: o.title }))} />
            <CmdButton def={cmd.saveOpportunity} payload={{ id: opp, title: s.db.opportunity[opp]?.title ?? '', description: s.db.opportunity[opp]?.description ?? '', signalIds: [...new Set([...(s.db.opportunity[opp]?.signalIds ?? []), x.id])] }} size="small" success="Signal rattaché">Rattacher</CmdButton></div>
          <div className="row" style={{ marginTop: 8 }}>
            <Button icon="council" onClick={() => navigate(`/conseil?nouveau=1&signal=${x.id}`)}>Transformer en sujet de Conseil</Button>
            <Button icon="quest" onClick={() => navigate(`/quetes?nouvelle=1&signal=${x.id}&titre=${encodeURIComponent(`Suite au signal : ${x.title}`.slice(0, 80))}&projet=${x.projectIds[0] ?? ''}`)}>Créer une quête</Button>
          </div>
          <h3 style={{ marginTop: 10 }}>Notes</h3>
          <ul className="plain stack tight">{x.notes.map((n) => <li key={n.id} className="small"><Person id={n.authorId} /> · {fmtDate(n.at, true)} — {n.text}</li>)}</ul>
          <TextArea label="Annoter" value={note} onChange={(e) => setNote(e.target.value)} />
          <CmdButton def={cmd.updateSignal} payload={{ id: x.id, note }} size="small" success="Note ajoutée" onDone={() => setNote('')}>Ajouter la note</CmdButton>
        </Panel>
      </div>
    </div>
  );
}

function Competitors() {
  const s = useAppState();
  const comps = list(s, 'competitor', s.session.orgId);
  const [v, setV] = useState({ name: '', kind: 'direct' as Competitor['kind'], description: '', strengths: '', weaknesses: '' });
  return (
    <div className="grid-2">
      {(['direct', 'indirect'] as const).map((k) => (
        <Panel key={k} title={`Concurrents ${k}s`}>
          {comps.filter((c) => c.kind === k).map((c) => (
            <div key={c.id} className="card" style={{ margin: 3 }}>
              <div className="row between"><strong>{c.name}</strong><span className="row"><Fictif /><button className="btn ghost icon small" aria-pressed={c.favorite} aria-label={c.favorite ? 'Retirer des favoris' : 'Favori'} onClick={() => dispatch(cmd.saveCompetitor, { ...c, favorite: !c.favorite }, { silent: true })}><Icon name="star" size={12} className={c.favorite ? 'fav-on' : ''} /></button></span></div>
              <p className="small muted" style={{ margin: '4px 0' }}>{c.description}</p>
              <p className="small" style={{ margin: 0 }}><span style={{ color: 'var(--success)' }}>Forces :</span> {c.strengths.join(', ')}</p>
              <p className="small" style={{ margin: 0 }}><span style={{ color: 'var(--danger)' }}>Faiblesses :</span> {c.weaknesses.join(', ')}</p>
              <p className="tiny muted" style={{ margin: '4px 0 0' }}>{list(s, 'signal', s.session.orgId).filter((x) => x.competitorId === c.id).length} signal(aux)</p>
            </div>
          ))}
        </Panel>
      ))}
      <Panel title="Ajouter un concurrent fictif">
        <TextField label="Nom" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <Select label="Type" value={v.kind} onChange={(e) => setV({ ...v, kind: e.target.value as Competitor['kind'] })} options={[{ value: 'direct', label: 'Direct' }, { value: 'indirect', label: 'Indirect' }]} />
        <TextArea label="Description" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />
        <TextField label="Forces (séparées par des virgules)" value={v.strengths} onChange={(e) => setV({ ...v, strengths: e.target.value })} />
        <TextField label="Faiblesses" value={v.weaknesses} onChange={(e) => setV({ ...v, weaknesses: e.target.value })} />
        <CmdButton def={cmd.saveCompetitor} payload={{ name: v.name, kind: v.kind, description: v.description, strengths: v.strengths.split(',').map((x) => x.trim()).filter(Boolean), weaknesses: v.weaknesses.split(',').map((x) => x.trim()).filter(Boolean) }} variant="primary" success="Concurrent fictif ajouté">Ajouter</CmdButton>
      </Panel>
    </div>
  );
}

function Sources() {
  const s = useAppState();
  const sources = list(s, 'source', s.session.orgId);
  const [v, setV] = useState({ name: '', url: 'https://example.invalid/', type: 'Site public' });
  return (
    <Panel title="Sources de veille (fictives)">
      <table className="data responsive"><thead><tr><th>Source</th><th>Type</th><th>Adresse</th><th>Signaux</th><th>Active</th></tr></thead>
        <tbody>{sources.map((x) => <tr key={x.id}><td data-label="Source">{x.name} <Fictif /></td><td data-label="Type">{x.type}</td><td data-label="Adresse" className="mono small">{x.url}</td><td data-label="Signaux">{list(s, 'signal', s.session.orgId).filter((g) => g.sourceId === x.id).length}</td><td data-label="Active"><Checkbox label={x.active ? 'active' : 'inactive'} checked={x.active} onChange={(e) => dispatch(cmd.saveSource, { id: x.id, name: x.name, url: x.url, type: x.type, active: e.target.checked }, {})} /></td></tr>)}</tbody></table>
      <div className="form-grid" style={{ marginTop: 10 }}>
        <TextField label="Nom" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <TextField label="Adresse" value={v.url} onChange={(e) => setV({ ...v, url: e.target.value })} hint="Aucune collecte réelle n’est effectuée." />
        <TextField label="Type" value={v.type} onChange={(e) => setV({ ...v, type: e.target.value })} />
      </div>
      <CmdButton def={cmd.saveSource} payload={{ ...v, active: true }} size="small" success="Source ajoutée">Ajouter la source</CmdButton>
    </Panel>
  );
}

function Trends() {
  const s = useAppState();
  const signals = list(s, 'signal', s.session.orgId);
  const max = Math.max(1, ...TYPES.map((t) => signals.filter((x) => x.type === t).length));
  return (
    <Panel title="Tendances des signaux (données fictives)">
      <div className="stack tight" role="list">
        {TYPES.map((t) => { const n = signals.filter((x) => x.type === t).length; const strong = signals.filter((x) => x.type === t && x.relevance.level === 'forte').length; return (
          <div key={t} role="listitem" className="row"><span style={{ width: 130, textTransform: 'capitalize' }}>{t}</span><span style={{ display: 'inline-block', height: 14, width: `${(n / max) * 60}%`, background: 'repeating-linear-gradient(90deg, var(--data) 0 6px, #4fa6b6 6px 8px)', minWidth: n ? 8 : 0 }} /><span className="small">{n} signal(aux){strong ? `, ${strong} forte(s)` : ''}</span></div>
        ); })}
      </div>
      <p className="tiny muted" style={{ marginTop: 10 }}>Répartition par type ; elle décrit le scénario fictif, pas un marché réel.</p>
    </Panel>
  );
}

function Comparison() {
  const s = useAppState();
  const comps = list(s, 'competitor', s.session.orgId);
  const criteria = ['Export des données', 'Traçabilité', 'Durée de conservation maîtrisée', 'Automatisations', 'Accompagnement grands comptes'];
  const ours: Record<string, string> = { 'Export des données': 'En cours (quête)', 'Traçabilité': 'Oui (journal d’audit)', 'Durée de conservation maîtrisée': 'Oui (règle PRIV-RET-02)', Automatisations: 'Partiel', 'Accompagnement grands comptes': 'Oui' };
  return (
    <Panel title="Comparaison (sociétés fictives)">
      <div className="table-wrap"><table className="data"><thead><tr><th>Critère</th><th>Atlas CRM</th>{comps.map((c) => <th key={c.id}>{c.name} (fictif)</th>)}</tr></thead>
        <tbody>{criteria.map((k) => <tr key={k}><td>{k}</td><td>{ours[k]}</td>{comps.map((c) => <td key={c.id} className="small">{c.strengths.some((x) => k.toLowerCase().includes(x.toLowerCase().split(' ')[0])) ? 'Point fort annoncé' : c.weaknesses.some((x) => x.toLowerCase().includes(k.split(' ')[0].toLowerCase())) ? 'Faiblesse signalée' : 'Non documenté'}</td>)}</tr>)}</tbody></table></div>
      <p className="tiny muted">« Non documenté » signifie qu’aucun signal ne renseigne ce critère : ce n’est pas une absence de fonctionnalité.</p>
    </Panel>
  );
}

function Opportunities() {
  const s = useAppState();
  const opps = list(s, 'opportunity', s.session.orgId);
  const [v, setV] = useState({ title: '', description: '' });
  return (
    <div className="grid-2">
      {opps.map((o) => (
        <Panel key={o.id} title={o.title} actions={<Badge tone={o.status === 'retained' ? 'success' : o.status === 'dismissed' ? 'muted' : 'info'}>{({ open: 'ouverte', council: 'en conseil', retained: 'retenue', dismissed: 'écartée' })[o.status]}</Badge>}>
          <p className="small">{o.description}</p>
          <p className="small muted">Signaux : {o.signalIds.map((x) => <ObjectLink key={x} to={{ kind: 'signal', id: x }} />)}</p>
          <div className="row">
            <Button size="small" icon="council" onClick={() => navigate(`/conseil?nouveau=1&signal=${o.signalIds[0] ?? ''}`)}>Examiner en Conseil</Button>
            <CmdButton def={cmd.saveOpportunity} payload={{ id: o.id, title: o.title, description: o.description, signalIds: o.signalIds, status: 'retained' }} size="small" success="Opportunité retenue" showReason={false}>Retenir</CmdButton>
            <CmdButton def={cmd.saveOpportunity} payload={{ id: o.id, title: o.title, description: o.description, signalIds: o.signalIds, status: 'dismissed' }} size="small" success="Opportunité écartée" showReason={false}>Écarter</CmdButton>
          </div>
        </Panel>
      ))}
      <Panel title="Nouvelle opportunité">
        <TextField label="Titre" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
        <TextArea label="Description" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />
        <CmdButton def={cmd.saveOpportunity} payload={{ ...v, signalIds: [] }} variant="primary" success="Opportunité créée">Créer</CmdButton>
      </Panel>
    </div>
  );
}

function WatchSettings() {
  const s = useAppState();
  const w = s.orgs[s.session.orgId!].settings.watch;
  const [topics, setTopics] = useState(w.topics.join(', '));
  return (
    <Panel title="Paramètres de la veille simulée">
      <Checkbox label="Veille activée" checked={w.enabled} onChange={(e) => dispatch(cmd.updateSettings, { patch: { watch: { ...w, enabled: e.target.checked } } }, { success: 'Paramètre enregistré' })} />
      <Select label="Cadence (simulée)" value={w.cadence} onChange={(e) => dispatch(cmd.updateSettings, { patch: { watch: { ...w, cadence: e.target.value as 'hebdomadaire' } } }, { success: 'Cadence enregistrée' })} options={[{ value: 'quotidienne', label: 'Quotidienne' }, { value: 'hebdomadaire', label: 'Hebdomadaire' }]} />
      <TextField label="Thèmes suivis" value={topics} onChange={(e) => setTopics(e.target.value)} />
      <CmdButton def={cmd.updateSettings} payload={{ patch: { watch: { ...w, topics: topics.split(',').map((x) => x.trim()).filter(Boolean) } } }} size="small" success="Thèmes enregistrés">Enregistrer les thèmes</CmdButton>
      <p className="small muted">Collecte simulée : {w.cursor} signal(aux) du scénario déjà récupéré(s). Aucune requête réseau n’est envoyée.</p>
    </Panel>
  );
}
