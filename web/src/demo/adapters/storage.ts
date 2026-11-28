/**
 * Local persistence (localStorage) with a schema version, a controlled migration path and
 * recoverable errors (quota, unreadable save). Never stores secrets: the demo has none.
 */
import { z } from 'zod';
import { SCHEMA_VERSION, emptyState } from '@/demo/domain/state';
import type { AppState } from '@/demo/domain/types';

export const STORAGE_KEY = 'open-guild-kit.demo';
const BACKUP_FORMAT = 'ogk-sauvegarde/1';

export type LoadResult = { state: AppState; problem?: string; savedAt?: number };
export interface KeyValueStore { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void }

const memory = new Map<string, string>();
const fallback: KeyValueStore = { getItem: (k) => memory.get(k) ?? null, setItem: (k, v) => void memory.set(k, v), removeItem: (k) => void memory.delete(k) };
export const defaultStore = (): KeyValueStore => (typeof localStorage !== 'undefined' ? localStorage : fallback);

/** Shape check of a saved workspace. Business consistency is checked by `integrityProblems`. */
const record = z.record(z.string(), z.object({ id: z.string() }).passthrough());
export const stateSchema = z.object({
  schema: z.number(),
  seq: z.number().int().nonnegative(),
  orgs: z.record(z.string(), z.object({ id: z.string(), name: z.string() }).passthrough()),
  users: z.record(z.string(), z.object({ id: z.string(), name: z.string() }).passthrough()),
  db: z.record(z.string(), record),
  catalogue: z.object({ added: z.array(z.any()), history: z.record(z.string(), z.any()), proposals: z.array(z.any()), favorites: z.record(z.string(), z.array(z.string())) }),
  session: z.object({ orgId: z.string().nullable(), projectId: z.string().nullable(), actor: z.object({ type: z.enum(['human', 'agent', 'system']) }).passthrough() }),
  prefs: z.object({ mode: z.enum(['explorer', 'focus']) }).passthrough(),
  demo: z.object({ timeOffsetMs: z.number(), nextFailure: z.enum(['tool-error', 'inconclusive']).nullable() }),
  drafts: z.record(z.string(), z.any()),
  appliedOps: z.array(z.string()),
});

/** Relations that must resolve for a workspace to be usable. */
export function integrityProblems(s: AppState): string[] {
  const out: string[] = [];
  const kinds = Object.keys(emptyState().db);
  for (const k of kinds) if (!s.db[k as keyof AppState['db']]) out.push(`Table « ${k} » absente.`);
  if (out.length) return out;
  for (const p of Object.values(s.db.project)) {
    if (!s.orgs[p.orgId]) out.push(`Le projet ${p.id} référence une organisation absente.`);
    if (!s.db.product[p.productId]) out.push(`Le projet ${p.id} référence un produit absent.`);
  }
  for (const q of Object.values(s.db.quest)) if (!s.db.project[q.projectId]) out.push(`La quête ${q.id} référence un projet absent.`);
  for (const d of Object.values(s.db.deliverable)) if (!d.versions?.some((v) => v.number === d.current)) out.push(`Le livrable ${d.id} n’a pas de version courante.`);
  for (const t of Object.values(s.db.task)) for (const dep of t.dependsOn ?? []) if (!s.db.task[dep]) out.push(`La tâche ${t.id} dépend d’une tâche absente.`);
  for (const [id, e] of Object.entries(s.db.event)) if (!s.orgs[e.orgId]) out.push(`L’événement ${id} appartient à une organisation absente.`);
  return out.slice(0, 12);
}

export function parseWorkspace(raw: unknown): { state?: AppState; errors: string[] } {
  const parsed = stateSchema.safeParse(raw);
  if (!parsed.success) return { errors: parsed.error.issues.slice(0, 8).map((i) => `${i.path.join('.') || 'racine'} : ${i.message}`) };
  const state = migrate(parsed.data as unknown as AppState);
  if (!state) return { errors: [`Version de schéma ${parsed.data.schema} non prise en charge (attendue : ${SCHEMA_VERSION}).`] };
  const problems = integrityProblems(state);
  return problems.length ? { errors: problems } : { state, errors: [] };
}

/** Migration hook: older schemas are upgraded here or refused explicitly. */
function migrate(s: AppState): AppState | null {
  if (s.schema === SCHEMA_VERSION) return s;
  if (s.schema === 3) return { ...s, schema: SCHEMA_VERSION, drafts: s.drafts ?? {} };
  return null;
}

export function loadWorkspace(store: KeyValueStore = defaultStore()): LoadResult {
  let text: string | null = null;
  try {
    text = store.getItem(STORAGE_KEY);
  } catch {
    return { state: emptyState(), problem: 'Le stockage local est inaccessible (navigation privée ou stockage bloqué). Vos actions fonctionneront mais ne seront pas conservées après fermeture.' };
  }
  if (!text) return { state: emptyState() };
  try {
    const envelope = JSON.parse(text) as { savedAt?: number; state: unknown };
    const { state, errors } = parseWorkspace(envelope.state);
    if (state) return { state, savedAt: envelope.savedAt };
    store.setItem(`${STORAGE_KEY}.illisible`, text);
    return { state: emptyState(), problem: `La sauvegarde locale est illisible (${errors[0]}). Une copie a été conservée sous « ${STORAGE_KEY}.illisible » ; vous repartez d’un espace vide.` };
  } catch {
    try { store.setItem(`${STORAGE_KEY}.illisible`, text); } catch { /* ignore */ }
    return { state: emptyState(), problem: 'La sauvegarde locale est corrompue. Une copie a été conservée ; vous repartez d’un espace vide.' };
  }
}

export function saveWorkspace(state: AppState, store: KeyValueStore = defaultStore()): { ok: true } | { ok: false; reason: string } {
  try {
    store.setItem(STORAGE_KEY, JSON.stringify({ savedAt: Date.now(), state }));
    return { ok: true };
  } catch (e) {
    const quota = e instanceof DOMException && (e.name === 'QuotaExceededError' || e.code === 22);
    return { ok: false, reason: quota ? 'Quota de stockage local atteint : la dernière modification n’est pas enregistrée. Exportez une sauvegarde puis réinitialisez les données de démonstration.' : `Enregistrement impossible : ${(e as Error).message}` };
  }
}

export function clearWorkspace(store: KeyValueStore = defaultStore()) {
  store.removeItem(STORAGE_KEY);
}

/* ---------------------------------------------------------------- backups */

export interface BackupPreview { ok: boolean; errors: string[]; state?: AppState; orgs: { id: string; name: string; conflict: boolean; counts: Record<string, number> }[]; exportedAt?: string }

export function backupOf(state: AppState): string {
  return JSON.stringify({ format: BACKUP_FORMAT, exportedAt: new Date().toISOString(), schema: SCHEMA_VERSION, state }, null, 1);
}

/** Validates an imported backup without touching the current workspace (RG-41). */
export function previewBackup(text: string, current: AppState): BackupPreview {
  let data: { format?: string; exportedAt?: string; state?: unknown };
  try { data = JSON.parse(text); } catch (e) { return { ok: false, errors: [`Fichier JSON illisible : ${(e as Error).message}`], orgs: [] }; }
  if (data.format !== BACKUP_FORMAT) return { ok: false, errors: [`Format inattendu « ${data.format ?? 'absent'} » (attendu : ${BACKUP_FORMAT}).`], orgs: [] };
  const { state, errors } = parseWorkspace(data.state);
  if (!state) return { ok: false, errors, orgs: [] };
  const orgs = Object.values(state.orgs).map((o) => ({
    id: o.id, name: o.name, conflict: !!current.orgs[o.id],
    counts: Object.fromEntries(['project', 'quest', 'decision', 'deliverable', 'event'].map((k) => [k, Object.values(state.db[k as 'project']).filter((e) => e.orgId === o.id).length])),
  }));
  return { ok: true, errors: [], state, orgs, exportedAt: data.exportedAt };
}

/** Applies an import: 'replace' swaps the workspace; 'merge' adds organisations and replaces the chosen conflicting ones. */
export function applyBackup(current: AppState, incoming: AppState, mode: 'replace' | 'merge', replaceOrgIds: string[] = []): AppState {
  if (mode === 'replace') return structuredClone(incoming);
  const next = structuredClone(current);
  const take = Object.keys(incoming.orgs).filter((id) => !current.orgs[id] || replaceOrgIds.includes(id));
  for (const orgId of take) {
    for (const table of Object.values(next.db)) for (const [id, e] of Object.entries(table)) if ((e as { orgId?: string }).orgId === orgId) delete (table as Record<string, unknown>)[id];
    next.orgs[orgId] = incoming.orgs[orgId];
    for (const [kind, table] of Object.entries(incoming.db)) for (const [id, e] of Object.entries(table)) if ((e as { orgId?: string }).orgId === orgId) (next.db[kind as 'project'] as Record<string, unknown>)[id] = e;
    next.catalogue.favorites[orgId] = incoming.catalogue.favorites[orgId] ?? [];
  }
  Object.assign(next.users, incoming.users);
  next.seq = Math.max(next.seq, incoming.seq);
  return next;
}
