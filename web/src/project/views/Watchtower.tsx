/** Tour de guet: instruction drift, host enforcement, guard coverage, the dependency alert register and open blockers. */
import { useCallback, useState } from 'react';
import { navigate } from '@/app/router';
import { Badge, Button, Panel, Tabs } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Icon } from '@/shared/pixel/icons';
import { batchJson, terminalCommand } from '../api';
import { onlyTasksFail, useAlerts, useCheck, useGuard, useHost, useTasks } from '../data';
import { showTerminal, useAction, useQuery } from '../query';
import { GUARD, SEVERITY, alertLabel, hostControl } from '../labels';
import { ActionForm, CheckNotice, ExternalLink, FilePick, Q, TableBox, TaskLink, useRemembered } from '../parts';
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
        { id: 'blocages', label: 'Points bloquants', icon: 'ban' },
      ]} />
      {tab === 'alertes' ? <Alerts /> : tab === 'blocages' ? <AllBlockers /> : <Controls />}
    </div>
  );
}

function Controls() {
  const check = useCheck();
  const tasks = useTasks();
  const host = useHost();
  const guard = useGuard();
  const { act, busy } = useAction();
  return (
    <div className="grid-2">
      <Panel title="Instructions du projet" actions={check.data && check.data.code !== 0 && onlyTasksFail(check.data) ? undefined : <Button size="small" busy={busy !== null} onClick={() => void act(['sync'], { success: 'Instructions synchronisées' })}>Synchroniser</Button>}>
        <Q q={check}>{(r) => <CheckNotice result={r} tasks={tasks.data ?? []} />}</Q>
        <p className="small muted"><code>openguildkit check</code> fait échouer la CI quand AGENTS.md, les réglages de l’hôte ou le verrou du catalogue s’écartent du profil.</p>
      </Panel>
      <Panel title="Ce que l’hôte applique" actions={<Button size="small" busy={busy !== null} onClick={() => void act(['host', 'apply'], { success: 'Réglages de l’hôte écrits' })}>Appliquer</Button>}>
        <Q q={host}>{(list) => <ul className="plain stack tight">{list.map((c) => { const l = hostControl(c.status); return <li key={c.id} className="card"><span className="row between"><strong lang="en">{c.title}</strong><Badge tone={l.tone} icon={l.icon}>{l.label}</Badge></span><span className="small muted" lang="en">{c.detail}</span></li>; })}</ul>}</Q>
      </Panel>
      <Panel title="Garde-fou des modifications">
        <Q q={guard}>{(g) => <>
          <p>Le garde-fou est <strong>{GUARD[g.mode] ?? g.mode}</strong>. Elle dit si une tâche approuvée couvre le travail en cours, pour les crochets de l’hôte et la CI.</p>
          <p className="small">Tâches qui couvrent le travail : {g.covered_by.length ? g.covered_by.map((id) => <TaskLink key={id} id={id} />) : 'aucune'}.</p>
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
        <p className="small muted">La CLI ne scanne pas : elle lit le rapport JSON d’un outil que le projet utilise déjà (<code>npm audit --json</code>, <code>pip-audit -f json</code>, <code>osv-scanner --format json</code>, alertes Dependabot) et garde une entrée par alerte. Un nouvel import conserve tes décisions.</p>
        <div className="grid-2">
          <FilePick label="Rapport JSON" onText={(text, name) => setReport({ text, name })} />
          <div className="field"><label htmlFor="alert-task">Lier à une tâche (facultatif)</label><select id="alert-task" className="input" value={task} onChange={(e) => setTask(e.target.value)}><option value="">Aucune</option>{(tasks.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}</select></div>
        </div>
        <Button variant="primary" disabled={!report} busy={busy !== null} onClick={() => { const name = /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(report!.name) ? report!.name : 'report.json'; void act(['alerts', 'import', `@upload:${name}`, ...(task ? ['--task', task] : [])], { uploads: { [name]: report!.text }, success: 'Rapport importé' }).then((r) => r && setReport(null)); }}>Importer</Button>
      </Panel>
      <Q q={alerts}>{(reg) => <Panel title={`Registre : ${reg.summary.total} alerte(s)`} actions={<select className="input" aria-label="Filtrer par statut" value={filter} onChange={(e) => setFilter(e.target.value)}><option value="">Tous les statuts</option>{Object.keys(reg.summary.by_status).map((s) => <option key={s} value={s}>{alertLabel(s).label} ({reg.summary.by_status[s]})</option>)}</select>}>
        {reg.summary.imports.length > 0 && <p className="tiny muted">Imports : {reg.summary.imports.map((i) => `${i.tool} (${i.file}, sha256 ${i.sha256.slice(0, 12)})`).join(' · ')}</p>}
        {shown.length === 0 ? <p className="muted">Aucune alerte.</p> : <TableBox label="Registre des alertes"><table className="data compact"><thead><tr><th>Paquet</th><th>Gravité</th><th>Avis</th><th>Statut</th><th>Tâches</th><th><span className="sr-only">Revue</span></th></tr></thead><tbody>
          {shown.map((a) => { const l = alertLabel(a.status); return <tr key={a.id}>
            <td><strong>{a.package}</strong> <span className="mono tiny">{a.version}</span><span className="tiny muted block">{a.ecosystem} · {a.scanners.join(', ')}</span></td>
            <td><Badge tone={SEVERITY[a.severity] ?? 'neutral'}>{a.severity}</Badge></td>
            <td className="small">{a.url ? <ExternalLink href={a.url}>{a.advisory}</ExternalLink> : a.advisory}<span className="block" lang="en">{a.summary}</span>{a.fix && <span className="tiny muted block">Correctif : <span lang="en">{a.fix}</span></span>}</td>
            <td><Badge tone={l.tone} icon={l.icon}>{l.label}</Badge>{a.by && <span className="tiny muted block" data-own>{a.by}{a.reason ? ` : ${a.reason}` : ''}</span>}{a.accepted && <span className="block"><Badge tone="info" icon="lock">risque accepté par {a.accepted.by}</Badge></span>}</td>
            <td className="small">{a.tasks.map((t) => <TaskLink key={t} id={t} />)}</td>
            <td><Button size="small" onClick={() => setReviewing(a)}>Revoir</Button></td>
          </tr>; })}
        </tbody></table></TableBox>}
      </Panel>}</Q>
      <Dialog open={!!reviewing} onClose={() => setReviewing(null)} title={`Revoir ${reviewing?.package ?? ''}`}>
        {reviewing && <>
          <p className="small" lang="en">{reviewing.summary}</p>
          <ActionForm busy={busy !== null} submit="Enregistrer" initial={{ by, status: reviewing.status === 'open' ? 'confirmed' : reviewing.status }} fields={[
            { name: 'status', label: 'Statut', required: true, options: [{ value: 'open', label: 'À vérifier' }, { value: 'confirmed', label: 'Confirmée' }, { value: 'dismissed', label: 'Écartée (motif obligatoire)' }] },
            { name: 'by', label: 'Tes initiales', required: true },
            { name: 'reason', label: 'Motif', hint: 'Obligatoire pour écarter une alerte.' },
          ]} onSubmit={async (v) => { setBy(v.by); if (await act(['alerts', 'set', reviewing.id, '--status', v.status, '--by', v.by, ...(v.reason ? ['--reason', v.reason] : [])], { success: 'Alerte revue' })) setReviewing(null); }} />
          <hr />
          <ActionForm busy={busy !== null} submit="Lier à la tâche" fields={[{ name: 'task', label: 'Tâche qui traite l’alerte', required: true, options: (tasks.data ?? []).map((t) => ({ value: t.id, label: t.id })) }]} onSubmit={async (v) => { if (await act(['alerts', 'link', reviewing.id, '--task', v.task], { success: 'Alerte liée' })) setReviewing(null); }} />
          <div className="row"><a className="btn small" href={`#/quetes?nouvelle=1`}><Icon name="plus" size={12} /> Ouvrir une tâche de correctif</a>
            {reviewing.severity === 'unknown' && <Button size="small" onClick={() => showTerminal({ title: 'Fixer la sévérité : à faire dans ton terminal', why: 'Le scanner n’a pas donné de sévérité (pip-audit par exemple). Une personne la fixe d’après l’avis, dans son terminal, avec ses initiales et la raison.', command: terminalCommand(['alerts', 'severity', reviewing.id, '--level', 'high', '--by', by || 'TES_INITIALES', '--reason', 'Score CVSS de l’avis']) })}>Fixer la sévérité…</Button>}
            {reviewing.status === 'confirmed' && !reviewing.accepted && <Button size="small" onClick={() => showTerminal({ title: 'Accepter le risque : à faire dans ton terminal', why: 'Accepter une alerte confirmée demande une personne devant un terminal.', command: terminalCommand(['alerts', 'accept', reviewing.id, '--by', by || 'TES_INITIALES', '--reason', 'Motif']) })}>Accepter le risque…</Button>}</div>
        </>}
      </Dialog>
    </div>
  );
}

function AllBlockers() {
  const tasks = useTasks();
  // Before the decision, and after it for the conditions of the approval (blockers of phase verification).
  const reviewed = (tasks.data ?? []).filter((t) => t.status === 'reviewed' || t.status === 'approved').map((t) => t.id);
  const key = `blockers:${reviewed.join(',')}`;
  const all = useQuery<{ task: string; items: BlockerItem[] }[]>(tasks.data ? key : null, useCallback(async () => {
    const results = await batchJson<BlockerItem[]>(Object.fromEntries(reviewed.map((id) => [id, ['task', 'blockers', id, '--json']])));
    return reviewed.map((id) => ({ task: id, items: results[id] ?? [] }));
  }, [key]));
  return (
    <Q q={all} label="Lecture des points bloquants">
      {(list) => {
        const items = list.flatMap((t) => t.items.map((b) => ({ ...b, task: t.task })));
        if (!items.length) return <p className="muted">Aucun point bloquant sur les tâches en attente de décision ou à réaliser.</p>;
        return <Panel title={`${items.filter((b) => !b.resolution).length} point(s) bloquant(s) ouvert(s)`}>
          <TableBox label="Points bloquants des tâches"><table className="data compact"><thead><tr><th>Tâche</th><th>Point bloquant</th><th>Responsable</th><th>État</th></tr></thead><tbody>
            {items.map((b) => <tr key={`${b.task}:${b.id}`}><td><a href={`#/conseil/${b.task}`}>{b.task}</a></td><td><span className="mono tiny">{b.id}</span><span className="small block" data-own>{b.finding}</span><span className="tiny muted block">Se lève quand : <span data-own>{b.clears_when}</span></span></td><td className="small">{b.owner}</td><td>{b.resolution ? <Badge tone="success" icon="check">{b.resolution.kind}</Badge> : b.phase === 'verification' ? <Badge tone="warning" icon="clock">condition</Badge> : <Badge tone="danger" icon="ban">ouvert</Badge>}</td></tr>)}
          </tbody></table></TableBox>
        </Panel>;
      }}
    </Q>
  );
}

