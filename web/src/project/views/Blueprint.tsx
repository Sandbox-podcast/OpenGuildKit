/**
 * Blueprint: set the project up (init), then read and edit its profile, the rule packs in force with their
 * origin, the components detected in the repository and the patterns recommended for the stack.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Brand } from '@/app/Brand';
import { Badge, Button, Checkbox, KV, Notice, Panel, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { Icon } from '@/shared/pixel/icons';
import { ApiError, cliMessage, currentSession, run, saveProfile } from '../api';
import { useBrains, useProfile } from '../data';
import { invalidate, showTerminal, useAction, useCli, useQuery } from '../query';
import { toast } from '@/shared/ui/toast';
import { RESEARCH } from '../labels';
import { ActionForm, ErrorNotice, JsonDetails, ListEditor, Q, useRemembered } from '../parts';
import type { Profile, Question, Recommendation, RulePlan } from '../types';

/* ------------------------------------------------------------------ setup */

type SetupAnswers = Record<string, unknown>;

export function Setup() {
  const session = currentSession();
  const questions = useCli<(Question & { type: string })[]>(['init', '--questions']);
  const [answers, setAnswers] = useState<SetupAnswers>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    if (!questions.data) return;
    const initial: SetupAnswers = {};
    for (const question of questions.data) {
      // Norm defaults apply to individual prompts. The CLI selects applicable norms when no overrides are sent.
      if (question.type !== 'norms' && question.default !== undefined && question.default !== null) {
        initial[question.id] = question.default;
      }
    }
    setAnswers((a) => ({ ...initial, ...a }));
  }, [questions.data]);
  const json = JSON.stringify(answers);
  const plan = useQuery<RulePlan | null>(answers.name ? `setup-plan:${json}` : null, useCallback(async () => (await run<RulePlan>(['preview', '--answers', '@upload:profile.json', '--json'], { 'profile.json': json })).json, [json]));
  const set = (id: string, value: unknown) => setAnswers((a) => { const next = { ...a }; if (value === undefined || (Array.isArray(value) && !value.length && id !== 'stack')) delete next[id]; else next[id] = value; return next; });

  const init = async () => {
    setBusy(true); setError(null);
    try {
      await run(['init', '--answers', '@upload:profile.json'], { 'profile.json': json });
      toast({ tone: 'success', title: 'Projet initialisé', text: 'AGENTS.md, CLAUDE.md et .openguildkit/ sont écrits.' });
      window.location.hash = '#/royaume';
      window.location.reload();
    } catch (e) { setError(e as ApiError); } finally { setBusy(false); }
  };

  return (
    <div className="setup-page">
      <div className="setup-hero"><Brand size="hero" /><h1>Installer la guilde dans {session?.project.name}</h1>
        <p>Le profil fixe la pile, les packs de règles, les cerveaux qui conseillent et la politique de recherche. Il est partagé par Git : chaque personne et chaque agent du projet suit les mêmes règles.</p>
        <p className="small muted mono">{session?.project.root}</p></div>
      <Q q={questions} label="Lecture du questionnaire d’installation">
        {(list) => <div className="grid-2 setup-grid">
          <Panel title="Le profil">
            <div className="stack">{list.map((q) => <SetupField key={q.id} q={q} value={answers[q.id]} onChange={(v) => set(q.id, v)} />)}</div>
          </Panel>
          <div className="stack">
            <Panel title="Règles qui s’appliqueront">
              {!answers.name ? <p className="muted">Donnez un nom au projet pour voir le plan.</p> : <Q q={plan} label="Calcul du plan">{(p) => p && <PlanView plan={p} />}</Q>}
              {plan.error && <ErrorNotice error={plan.error} title="Le profil n’est pas encore valide" />}
            </Panel>
            <Panel title="Écrire le profil">
              <p className="small">L’installation écrit <code>.openguildkit/project.json</code>, le verrou du catalogue, le bloc géré d’<code>AGENTS.md</code> et <code>CLAUDE.md</code>. Votre propre texte dans ces fichiers reste autour du bloc.</p>
              <ErrorNotice error={error} title="Installation refusée" />
              <Button variant="primary" icon="flag" busy={busy} disabled={!answers.name || !!plan.error} onClick={() => void init()}>Installer la guilde</Button>
            </Panel>
          </div>
        </div>}
      </Q>
    </div>
  );
}

/** A setup question, with its one-line help in plain words (the CLI's help and what an unsure answer means). */
function SetupField({ q, value, onChange }: { q: Question & { type: string; help?: string; unsure?: string }; value: unknown; onChange: (v: unknown) => void }) {
  const choices = q.choices ?? [];
  const hint = [q.help, q.unsure ? `Sans réponse : ${q.unsure}` : ''].filter(Boolean).join(' ') || undefined;
  if (q.type === 'text') return <TextField label={q.prompt} hint={hint} value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value)} />;
  if (q.type === 'select') return <div className="field"><label htmlFor={`setup-${q.id}`}>{q.prompt}</label><select id={`setup-${q.id}`} className="input" value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)}>{value === undefined || value === null ? <option value="">Choisir…</option> : null}{choices.map((c) => <option key={c.id} value={c.id}>{RESEARCH[c.id] ?? c.label}</option>)}</select>{hint && <p className="hint">{hint}</p>}</div>;
  if (q.type === 'list') return <ListEditor label={q.prompt} hint={hint} items={(value as string[]) ?? []} onChange={onChange} />;
  if (q.type === 'components') return <div className="field"><p className="label">{q.prompt}</p>{Array.isArray(q.default) && q.default.length ? <JsonDetails data={q.default} label={`${q.default.length} composant(s) détecté(s)`} /> : <p className="tiny muted">Aucun composant détecté : un seul composant à la racine.</p>}</div>;
  if (q.type === 'multi-select') {
    const selected = (value as string[]) ?? [];
    return <details className="field multi"><summary>{q.prompt} <span className="tiny muted">{selected.length ? `${selected.length} choisi(s)` : 'par défaut'}</span></summary>
      <div className="choice-cloud">{choices.map((c) => <Checkbox key={c.id} label={c.label} checked={selected.includes(c.id)} onChange={() => onChange(selected.includes(c.id) ? selected.filter((x) => x !== c.id) : [...selected, c.id])} />)}</div>
      <p className="tiny muted">Sans choix, la CLI prend sa valeur par défaut.</p></details>;
  }
  return <p className="small">{q.prompt}</p>;
}

function PlanView({ plan }: { plan: RulePlan }) {
  return <>
    <ul className="plain stack tight rule-plan">{plan.packs.map((p) => <li key={p.id} className="row between"><span><strong>{p.title}</strong> <span className="mono tiny">{p.id} {p.version}</span><span className="tiny muted block">{p.provenance.join(' · ')}</span></span><Badge>{p.rules.length} règle(s)</Badge></li>)}</ul>
    {plan.conflicts.length > 0 && <Notice tone="danger" title="Conflits :"><pre>{JSON.stringify(plan.conflicts, null, 2)}</pre></Notice>}
    {plan.conventions.length > 0 && <p className="small"><strong>Conventions :</strong> {plan.conventions.join(' · ')}</p>}
    {plan.checks.length > 0 && <p className="small rule-checks"><strong>Vérifications :</strong> {plan.checks.map((c) => <code key={c}>{c} </code>)}</p>}
  </>;
}

/* ------------------------------------------------------------------ blueprint */

export function Blueprint({ tab = 'profil' }: { tab?: string }) {
  return (
    <div className="page-grid">
      <Tabs label="Blueprint" value={tab} onChange={(t) => { window.location.hash = `#/blueprint/${t}`; }} tabs={[
        { id: 'profil', label: 'Profil', icon: 'plan' },
        { id: 'regles', label: 'Règles en vigueur', icon: 'scroll' },
        { id: 'detection', label: 'Pile détectée', icon: 'search' },
        { id: 'json', label: 'project.json', icon: 'edit' },
      ]} />
      {tab === 'regles' ? <Rules /> : tab === 'detection' ? <Detection /> : tab === 'json' ? <RawProfile /> : <ProfileEditor />}
    </div>
  );
}

async function save(next: Profile | string) {
  const text = typeof next === 'string' ? next : `${JSON.stringify(next, null, 2)}\n`;
  try {
    const result = await saveProfile(text);
    if (result.code !== 0) { toast({ tone: 'danger', title: 'Profil refusé, version précédente remise', text: cliMessage(result).slice(0, 240) }); return false; }
    toast({ tone: 'success', title: 'Profil enregistré et instructions synchronisées' });
    invalidate();
    return true;
  } catch (e) {
    // A lower guard, public research or a regulation dropped is the person's decision at a terminal.
    if (e instanceof ApiError && e.command) showTerminal({ title: 'Changement du profil : à faire dans votre terminal', why: e.message, command: e.command, after: 'Remplacez NAME et WHY par votre nom et la raison. La commande demande de confirmer ; revenez ici et actualisez.' });
    else toast({ tone: 'danger', title: 'Enregistrement impossible', text: (e as Error).message });
    return false;
  }
}

function ProfileEditor() {
  const profile = useProfile();
  const brains = useBrains();
  const [draft, setDraft] = useState<Profile | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (profile.data) setDraft(profile.data); }, [profile.data]);
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(profile.data), [draft, profile.data]);
  if (!draft) return <Q q={profile}>{() => null}</Q>;
  const set = <K extends keyof Profile>(key: K, value: Profile[K]) => setDraft((d) => { const next = { ...d! }; if (value === undefined || (Array.isArray(value) && value.length === 0 && key !== 'boards' && key !== 'conventions' && key !== 'checks')) delete next[key]; else next[key] = value; return next; });
  const boards = Object.values(brains.data ?? {});
  return (
    <div className="page-grid">
      <Notice tone="warn">Changer le profil change l’empreinte des règles : une quête validée sous l’ancien profil doit être consultée à nouveau, ou suivie d’une quête liée, avant sa réalisation. Baisser la garde, ouvrir la recherche publique ou retirer une réglementation se décide dans un terminal : l’interface donne la commande.</Notice>
      <div className="grid-2">
        <Panel title="Identité et politique">
          <TextField label="Nom du projet" value={draft.name} onChange={(e) => set('name', e.target.value)} />
          <div className="field"><label htmlFor="research">Recherche publique</label><select id="research" className="input" value={draft.research ?? 'local-only'} onChange={(e) => set('research', e.target.value as Profile['research'])}><option value="local-only">Locale uniquement</option><option value="public-sources">Sources publiques autorisées, quête par quête</option></select></div>
          <div className="field"><label htmlFor="host">Hôte de l’agent</label><select id="host" className="input" value={draft.host ?? ''} onChange={(e) => set('host', e.target.value || undefined)}><option value="">Non défini</option><option value="claude-code">Claude Code</option><option value="codex">Codex</option></select></div>
          <div className="field"><label htmlFor="guard">Garde des modifications</label><select id="guard" className="input" value={draft.guard ?? 'off'} onChange={(e) => set('guard', e.target.value as Profile['guard'])}><option value="off">Désactivée</option><option value="observe">Observation</option><option value="enforce">Appliquée</option></select></div>
          <KV items={[['Secteur', draft.sector ?? 'general'], ['Pile', (draft.stack ?? []).join(', ')], ['Approbation', draft.approval?.mode === 'signed' ? 'signée (voir project.json)' : 'au terminal']]} />
        </Panel>
        <Panel title="Conventions et vérifications">
          <ListEditor label="Conventions de l’équipe" items={draft.conventions ?? []} onChange={(v) => set('conventions', v)} placeholder="Use Conventional Commits for commit messages." />
          <ListEditor label="Commandes de vérification" hint="task verify lance ces commandes, à la racine du projet. Chacune est obligatoire." items={draft.checks ?? []} onChange={(v) => set('checks', v)} placeholder="npm test" />
          <ListEditor label="Outils approuvés" hint="Les livrables métier ne démarrent qu’avec l’un d’eux." items={draft.tools ?? []} onChange={(v) => set('tools', v)} placeholder="Brevo" />
          <ListEditor label="Règles obligatoires" hint="PACK ou PACK/RÈGLE, comme dans openguildkit catalog." items={draft.required_rules ?? []} onChange={(v) => set('required_rules', v)} placeholder="secure-sdlc" />
        </Panel>
      </div>
      <Panel title="Cerveaux">
        <p className="small muted">Sans cerveau coché, tous conseillent. Un cerveau obligatoire rejoint chaque consultation et ne peut pas en être retiré.</p>
        <table className="data compact"><thead><tr><th>Cerveau</th><th>Activé</th><th>Obligatoire</th></tr></thead><tbody>
          {boards.map((b) => { const on = (draft.boards ?? []).includes(b.id); const req = (draft.required_boards ?? []).includes(b.id); return <tr key={b.id}><td><strong>{b.title}</strong> <span className="mono tiny">{b.id}</span></td>
            <td><input type="checkbox" aria-label={`Activer ${b.title}`} checked={on} onChange={() => set('boards', on ? (draft.boards ?? []).filter((x) => x !== b.id) : [...(draft.boards ?? []), b.id])} /></td>
            <td><input type="checkbox" aria-label={`Rendre ${b.title} obligatoire`} checked={req} onChange={() => set('required_boards', req ? (draft.required_boards ?? []).filter((x) => x !== b.id) : [...(draft.required_boards ?? []), b.id])} /></td></tr>; })}
        </tbody></table>
      </Panel>
      <Panel title="Dérogations">
        <ListEditor label="Personnes autorisées à déroger à un blocage" items={draft.waivers?.allowed_by ?? []} onChange={(v) => set('waivers', v.length ? { allowed_by: v, max_days: draft.waivers?.max_days ?? 30 } : undefined)} placeholder="Camille Martin" />
        {draft.waivers && <TextField label="Durée maximale (jours)" type="number" value={String(draft.waivers.max_days)} onChange={(e) => set('waivers', { ...draft.waivers!, max_days: Number(e.target.value) || 1 })} />}
      </Panel>
      <ProfileDecisions profile={draft} />
      <div className="sticky-actions row">
        <Button variant="primary" busy={busy} disabled={!dirty} onClick={async () => { setBusy(true); await save(draft); setBusy(false); }}>Enregistrer et synchroniser</Button>
        <Button disabled={!dirty} onClick={() => setDraft(profile.data ?? null)}>Annuler les modifications</Button>
        {dirty && <span className="small muted">Modifications non enregistrées</span>}
      </div>
    </div>
  );
}

/** Adopt or decline a pattern or regulation with `profile`: who and why are recorded with the change. Declining a
 * regulation weakens a protection: the CLI refuses it here and the page gives the command for the terminal. */
function ProfileDecisions({ profile }: { profile: Profile }) {
  const recommend = useCli<Recommendation>(['recommend', '--json']);
  const [by, setBy] = useRemembered('decider');
  const { act, busy } = useAction();
  const active = new Set((profile.patterns ?? []).map((p) => (typeof p === 'string' ? p : p.id)));
  const declined = (profile.declined ?? []).map((d) => (typeof d === 'string' ? { id: d, by: '', on: '', reason: '' } : d));
  const candidates = [...(recommend.data?.matched ?? []), ...(recommend.data?.suggested ?? [])];
  return (
    <Panel title="Normes et patterns : décisions">
      <p className="small muted">Adopter ou refuser une norme ou un pattern passe par <code>openguildkit profile</code>, qui note qui a décidé, quand et pourquoi, et réécrit les instructions.</p>
      <ActionForm busy={busy !== null} submit="Enregistrer la décision" initial={{ by, action: 'adopt' }} fields={[
        { name: 'action', label: 'Décision', required: true, options: [{ value: 'adopt', label: 'Adopter' }, { value: 'decline', label: 'Refuser (une réglementation : au terminal)' }] },
        { name: 'pattern', label: 'Norme ou pattern', required: true, options: candidates.map((p) => ({ value: p.id, label: `${p.title}${active.has(p.id) ? ' (actif)' : ''}` })) },
        { name: 'by', label: 'Personne qui décide', required: true },
        { name: 'reason', label: 'Pourquoi', required: true },
      ]} onSubmit={async (v) => { setBy(v.by); await act(['profile', v.action, v.pattern, '--by', v.by, '--reason', v.reason], { success: 'Profil changé' }); }} />
      {declined.length > 0 && <><h3 className="h-card">Refusés</h3><ul className="small">{declined.map((d) => <li key={d.id}><span className="mono">{d.id}</span>{d.by && ` : ${d.by}, ${d.on} (${d.reason})`}</li>)}</ul></>}
      {(profile.changes ?? []).length > 0 && <details className="small"><summary>Historique des changements ({profile.changes!.length})</summary><ul>{profile.changes!.map((c, i) => <li key={i}>{c.on} · {c.change} · {c.by} : {c.reason}</li>)}</ul></details>}
    </Panel>
  );
}

function RawProfile() {
  const profile = useProfile();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (profile.data) setText(`${JSON.stringify(profile.data, null, 2)}\n`); }, [profile.data]);
  let error: string | null = null;
  try { JSON.parse(text || '{}'); } catch (e) { error = (e as Error).message; }
  return (
    <Panel title=".openguildkit/project.json">
      <p className="small muted">Pour les champs sans formulaire (composants, patterns, approbation signée). L’enregistrement lance <code>sync</code> ; si la CLI refuse le profil, la version précédente est remise.</p>
      <TextArea label="Profil (JSON)" className="mono-area" value={text} error={error} onChange={(e) => setText(e.target.value)} rows={24} />
      <Button variant="primary" busy={busy} disabled={!!error} onClick={async () => { setBusy(true); await save(text); setBusy(false); }}>Enregistrer et synchroniser</Button>
    </Panel>
  );
}

function Rules() {
  const plan = useCli<RulePlan>(['preview', '--json']);
  return <Panel title="Packs de règles en vigueur et leur origine"><Q q={plan}>{(p) => <PlanView plan={p} />}</Q>
    <p className="small"><a href="#/bibliotheque/packs">Lire chaque règle et sa vérification dans la Bibliothèque</a></p></Panel>;
}

function Detection() {
  const detect = useCli<{ components: { path: string; technologies?: { name: string; version?: string; evidence?: string }[]; [k: string]: unknown }[] }>(['detect', '--json']);
  const recommend = useCli<Recommendation>(['recommend', '--json']);
  return (
    <div className="grid-2">
      <Panel title="Composants détectés">
        <p className="small muted">D’après les manifestes du dépôt, sans lancer de gestionnaire de paquets.</p>
        <Q q={detect}>{(d) => d.components.length === 0 ? <p className="muted">Aucun manifeste reconnu.</p> : <ul className="plain stack tight">{d.components.map((c) => <li key={c.path} className="card"><strong className="mono">{c.path}</strong><JsonDetails data={c} label="Technologies et preuves" /></li>)}</ul>}</Q>
      </Panel>
      <Panel title="Patterns pour cette pile">
        <Q q={recommend}>{(r) => <>
          <h3 className="h-card"><Icon name="check" size={12} /> Retenus ({r.matched.length})</h3>
          <ul className="small">{r.matched.map((p) => <li key={p.id}><strong>{p.title}</strong> <span className="tiny muted">{p.matched_stack?.join(', ')}</span></li>)}</ul>
          {r.suggested.length > 0 && <><h3 className="h-card">Suggérés ({r.suggested.length})</h3><ul className="small">{r.suggested.map((p) => <li key={p.id}>{p.title}</li>)}</ul></>}
          {r.review.length > 0 && <Notice tone="warn" title="À revoir :"><ul>{r.review.map((x) => <li key={x.id}>{x.id} : {x.reasons.join('; ')}</li>)}</ul></Notice>}
          <p className="tiny muted">Packs recommandés : {r.recommended_packs.join(', ')}</p>
        </>}</Q>
      </Panel>
    </div>
  );
}
