/** Building blocks shared by the places of the project interface. */
import { useCallback, useEffect, useId, useState, useSyncExternalStore, type ReactNode } from 'react';
import { Badge, Button, Notice, TextArea, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Icon, type PixelIconName } from '@/shared/pixel/icons';
import { toast } from '@/shared/ui/toast';
import { isSafeUrl } from '@/shared/text';
import { ApiError, cliMessage, type CliResult } from './api';
import { onlyTasksFail } from './data';
import type { TaskListItem } from './types';
import { showTerminal, showTouched, useTerminalRequest, useTouched, type Query } from './query';
import { STEPS, needsReconsult, stepOf, taskStatus, touchedStep } from './labels';
import { usePrefs } from './prefs';

export function Loading({ label = 'Chargement' }: { label?: string }) {
  return <p className="muted loading-line" role="status"><Icon name="hourglass" size={14} /> {label}…</p>;
}

/** Text the CLI wrote in English and the page does not translate: marked so a screen reader reads it in English. */
export function En({ children, block, className }: { children: ReactNode; block?: boolean; className?: string }) {
  return block ? <div lang="en" className={className}>{children}</div> : <span lang="en" className={className}>{children}</span>;
}

export function ErrorNotice({ error, title = 'La commande a échoué' }: { error: ApiError | Error | undefined | null; title?: string }) {
  if (!error) return null;
  return <Notice tone="danger" title={title}><span className="pre-line" lang={error instanceof ApiError ? error.lang : undefined}>{error.message}</span></Notice>;
}

/** Renders a query: a loading line, its error, or the content once the data is there. */
export function Q<T>({ q, children, label, empty }: { q: Query<T>; children: (data: T) => ReactNode; label?: string; empty?: ReactNode }) {
  if (q.data === undefined) return q.error ? <ErrorNotice error={q.error} /> : <Loading label={label} />;
  if (empty !== undefined && (q.data === null || (Array.isArray(q.data) && q.data.length === 0))) return <>{empty}</>;
  return <>{children(q.data)}</>;
}

export function TaskStatusBadge({ status }: { status: string }) {
  const rpg = usePrefs().mode === 'explorer';
  const s = taskStatus(status);
  return <Badge tone={s.tone} icon={s.icon}>{rpg ? s.rpg : s.label}</Badge>;
}

export function TaskLink({ id, to = 'quetes' }: { id: string; to?: string }) {
  return <a className="mono objlink" href={`#/${to}/${id}`}>{id}</a>;
}

export function ExternalLink({ href, children }: { href: string; children?: ReactNode }) {
  if (!isSafeUrl(href)) return <span>{children ?? href}</span>;
  return <a href={href} target="_blank" rel="noopener noreferrer">{children ?? href} <Icon name="external" size={11} /></a>;
}

export async function copyText(text: string) {
  try { await navigator.clipboard.writeText(text); toast({ tone: 'success', title: 'Commande copiée' }); }
  catch { toast({ tone: 'warning', title: 'Copie impossible', text: 'Sélectionnez la commande et copiez-la.' }); }
}

/** A command a person types in their own terminal, with a copy button. */
export function CommandLine({ command, label = 'Commande' }: { command: string; label?: string }) {
  return (
    <div className="command-line">
      <code aria-label={label}>{command}</code>
      <Button size="small" icon="copy" onClick={() => void copyText(command)}>Copier</Button>
    </div>
  );
}

/** Shown when the server refuses an action that only a person at a terminal may record. */
export function TerminalDialog() {
  const request = useTerminalRequest();
  return (
    <Dialog open={!!request} onClose={() => showTerminal(null)} title={request?.title ?? ''} footer={<Button variant="primary" onClick={() => showTerminal(null)}>J’ai compris</Button>}>
      {request && <>
        <p>{request.why}</p>
        <CommandLine command={request.command} />
        <p className="muted small">{request.after ?? 'La commande affiche le dossier, puis vous demande de retaper l’identifiant. L’interface se met à jour dès que la commande est enregistrée : revenez ici et actualisez.'}</p>
      </>}
    </Dialog>
  );
}

/** The tasks the last change of rules left under the previous ones (sync, update --apply, a saved profile), in full. */
export function TouchedNotice() {
  const list = useTouched();
  if (!list) return null;
  return (
    <div className="notice warn touched-notice" role="status">
      <Icon name="warn" size={16} />
      <div className="grow"><strong>Tâches consultées sous les règles précédentes :</strong>
        <ul>{list.map((t) => { const step = touchedStep(t.step); return <li key={t.id}><TaskLink id={t.id} /> ({taskStatus(t.status).label}) : {step ?? <span lang="en">{t.step}</span>}.</li>; })}</ul>
        <span className="small">Une tâche terminée garde son enregistrement comme historique.</span></div>
      <Button size="small" variant="ghost" onClick={() => showTouched(null)}>Masquer</Button>
    </div>
  );
}

/**
 * The result of `check`: the instructions in line with the profile, drifted from it (sync fixes that), or in line
 * while tasks fail it, an approval that no longer holds or an unreadable record, which only a person can fix.
 */
export function CheckNotice({ result, tasks }: { result: CliResult; tasks: TaskListItem[] }) {
  const notes = result.stderr.replace(/^OpenGuildKit:\s*/gm, '').trim();
  if (result.code === 0) return <Notice tone="success">Les instructions correspondent au profil du projet.{notes && <span className="block small pre-line" lang="en">{notes}</span>}</Notice>;
  if (onlyTasksFail(result)) {
    const named = tasks.filter((t) => needsReconsult(t) || t.status === 'unreadable');
    return <Notice tone="warn" title="Les instructions correspondent au profil, mais des tâches sont à reprendre par une personne :">
      <ul>{named.map((t) => <li key={t.id}><TaskLink id={t.id} to={t.status === 'unreadable' ? 'quetes' : 'conseil'} /> : {t.status === 'unreadable' ? 'fichier illisible, à réparer' : 'approbation qui ne tient plus, à consulter à nouveau'}</li>)}</ul>
      Synchroniser ne change rien à ces tâches.</Notice>;
  }
  return <Notice tone="danger" title="À corriger :"><span className="pre-line" lang="en">{cliMessage(result)}</span></Notice>;
}

/** What a page shows for a task record the CLI cannot read, instead of a failed `task show`. */
export function UnreadableTask({ id, message }: { id: string; message: string }) {
  return (
    <Notice tone="danger" title={`Le fichier de la tâche ${id} est illisible.`}>
      <span className="block pre-line" lang="en">{message}</span>
      <span className="block small">C’est souvent un conflit de fusion Git laissé dans <code>.openguildkit/tasks/{id}.json</code>. Ouvre le fichier dans ton éditeur et garde une seule version de chaque bloc (sans les marqueurs <code>&lt;&lt;&lt;&lt;&lt;&lt;&lt;</code>, <code>=======</code>, <code>&gt;&gt;&gt;&gt;&gt;&gt;&gt;</code>), ou reprends la version d’une branche avec Git, puis actualise la page. Tant qu’il est illisible, la CLI et la page ne peuvent rien faire de cette tâche.</span>
    </Notice>
  );
}

/** The six steps of a task, from the brief to the proof. */
export function StepRail({ status, hasResult }: { status: string; hasResult: boolean }) {
  const rpg = usePrefs().mode === 'explorer';
  const current = stepOf(status, hasResult);
  return (
    <ol className="step-rail" aria-label="Étapes de la quête">
      {STEPS.map((step, i) => {
        const state = i < current ? 'done' : i === current ? 'current' : 'todo';
        return (
          <li key={step.id} className={`step-rail-item ${state}`} aria-current={state === 'current' ? 'step' : undefined}>
            <span className="step-rail-dot"><Icon name={state === 'done' ? 'check' : step.icon as PixelIconName} size={14} /></span>
            <span>{rpg ? step.rpg : step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Reads a local file as text, for a JSON report, a review or a signature. */
export function FilePick({ label, accept = '.json,application/json', onText, hint }: { label: string; accept?: string; onText: (text: string, name: string) => void; hint?: string }) {
  const id = useId();
  const [name, setName] = useState('');
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} type="file" accept={accept} onChange={async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (file.size > 4_000_000) { toast({ tone: 'danger', title: 'Fichier trop lourd', text: '4 Mo au plus.' }); return; }
        setName(file.name);
        onText(await file.text(), file.name);
      }} />
      {(hint || name) && <p className="hint">{name ? `Fichier lu : ${name}` : hint}</p>}
    </div>
  );
}

/** Edits a list of single-line texts (conventions, checks, tools, recipients). */
export function ListEditor({ label, items, onChange, placeholder, hint, error }: { label: string; items: string[]; onChange: (items: string[]) => void; placeholder?: string; hint?: string; error?: string | null }) {
  const [draft, setDraft] = useState('');
  const add = () => { const v = draft.trim(); if (v && !items.includes(v)) onChange([...items, v]); setDraft(''); };
  return (
    <fieldset className="list-editor">
      <legend>{label}</legend>
      {hint && <p className="hint">{hint}</p>}
      {items.length > 0 && <ul className="plain chips">{items.map((item) => (
        <li key={item} className="chip"><span>{item}</span><button type="button" className="chip-remove" aria-label={`Retirer ${item}`} onClick={() => onChange(items.filter((x) => x !== item))}><Icon name="cross" size={11} /></button></li>
      ))}</ul>}
      <div className="row">
        <input className="input" value={draft} placeholder={placeholder} aria-label={`Ajouter : ${label}`} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }} />
        <Button size="small" icon="plus" onClick={add} disabled={!draft.trim()}>Ajouter</Button>
      </div>
      {error && <p className="error small" role="alert">{error}</p>}
    </fieldset>
  );
}

export function JsonDetails({ data, label = 'Voir le JSON' }: { data: unknown; label?: string }) {
  return <details className="json-details"><summary>{label}</summary><pre className="code-block">{JSON.stringify(data, null, 2)}</pre></details>;
}

export function Pre({ text }: { text: string }) {
  return <pre className="code-block pre-wrap">{text.trim()}</pre>;
}

/**
 * A small form with the fields a CLI action needs; the submit runs `onSubmit` with the values. A field's `check`
 * says why its value is refused, under the field, and `problem` why the form as a whole cannot be sent yet.
 */
export function ActionForm({ fields, submit, busy, onSubmit, initial, tone, problem }: {
  fields: { name: string; label: string; required?: boolean; multiline?: boolean; placeholder?: string; type?: string; hint?: string; options?: { value: string; label: string }[]; check?: (value: string) => string | null }[];
  submit: string; busy?: boolean; tone?: 'primary' | 'danger' | 'ai';
  onSubmit: (values: Record<string, string>) => void | Promise<unknown>;
  initial?: Record<string, string>;
  problem?: string | null;
}) {
  const [values, setValues] = useState<Record<string, string>>(initial ?? {});
  const [tried, setTried] = useState(false);
  const missing = fields.filter((f) => f.required && !values[f.name]?.trim());
  const errorOf = (f: (typeof fields)[number]) => (values[f.name]?.trim() && f.check ? f.check(values[f.name].trim()) : null);
  const refused = fields.filter((f) => errorOf(f));
  const set = (name: string, value: string) => setValues((v) => ({ ...v, [name]: value }));
  return (
    <form className="stack action-form" onSubmit={(e) => { e.preventDefault(); setTried(true); if (!missing.length && !refused.length && !problem) void onSubmit(values); }}>
      {fields.map((f) => f.options
        ? <div className="field" key={f.name}><label htmlFor={`f-${f.name}`}>{f.label}</label>
            <select id={`f-${f.name}`} className="input" value={values[f.name] ?? ''} required={f.required} onChange={(e) => set(f.name, e.target.value)}>
              <option value="">Choisir…</option>
              {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>{f.hint && <p className="hint">{f.hint}</p>}</div>
        : f.multiline
          ? <TextArea key={f.name} label={f.label} hint={f.hint} error={errorOf(f)} value={values[f.name] ?? ''} required={f.required} placeholder={f.placeholder} onChange={(e) => set(f.name, e.target.value)} />
          : <TextField key={f.name} label={f.label} hint={f.hint} error={errorOf(f)} type={f.type ?? 'text'} value={values[f.name] ?? ''} required={f.required} placeholder={f.placeholder} onChange={(e) => set(f.name, e.target.value)} />)}
      {tried && problem && <p className="error small" role="alert">{problem}</p>}
      <div className="row"><Button type="submit" variant={tone ?? 'primary'} busy={busy} disabled={busy || missing.length > 0 || refused.length > 0}>{submit}</Button></div>
    </form>
  );
}

/** The value once it has not changed for `ms`: requests follow what a person types once typing pauses. */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => { const t = setTimeout(() => setSettled(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return settled;
}

/** Keeps a field's value in this browser between visits (the name of the decision owner), shared by every form of the page. */
const remembered = new Map<string, string>();
const rememberedListeners = new Set<() => void>();
export function useRemembered(key: string, initial = '') {
  const read = () => { if (!remembered.has(key)) { try { remembered.set(key, localStorage.getItem(`ogk-ui:${key}`) ?? initial); } catch { remembered.set(key, initial); } } return remembered.get(key)!; };
  const value = useSyncExternalStore((l) => { rememberedListeners.add(l); return () => { rememberedListeners.delete(l); }; }, read);
  const setValue = useCallback((next: string) => { remembered.set(key, next); try { localStorage.setItem(`ogk-ui:${key}`, next); } catch { /* private mode */ } rememberedListeners.forEach((l) => l()); }, [key]);
  return [value, setValue] as const;
}

export function Section({ title, icon, children, actions, id }: { title: ReactNode; icon?: PixelIconName; children: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <section className="panel" id={id} aria-label={typeof title === 'string' ? title : undefined}>
      <header><h2 className="h-panel">{icon && <Icon name={icon} size={16} />} {title}</h2>{actions && <div className="row">{actions}</div>}</header>
      {children}
    </section>
  );
}
