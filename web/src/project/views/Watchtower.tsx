/** Tour de guet: instruction drift, host enforcement, guard coverage, the dependency alert register and open blockers. */
import { useCallback, useState } from 'react';
import { navigate } from '@/app/router';
import { Badge, Button, Notice, Panel, Tabs } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Icon } from '@/shared/pixel/icons';
import { batchJson, terminalCommand } from '../api';
import { useAlerts, useCheck, useGuard, useHost, useTasks } from '../data';
import { showTerminal, useAction, useQuery } from '../query';
import { GUARD, SEVERITY, alertLabel, hostControl } from '../labels';
import { ActionForm, ExternalLink, FilePick, Q, TaskLink, useRemembered } from '../parts';
import type { Alert, BlockerItem } from '../types';

export function Watchtower({ tab = 'controles' }: { tab?: string }) {
  const alerts = useAlerts();
  const open = (alerts.data?.summary.by_status.open ?? 0) + (alerts.data?.summary.by_status.confirmed ?? 0);
  const changeTab = (id: string, focus?: HTMLButtonElement) => navigate(`/tour/${id}`, { focus });
  return (
    <div className="page-grid">
      <Tabs label="Tour de guet" value={tab} onChange={changeTab} onKeyboardChange={changeTab} tabs={[
        { id: 'controles', label: 'Contrôles', icon: 'shield' },
        { id: 'alertes', label: 'Alertes de dépendances', icon: 'warn', count: open || undefined },
        { id: 'blocages', label: 'Blocages', icon: 'ban' },
      ]} />
      {tab === 'alertes' ? <Alerts /> : tab === 'blocages' ? <AllBlockers /> : <Controls />}
    </div>
  );
}

function Controls() {
  const check = useCheck();
  const host = useHost();
  const guard = useGuard();
  const { act, busy } = useAction();
  return (
    <div className="grid-2">
      <Panel title="Instructions du projet" actions={<Button size="small" busy={busy !== null} onClick={() => void act(['sync'], { success: 'Instructions synchronisées' })}>Synchroniser</Button>}>
        <Q q={check}>{(r) => r.code === 0 ? <Notice tone="success">{r.stdout.trim()}</Notice> : <Notice tone="danger" title="À corriger :">{(r.stderr || r.stdout).replace(/^OpenGuildKit:\s*/gm, '').trim()}</Notice>}</Q>
        <p className="small muted"><code>openguildkit check</code> fait échouer la CI quand AGENTS.md, les réglages de l’hôte ou le verrou du catalogue s’écartent du profil.</p>
      </Panel>
      <Panel title="Ce que l’hôte applique" actions={<Button size="small" busy={busy !== null} onClick={() => void act(['host', 'apply'], { success: 'Réglages de l’hôte écrits' })}>Appliquer</Button>}>
        <Q q={host}>{(list) => <ul className="plain stack tight">{list.map((c) => { const l = hostControl(c.status); return <li key={c.id} className="card"><span className="row between"><strong>{c.title}</strong><Badge tone={l.tone} icon={l.icon}>{l.label}</Badge></span><span className="small muted">{c.detail}</span></li>; })}</ul>}</Q>
      </Panel>
      <Panel title="Garde des modifications">
        <Q q={guard}>{(g) => <>
          <p>La garde est <strong>{GUARD[g.mode] ?? g.mode}</strong>. Elle dit si une quête validée couvre le travail en cours, pour les crochets de l’hôte et la CI.</p>
          <p className="small">Quêtes qui couvrent le travail : {g.covered_by.length ? g.covered_by.map((id) => <TaskLink key={id} id={id} />) : 'aucune'}.</p>
          <p className="tiny muted">Le mode se règle avec <code>"guard": "off" | "observe" | "enforce"</code> dans le profil (Blueprint).</p>
        </>}</Q>
      </Panel>
    </div>
  );
}

function Alerts() {
  const alerts = useAlerts();
  const tasks = useTasks();
  const [by, setBy] = useRemembered('decider');
  const [report, setReport] = useState<{ text: string; name: string } | null>(null);
  const [task, setTask] = useState('');
  const [reviewing, setReviewing] = useState<Alert | null>(null);
  const [filter, setFilter] = useState('');
  const { act, busy } = useAction();
  const shown = (alerts.data?.alerts ?? []).filter((a) => !filter || a.status === filter);
  return (
    <div className="page-grid">
      <Panel title="Importer un rapport de scanner">
        <p className="small muted">La CLI ne scanne pas : elle lit le rapport JSON d’un outil que le projet utilise déjà (<code>npm audit --json</code>, <code>pip-audit -f json</code>, <code>osv-scanner --format json</code>, alertes Dependabot) et garde une entrée par alerte. Un nouvel import conserve vos décisions.</p>
        <div className="grid-2">
          <FilePick label="Rapport JSON" onText={(text, name) => setReport({ text, name })} />
          <div className="field"><label htmlFor="alert-task">Lier à une quête (facultatif)</label><select id="alert-task" className="input" value={task} onChange={(e) => setTask(e.target.value)}><option value="">Aucune</option>{(tasks.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}</select></div>
        </div>
        <Button variant="primary" disabled={!report} busy={busy !== null} onClick={() => { const name = /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(report!.name) ? report!.name : 'report.json'; void act(['alerts', 'import', `@upload:${name}`, ...(task ? ['--task', task] : [])], { uploads: { [name]: report!.text }, success: 'Rapport importé' }).then((r) => r && setReport(null)); }}>Importer</Button>
      </Panel>
      <Q q={alerts}>{(reg) => <Panel title={`Registre : ${reg.summary.total} alerte(s)`} actions={<select className="input" aria-label="Filtrer par statut" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="">Tous les statuts</option>{Object.keys(reg.summary.by_status).map((s) => <option key={s} value={s}>{alertLabel(s).label} ({reg.summary.by_status[s]})</option>)}</select>}>
        {reg.summary.imports.length > 0 && <p className="tiny muted">Imports : {reg.summary.imports.map((i) => `${i.tool} (${i.file}, sha256 ${i.sha256.slice(0, 12)})`).join(' · ')}</p>}
        {shown.length === 0 ? <p className="muted">Aucune alerte.</p> : <div className="table-wrap"><table className="data compact"><thead><tr><th>Paquet</th><th>Gravité</th><th>Avis</th><th>Statut</th><th>Quêtes</th><th /></tr></thead><tbody>
          {shown.map((a) => { const l = alertLabel(a.status); return <tr key={a.id}>
            <td><strong>{a.package}</strong> <span className="mono tiny">{a.version}</span><span className="tiny muted block">{a.ecosystem} · {a.scanners.join(', ')}</span></td>
            <td><Badge tone={SEVERITY[a.severity] ?? 'neutral'}>{a.severity}</Badge></td>
            <td className="small">{a.url ? <ExternalLink href={a.url}>{a.advisory}</ExternalLink> : a.advisory}<span className="block">{a.summary}</span>{a.fix && <span className="tiny muted block">Correctif : {a.fix}</span>}</td>
            <td><Badge tone={l.tone} icon={l.icon}>{l.label}</Badge>{a.by && <span className="tiny muted block">{a.by}{a.reason ? ` : ${a.reason}` : ''}</span>}{a.accepted && <span className="block"><Badge tone="info" icon="lock">risque accepté par {a.accepted.by}</Badge></span>}</td>
            <td className="small">{a.tasks.map((t) => <TaskLink key={t} id={t} />)}</td>
            <td><Button size="small" onClick={() => setReviewing(a)}>Revoir</Button></td>
          </tr>; })}
        </tbody></table></div>}
      </Panel>}</Q>
      <Dialog open={!!reviewing} onClose={() => setReviewing(null)} title={`Revoir ${reviewing?.package ?? ''}`}>
        {reviewing && <>
          <p className="small">{reviewing.summary}</p>
          <ActionForm busy={busy !== null} submit="Enregistrer" initial={{ by, status: reviewing.status === 'open' ? 'confirmed' : reviewing.status }} fields={[
            { name: 'status', label: 'Statut', required: true, options: [{ value: 'open', label: 'À vérifier' }, { value: 'confirmed', label: 'Confirmée' }, { value: 'dismissed', label: 'Écartée (motif obligatoire)' }] },
            { name: 'by', label: 'Votre nom', required: true },
            { name: 'reason', label: 'Motif', hint: 'Obligatoire pour écarter une alerte.' },
          ]} onSubmit={async (v) => { setBy(v.by); if (await act(['alerts', 'set', reviewing.id, '--status', v.status, '--by', v.by, ...(v.reason ? ['--reason', v.reason] : [])], { success: 'Alerte revue' })) setReviewing(null); }} />
          <hr />
          <ActionForm busy={busy !== null} submit="Lier à la quête" fields={[{ name: 'task', label: 'Quête qui traite l’alerte', required: true, options: (tasks.data ?? []).map((t) => ({ value: t.id, label: t.id })) }]} onSubmit={async (v) => { if (await act(['alerts', 'link', reviewing.id, '--task', v.task], { success: 'Alerte liée' })) setReviewing(null); }} />
          <div className="row"><a className="btn small" href={`#/quetes?nouvelle=1`}><Icon name="plus" size={12} /> Ouvrir une quête de correctif</a>
            {reviewing.status === 'confirmed' && !reviewing.accepted && <Button size="small" onClick={() => showTerminal({ title: 'Accepter le risque : à faire dans votre terminal', why: 'Accepter une alerte confirmée demande une personne devant un terminal.', command: terminalCommand(['alerts', 'accept', reviewing.id, '--by', by || 'Votre nom', '--reason', 'Motif']) })}>Accepter le risque…</Button>}</div>
        </>}
      </Dialog>
    </div>
  );
}

function AllBlockers() {
  const tasks = useTasks();
  const reviewed = (tasks.data ?? []).filter((t) => t.status === 'reviewed').map((t) => t.id);
  const key = `blockers:${reviewed.join(',')}`;
  const all = useQuery<{ task: string; items: BlockerItem[] }[]>(tasks.data ? key : null, useCallback(async () => {
    const results = await batchJson<BlockerItem[]>(Object.fromEntries(reviewed.map((id) => [id, ['task', 'blockers', id, '--json']])));
    return reviewed.map((id) => ({ task: id, items: results[id] ?? [] }));
  }, [key]));
  return (
    <Q q={all} label="Lecture des blocages">
      {(list) => {
        const items = list.flatMap((t) => t.items.map((b) => ({ ...b, task: t.task })));
        if (!items.length) return <p className="muted">Aucun blocage sur les quêtes en attente de décision.</p>;
        return <Panel title={`${items.filter((b) => !b.resolution).length} blocage(s) ouvert(s)`}>
          <table className="data compact"><thead><tr><th>Quête</th><th>Blocage</th><th>Responsable</th><th>État</th></tr></thead><tbody>
            {items.map((b) => <tr key={`${b.task}:${b.id}`}><td><a href={`#/conseil/${b.task}`}>{b.task}</a></td><td><span className="mono tiny">{b.id}</span><span className="small block">{b.finding}</span><span className="tiny muted block">Se lève quand : {b.clears_when}</span></td><td className="small">{b.owner}</td><td>{b.resolution ? <Badge tone="success" icon="check">{b.resolution.kind}</Badge> : <Badge tone="danger" icon="ban">ouvert</Badge>}</td></tr>)}
          </tbody></table>
        </Panel>;
      }}
    </Q>
  );
}

