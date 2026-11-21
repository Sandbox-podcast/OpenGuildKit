/**
 * Forge: implement approved tasks (handoff, checks, verification, results, completion), start business
 * deliverables, connect the tools of the stack with their MCP servers or mocks, and extract a design system.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { setQuery, useRoute } from '@/app/router';
import { Badge, Button, Empty, Notice, Panel, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Markdown } from '@/shared/ui/markdown';
import { norm } from '@/shared/text';
import { toast } from '@/shared/ui/toast';
import { batchJson, currentSession, readJson, readText, run, terminalCommand, writeFile } from '../api';
import { useProfile, useTasks } from '../data';
import { invalidate, showTerminal, useAction, useCli, useCliResult, useCliText, useQuery } from '../query';
import { checkLabel, fmtWhen, nextLabel, parseTemplates } from '../labels';
import { ActionForm, CommandLine, ExternalLink, FilePick, JsonDetails, Pre, Q, Section, StepRail, TaskStatusBadge, copyText, useRemembered } from '../parts';
import type { ExpectedCheck, TaskRecord, Tool } from '../types';

export function Forge({ tab = 'quetes' }: { tab?: string }) {
  return (
    <div className="page-grid">
      <Tabs label="Forge" value={tab} onChange={(t) => { window.location.hash = t === 'quetes' ? '#/forge' : `#/forge/${t}`; }} tabs={[
        { id: 'quetes', label: 'À réaliser', icon: 'anvil' },
        { id: 'livrables', label: 'Livrables', icon: 'scroll' },
        { id: 'outils', label: 'Outils et MCP', icon: 'key' },
        { id: 'storybook', label: 'Storybook', icon: 'grid' },
      ]} />
      {tab === 'livrables' ? <Deliverables /> : tab === 'outils' ? <Tools /> : tab === 'storybook' ? <Storybook /> : <ToBuild />}
    </div>
  );
}

function ToBuild() {
  const tasks = useTasks();
  return (
    <Q q={tasks}>
      {(list) => {
        const approved = list.filter((t) => t.status === 'approved');
        const done = list.filter((t) => t.status === 'done');
        return <div className="grid-2">
          <Panel title={<>Validées, à réaliser <span className="badge count">{approved.length}</span></>}>
            {approved.length === 0 ? <Empty title="Rien à forger">Une quête arrive ici quand une personne l’a validée dans son terminal.</Empty>
              : <ul className="plain stack tight">{approved.map((t) => <li key={t.id}><a className="card" href={`#/forge/${t.id}`}><span className="mono small">{t.id}</span><strong>{t.brief}</strong><span className="small muted">{nextLabel(t.next)}</span></a></li>)}</ul>}
          </Panel>
          <Panel title={<>Terminées <span className="badge count">{done.length}</span></>}>
            {done.length === 0 ? <p className="muted">Aucune quête terminée.</p> : <ul className="plain stack tight">{done.map((t) => <li key={t.id}><a className="card" href={`#/forge/${t.id}`}><span className="mono small">{t.id}</span><strong>{t.brief}</strong></a></li>)}</ul>}
          </Panel>
        </div>;
      }}
    </Q>
  );
}

/* ------------------------------------------------------------------ one task */

export function ForgeTask({ id }: { id: string }) {
  const record = useCli<TaskRecord>(['task', 'show', id], { omit: ['markdown', 'review_template', 'scope', 'review'] });
  const [handoff, setHandoff] = useState(false);
  return (
    <Q q={record}>
      {(t) => (
        <div className="page-grid">
          <div className="quest-head"><div className="grow"><p className="mono small muted"><a href={`#/quetes/${t.id}`}>{t.id}</a></p><h2 className="h-title clamp-2">{t.brief.split('\n')[0]}</h2><TaskStatusBadge status={t.status} /></div>
            <div className="row"><Button icon="scroll" variant="primary" onClick={() => setHandoff(true)}>{t.answers?.kind === 'decision' ? 'Relevé de décision' : 'Passation (handoff)'}</Button></div></div>
          <StepRail status={t.status} hasResult={!!t.result} />
          {t.status !== 'approved' && t.status !== 'done' ? <Notice tone="warn">Cette quête n’est pas validée : la Forge n’a pas de passation. <a href={`#/conseil/${t.id}`}>Ouvrir le Conseil</a></Notice> : <>
            {t.answers?.kind === 'decision' && <Notice tone="info" title="Quête de décision :">la passation est un relevé de décision. Rapportez la décision sans modifier le projet ; ouvrez une nouvelle quête pour la mettre en œuvre.</Notice>}
            <Checks task={t} />
            {t.status === 'approved' && <Results task={t} />}
            <Authorizations task={t} />
            <Runs id={t.id} />
          </>}
          <HandoffDialog id={t.id} open={handoff} onClose={() => setHandoff(false)} />
        </div>
      )}
    </Q>
  );
}

function HandoffDialog({ id, open, onClose }: { id: string; open: boolean; onClose: () => void }) {
  const text = useCliText(open ? ['task', 'handoff', id] : null);
  return (
    <Dialog open={open} onClose={onClose} wide title="Passation validée" footer={<><Button onClick={onClose}>Fermer</Button>{text.data && <Button variant="primary" icon="copy" onClick={() => void copyText(text.data!)}>Copier pour l’agent</Button>}</>}>
      <p className="small muted">La décision (qui et pourquoi), le périmètre validé avec les règles en vigueur et la revue. Elle échoue si le profil ou le catalogue ont changé depuis la validation.</p>
      <Q q={text}>{(t) => <div className="scroll-box"><Markdown text={t} /></div>}</Q>
    </Dialog>
  );
}

function Checks({ task }: { task: TaskRecord }) {
  const checks = useCli<ExpectedCheck[]>(['task', 'checks', task.id, '--json']);
  const { act, busy } = useAction();
  const [chaos, setChaos] = useState<string | null>(null);
  const [toolVersion, setToolVersion] = useState('');
  return (
    <Section title="Vérifications attendues" icon="shield" actions={task.status === 'approved' ? <Button size="small" variant="primary" icon="play" busy={busy !== null} onClick={() => void act(['task', 'verify', task.id], { success: 'Vérifications lancées' })}>Lancer les commandes du projet</Button> : undefined}>
      <p className="small muted"><code>task verify</code> lance seulement les commandes du profil, à la racine du projet, et garde le journal de chacune comme preuve.</p>
      <Q q={checks}>
        {(list) => <table className="data compact"><thead><tr><th>Contrôle</th><th>Type</th><th>Obligatoire</th><th>Résultat</th></tr></thead>
          <tbody>{list.map((c) => { const l = checkLabel(c.result?.status); return (
            <tr key={c.id}><td><span className="mono small">{c.id}</span><span className="small block">{c.command ?? c.instruction ?? c.rule}</span>{c.verification && <span className="tiny muted block">{c.verification}</span>}</td>
              <td className="small">{c.kind === 'command' ? 'commande' : c.kind === 'rule' ? 'règle' : 'scénario'}</td>
              <td>{c.mandatory ? <Badge tone="warning" icon="lock">oui</Badge> : <span className="tiny muted">non</span>}</td>
              <td><Badge tone={l.tone} icon={l.icon}>{l.label}</Badge>{c.result?.evidence && <span className="tiny muted block mono">{c.result.evidence}</span>}{c.result?.reason && <span className="tiny muted block">{c.result.reason}</span>}</td></tr>); })}</tbody></table>}
      </Q>
      {task.status === 'approved' && <details className="small"><summary>Enregistrer un rejeu ChaosFolk</summary>
        <FilePick label="summary.json du rejeu" onText={(t) => setChaos(t)} />
        <TextField label="Version ou commit de ChaosFolk" value={toolVersion} onChange={(e) => setToolVersion(e.target.value)} />
        <Button disabled={!chaos} busy={busy !== null} onClick={() => void act(['task', 'verify', task.id, '--chaosfolk', '@upload:summary.json', ...(toolVersion ? ['--tool-version', toolVersion] : [])], { uploads: { 'summary.json': chaos! }, success: 'Scénarios ChaosFolk enregistrés' })}>Enregistrer les scénarios</Button>
      </details>}
    </Section>
  );
}

type Outcome = { status: string; evidence: string; reason: string; owner: string };

function Results({ task }: { task: TaskRecord }) {
  const checks = useCli<ExpectedCheck[]>(['task', 'checks', task.id, '--json']);
  const [owner, setOwner] = useRemembered('decider');
  const [delivery, setDelivery] = useState<'pull_request' | 'revision'>(task.result?.pull_request ? 'pull_request' : 'pull_request');
  const [ref, setRef] = useState(task.result?.pull_request ?? task.result?.revision ?? '');
  const [criteria, setCriteria] = useState(task.result?.criteria ?? []);
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const { act, busy, error } = useAction();
  const rules = (checks.data ?? []).filter((c) => c.kind !== 'command');
  const outcome = (id: string): Outcome => outcomes[id] ?? { status: '', evidence: '', reason: '', owner };
  const setOutcome = (id: string, patch: Partial<Outcome>) => setOutcomes((o) => ({ ...o, [id]: { ...outcome(id), ...patch } }));
  const result = {
    ...(ref ? { [delivery]: ref.trim() } : {}),
    criteria: criteria.filter((c) => c.criterion.trim()),
    checks: Object.entries(outcomes).filter(([, o]) => o.status).map(([check, o]) => (o.status === 'passed' || o.status === 'failed' ? { check, status: o.status, evidence: o.evidence } : { check, status: o.status, reason: o.reason, owner: o.owner || owner })),
  };
  const incomplete = result.checks.filter((c) => ('reason' in c && (!c.reason?.trim() || !c.owner?.trim())) || ('evidence' in c && !c.evidence?.trim())).map((c) => c.check);
  const save = () => act(['task', 'result', task.id, '--file', '@upload:result.json'], { uploads: { 'result.json': JSON.stringify(result, null, 2) }, success: 'Résultats enregistrés' });
  return (
    <Section title="Rapporter les résultats" icon="flag">
      <p className="small muted">Les rapports suivants mettent à jour les précédents, contrôle par contrôle. <code>task complete</code> passe la quête à « terminée » seulement quand chaque contrôle obligatoire a réussi avec sa preuve et que chaque critère est atteint.</p>
      <TextField label="Votre nom" hint="Responsable des règles ignorées ou non applicables que vous rapportez." value={owner} onChange={(e) => setOwner(e.target.value)} />
      <div className="grid-2">
        <div className="field"><label htmlFor="delivery">Livraison</label><select id="delivery" className="input" value={delivery} onChange={(e) => setDelivery(e.target.value as typeof delivery)}><option value="pull_request">Pull request</option><option value="revision">Révision Git</option></select></div>
        <TextField label={delivery === 'pull_request' ? 'Adresse de la pull request' : 'Révision'} value={ref} onChange={(e) => setRef(e.target.value)} placeholder={delivery === 'pull_request' ? 'https://github.com/…/pull/7' : 'abc1234'} />
      </div>
      <fieldset className="list-editor"><legend>Critères d’acceptation</legend>
        {criteria.map((c, i) => <div className="row criteria-row" key={i}>
          <input className="input grow" aria-label="Critère" value={c.criterion} onChange={(e) => setCriteria((x) => x.map((y, j) => (j === i ? { ...y, criterion: e.target.value } : y)))} />
          <select className="input" aria-label="Statut" value={c.status} onChange={(e) => setCriteria((x) => x.map((y, j) => (j === i ? { ...y, status: e.target.value as 'met' } : y)))}><option value="met">atteint</option><option value="not-met">non atteint</option></select>
          <input className="input" aria-label="Preuve" placeholder="Preuve" value={c.evidence} onChange={(e) => setCriteria((x) => x.map((y, j) => (j === i ? { ...y, evidence: e.target.value } : y)))} />
          <Button size="small" variant="ghost" icon="trash" aria-label="Retirer le critère" onClick={() => setCriteria((x) => x.filter((_, j) => j !== i))} />
        </div>)}
        <Button size="small" icon="plus" onClick={() => setCriteria((x) => [...x, { criterion: '', status: 'met', evidence: '' }])}>Ajouter un critère</Button>
      </fieldset>
      {rules.length > 0 && <div className="table-wrap"><table className="data compact"><thead><tr><th>Règle</th><th>Issue</th><th>Preuve, ou motif et responsable</th></tr></thead><tbody>
        {rules.map((c) => { const o = outcome(c.id); return <tr key={c.id}>
          <td><span className="mono small">{c.id}</span><span className="tiny muted block">{c.instruction}</span></td>
          <td><select className="input" aria-label={`Issue de ${c.id}`} value={o.status || (c.result?.status ?? '')} onChange={(e) => setOutcome(c.id, { status: e.target.value })}><option value="">{c.result ? checkLabel(c.result.status).label : 'À rapporter'}</option><option value="passed">réussie</option><option value="failed">en échec</option><option value="skipped">ignorée</option><option value="not-applicable">non applicable</option></select></td>
          <td>{o.status === 'passed' || o.status === 'failed' ? <input className="input" aria-label="Preuve" value={o.evidence} onChange={(e) => setOutcome(c.id, { evidence: e.target.value })} /> : o.status ? <span className="row"><input className="input" aria-label="Motif" placeholder="Motif" value={o.reason} onChange={(e) => setOutcome(c.id, { reason: e.target.value })} /><input className="input" aria-label="Responsable" placeholder="Responsable" value={o.owner} onChange={(e) => { setOwner(e.target.value); setOutcome(c.id, { owner: e.target.value }); }} /></span> : <span className="tiny muted">—</span>}</td>
        </tr>; })}
      </tbody></table>
      <Button size="small" variant="ghost" disabled={!owner.trim()} title={owner.trim() ? undefined : 'Indiquez d’abord votre nom'} onClick={() => rules.forEach((c) => !c.result && setOutcome(c.id, { status: 'not-applicable', reason: 'Aucun changement dans ce domaine.', owner }))}>Marquer les règles non rapportées « non applicables »</Button></div>}
      {incomplete.length > 0 && <Notice tone="warn">Il manque une preuve, ou un motif et un responsable, pour : {incomplete.join(', ')}.</Notice>}
      {error && <Notice tone="danger" title="La CLI a refusé :"><span className="pre-line">{error.message}</span></Notice>}
      <div className="row">
        <Button variant="primary" busy={busy !== null} disabled={(!result.criteria.length && !result.checks.length && !ref) || incomplete.length > 0} onClick={() => void save()}>Enregistrer les résultats</Button>
        <Button icon="star" busy={busy !== null} onClick={() => void act(['task', 'complete', task.id], { success: 'Quête terminée' })}>Terminer la quête</Button>
      </div>
      <JsonDetails data={result} label="Aperçu du fichier de résultats" />
    </Section>
  );
}

/** The actions of task authorize --action (tasks.ACTIONS). */
const ACTIONS: [string, string][] = [['public-research', 'Recherche publique'], ['external-api', 'Appel d’une API externe'], ['send-message', 'Envoi de messages'], ['publish', 'Publication'], ['install-dependency', 'Installation d’une dépendance'], ['other', 'Autre']];

function Authorizations({ task }: { task: TaskRecord }) {
  const [by] = useRemembered('decider');
  const { act, busy } = useAction();
  return (
    <Section title="Actions externes hors périmètre" icon="external">
      <p className="small muted">Envoyer un message, publier, acheter… hors du périmètre validé demande la décision d’une personne. Refuser se fait ici ; autoriser se fait au terminal.</p>
      {task.authorizations?.length ? <ul className="small">{task.authorizations.map((a, i) => <li key={i}><strong>{ACTIONS.find(([id]) => id === a.action)?.[1] ?? a.action}</strong> sur {a.target} : {a.decision === 'allow' ? 'autorisée' : 'refusée'} par {a.by} ({a.reason}), {fmtWhen(a.at)}</li>)}</ul> : <p className="tiny muted">Aucune décision enregistrée.</p>}
      <ActionForm busy={busy !== null} submit="Préparer" initial={{ by, decision: 'deny' }} fields={[
        { name: 'action', label: 'Action', required: true, options: ACTIONS.map(([value, label]) => ({ value, label })) },
        { name: 'target', label: 'Hôte ou outil', required: true, placeholder: 'Brevo, api.example.org', hint: 'Un nom d’hôte ou d’outil, sans requête, adresse ni détail privé.' },
        { name: 'decision', label: 'Décision', required: true, options: [{ value: 'deny', label: 'Refuser (enregistré ici)' }, { value: 'allow', label: 'Autoriser (commande au terminal)' }] },
        { name: 'by', label: 'Personne qui décide', required: true },
        { name: 'reason', label: 'Motif', required: true },
      ]} onSubmit={(v) => {
        const argv = ['task', 'authorize', task.id, '--action', v.action, '--target', v.target, v.decision === 'allow' ? '--allow' : '--deny', '--by', v.by, '--reason', v.reason];
        if (v.decision === 'allow') showTerminal({ title: 'Autorisation : à faire dans votre terminal', why: 'Autoriser une action externe demande une personne devant un terminal.', command: terminalCommand(argv) });
        else void act(argv, { success: 'Refus enregistré' });
      }} />
    </Section>
  );
}

function Runs({ id }: { id: string }) {
  const runs = useCliResult(['task', 'runs', id, '--json']);
  if (!runs.data || runs.data.code !== 0) return null;
  return <Section title="Rejeux ChaosFolk" icon="history"><JsonDetails data={runs.data.json} label="Comparaison des deux derniers rejeux" /></Section>;
}

/* ------------------------------------------------------------------ deliverables */

function Deliverables() {
  const list = useCliText(['deliverable', 'list']);
  const tasks = useTasks();
  const profile = useProfile();
  const route = useRoute();
  const [show, setShow] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(route.query.get('brouillon'));
  const { act, busy } = useAction();
  const templates = useMemo(() => parseTemplates(list.data ?? ''), [list.data]);
  const records = useQuery<TaskRecord[]>(tasks.data ? `deliverable-records:${(tasks.data ?? []).map((t) => `${t.id}=${t.status}`).join(',')}` : null, useCallback(async () => {
    const ids = (tasks.data ?? []).filter((x) => x.status === 'approved' || x.status === 'done').map((x) => x.id);
    const records = await batchJson<TaskRecord>(Object.fromEntries(ids.map((id) => [id, ['task', 'show', id]])), { omit: ['consultation', 'review', 'rounds', 'answers'] });
    return ids.map((id) => records[id]).filter((r): r is TaskRecord => !!r);
  }, [tasks.data]));
  const drafts = (records.data ?? []).flatMap((t) => (t.deliverables ?? []).map((d) => ({ ...d, task: t.id })));
  const root = profileRootRelative;
  return (
    <div className="page-grid">
      <Panel title="Modèles de livrables">
        <p className="small muted">Un livrable métier (brief de campagne, annonce, article d’aide) part d’une quête validée. Le modèle liste les entrées, les données qu’elles touchent, les actions qui demandent votre accord et les contrôles du relecteur.</p>
        <Q q={list}>{() => <ul className="plain board-grid">{templates.map((t) => <li key={t.id} className="card"><strong>{t.title}</strong><span className="mono tiny">{t.id}</span>{t.method && <span className="tiny muted">méthode {t.method}</span>}<span className="row">{t.brains.map((b) => <Badge key={b}>{b}</Badge>)}</span><Button size="small" onClick={() => setShow(t.id)}>Voir le modèle</Button></li>)}</ul>}</Q>
      </Panel>
      <Panel title="Nouveau brouillon">
        {!profile.data?.tools?.length && <Notice tone="warn">Le profil ne liste aucun outil approuvé (<code>"tools"</code>). Ajoutez-les dans le Blueprint.</Notice>}
        <ActionForm busy={busy !== null} submit="Écrire le brouillon" fields={[
          { name: 'template', label: 'Modèle', required: true, options: templates.map((t) => ({ value: t.id, label: t.title })) },
          { name: 'task', label: 'Quête validée', required: true, options: (tasks.data ?? []).filter((t) => t.status === 'approved' || t.status === 'done').map((t) => ({ value: t.id, label: t.id })) },
          { name: 'tool', label: 'Outil de l’équipe', required: true, options: (profile.data?.tools ?? []).map((t) => ({ value: t, label: t })) },
          { name: 'output', label: 'Fichier Markdown à écrire', required: true, placeholder: 'marketing/brief-printemps.md', hint: 'Chemin relatif à la racine du projet.' },
        ]} onSubmit={(v) => act(['deliverable', 'new', v.template, '--task', v.task, '--tool', v.tool, '--output', v.output], { success: 'Brouillon écrit' })} />
      </Panel>
      <Panel title={<>Brouillons des quêtes <span className="badge count">{drafts.length}</span></>}>
        {drafts.length === 0 ? <p className="muted">Aucun brouillon.</p> : <table className="data compact"><thead><tr><th>Brouillon</th><th>Quête</th><th>Outil</th><th /></tr></thead>
          <tbody>{drafts.map((d) => <tr key={d.path}><td><span className="mono small">{root(d.path)}</span><span className="tiny muted block">{d.deliverable}</span></td><td><a href={`#/quetes/${d.task}`}>{d.task}</a></td><td>{d.tool}</td><td><Button size="small" onClick={() => setDraft(root(d.path))}>Ouvrir</Button></td></tr>)}</tbody></table>}
      </Panel>
      <TemplateDialog id={show} onClose={() => setShow(null)} />
      <DraftDialog path={draft} onClose={() => { setDraft(null); setQuery({ brouillon: null }); }} />
    </div>
  );
}

/** The CLI records absolute paths; the file API takes paths relative to the project. */
function profileRootRelative(path: string) {
  const normalized = path.replace(/\\/g, '/');
  const root = (currentSession()?.project.root ?? '').replace(/\\/g, '/').replace(/\/$/, '');
  return root && normalized.toLowerCase().startsWith(`${root.toLowerCase()}/`) ? normalized.slice(root.length + 1) : normalized;
}

function TemplateDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const text = useCliText(id ? ['deliverable', 'show', id] : null);
  return <Dialog open={!!id} onClose={onClose} wide title={`Modèle ${id ?? ''}`} footer={<Button onClick={onClose}>Fermer</Button>}><Q q={text}>{(t) => <Pre text={t} />}</Q></Dialog>;
}

function DraftDialog({ path, onClose }: { path: string | null; onClose: () => void }) {
  const text = useQuery<string>(path ? `file:${path}` : null, useCallback(() => readText(path!), [path]));
  const check = useCliResult(path ? ['deliverable', 'check', path] : null);
  return (
    <Dialog open={!!path} onClose={onClose} wide title={path ?? ''} footer={<Button onClick={onClose}>Fermer</Button>}>
      {check.data && (check.data.code === 0 ? <Notice tone="success">Prêt pour la relecture.</Notice> : <Notice tone="warn" title="Ce qui empêche la relecture :"><Pre text={check.data.stdout || check.data.stderr} /></Notice>)}
      <Q q={text}>{(t) => <div className="scroll-box"><Markdown text={t.replace(/^---[\s\S]*?---\n/, '')} /></div>}</Q>
      <p className="tiny muted">Modifiez le fichier dans votre éditeur ; rouvrez ce brouillon pour revoir les contrôles.</p>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ tools */

const HOSTS = ['claude-code', 'codex'];

function Tools() {
  const tools = useCli<Tool[]>(['tools', 'list', '--json']);
  const recommended = useCli<{ tools: { id: string; title: string; named: boolean; signals: string[]; servers: string[]; mock: boolean }[]; unknown: string[] }>(['tools', 'recommend', '--json']);
  const status = useCli<unknown[]>(['tools', 'status', '--json']);
  const profile = useProfile();
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [onlyMocks, setOnlyMocks] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [host, setHost] = useState(profile.data?.host ?? '');
  const [mock, setMock] = useState(true);
  const [plan, setPlan] = useState<string | null>(null);
  const [call, setCall] = useState<string | null>(null);
  const { act, busy } = useAction();
  const categories = [...new Set((tools.data ?? []).map((t) => t.category))].sort();
  const shown = (tools.data ?? []).filter((t) => (!category || t.category === category) && (!onlyMocks || t.mock) && (!q || norm(`${t.id} ${t.title} ${t.vendor} ${t.summary} ${t.brains.join(' ')}`).includes(norm(q))));
  const hostArgs = host ? ['--host', host] : [];
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const doPlan = async () => {
    try { setPlan((await run(['tools', 'plan', ...picked, ...hostArgs, ...(mock ? ['--mock'] : [])], undefined, { raw: true })).stdout); }
    catch (e) { setPlan(`Erreur : ${(e as Error).message}`); }
  };

  return (
    <div className="page-grid">
      <div className="grid-2">
        <Panel title="Recommandés pour ce projet">
          <Q q={recommended}>{(r) => r.tools.length === 0 ? <p className="muted">Aucun outil reconnu dans le profil ou le dépôt.</p> : <ul className="plain stack tight">{r.tools.map((t) => <li key={t.id} className="row between"><span><strong>{t.title}</strong> <span className="tiny muted">{t.named ? 'nommé dans le profil' : t.signals.join(', ')}</span></span><span className="row">{t.mock && <Badge tone="ai">simulable</Badge>}<Button size="small" onClick={() => toggle(t.id)}>{picked.includes(t.id) ? 'Retirer' : 'Choisir'}</Button></span></li>)}</ul>}</Q>
          {recommended.data?.unknown.length ? <p className="tiny muted">Inconnus du registre : {recommended.data.unknown.join(', ')}</p> : null}
        </Panel>
        <Panel title="Connexions enregistrées">
          <Q q={status}>{(s) => s.length === 0 ? <p className="muted">Aucune connexion. Choisissez des outils, vérifiez le plan, puis écrivez la configuration de l’hôte.</p> : <JsonDetails data={s} label={`${s.length} connexion(s)`} />}</Q>
        </Panel>
      </div>
      <Panel title={`Registre : ${tools.data?.length ?? '…'} outils`}>
        <div className="toolbar">
          <input className="input" type="search" placeholder="Outil, éditeur, cerveau…" aria-label="Rechercher un outil" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input" aria-label="Catégorie" value={category} onChange={(e) => setCategory(e.target.value)}><option value="">Toutes les catégories</option>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select>
          <label className="row small"><input type="checkbox" checked={onlyMocks} onChange={(e) => setOnlyMocks(e.target.checked)} /> Avec une simulation</label>
        </div>
        <div className="table-wrap tall"><table className="data compact"><thead><tr><th /><th>Outil</th><th>Catégorie</th><th>Serveurs MCP</th><th>Cerveaux</th><th /></tr></thead><tbody>
          {shown.map((t) => <tr key={t.id}>
            <td><input type="checkbox" aria-label={`Choisir ${t.title}`} checked={picked.includes(t.id)} onChange={() => toggle(t.id)} /></td>
            <td><strong>{t.title}</strong> <span className="tiny muted">{t.vendor}</span><span className="tiny muted block clamp-1">{t.summary}</span></td>
            <td className="small">{t.category}</td>
            <td className="small">{t.servers.length || '—'}{t.mock && <> · <Badge tone="ai">simulation</Badge></>}</td>
            <td className="tiny">{t.brains.join(', ')}</td>
            <td>{t.mock && <Button size="small" variant="ghost" onClick={() => setCall(t.id)}>Essayer</Button>}{t.homepage && <ExternalLink href={t.homepage}>site</ExternalLink>}</td>
          </tr>)}
        </tbody></table></div>
      </Panel>
      <Panel title={`Connecter ${picked.length} outil(s)`} tone={picked.length ? 'ai' : undefined}>
        <p className="small">{picked.join(', ') || 'Cochez des outils dans le registre.'}</p>
        <div className="grid-2">
          <div className="field"><label htmlFor="host">Hôte de l’agent</label><select id="host" className="input" value={host} onChange={(e) => setHost(e.target.value)}><option value="">Celui du profil</option>{HOSTS.map((h) => <option key={h} value={h}>{h}</option>)}</select></div>
          <label className="row small"><input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} /> Simulations locales (données synthétiques, sans réseau ni compte)</label>
        </div>
        <div className="row">
          <Button disabled={!picked.length} onClick={() => void doPlan()}>Voir le plan</Button>
          <Button variant="primary" disabled={!picked.length} busy={busy !== null} onClick={() => void act(['tools', 'apply', ...picked, ...hostArgs, ...(mock ? ['--mock'] : [])], { success: 'Configuration de l’hôte écrite' })}>Écrire la configuration</Button>
          <Button variant="danger" disabled={!picked.length} busy={busy !== null} onClick={() => void act(['tools', 'remove', ...picked, ...hostArgs], { success: 'Connexions retirées' })}>Retirer</Button>
        </div>
        {plan && <Pre text={plan} />}
      </Panel>
      <MockConsole id={call} onClose={() => setCall(null)} />
    </div>
  );
}

function MockConsole({ id, onClose }: { id: string | null; onClose: () => void }) {
  const list = useCliText(id ? ['tools', 'call', id] : null);
  const [name, setName] = useState('');
  const [args, setArgs] = useState('{}');
  const [answer, setAnswer] = useState('');
  const names = (list.data ?? '').split('\n').map((l) => l.split(/\s+/)[0]).filter(Boolean);
  return (
    <Dialog open={!!id} onClose={onClose} wide title={`Simulation ${id ?? ''}`} footer={<Button onClick={onClose}>Fermer</Button>}>
      <p className="small muted">La simulation répond avec des données synthétiques : un portail de support fictif, ses tickets, ses alertes. Aucun réseau, aucun compte.</p>
      <Q q={list}>{(t) => <Pre text={t} />}</Q>
      <div className="grid-2">
        <div className="field"><label htmlFor="mock-name">Outil de la simulation</label><select id="mock-name" className="input" value={name} onChange={(e) => setName(e.target.value)}><option value="">Choisir…</option>{names.map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
        <TextArea label="Arguments (JSON)" value={args} onChange={(e) => setArgs(e.target.value)} rows={2} />
      </div>
      <Button variant="primary" disabled={!name} onClick={() => void run(['tools', 'call', id!, name, '--args', args], undefined, { raw: true }).then((r) => setAnswer(r.stdout)).catch((e: Error) => setAnswer(e.message))}>Appeler</Button>
      {answer && <Pre text={answer} />}
    </Dialog>
  );
}

/* ------------------------------------------------------------------ storybook */

type Status = 'proposed' | 'validated' | 'rejected';
interface Item { key: string; name: string; status: Status; kind?: string; confidence?: string; basis?: string; observed?: boolean; file?: string; line?: number; component?: string; props?: Record<string, unknown>; value?: string; occurrences?: number; usages?: number; origins?: string[] }
interface Proposals { components: Item[]; variants: Item[]; tokens: Item[]; [key: string]: unknown }
const SECTIONS = [['components', 'Composants'], ['variants', 'Variantes'], ['tokens', 'Jetons']] as const;
type Section = (typeof SECTIONS)[number][0];
const STATUS_LABEL: Record<Status, string> = { proposed: 'à décider', validated: 'validé', rejected: 'rejeté' };

function itemOrigin(it: Item, section: Section, draft: Proposals) {
  if (section === 'variants') {
    const component = draft.components.find((c) => c.key === it.component)?.name ?? it.component;
    return `${component} · ${Object.entries(it.props ?? {}).map(([k, v]) => `${k}=${String(v)}`).join(', ')}`;
  }
  if (section === 'tokens') return `${it.kind} ${it.value}`;
  return `${it.file}:${it.line}`;
}

function Storybook() {
  const proposals = useQuery<Proposals | null>('file:proposals', useCallback(async () => {
    try { return await readJson<Proposals>('.openguildkit/storybook/proposals.json'); } catch { return null; }
  }, []));
  const inventory = useQuery<{ scanned?: { components: number; styles: number }; notes?: string[]; sources?: string[] } | null>('file:inventory', useCallback(async () => {
    try { return await readJson('.openguildkit/storybook/inventory.json'); } catch { return null; }
  }, []));
  const [draft, setDraft] = useState<Proposals | null>(null);
  const [src, setSrc] = useState('src');
  const [section, setSection] = useState<Section>('components');
  const [saving, setSaving] = useState(false);
  const { act, busy } = useAction();
  useEffect(() => { setDraft(proposals.data ?? null); }, [proposals.data]);
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(proposals.data);
  const update = (key: string, patch: Partial<Item>) => setDraft((d) => d && ({ ...d, [section]: d[section].map((it) => (it.key === key ? { ...it, ...patch } : it)) }));
  const bulk = (status: Status, only: (it: Item) => boolean) => setDraft((d) => d && ({ ...d, [section]: d[section].map((it) => (only(it) ? { ...it, status } : it)) }));
  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try { await writeFile('.openguildkit/storybook/proposals.json', JSON.stringify(draft, null, 2)); toast({ tone: 'success', title: 'Décisions enregistrées' }); invalidate(); }
    catch (e) { toast({ tone: 'danger', title: 'Enregistrement impossible', text: (e as Error).message }); }
    finally { setSaving(false); }
  };
  const items = draft?.[section] ?? [];
  const validated = draft ? SECTIONS.reduce((n, [k]) => n + draft[k].filter((it) => it.status === 'validated').length, 0) : 0;

  return (
    <div className="page-grid">
      <Panel title="Extraire le design system d’une application React">
        <p className="small muted">La CLI inventorie les composants fonctionnels, leurs props et variantes, et les jetons CSS, sans réseau. Elle lit le code par motifs, pas avec un analyseur complet : vérifiez l’inventaire avant de valider.</p>
        <div className="row">
          <TextField label="Dossiers ou fichiers à lire, relatifs au projet (séparés par des virgules)" value={src} onChange={(e) => setSrc(e.target.value)} />
          <Button variant="primary" busy={busy !== null} disabled={!src.trim()} onClick={() => void act(['storybook', 'extract', ...src.split(',').map((s) => s.trim()).filter(Boolean).flatMap((s) => ['--src', s])], { success: 'Inventaire écrit' })}>Inventorier</Button>
          <Button busy={busy !== null} disabled={!inventory.data} onClick={() => void act(['storybook', 'propose'], { success: 'Propositions mises à jour' })}>Proposer</Button>
          <Button busy={busy !== null} disabled={!validated || dirty} title={dirty ? 'Enregistrez d’abord vos décisions' : undefined} onClick={() => void act(['storybook', 'generate'], { success: 'Jetons, stories et index générés' })}>Générer ({validated} validé(s))</Button>
        </div>
        {inventory.data?.scanned && <p className="small">Inventaire de {inventory.data.sources?.join(', ')} : {inventory.data.scanned.components} composant(s) et {inventory.data.scanned.styles} feuille(s) de style lus.</p>}
        {inventory.data?.notes?.map((n) => <Notice key={n} tone="warn">{n}</Notice>)}
      </Panel>
      <Panel title="Propositions" actions={draft ? <>
        <Button size="small" onClick={() => bulk('validated', (it) => it.confidence === 'observed' && it.status === 'proposed')}>Valider ce qui est observé</Button>
        <Button size="small" variant="ghost" onClick={() => bulk('rejected', (it) => it.status === 'proposed')}>Rejeter le reste</Button>
      </> : undefined}>
        {!draft ? <p className="muted">Aucune proposition. Inventoriez puis proposez.</p> : <>
          <Tabs label="Type de proposition" value={section} onChange={(s) => setSection(s as Section)} tabs={SECTIONS.map(([id, title]) => ({ id, label: title, count: draft[id].length }))} />
          <div className="table-wrap tall"><table className="data compact"><thead><tr><th>Nom</th><th>Origine</th><th>Confiance</th><th>Décision</th></tr></thead><tbody>
            {items.map((it) => (
              <tr key={it.key} className={it.observed === false ? 'muted' : undefined}>
                <td><input className="input" aria-label={`Nom de ${it.key}`} value={it.name} onChange={(e) => update(it.key, { name: e.target.value })} />
                  <span className="mono tiny block">{it.key}</span></td>
                <td className="small">{section === 'tokens' && it.kind === 'color' && <span className="swatch" style={{ background: it.value }} aria-hidden="true" />}{itemOrigin(it, section, draft)}
                  {it.kind === 'screen' && <> <Badge tone="muted">écran</Badge></>}{it.observed === false && <> <Badge tone="warning">plus observé</Badge></>}
                  {it.origins?.length ? <span className="tiny muted block">{it.origins.slice(0, 3).join(' · ')}{it.origins.length > 3 ? ` · +${it.origins.length - 3}` : ''}</span> : null}</td>
                <td><Badge tone={it.confidence === 'observed' ? 'success' : 'warning'}>{it.confidence === 'observed' ? 'observé' : 'hypothèse'}</Badge>{it.basis && <span className="tiny muted block">{it.basis}</span>}</td>
                <td><select className="input" aria-label={`Décision pour ${it.key}`} value={it.status} onChange={(e) => update(it.key, { status: e.target.value as Status })}>{(Object.keys(STATUS_LABEL) as Status[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}</select></td>
              </tr>
            ))}
          </tbody></table></div>
          <div className="row">
            <Button variant="primary" busy={saving} disabled={!dirty} onClick={() => void save()}>Enregistrer les décisions</Button>
            <Button disabled={!dirty} onClick={() => setDraft(proposals.data ?? null)}>Annuler</Button>
            {dirty && <span className="small muted">Décisions non enregistrées</span>}
          </div>
          <p className="tiny muted">Les décisions sont écrites dans <code>.openguildkit/storybook/proposals.json</code> ; un nouveau <code>propose</code> les garde. <code>generate</code> écrit dans <code>src/design-system/</code> et ne remplace jamais un fichier modifié à la main.</p>
        </>}
      </Panel>
      <Panel title="Design system de l’entreprise">
        <ActionForm busy={busy !== null} submit="Ajouter la référence" fields={[
          { name: 'ref', label: 'Identifiant de la référence', required: true, placeholder: 'company' },
          { name: 'url', label: 'Adresse du Storybook publié', required: true, placeholder: 'https://design.example.com' },
          { name: 'title', label: 'Titre dans la barre latérale', placeholder: 'Design system Acme' },
        ]} onSubmit={(v) => act(['storybook', 'compose', v.ref, '--url', v.url, ...(v.title ? ['--title', v.title] : [])], { success: 'Référence ajoutée' })} />
        <p className="tiny muted">Une story se cite ensuite comme <code>storybook:REF_STORY_ID</code> dans un avis du cerveau Design.</p>
        <Notice tone="info">Pour comparer les index Storybook du projet et de l’entreprise : <CommandLine command={terminalCommand(['storybook', 'import', '--company-index', 'company/index.json'])} /></Notice>
      </Panel>
    </div>
  );
}
