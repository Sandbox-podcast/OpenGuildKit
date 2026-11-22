/** Quêtes: every task of the project by state, a new task, and the sheet of one task with its next step. */
import { useMemo, useState } from 'react';
import { navigate, setQuery, useRoute } from '@/app/router';
import { Badge, Button, Empty, KV, Notice, Panel, TextArea, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Icon } from '@/shared/pixel/icons';
import { norm } from '@/shared/text';
import { useBrains, useTasks, boardTitle } from '../data';
import { useAction, useCli } from '../query';
import { DATA, KIND, RESEARCH, SURFACE, fmtDay, fmtWhen, isBlocked, isDecided, needsReconsult, nextLabel, nextLang, statusesOf, taskStatus, verdict } from '../labels';
import { ExternalLink, JsonDetails, Q, StepRail, TaskLink, TaskStatusBadge, UnreadableTask } from '../parts';
import { usePrefs } from '../prefs';
import type { TaskListItem, TaskRecord } from '../types';

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function NewQuestDialog({ open, onClose, follows }: { open: boolean; onClose: () => void; follows?: string }) {
  const tasks = useTasks();
  const [brief, setBrief] = useState('');
  const [id, setId] = useState('');
  const [after, setAfter] = useState(follows ?? '');
  const { act, busy } = useAction();
  const idError = id && (!SLUG.test(id) || id.length > 64) ? 'Minuscules, chiffres et tirets simples, 64 caractères au plus.' : null;
  const submit = async () => {
    const argv = ['task', 'new', '--file', '@upload:brief.md', ...(id ? ['--id', id] : []), ...(after ? ['--follows', after] : [])];
    const result = await act(argv, { uploads: { 'brief.md': brief.trim() + '\n' }, success: 'Quête ouverte' });
    if (result) {
      const created = result.stdout.trim().split(/\s+/).pop() ?? id;
      setBrief(''); setId(''); onClose();
      navigate(`/conseil/${created}`);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} title="Ouvrir une quête" footer={<><Button onClick={onClose}>Annuler</Button><Button variant="primary" busy={busy !== null} disabled={!brief.trim() || !!idError} onClick={() => void submit()}>Ouvrir la quête</Button></>}>
      <p className="small muted">La CLI enregistre le brief tel quel, puis le Conseil le cadre avec le questionnaire. <code>openguildkit sync</code> doit être à jour.</p>
      <TextArea label="Ce que l’équipe doit faire" hint="Le besoin, sans la solution. Plusieurs lignes possibles." value={brief} onChange={(e) => setBrief(e.target.value)} rows={5} required />
      <TextField label="Identifiant (facultatif)" hint="Par exemple request-status. Sans identifiant, la CLI en génère un." value={id} error={idError} onChange={(e) => setId(e.target.value.trim())} />
      <div className="field"><label htmlFor="follows">Fait suite à (facultatif)</label>
        <select id="follows" className="input" value={after} onChange={(e) => setAfter(e.target.value)}>
          <option value="">Aucune quête</option>
          {(tasks.data ?? []).filter((t) => isDecided(t.status)).map((t) => <option key={t.id} value={t.id}>{t.id} : {(t.brief ?? '').slice(0, 60)}</option>)}
        </select>
        <p className="hint">La consultation reprendra la décision de cette quête.</p>
      </div>
    </Dialog>
  );
}

export function Quests() {
  const tasks = useTasks();
  const route = useRoute();
  const { mode } = usePrefs();
  const q = route.query.get('q') ?? '';
  const status = route.query.get('statut') ?? '';
  const owner = route.query.get('responsable') ?? '';
  const [open, setOpen] = useState(route.query.has('nouvelle'));
  const items = useMemo(() => (tasks.data ?? []).filter((t) => (!status || t.status === status) && (!owner || t.owner === owner) && (!q || norm(`${t.id} ${t.brief} ${t.next}`).includes(norm(q)))), [tasks.data, q, status, owner]);
  const owners = [...new Set((tasks.data ?? []).map((t) => t.owner).filter(Boolean))] as string[];
  const columns = statusesOf(tasks.data ?? []).filter((s) => !status || s === status);

  return (
    <div className="page-grid">
      <div className="toolbar">
        <input className="input" type="search" placeholder="Rechercher une quête…" aria-label="Rechercher une quête" value={q} onChange={(e) => setQuery({ q: e.target.value })} />
        <select className="input" aria-label="État" value={status} onChange={(e) => setQuery({ statut: e.target.value })}>
          <option value="">Tous les états</option>{statusesOf(tasks.data ?? []).map((s) => <option key={s} value={s}>{taskStatus(s).label}</option>)}
        </select>
        <select className="input" aria-label="Responsable de la décision" value={owner} onChange={(e) => setQuery({ responsable: e.target.value })}>
          <option value="">Toutes les personnes</option>{owners.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <span className="grow" />
        <Button variant="primary" icon="plus" onClick={() => setOpen(true)}>Nouvelle quête</Button>
      </div>
      <Q q={tasks} empty={<Empty title="Aucune quête" action={<Button variant="primary" onClick={() => setOpen(true)}>Ouvrir la première quête</Button>}>Une quête décrit une demande : une fonctionnalité, une anomalie, une décision.</Empty>}>
        {() => (
          <div className="kanban" role="list" aria-label="Quêtes par état">
            {columns.map((s) => {
              const col = items.filter((t) => t.status === s);
              return (
                <section key={s} className="kanban-col" role="listitem" aria-label={`${taskStatus(s).label} (${col.length})`}>
                  <header><TaskStatusBadge status={s} /><span className="badge count">{col.length}</span></header>
                  <ul className="plain stack tight">{col.map((t) => <QuestCard key={t.id} t={t} rpg={mode === 'explorer'} />)}</ul>
                  {col.length === 0 && <p className="tiny muted">—</p>}
                </section>
              );
            })}
          </div>
        )}
      </Q>
      <NewQuestDialog open={open} onClose={() => { setOpen(false); if (route.query.has('nouvelle')) setQuery({ nouvelle: null }); }} />
    </div>
  );
}

function QuestCard({ t, rpg }: { t: TaskListItem; rpg: boolean }) {
  const reconsult = needsReconsult(t);
  const stuck = isBlocked(t.next) || reconsult || t.status === 'unreadable';
  return (
    <li><a className={`card task-card ${stuck ? 'blocked' : ''}`} href={`#/quetes/${t.id}`}>
      <span className="mono small">{t.id}</span>
      {t.brief && <strong className="clamp-2">{t.brief}</strong>}
      {reconsult && <Badge tone="danger" icon="replace">À consulter à nouveau, par une personne</Badge>}
      {t.status === 'unreadable' && <Badge tone="danger" icon="warn">À réparer, par une personne</Badge>}
      <span className="small muted clamp-2" lang={nextLang(t.next)}>{isBlocked(t.next) && <Icon name="ban" size={12} />} {nextLabel(t.next)}</span>
      <span className="row tiny muted">{fmtDay(t.created)}{t.owner && <> · {rpg ? 'scellée par' : 'décidée par'} {t.owner}</>}{t.follows && <> · suite de {t.follows}</>}</span>
    </a></li>
  );
}

/** Where the next action of a task happens. */
export function nextPlace(t: { id: string; status: string; severity?: string }) {
  if (needsReconsult(t)) return { to: `/conseil/${t.id}`, label: 'Consulter à nouveau', icon: 'council' as const };
  switch (t.status) {
    case 'draft': case 'consulting': case 'changes-requested': case 'reviewed': return { to: `/conseil/${t.id}`, label: 'Ouvrir la salle du Conseil', icon: 'council' as const };
    case 'approved': return { to: `/forge/${t.id}`, label: 'Aller à la Forge', icon: 'anvil' as const };
    default: return { to: `/documentation`, label: 'Documenter', icon: 'scroll' as const };
  }
}

export function QuestSheet({ id }: { id: string }) {
  const list = useTasks();
  const item = list.data?.find((t) => t.id === id);
  // A record the CLI cannot read is explained here: task show would only fail without context.
  if (item?.status === 'unreadable') return <div className="page-grid"><p className="mono small muted">{id}</p><UnreadableTask id={id} message={item.next} /></div>;
  return <QuestRecord id={id} item={item} />;
}

function QuestRecord({ id, item }: { id: string; item?: TaskListItem }) {
  const record = useCli<TaskRecord>(['task', 'show', id], { omit: ['markdown', 'review_template', 'scope'] });
  const list = useTasks();
  const brains = useBrains();
  const [followUp, setFollowUp] = useState(false);
  const { act, busy } = useAction();
  const children = (list.data ?? []).filter((t) => t.follows === id);

  return (
    <Q q={record} label="Lecture de la quête">
      {(t) => {
        const place = nextPlace({ ...t, severity: item?.severity });
        return (
          <div className="page-grid">
            <div className="quest-head">
              <div className="grow">
                <p className="mono small muted">{t.id} · ouverte le {fmtWhen(t.created_at)}</p>
                <h2 className="h-title">{t.brief.split('\n')[0]}</h2>
                <div className="row"><TaskStatusBadge status={t.status} />{t.follows && <Badge tone="info" icon="link">suite de {t.follows.task}</Badge>}{t.answers?.kind && <Badge>{KIND[t.answers.kind] ?? t.answers.kind}</Badge>}</div>
              </div>
              <div className="row">
                <a className="btn primary" href={`#${place.to}`}><Icon name={place.icon} size={14} /> {place.label}</a>
                {isDecided(t.status) && <Button icon="download" busy={busy !== null} onClick={() => void act(['task', 'export', t.id], { success: 'Décision exportée dans .openguildkit/decisions' })}>Exporter la décision</Button>}
                {isDecided(t.status) && <Button icon="plus" onClick={() => setFollowUp(true)}>Quête de suite</Button>}
              </div>
            </div>
            <StepRail status={t.status} hasResult={!!t.result} />
            {item && <Notice tone={isBlocked(item.next) || needsReconsult(item) ? 'danger' : 'info'} title={needsReconsult(item) ? 'L’approbation ne tient plus :' : 'Prochaine étape :'}><span lang={nextLang(item.next)}>{nextLabel(item.next)}</span></Notice>}
            <div className="grid-2">
              <Panel title="Brief">
                <p className="pre-line">{t.brief}</p>
                {t.answers && <KV items={[
                  ['Nature', KIND[t.answers.kind ?? ''] ?? t.answers.kind ?? '—'],
                  ['Zones', [t.answers.surface].flat().filter(Boolean).map((s) => SURFACE[s as string] ?? s).join(', ') || '—'],
                  ['Données', DATA[t.answers.data ?? ''] ?? '—'],
                  ['Preuves consultables', RESEARCH[t.answers.research ?? ''] ?? '—'],
                  ...(t.answers.context ? [['Contexte', t.answers.context] as [string, string]] : []),
                  ...(t.answers.outcome ? [['Résultat attendu', t.answers.outcome] as [string, string]] : []),
                ]} />}
                {t.follows && <p className="small">Fait suite à <TaskLink id={t.follows.task} /> : {t.follows.decision ? `${t.follows.decision.outcome === 'approved' ? 'validée' : 'renvoyée'} par ${t.follows.decision.by}` : t.follows.status}.</p>}
              </Panel>
              <Panel title="Conseil">
                {t.consultation ? <>
                  <p className="small muted">Consultation {t.consultation.id.slice(0, 8)} · {t.consultation.boards.length} cerveau(x)</p>
                  <ul className="plain stack tight">{t.consultation.boards.map((b) => {
                    const entry = t.review?.boards.find((x) => x.id === b);
                    const v = verdict(entry?.challenge?.verdict);
                    return <li key={b} className="row between"><span><a href={`#/guilde/${b}`}>{boardTitle(brains.data, b)}</a> <span className="tiny muted">{t.consultation!.routing[b]?.join(' · ')}</span></span>{entry ? <Badge tone={v.tone} icon={v.icon}>{v.label}</Badge> : <Badge tone="muted" icon="clock">en attente</Badge>}</li>;
                  })}</ul>
                </> : <p className="muted">Pas encore de consultation.</p>}
                {t.decision && <p className="small"><Icon name={t.decision.outcome === 'approved' ? 'lock' : 'replace'} size={12} /> {t.decision.outcome === 'approved' ? 'Validée' : 'Renvoyée'} par <strong>{t.decision.by}</strong> le {fmtWhen(t.decision.at)} : {t.decision.reason}</p>}
              </Panel>
            </div>
            {(t.result || t.deliverables?.length) && <div className="grid-2">
              {t.result && <Panel title="Résultats">
                <KV items={[
                  ['Livré', t.result.pull_request ? <ExternalLink href={t.result.pull_request} /> : t.result.revision ?? '—'],
                  ['Critères', `${t.result.criteria.filter((c) => c.status === 'met').length}/${t.result.criteria.length} atteints`],
                  ['Vérifications', `${t.result.checks.filter((c) => c.status === 'passed').length} réussie(s), ${t.result.checks.filter((c) => c.status === 'failed').length} en échec, ${t.result.checks.filter((c) => c.cannot_run).length} ne pouvant pas tourner ici`],
                  ['Terminée', t.completed_at ? fmtWhen(t.completed_at) : 'pas encore'],
                ]} />
                {!!t.result.waiting_for?.length && <p className="small"><Badge tone="warning" icon="clock">en attente</Badge> {t.result.waiting_for.map((w) => `${w.title} (${w.owner})`).join(', ')}</p>}
                {t.result.closing && t.result.closing.open_points.length > 0 && <details className="small" open={t.status === 'done-with-reservations'}><summary>Réserves de la clôture{t.result.closing.by ? `, confirmée par ${t.result.closing.by}` : ''}</summary>
                  {t.result.closing.open_points.map((g) => <div key={g.group}><strong>{g.group}</strong><ul>{g.points.map((p) => <li key={p}>{p}</li>)}</ul></div>)}</details>}
              </Panel>}
              {!!t.deliverables?.length && <Panel title="Livrables">
                <ul className="plain stack tight">{t.deliverables.map((d) => <li key={d.path}><a href={`#/forge/livrables?brouillon=${encodeURIComponent(d.path)}`}>{d.deliverable}</a> <span className="tiny muted">{d.tool ? `${d.tool} · ` : ''}{fmtDay(d.created_at)}</span></li>)}</ul>
              </Panel>}
            </div>}
            {(t.rounds.length > 0 || children.length > 0) && <Panel title="Historique">
              {t.rounds.map((r, i) => <div key={i} className="small"><p>Tour {i + 1} : {r.decision ? `${r.decision.outcome === 'approved' ? 'validé' : 'renvoyé'} par ${r.decision.by} (${r.decision.reason})` : 'consultation archivée'}.</p>
                {r.brief && r.brief.trim() !== t.brief.trim() && <details><summary>Brief de ce tour</summary><p className="pre-line">{r.brief}</p></details>}</div>)}
              {children.map((c) => <p key={c.id} className="small">Suite : <TaskLink id={c.id} /> <TaskStatusBadge status={c.status} /></p>)}
            </Panel>}
            <JsonDetails data={t} label="Voir l’enregistrement (task show, sans le texte de la consultation)" />
            <NewQuestDialog open={followUp} onClose={() => setFollowUp(false)} follows={t.id} />
          </div>
        );
      }}
    </Q>
  );
}
