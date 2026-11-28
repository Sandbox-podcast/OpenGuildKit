/** Council: sessions, structured contributions, options and disagreements, synthesis, human arbitration and decisions (brief §5.6). */
import { useEffect, useMemo, useState } from 'react';
import { NotFound } from '@/demo/app/App';
import { dispatch, newOpId, useAppState } from '@/demo/app/store';
import { navigate, setQuery, useRoute } from '@/shared/router';
import { cmd } from '@/demo/domain/commands';
import { list } from '@/demo/domain/engine';
import { stateDef } from '@/demo/domain/machines';
import { bpVersion, fmtDate, objectLabel, unknownFacts } from '@/demo/domain/selectors';
import type { Contribution, Council, CouncilOption, ID, Signal, Stance } from '@/demo/domain/types';
import { services } from '@/demo/adapters/services';
import { Icon } from '@/shared/pixel/icons';
import { characterUrl, CLASS_COLORS } from '@/shared/pixel/portraits';
import { Badge, Button, Empty, KV, Notice, Panel, Select, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { ApprovalList, CmdButton, ExpertChip, Lifecycle, ObjectLink, Person, Portrait, SimBadge, StatusBadge, Version } from '@/demo/ui/domain';
import { DiffView } from '@/demo/ui/content';

/* ------------------------------------------------------------------ list */
export function CouncilList() {
  const s = useAppState();
  const route = useRoute();
  const councils = list(s, 'council', s.session.orgId).sort((a, b) => b.createdAt - a.createdAt);
  const decisions = list(s, 'decision', s.session.orgId).sort((a, b) => b.createdAt - a.createdAt);
  const creating = route.query.get('nouveau') === '1';
  const signalId = route.query.get('signal');
  const presetSignal = list(s, 'signal', s.session.orgId).find((signal) => signal.id === signalId);
  return (
    <div className="stack">
      <Panel title="Sessions du Conseil" actions={<CmdButton def={cmd.createCouncil} payload={{ projectId: s.session.projectId ?? '', title: 'xxxx', objective: 'xxxxxxxxxxxx', scenario: null, context: '', constraints: [], ruleIds: [], participantIds: [], documentIds: [], ownerId: 'x' }} variant="primary" icon="plus" onRun={() => setQuery({ nouveau: '1' })}>Préparer une session</CmdButton>}>
        {councils.length === 0 ? <Empty title="Aucune session" /> : (
          <div className="grid-auto">
            {councils.map((c) => (
              <a key={c.id} className="card" href={`#/conseil/${c.id}`}>
                <div className="row between"><strong>{c.title}</strong><StatusBadge kind="council" state={c.status} /></div>
                <p className="small muted" style={{ margin: '4px 0' }}>{c.objective}</p>
                <div className="row">{c.participantIds.slice(0, 7).map((id) => <Portrait key={id} k={s.db.expert[id]?.key ?? 'product'} size={28} alt={s.db.expert[id]?.name} />)}</div>
                <div className="row" style={{ marginTop: 6 }}><span className="tiny muted">{s.db.project[c.projectId]?.name}. {c.contributions.length} {c.contributions.length === 1 ? 'avis reçu' : 'avis reçus'}.</span><SimBadge label={c.scenario ? services.agents.scenarios[c.scenario]?.label : 'Hors scénario'} /></div>
              </a>
            ))}
          </div>
        )}
      </Panel>
      <Panel title="Décisions">
        {decisions.length === 0 ? <p className="small muted">Aucune décision.</p> : (
          <table className="data responsive"><thead><tr><th>Décision</th><th>Option</th><th>Version</th><th>État</th><th>Responsable</th><th>Quêtes</th></tr></thead>
            <tbody>{decisions.map((d) => <tr key={d.id}><td data-label="Décision"><a href={`#/decisions/${d.id}`}>{d.title}</a></td><td data-label="Option">{d.optionTitle}</td><td data-label="Version"><Version n={d.number} /></td><td data-label="État"><StatusBadge kind="decision" state={d.status} /></td><td data-label="Responsable"><Person id={d.ownerId} /></td><td data-label="Quêtes">{d.questIds.length}</td></tr>)}</tbody></table>
        )}
      </Panel>
      {creating && <CouncilForm key={`${s.session.orgId}:${presetSignal?.id ?? ''}`} onClose={() => setQuery({ nouveau: null, experts: null, signal: null })} presetExperts={route.query.get('experts')?.split(',').filter(Boolean)} signal={presetSignal} />}
    </div>
  );
}

function CouncilForm({ onClose, presetExperts, signal }: { onClose: () => void; presetExperts?: string[]; signal?: Signal }) {
  const s = useAppState();
  const projects = list(s, 'project', s.session.orgId).filter((p) => p.status === 'active');
  const experts = list(s, 'expert', s.session.orgId);
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : '';
  const [v, setV] = useState(() => ({
    projectId: projects.find((p) => p.id === (signal?.projectIds[0] ?? s.session.projectId))?.id ?? projects[0]?.id ?? '', title: signal ? `Réponse à ${signal.title}` : '', objective: signal ? "Choisir un positionnement et soumettre toute modification de la feuille de route à l'arbitrage." : '',
    scenario: signal ? 'positionnement' : '', context: signal?.context ?? '', constraints: '', ruleIds: [] as string[], participantIds: presetExperts ? presetExperts.filter((id) => experts.some((expert) => expert.id === id && expert.active)) : signal ? services.agents.scenarios.positionnement.defaultExperts.map((k) => `exp-${s.session.orgId}-${k}`) : [], documentIds: [] as string[], ownerId: me,
  }));
  const [opId] = useState(newOpId);
  const scenario = v.scenario ? services.agents.scenarios[v.scenario] : undefined;
  const submit = () => {
    const out = dispatch(cmd.createCouncil, { ...v, scenario: v.scenario || null, constraints: v.constraints.split('\n').map((x) => x.trim()).filter(Boolean), origin: signal ? { kind: 'signal', id: signal.id } : undefined }, { opId, success: 'Session préparée' });
    if (out.ok) { onClose(); navigate(`/conseil/${out.value}`); }
  };
  return (
    <Dialog open onClose={onClose} wide title="Préparer une session du Conseil" footer={<><Button onClick={onClose}>Annuler</Button><Button variant="primary" onClick={submit}>Préparer la session</Button></>}>
      <div className="form-grid">
        <TextField label="Titre" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
        <Select label="Projet" value={v.projectId} onChange={(e) => setV({ ...v, projectId: e.target.value })} options={projects.map((p) => ({ value: p.id, label: p.name }))} />
        <TextArea className="full" label="Objectif" value={v.objective} onChange={(e) => setV({ ...v, objective: e.target.value })} />
        <Select className="full" label="Scénario de simulation" hint="Choisissez un scénario pour obtenir des avis simulés." value={v.scenario} placeholder="Hors scénario (contributions limitées)" onChange={(e) => { const sc = services.agents.scenarios[e.target.value]; setV({ ...v, scenario: e.target.value, participantIds: sc ? sc.defaultExperts.map((k) => `exp-${s.session.orgId}-${k}`) : v.participantIds, objective: v.objective || sc?.summary || '' }); }} options={services.agents.list.map((x) => ({ value: x.key, label: x.label }))} />
        {scenario && <p className="full small muted">{scenario.summary}</p>}
        <TextArea className="full" label="Contexte" value={v.context} onChange={(e) => setV({ ...v, context: e.target.value })} />
        <TextArea label="Contraintes (une par ligne)" value={v.constraints} onChange={(e) => setV({ ...v, constraints: e.target.value })} />
        <fieldset className="field" style={{ border: 0, padding: 0 }}><legend className="label">Règles retenues</legend><div className="choice-group">{list(s, 'rule', s.session.orgId).slice(0, 14).map((r) => <label key={r.id} className="choice"><input type="checkbox" checked={v.ruleIds.includes(r.id)} onChange={(e) => setV({ ...v, ruleIds: e.target.checked ? [...v.ruleIds, r.id] : v.ruleIds.filter((x) => x !== r.id) })} /><span>{r.code}</span></label>)}</div></fieldset>
        <fieldset className="full field" style={{ border: 0, padding: 0 }}>
          <legend className="label">Expertises convoquées</legend>
          <div className="choice-group">{experts.map((e) => <label key={e.id} className="choice"><input type="checkbox" disabled={!e.active} checked={v.participantIds.includes(e.id)} onChange={(ev) => setV({ ...v, participantIds: ev.target.checked ? [...v.participantIds, e.id] : v.participantIds.filter((x) => x !== e.id) })} /><span><Portrait k={e.key} size={18} /> {e.name} <span className="tiny muted">{e.domain}</span></span></label>)}</div>
        </fieldset>
        <Select label="Responsable humain de la session" value={v.ownerId} onChange={(e) => setV({ ...v, ownerId: e.target.value })} options={[...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))].map((id) => ({ value: id, label: s.users[id]?.name ?? id }))} />
        <Select label="Document joint" value={v.documentIds[0] ?? ''} placeholder="Aucun" onChange={(e) => setV({ ...v, documentIds: e.target.value ? [e.target.value] : [] })} options={list(s, 'deliverable', s.session.orgId).filter((d) => d.projectId === v.projectId).map((d) => ({ value: d.id, label: d.title }))} />
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ room */
const STANCE: Record<Stance, { icon: 'check' | 'question' | 'cross'; label: string }> = { pour: { icon: 'check', label: 'pour' }, réservé: { icon: 'question', label: 'réservé' }, contre: { icon: 'cross', label: 'contre' } };

export function CouncilRoom({ id }: { id: ID }) {
  const s = useAppState();
  const route = useRoute();
  const tab = route.query.get('onglet') ?? 'contributions';
  const c = s.db.council[id];
  if (!c || c.orgId !== s.session.orgId) return <NotFound what="Session du Conseil" />;
  const scenario = c.scenario ? services.agents.scenarios[c.scenario] : undefined;
  const decisions = list(s, 'decision', s.session.orgId).filter((d) => d.councilId === c.id).sort((a, b) => a.number - b.number);
  return (
    <div className="stack">
      <Panel title={c.title} actions={<><SimBadge label={scenario ? `Simulation : ${scenario.label}` : 'Hors scénario'} /><Lifecycle kind="council" id={c.id} state={c.status} /></>}>
        <p style={{ margin: 0 }}>{c.objective}</p>
        <p className="small muted" style={{ margin: '4px 0 0' }}>Projet <ObjectLink bare to={{ kind: 'project', id: c.projectId }} /> · responsable <Person id={c.ownerId} /> · Blueprint <Version n={c.blueprintVersion} /> au lancement</p>
        {c.status === 'prepared' && <p className="small muted" style={{ margin: '4px 0 0' }}>{c.participantIds.length} {c.participantIds.length === 1 ? 'expertise sélectionnée' : 'expertises sélectionnées'}. La décision revient au responsable humain.</p>}
        {c.statusReason && <Notice tone="warn">Motif : {c.statusReason}</Notice>}
      </Panel>
      <Tabs label="Session" value={tab} onChange={(t) => setQuery({ onglet: t, avis: null })} tabs={[
        { id: 'contributions', label: 'Contributions', icon: 'ai', count: c.contributions.length },
        { id: 'options', label: 'Options et désaccords', icon: 'council' },
        { id: 'synthese', label: 'Synthèse', icon: 'scroll' },
        { id: 'arbitrage', label: 'Arbitrage humain', icon: 'shield', count: decisions.filter((d) => d.status === 'review').length },
        { id: 'contexte', label: 'Contexte', icon: 'book' },
      ]} />
      <CouncilTable c={c} />
      {tab === 'contributions' && <Contributions c={c} />}
      {tab === 'options' && <Options c={c} />}
      {tab === 'synthese' && <Synthesis c={c} />}
      {tab === 'arbitrage' && <Arbitration c={c} />}
      {tab === 'contexte' && <ContextTab c={c} />}
    </div>
  );
}

function CouncilTable({ c }: { c: Council }) {
  const s = useAppState();
  const [focusOpt, setFocusOpt] = useState<string>(c.options[0]?.id ?? '');
  const n = c.participantIds.length;
  const listSeats = s.prefs.mode === 'focus' || n > 6;
  const selectedOption = c.options.some((o) => o.id === focusOpt) ? focusOpt : c.options[0]?.id;
  const last = c.contributions.at(-1)?.expertId;
  const running = c.status === 'running';
  return (
    <section className={`council-room${listSeats ? ' list-seats' : ''}`} aria-label="Salle du conseil">
      <div className="council-table">
        {!listSeats && <picture className="council-room-art" aria-hidden="true">
          <img src="./assets/world/salle-conseil.webp" srcSet="./assets/world/salle-conseil-mobile.webp 720w, ./assets/world/salle-conseil.webp 1440w" sizes="(max-width: 900px) 94vw, (max-width: 1560px) 78vw, 70vw" width={1440} height={603} alt="" />
        </picture>}
        <div className="seat human" style={{ left: '50%', top: '87%' }}>
          <CouncilFigure identity={s.users[c.ownerId]?.portrait ?? 'human-1'} list={listSeats} />
          <span className="seat-name">{s.users[c.ownerId]?.name} · arbitre</span>
        </div>
        {c.participantIds.map((eid, i) => {
          const e = s.db.expert[eid];
          const angle = Math.PI + (Math.PI * (i + 0.5)) / n;
          const contrib = c.contributions.find((x) => x.expertId === eid);
          const stance = selectedOption ? contrib?.stances[selectedOption] : undefined;
          const position = { left: `${50 + Math.cos(angle) * 37}%`, top: `${70 + Math.sin(angle) * 34}%`, ['--class' as string]: CLASS_COLORS[e?.key ?? ''] };
          const portrait = <><CouncilFigure identity={e?.key ?? 'product'} list={listSeats} /><span className="seat-name">{e?.name}</span></>;
          if (!contrib) return <span key={eid} className="seat waiting" style={position}>{portrait}<span className="sr-only">{running ? 'Avis en préparation' : c.status === 'prepared' ? 'Avis à demander' : 'Aucun avis'}</span>{running && <span className="stance" aria-hidden><span className="spinner" /></span>}</span>;
          const href = `#/conseil/${c.id}?onglet=contributions&avis=${encodeURIComponent(eid)}`;
          return <a key={eid} href={href} className={`seat ${running && last === eid ? 'speaking' : ''}`} style={position}
            aria-label={`Lire l'avis de ${e?.name}${stance ? ` (${STANCE[stance].label})` : ''}`}
            onClick={() => { if (window.location.hash === href) document.getElementById(`contrib-${eid}`)?.focus(); }}>
            {portrait}{stance && <span className={`stance badge tone-${stance === 'pour' ? 'success' : stance === 'contre' ? 'danger' : 'warning'}`}><Icon name={STANCE[stance].icon} size={10} />{STANCE[stance].label}</span>}
          </a>;
        })}
      </div>
      <div className="row between council-room-footer">
        {c.options.length > 0 && (
          <div className="seg" role="group" aria-label="Positions par option">
            {c.options.map((o) => <button key={o.id} aria-pressed={selectedOption === o.id} onClick={() => setFocusOpt(o.id)}>{o.title}</button>)}
          </div>
        )}
        <p className="tiny muted" style={{ margin: 0 }}>{c.contributions.length}/{n} avis ({stateDef('council', c.status).label.toLowerCase()})</p>
      </div>
    </section>
  );
}

function CouncilFigure({ identity, list }: { identity: string; list: boolean }) {
  if (list) return <span className="portrait-frame"><Portrait k={identity} size={48} /></span>;
  return <img className="pixel council-figure" width={80} height={112} src={characterUrl(identity)} alt="" />;
}

function ContributionCard({ x, c }: { x: Contribution; c: Council }) {
  const s = useAppState();
  const [ask, setAsk] = useState(false);
  const [question, setQuestion] = useState('');
  const section = (title: string, icon: Parameters<typeof Icon>[0]['name'], items: string[]) => items.length > 0 && (
    <div><h4><Icon name={icon} size={12} />{title}</h4><ul className="bullets small">{items.map((t) => <li key={t}>{t}</li>)}</ul></div>
  );
  const clar = c.clarifications.filter((k) => k.expertId === x.expertId);
  return (
    <article id={`contrib-${x.expertId}`} className="panel ai contribution" aria-label={`Contribution de ${s.db.expert[x.expertId]?.name}`} tabIndex={-1} style={{ scrollMarginTop: 'calc(var(--header-h) + 12px)' }}>
      <header>
        <ExpertChip id={x.expertId} />
        <div className="row"><SimBadge />{x.limited && <Badge tone="warning" icon="warn">Contribution limitée</Badge>}<span className="tiny muted">{fmtDate(x.at, true)}</span></div>
      </header>
      <div className="sections">
        {section('Faits et observations', 'eye', x.facts)}
        {section('Hypothèses', 'question', x.hypotheses)}
        {section('Questions', 'question', x.questions)}
        {section('Risques', 'warn', x.risks)}
      </div>
      <div className="rec"><h4><Icon name="spark" size={12} />Recommandation</h4><p style={{ margin: 0 }}>{x.recommendation}</p></div>
      {x.reservation && <div className="rec reserve"><h4><Icon name="warn" size={12} />Réserve</h4><p style={{ margin: 0 }}>{x.reservation}</p></div>}
      <div className="row small" style={{ marginTop: 8 }}>
        {x.deliverable && <span><Icon name="anvil" size={12} /> Livrable attendu : {x.deliverable}</span>}
        {x.sourceRefIds.length > 0 && <span className="muted">· Sources :</span>}
        {x.sourceRefIds.map((r) => <ObjectLink key={r} to={{ kind: 'reference', id: r }} />)}
      </div>
      {Object.keys(x.stances).length > 0 && <div className="row small" style={{ marginTop: 6 }}>{c.options.map((o) => x.stances[o.id] && <span key={o.id} className={`stance-${x.stances[o.id]}`}><Icon name={STANCE[x.stances[o.id]].icon} size={10} /> {o.title} : {x.stances[o.id]}</span>)}</div>}
      {clar.map((k) => <div key={k.id} className="notice ai" style={{ marginTop: 8 }}><Icon name="question" size={14} /><div><strong>Q.</strong> {k.question}<br /><strong>R. (simulée)</strong> {k.answer}</div></div>)}
      <div className="row" style={{ marginTop: 8 }}>
        {!ask ? <Button size="small" icon="question" onClick={() => setAsk(true)}>Demander une clarification</Button> : (
          <><div className="grow"><TextField label="Question" value={question} onChange={(e) => setQuestion(e.target.value)} /></div><CmdButton def={cmd.requestClarification} payload={{ councilId: c.id, expertId: x.expertId, question }} size="small" variant="ai" success="Réponse simulée ajoutée" onDone={() => { setAsk(false); setQuestion(''); }}>Envoyer</CmdButton></>
        )}
      </div>
    </article>
  );
}

function Contributions({ c }: { c: Council }) {
  const s = useAppState();
  const route = useRoute();
  const expertId = route.query.get('avis');
  const selected = c.contributions.find((x) => x.expertId === expertId);
  useEffect(() => { if (selected) document.getElementById(`contrib-${selected.expertId}`)?.focus(); }, [selected]);
  const waiting = c.participantIds.filter((e) => !c.contributions.some((x) => x.expertId === e));
  return (
    <div className="stack">
      {c.status === 'running' && waiting.length > 0 && <Notice tone="ai" icon="ai" title="Avis simulés en préparation">{waiting.map((e) => s.db.expert[e]?.name).join(', ')}</Notice>}
      {c.contributions.map((x) => <ContributionCard key={x.id} x={x} c={c} />)}
      {c.contributions.length === 0 && c.status !== 'prepared' && <Empty title="Aucun avis pour le moment" />}
    </div>
  );
}

function Options({ c }: { c: Council }) {
  const s = useAppState();
  const [note, setNote] = useState('');
  const [sel, setSel] = useState<string[]>([]);
  const [opt, setOpt] = useState('');
  const [invite, setInvite] = useState('');
  const others = list(s, 'expert', s.session.orgId).filter((e) => e.active && !c.participantIds.includes(e.id));
  const impactKeys = [...new Set(c.options.flatMap((o) => Object.keys(o.impacts)))];
  return (
    <div className="stack">
      {c.options.length === 0 ? <Notice tone="warn">Ce sujet est hors des scénarios de simulation : aucune option n’est préparée. Les questions des expertises figurent dans la synthèse.</Notice> : (
        <Panel title="Comparaison des options">
          <div className="table-wrap">
            <table className="data options-matrix">
              <thead><tr><th>Critère</th>{c.options.map((o) => <th key={o.id}>{o.title}</th>)}</tr></thead>
              <tbody>
                <tr><td>Description</td>{c.options.map((o) => <td key={o.id} className="small">{o.summary}</td>)}</tr>
                {impactKeys.map((k) => <tr key={k}><td style={{ textTransform: 'capitalize' }}>{k}</td>{c.options.map((o) => <td key={o.id}>{o.impacts[k] ?? '—'}</td>)}</tr>)}
                <tr><td>Avantages</td>{c.options.map((o) => <td key={o.id} className="small">{o.pros.join(' · ')}</td>)}</tr>
                <tr><td>Inconvénients</td>{c.options.map((o) => <td key={o.id} className="small">{o.cons.join(' · ')}</td>)}</tr>
                <tr><td>Points bloquants</td>{c.options.map((o) => <td key={o.id} className="small" style={{ color: o.blocking.length ? 'var(--danger)' : undefined }}>{o.blocking.join(' · ') || '—'}</td>)}</tr>
                {c.contributions.filter((x) => Object.keys(x.stances).length).map((x) => (
                  <tr key={x.id}><td><ExpertChip id={x.expertId} /></td>{c.options.map((o) => { const st = x.stances[o.id]; return <td key={o.id} className={st ? `stance-${st}` : ''}>{st ? <><Icon name={STANCE[st].icon} size={12} /> {st}</> : '—'}</td>; })}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="tiny muted">Un décompte des positions n’est pas une décision : aucun score ni majorité ne lève un blocage obligatoire.</p>
        </Panel>
      )}
      <div className="grid-2">
        <Panel title={`Désaccords annotés (${c.annotations.length})`}>
          <ul className="plain stack tight">{c.annotations.map((a) => <li key={a.id} className="card"><p style={{ margin: 0 }}>{a.text}</p><p className="tiny muted" style={{ margin: '4px 0 0' }}><Person id={a.authorId} /> · {fmtDate(a.at, true)} · {a.contributionIds.map((id) => s.db.expert[c.contributions.find((x) => x.id === id)?.expertId ?? '']?.name).join(', ')}{a.optionId && ` · ${c.options.find((o) => o.id === a.optionId)?.title}`}</p></li>)}</ul>
          <div className="stack tight" style={{ marginTop: 8 }}>
            <TextArea label="Nouvelle annotation" value={note} onChange={(e) => setNote(e.target.value)} />
            <div className="choice-group">{c.contributions.map((x) => <label key={x.id} className="choice"><input type="checkbox" checked={sel.includes(x.id)} onChange={(e) => setSel(e.target.checked ? [...sel, x.id] : sel.filter((y) => y !== x.id))} /><span>{s.db.expert[x.expertId]?.name}</span></label>)}</div>
            {c.options.length > 0 && <Select label="Option concernée" value={opt} placeholder="Aucune" onChange={(e) => setOpt(e.target.value)} options={c.options.map((o) => ({ value: o.id, label: o.title }))} />}
            <CmdButton def={cmd.annotateCouncil} payload={{ councilId: c.id, text: note, contributionIds: sel, optionId: opt || undefined }} size="small" success="Annotation ajoutée" onDone={() => { setNote(''); setSel([]); }}>Annoter le désaccord</CmdButton>
          </div>
        </Panel>
        <Panel title="Inviter une expertise supplémentaire">
          <Select label="Expertise" value={invite} placeholder="Choisir…" onChange={(e) => setInvite(e.target.value)} options={others.map((e) => ({ value: e.id, label: `${e.name} — ${e.domain}${e.budget.used >= e.budget.units ? ' (budget atteint)' : ''}` }))} />
          <CmdButton def={cmd.inviteExpert} payload={{ councilId: c.id, expertId: invite }} size="small" success="Expertise invitée : son avis arrivera pendant la session">Inviter</CmdButton>
        </Panel>
      </div>
    </div>
  );
}

function synthesisOf(s: ReturnType<typeof useAppState>, c: Council) {
  const scenario = c.scenario ? services.agents.scenarios[c.scenario] : undefined;
  const project = s.db.project[c.projectId];
  const unknown = unknownFacts(bpVersion(s, c.orgId, project?.blueprintVersion)).filter((f) => c.requiredFacts.includes(f.key));
  const tally = (o: CouncilOption) => c.contributions.reduce((n, x) => n + (x.stances[o.id] === 'pour' ? 1 : x.stances[o.id] === 'contre' ? -1 : 0), 0);
  const best = [...c.options].sort((a, b) => tally(b) - tally(a))[0];
  return {
    problem: scenario?.problem ?? c.objective,
    compromise: scenario?.compromise ?? 'Aucun compromis préparé : sujet hors scénario.',
    blocking: [...unknown.map((f) => `Information inconnue requise : ${f.label}`), ...c.options.flatMap((o) => o.blocking.map((b) => `${o.title} : ${b}`)), ...c.contributions.filter((x) => x.reservation && !x.limited).map((x) => `${s.db.expert[x.expertId]?.name} : ${x.reservation}`)],
    recommendation: best ? `${best.title} recueille le plus d’avis favorables (${tally(best)} net). Indicatif : la décision revient au responsable humain et ne lève aucun blocage.` : 'Aucune recommandation : pas d’option préparée.',
    questions: [...c.contributions.flatMap((x) => x.questions.map((q) => `${s.db.expert[x.expertId]?.name} : ${q}`)), ...c.clarifications.filter((k) => /ne contient pas/.test(k.answer)).map((k) => k.question)],
    unknown,
  };
}

function Synthesis({ c }: { c: Council }) {
  const s = useAppState();
  const syn = useMemo(() => synthesisOf(s, c), [s, c]);
  return (
    <div className="grid-2">
      <Panel title="Problème"><p>{syn.problem}</p></Panel>
      <Panel title="Compromis"><p>{syn.compromise}</p></Panel>
      <Panel title="Options et impacts">{c.options.length ? <ul className="bullets">{c.options.map((o) => <li key={o.id}><strong>{o.title}</strong> — {Object.entries(o.impacts).map(([k, v]) => `${k} : ${v}`).join(' ; ')}</li>)}</ul> : <p className="muted small">Aucune option préparée.</p>}</Panel>
      <Panel title={`Points bloquants (${syn.blocking.length})`} tone={syn.blocking.length ? 'danger' : undefined}>{syn.blocking.length ? <ul className="bullets">{syn.blocking.map((b) => <li key={b}>{b}</li>)}</ul> : <p className="small muted">Aucun.</p>}{syn.unknown.length > 0 && <a href="#/blueprint/assistant" className="small">Résoudre l’inconnue dans le Blueprint</a>}</Panel>
      <Panel title="Recommandation" tone="ai"><p>{syn.recommendation}</p></Panel>
      <Panel title={`Questions ouvertes (${syn.questions.length})`}>{syn.questions.length ? <ul className="bullets small">{syn.questions.map((q) => <li key={q}>{q}</li>)}</ul> : <p className="small muted">Aucune.</p>}</Panel>
    </div>
  );
}

function Arbitration({ c }: { c: Council }) {
  const s = useAppState();
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : '';
  const [optionId, setOptionId] = useState(c.options[0]?.id ?? '');
  const [justification, setJustification] = useState('');
  const [ownerId, setOwnerId] = useState(c.ownerId || me);
  const decisions = list(s, 'decision', s.session.orgId).filter((d) => d.councilId === c.id).sort((a, b) => b.number - a.number);
  return (
    <div className="grid-2">
      <Panel title="Décision humaine">
        {c.status !== 'awaiting' && !decisions.length && <Notice tone="info">L’arbitrage s’ouvre quand la session passe « en attente d’arbitrage ».</Notice>}
        <Select label="Option retenue" value={optionId} onChange={(e) => setOptionId(e.target.value)} options={c.options.map((o) => ({ value: o.id, label: o.title }))} />
        <TextArea label="Justification" value={justification} onChange={(e) => setJustification(e.target.value)} hint="Conservée avec les options et les désaccords." />
        <Select label="Responsable de la décision" value={ownerId} onChange={(e) => setOwnerId(e.target.value)} options={[...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))].map((id) => ({ value: id, label: s.users[id]?.name ?? id }))} />
        <CmdButton def={cmd.proposeDecision} payload={{ councilId: c.id, optionId, justification, ownerId }} variant="primary" icon="check" success="Décision proposée (brouillon)">Enregistrer la décision</CmdButton>
      </Panel>
      <Panel title="Décisions de la session">
        {decisions.length === 0 ? <p className="small muted">Aucune décision.</p> : decisions.map((d) => (
          <div key={d.id} className="card" style={{ margin: 3 }}>
            <div className="row between"><a href={`#/decisions/${d.id}`}><strong>{d.optionTitle}</strong></a><span className="row"><Version n={d.number} /><StatusBadge kind="decision" state={d.status} /></span></div>
            <p className="small" style={{ margin: '4px 0' }}>{d.justification}</p>
            <Lifecycle kind="decision" id={d.id} state={d.status} compact />
          </div>
        ))}
      </Panel>
    </div>
  );
}

function ContextTab({ c }: { c: Council }) {
  const s = useAppState();
  return (
    <Panel title="Contexte de départ">
      <KV items={[
        ['Objectif', c.objective], ['Contexte', c.context || '—'], ['Contraintes', c.constraints.length ? <ul className="bullets">{c.constraints.map((x) => <li key={x}>{x}</li>)}</ul> : '—'],
        ['Règles retenues', c.ruleIds.map((r) => <span key={r} style={{ display: 'block' }}><ObjectLink to={{ kind: 'rule', id: r }} /></span>)], ['Documents', c.documentIds.map((d) => <ObjectLink key={d} to={{ kind: 'deliverable', id: d }} />)],
        ['Participants', <div className="row">{c.participantIds.map((p) => <ExpertChip key={p} id={p} />)}</div>], ['Informations requises', c.requiredFacts.length ? c.requiredFacts.join(', ') : '—'],
        ['Version du Blueprint au lancement', <Version n={c.blueprintVersion} />], ['Origine', c.origin ? <ObjectLink to={c.origin} /> : 'Création directe'], ['Préparée le', fmtDate(c.createdAt, true)],
      ]} />
      <p className="tiny muted" style={{ marginTop: 8 }}>{objectLabel(s, { kind: 'project', id: c.projectId })}</p>
    </Panel>
  );
}

/* ------------------------------------------------------------------ decision */
export function DecisionPage({ id }: { id?: ID }) {
  const s = useAppState();
  const d = id ? s.db.decision[id] : undefined;
  const [revise, setRevise] = useState('');
  const [extra, setExtra] = useState(false);
  if (!d || d.orgId !== s.session.orgId) return <NotFound what="Décision" />;
  const versions = list(s, 'decision', s.session.orgId).filter((x) => x.councilId === d.councilId).sort((a, b) => a.number - b.number);
  const prev = versions.find((x) => x.id === d.revisionOf);
  return (
    <div className="stack">
      <Panel title={`Décision — ${d.title}`} actions={<><Version n={d.number} /><Lifecycle kind="decision" id={d.id} state={d.status} /></>}>
        <KV items={[['Option retenue', d.optionTitle], ['Justification', d.justification], ['Responsable', <Person id={d.ownerId} showRole />], ['Auteur', <Person id={d.authorId} />], ['Session', d.councilId ? <ObjectLink to={{ kind: 'council', id: d.councilId }} /> : '—'],
          ['Versions prises en compte', <>Blueprint <Version n={d.considered.blueprintVersion} />, {d.considered.rules.length} règle(s)</>], ['Remplace', d.revisionOf ? <ObjectLink to={{ kind: 'decision', id: d.revisionOf }} /> : '—'], ['Remplacée par', d.replacedBy ? <ObjectLink to={{ kind: 'decision', id: d.replacedBy }} /> : '—'],
          ['Motif', d.statusReason ?? '—'], ['Décidée le', fmtDate(d.decidedAt, true)]]} />
      </Panel>
      <div className="grid-2">
        <Panel title="Validation humaine"><ApprovalList subject={{ kind: 'decision', id: d.id }} /></Panel>
        <Panel title="Quêtes issues de la décision">
          {d.questIds.length ? <ul className="plain stack tight">{d.questIds.map((q) => <li key={q}><ObjectLink to={{ kind: 'quest', id: q }} /> <StatusBadge kind="quest" state={s.db.quest[q]?.status ?? 'todo'} /></li>)}</ul> : <p className="small muted">Aucune quête créée.</p>}
          {d.questPlan.length > 0 && <p className="small muted">Plan : {d.questPlan.map((p) => p.title).join(' ; ')}</p>}
          <CmdButton def={cmd.convertDecision} payload={{ decisionId: d.id }} variant="primary" icon="quest" success={(ids) => `${(ids as string[]).length} quête(s) créée(s)`}>Créer les quêtes</CmdButton>
          {d.questIds.length > 0 && (extra
            ? <CmdButton def={cmd.convertDecision} payload={{ decisionId: d.id, confirmExtra: true }} variant="danger" icon="plus" success="Quête supplémentaire créée" confirm={{ title: 'Créer une quête supplémentaire ?', message: <p>Cette décision a déjà produit {d.questIds.length} quête(s). Confirmez pour en créer une de plus.</p>, label: 'Créer une quête supplémentaire' }}>Confirmer la création supplémentaire</CmdButton>
            : <Button size="small" variant="ghost" onClick={() => setExtra(true)}>Créer une quête supplémentaire…</Button>)}
        </Panel>
      </div>
      <Panel title="Réviser la décision">
        <p className="small muted">La révision crée une nouvelle version en brouillon ; cette version reste en vigueur jusqu’à l’approbation de la nouvelle.</p>
        <TextArea label="Motif de la révision" value={revise} onChange={(e) => setRevise(e.target.value)} />
        <CmdButton def={cmd.reviseDecision} payload={{ decisionId: d.id, justification: revise }} icon="edit" success="Révision proposée" onDone={(nid) => navigate(`/decisions/${nid}`)}>Proposer une révision</CmdButton>
      </Panel>
      {prev && <Panel title={`Différences avec la v${prev.number}`}><DiffView before={`Option : ${prev.optionTitle}\nJustification : ${prev.justification}`} after={`Option : ${d.optionTitle}\nJustification : ${d.justification}`} labels={[`v${prev.number}`, `v${d.number}`]} /></Panel>}
      <Panel title="Historique des versions">
        <ul className="plain stack tight">{versions.map((v) => <li key={v.id} className="row"><Version n={v.number} /><StatusBadge kind="decision" state={v.status} /><a href={`#/decisions/${v.id}`}>{v.optionTitle}</a><span className="tiny muted">{fmtDate(v.createdAt)}</span></li>)}</ul>
      </Panel>
    </div>
  );
}
