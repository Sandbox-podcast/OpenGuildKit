/** Guild: the AI expertises, their sheets, team composition and versioned instructions (brief §5.4). */
import { useState } from 'react';
import { NotFound } from '@/demo/app/App';
import { useAppState } from '@/demo/app/store';
import { navigate } from '@/shared/router';
import { cmd } from '@/demo/domain/commands';
import { list } from '@/demo/domain/engine';
import { fmtDate } from '@/demo/domain/selectors';
import type { Expert, ID } from '@/demo/domain/types';
import { CLI_BOARDS } from '@/demo/fixtures/registry';
import { Icon } from '@/shared/pixel/icons';
import { toDataUrl } from '@/shared/pixel/painter';
import { characterGrid, characterUrl, CLASS_COLORS } from '@/shared/pixel/portraits';
import { Badge, Button, Checkbox, Empty, KV, Notice, Panel, Progress, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { ApprovalList, CmdButton, ObjectLink, Person, Portrait, Version } from '@/demo/ui/domain';
import { DiffView } from '@/demo/ui/content';
import './guild-scene.css';

const WORKBENCHES = ['architecture', 'product', 'engineering', 'documentation'] as const;

function GuildWorkshop({ experts }: { experts: Expert[] }) {
  const active = experts.filter((expert) => expert.active);
  const assigned = WORKBENCHES.map((key) => active.find((expert) => expert.key === key));
  const available = active.filter((expert) => !assigned.includes(expert));
  const stations = assigned.map((expert) => expert ?? available.shift());
  if (active.length === 0) return null;

  return (
    <section className="guild-workshop" aria-label="Postes de la guilde">
      <img className="guild-workshop-image" src="./assets/world/atelier-guilde.webp" srcSet="./assets/world/atelier-guilde-mobile.webp 720w, ./assets/world/atelier-guilde.webp 1440w" sizes="(max-width: 900px) 100vw, calc(100vw - 280px)" width={1440} height={628} alt="" decoding="async" />
      <ul className="plain guild-workshop-stations">
        {stations.map((expert, index) => expert && (
          <li key={expert.id} className={`guild-station guild-station-${index + 1}`}>
            <a className="guild-station-link" href={`#/guilde/${expert.id}`}>
              <picture className="guild-station-art">
                <source media="(max-width: 680px)" srcSet={toDataUrl(`standing:${expert.key}`, () => characterGrid(expert.key))} />
                <img className="pixel guild-station-sprite" src={characterUrl(expert.key)} width={80} height={112} alt="" />
              </picture>
              <span className="guild-station-sign"><strong>{expert.name}</strong><span>{expert.domain}</span></span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function GuildSpace({ tab }: { tab?: string }) {
  const s = useAppState();
  const experts = list(s, 'expert', s.session.orgId);
  const [team, setTeam] = useState<ID[]>([]);
  const view = tab === 'equipe' ? 'equipe' : 'salle';
  const pending = experts.filter((e) => e.instructions.some((i) => i.status === 'proposed'));
  return (
    <div className="stack">
      <Tabs label="Expertises" value={view} onChange={(t) => navigate(t === 'equipe' ? '/guilde/equipe' : '/guilde')} tabs={[{ id: 'salle', label: s.prefs.mode === 'focus' ? 'Catalogue' : 'Salle de la guilde', icon: 'guild' }, { id: 'equipe', label: 'Composer une équipe', icon: 'council', count: team.length }]} />
      {view === 'salle' && s.prefs.mode === 'explorer' && <GuildWorkshop experts={experts} />}
      <Notice tone="ai">Les expertises IA donnent des avis. Un responsable humain valide les décisions.</Notice>
      {pending.length > 0 && view === 'salle' && <Notice tone="warn" title="Évolutions en attente :">{pending.map((e) => <a key={e.id} href={`#/guilde/${e.id}?onglet=instructions`} style={{ marginRight: 10 }}>{e.name}</a>)}</Notice>}
      {view === 'equipe' && (
        <Panel title="Équipe pour un Conseil" actions={<Button variant="primary" icon="council" disabled={!team.length} onClick={() => navigate(`/conseil?nouveau=1&experts=${team.join(',')}`)}>Préparer un Conseil</Button>}>
          <p className="small muted">Sélectionnez les expertises à mobiliser. Les expertises inactives ne peuvent pas être convoquées.</p>
        </Panel>
      )}
      {view === 'salle' && <h2 className="guild-roster-title">Toutes les expertises <span className="tiny muted">{experts.length}</span></h2>}
      <div className="guild-hall">
        {experts.map((e) => {
          const chosen = team.includes(e.id);
          const card = (
            <>
              <span className="portrait-frame" style={{ ['--class' as string]: CLASS_COLORS[e.key] }}><Portrait k={e.key} size={96} alt={`Portrait de l’expertise ${e.name}`} /></span>
              <span className="class">{e.name}</span>
              <span className="small">{e.domain}</span>
              <span className="row" style={{ justifyContent: 'center' }}><span className="ai-mark"><Icon name="ai" size={10} />IA</span>{!e.active && <Badge tone="muted">inactive</Badge>}{e.budget.used >= e.budget.units && <Badge tone="danger" icon="warn">budget atteint</Badge>}</span>
            </>
          );
          return view === 'equipe' ? (
            <button key={e.id} className={`card expert-card ${chosen ? 'selected' : ''} ${e.active ? '' : 'inactive'}`} aria-pressed={chosen} disabled={!e.active} onClick={() => setTeam((t) => (chosen ? t.filter((x) => x !== e.id) : [...t, e.id]))}>{card}</button>
          ) : (
            <a key={e.id} href={`#/guilde/${e.id}`} className={`card expert-card ${e.active ? '' : 'inactive'}`}>{card}</a>
          );
        })}
      </div>
    </div>
  );
}

export function ExpertSheet({ id }: { id: ID }) {
  const s = useAppState();
  const e = s.db.expert[id];
  const [tab, setTab] = useState(() => new URLSearchParams(location.hash.split('?')[1]).get('onglet') ?? 'fiche');
  if (!e || e.orgId !== s.session.orgId) return <NotFound what="Expertise" />;
  const board = CLI_BOARDS[e.boardId];
  const contributions = list(s, 'council', s.session.orgId).flatMap((c) => c.contributions.filter((x) => x.expertId === e.id).map((x) => ({ c, x }))).sort((a, b) => b.x.at - a.x.at);
  return (
    <div className="stack">
      <Panel>
        <div className="expert-hero">
          <span className="expert-profile-art">
            {s.prefs.mode === 'explorer' ? <img className="pixel" src={characterUrl(e.key)} width={120} height={168} alt="" /> : <Portrait k={e.key} size={64} />}
          </span>
          <div className="stack tight">
            <h1 className="pixel-font" style={{ margin: 0 }}>{e.name} <span className="ai-mark"><Icon name="ai" size={12} />Expertise IA</span></h1>
            <p className="muted" style={{ margin: 0 }}>{e.domain} — {e.specialty}</p>
            <div className="row">{e.active ? <Badge tone="success" icon="check">Active</Badge> : <Badge tone="muted">Inactive</Badge>}<Badge tone="info">Board CLI : {e.boardId}</Badge></div>
            <KV items={[['Agent (IA)', <span className="row"><Portrait k={e.key} size={20} />{e.name}<span className="ai-mark">IA</span></span>], ['Créateur', <Person id={e.creatorId} showRole />], ['Responsable humain', <Person id={e.humanOwnerId} showRole />], ['Approbateur des évolutions', <Person id={e.approverId} showRole />]]} />
          </div>
        </div>
      </Panel>
      <div className="tabs" role="tablist" aria-label="Fiche d’expertise">
        {[['fiche', 'Fiche'], ['outils', 'Outils et budget'], ['instructions', 'Instructions versionnées'], ['contributions', 'Contributions récentes']].map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === 'fiche' && (
        <div className="grid-2">
          <Panel title="Capacités et méthodes">
            <h3>Capacités</h3><ul className="bullets">{e.capabilities.map((c) => <li key={c}>{c}</li>)}</ul>
            <h3>Méthodes</h3><ul className="bullets">{e.methods.map((c) => <li key={c}>{c}</li>)}</ul>
            <h3>Skills</h3><ul className="bullets">{e.skillIds.map((sid) => <li key={sid}><a href={`#/forge/skills?skill=${sid}`}>{s.db.skill[sid]?.name ?? sid}</a></li>)}</ul>
          </Panel>
          <Panel title="Sources, contexte et limites">
            <h3>Sources</h3><ul className="bullets">{e.sources.map((r) => <li key={r}><ObjectLink to={{ kind: 'reference', id: r }} /></li>)}</ul>
            <h3>Contexte accessible</h3><p className="small">{e.contextAccess.join(' · ')}</p>
            <h3>Limites</h3><ul className="bullets">{e.limits.map((c) => <li key={c}>{c}</li>)}</ul>
            <MemoryPanel e={e} />
          </Panel>
          {board && (
            <Panel title={`Grille de revue du board « ${board.title} » (registre CLI, en anglais)`} className="full">
              <p className="small muted">{board.description}</p>
              <ul className="bullets small">{board.review?.specialists?.map((sp) => <li key={sp.id}><strong>{sp.title}</strong> — {sp.focus}</li>)}</ul>
              <h3>Questions</h3><ul className="bullets small">{board.questions.map((q) => <li key={q}>{q}</li>)}</ul>
            </Panel>
          )}
        </div>
      )}
      {tab === 'outils' && <ToolsPanel e={e} />}
      {tab === 'instructions' && <InstructionsPanel e={e} />}
      {tab === 'contributions' && (
        <Panel title="Contributions récentes">
          {contributions.length === 0 ? <Empty title="Aucune contribution">Invitez cette expertise à un Conseil.</Empty> : (
            <ul className="plain stack tight">{contributions.slice(0, 12).map(({ c, x }) => <li key={x.id} className="card"><div className="row between"><ObjectLink to={{ kind: 'council', id: c.id }} /><span className="tiny muted">{fmtDate(x.at, true)}</span></div><p className="small" style={{ margin: '4px 0 0' }}>{x.recommendation}</p></li>)}</ul>
          )}
        </Panel>
      )}
    </div>
  );
}

function MemoryPanel({ e }: { e: Expert }) {
  const [text, setText] = useState('');
  return (
    <>
      <h3>Mémoire de démonstration</h3>
      {e.memory.length === 0 ? <p className="small muted">Aucun élément mémorisé.</p> : <ul className="bullets small">{e.memory.map((m) => <li key={m}>{m}</li>)}</ul>}
      <div className="row"><div className="grow"><TextField label="Ajouter un élément" value={text} onChange={(ev) => setText(ev.target.value)} /></div><CmdButton def={cmd.updateExpert} payload={{ expertId: e.id, memory: text }} size="small" success="Mémoire mise à jour" onDone={() => setText('')}>Ajouter</CmdButton></div>
    </>
  );
}

function ToolsPanel({ e }: { e: Expert }) {
  const s = useAppState();
  const [tools, setTools] = useState(e.toolsAllowed);
  const [budget, setBudget] = useState(e.budget.units);
  const members = [...new Set(list(s, 'member', s.session.orgId).filter((m) => ['owner', 'admin', 'maintainer'].includes(m.role)).map((m) => m.userId))];
  return (
    <div className="grid-2">
      <Panel title="Outils autorisés">
        <p className="small muted">Un agent n’agit qu’avec les outils autorisés pour sa mission. Il ne peut ni élargir ses droits, ni modifier cette politique.</p>
        {e.toolsAvailable.map((t) => <Checkbox key={t} label={t} checked={tools.includes(t)} onChange={(ev) => setTools(ev.target.checked ? [...tools, t] : tools.filter((x) => x !== t))} />)}
        <CmdButton def={cmd.restrictTools} payload={{ expertId: e.id, tools }} variant="primary" success="Outils mis à jour">Enregistrer les outils</CmdButton>
      </Panel>
      <Panel title="Budget et responsabilités">
        <p className="small">Consommation : {e.budget.used} / {e.budget.units} unités de simulation</p>
        <Progress value={Math.min(100, Math.round((e.budget.used / Math.max(1, e.budget.units)) * 100))} label="Budget consommé" />
        <div className="row" style={{ marginTop: 8 }}><TextField label="Budget (unités)" type="number" value={budget} onChange={(ev) => setBudget(Number(ev.target.value))} /><CmdButton def={cmd.updateExpert} payload={{ expertId: e.id, budget }} size="small" success="Budget mis à jour">Appliquer</CmdButton></div>
        <div className="row" style={{ marginTop: 8 }}>
          <CmdButton def={cmd.updateExpert} payload={{ expertId: e.id, active: !e.active }} size="small" success={e.active ? 'Expertise désactivée' : 'Expertise activée'}>{e.active ? 'Désactiver' : 'Activer'}</CmdButton>
        </div>
        <h3 style={{ marginTop: 10 }}>Approbateur des évolutions</h3>
        <div className="row">{members.filter((m) => m !== e.approverId).slice(0, 3).map((m) => <CmdButton key={m} def={cmd.updateExpert} payload={{ expertId: e.id, approverId: m }} size="small" success="Approbateur modifié">{s.users[m]?.name}</CmdButton>)}</div>
      </Panel>
    </div>
  );
}

function InstructionsPanel({ e }: { e: Expert }) {
  const active = e.instructions.find((i) => i.status === 'active');
  const proposed = e.instructions.find((i) => i.status === 'proposed');
  const [text, setText] = useState(active?.text ?? '');
  return (
    <div className="grid-2">
      <Panel title="Versions des instructions">
        <ul className="plain stack tight">
          {[...e.instructions].reverse().map((i) => (
            <li key={i.number} className="card">
              <div className="row between"><span className="row"><Version n={i.number} /><Badge tone={i.status === 'active' ? 'success' : i.status === 'proposed' ? 'info' : 'muted'}>{({ active: 'en vigueur', proposed: 'proposée', rejected: 'refusée', retired: 'remplacée' })[i.status]}</Badge></span><span className="tiny muted">{fmtDate(i.at)}</span></div>
              <p className="small" style={{ margin: '6px 0' }}>{i.text}</p>
              <span className="tiny muted">Auteur : <Person id={i.authorId} />{i.decidedBy && <> · décision : <Person id={i.decidedBy} /></>}</span>
            </li>
          ))}
        </ul>
        {proposed && active && <><h3 style={{ marginTop: 10 }}>Évolution proposée</h3><DiffView before={active.text} after={proposed.text} labels={[`v${active.number}`, `v${proposed.number}`]} /></>}
      </Panel>
      <div className="stack">
        <Panel title="Validation des évolutions"><ApprovalList subject={{ kind: 'expert', id: e.id }} /></Panel>
        <Panel title="Proposer une évolution">
          <TextArea label="Nouvelles instructions" value={text} onChange={(ev) => setText(ev.target.value)} hint="La proposition doit être approuvée par l’approbateur désigné, distinct de son auteur." />
          <CmdButton def={cmd.proposeInstructions} payload={{ expertId: e.id, text }} variant="primary" success={(n) => `Instructions v${n} proposées`}>Proposer la version {e.instructions.length + 1}</CmdButton>
        </Panel>
      </div>
    </div>
  );
}

