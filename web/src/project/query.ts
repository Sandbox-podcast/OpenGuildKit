/**
 * Small cache over the local API. A view asks for a command's output with `useCli`; every action that
 * changes the project marks the cache stale, and mounted views reload what they show.
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { ApiError, run, type CliResult, type RunOptions } from './api';
import { toast } from '@/shared/ui/toast';
import { touchedTasks } from './labels';
import { errorText } from './refusals';

interface Entry { data?: unknown; error?: ApiError; loading: boolean; stale: boolean; at: number }

const cache = new Map<string, Entry>();
const listeners = new Set<() => void>();
let version = 0;
const emit = () => { version++; listeners.forEach((listener) => listener()); };
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };

/** Exported for the tests; views use the hooks. */
export const peek = (key: string) => cache.get(key);

export async function load(key: string, fetcher: () => Promise<unknown>) {
  const previous = cache.get(key);
  if (previous?.loading) return;
  cache.set(key, { ...previous, loading: true, stale: false, at: previous?.at ?? 0 });
  emit();
  // An action that changed the project while this request was in flight marks the entry stale again:
  // the answer may predate the change, so the view reloads once more.
  const staleAgain = () => cache.get(key)?.stale ?? false;
  try {
    const data = await fetcher();
    cache.set(key, { data, loading: false, stale: staleAgain(), at: Date.now() });
  } catch (error) {
    cache.set(key, { data: previous?.data, error: error instanceof ApiError ? error : new ApiError(String(error), 0), loading: false, stale: staleAgain(), at: Date.now() });
  }
  emit();
}

export interface Query<T> { data: T | undefined; error: ApiError | undefined; loading: boolean; reload: () => void }

export function useQuery<T>(key: string | null, fetcher: () => Promise<T>): Query<T> {
  useSyncExternalStore(subscribe, () => version);
  const entry = key ? cache.get(key) : undefined;
  const missing = !!key && (!entry || entry.stale);
  useEffect(() => { if (key && missing) void load(key, fetcher); });
  const reload = useCallback(() => { if (key) void load(key, fetcher); }, [key, fetcher]);
  return { data: entry?.data as T | undefined, error: entry?.error, loading: !!key && (!entry || entry.loading || entry.stale) && entry?.data === undefined, reload };
}

const keyOf = (argv: string[]) => argv.join('\u0001');

export const jsonKey = (argv: string[]) => `json:${keyOf(argv)}`;
export const resultKey = (argv: string[]) => `result:${keyOf(argv)}`;

/** JSON output of a read command. */
export function useCli<T>(argv: string[] | null, opts: Pick<RunOptions, 'omit'> = {}): Query<T> {
  const key = argv ? `${jsonKey(argv)}${opts.omit ? `|omit:${opts.omit.join(',')}` : ''}` : null;
  remember(key, argv);
  return useQuery<T>(key, useCallback(async () => {
    const result = await run<T>(argv!, undefined, { omit: opts.omit });
    if (result.json === null) throw new ApiError(`La commande « ${argv!.join(' ')} » n’a pas renvoyé de JSON.${result.stdout ? ` Sortie : ${result.stdout.slice(0, 200)}` : ''}`, 200, { result });
    return result.json;
  }, [key]));
}

/** Text output of a read command (Markdown briefs, handoffs). */
export function useCliText(argv: string[] | null): Query<string> {
  const key = argv ? `text:${keyOf(argv)}` : null;
  remember(key, argv);
  return useQuery<string>(key, useCallback(async () => (await run(argv!, undefined, { raw: true })).stdout, [key]));
}

/** Full result, including a non-zero exit code: `check` and `docs share check` answer through their code. */
export function useCliResult(argv: string[] | null): Query<CliResult> {
  const key = argv ? resultKey(argv) : null;
  return useQuery<CliResult>(key, useCallback(() => run(argv!, undefined, { allowFailure: true, raw: true }), [key]));
}

/**
 * Commands whose answer depends only on the catalog in force (brains, references, patterns, packs, tools,
 * deliverable templates): an ordinary action leaves them as they are.
 */
const catalogKeys = new Set<string>();
const CATALOG = /^(brains|references|patterns|catalog)\u0001|^tools\u0001list|^deliverable\u0001(list|show)|^init\u0001--questions/;
export const remember = (key: string | null, argv: string[] | null) => { if (key && argv && CATALOG.test(argv.join('\u0001'))) catalogKeys.add(key); };
/** Commands that can change the catalog in force or the profile. */
export const changesCatalog = (argv: string[]) => ['update', 'sync', 'init', 'integrations'].includes(argv[0]);

/** Marks the cache stale; mounted views reload. 'project' keeps what depends only on the catalog. */
export function invalidate(scope: 'all' | 'project' = 'all') {
  cache.forEach((entry, key) => { if (scope === 'all' || !catalogKeys.has(key)) cache.set(key, { ...entry, stale: true }); });
  emit();
}

/* ------------------------------------------------------------------ terminal hand-off */
/** why: what the page says, in French or marked English (lang); detail: the server's own words behind a French text. */
export interface TerminalRequest { title: string; why: string; lang?: 'en'; detail?: string; command: string; after?: string }
let terminal: TerminalRequest | null = null;
const terminalListeners = new Set<() => void>();
export const showTerminal = (request: TerminalRequest | null) => { terminal = request; terminalListeners.forEach((l) => l()); };
export const useTerminalRequest = () => useSyncExternalStore((l) => { terminalListeners.add(l); return () => { terminalListeners.delete(l); }; }, () => terminal);

/* ------------------------------------------------------------------ tasks a change of rules touched */
interface Touched { id: string; status: string; step: string }
let touched: Touched[] | null = null;
const touchedListeners = new Set<() => void>();
/** Keeps on screen the tasks that sync, update --apply or a saved profile names, until the person closes the list. */
export const showTouched = (list: Touched[] | null) => { touched = list?.length ? list : null; touchedListeners.forEach((l) => l()); };
export const useTouched = () => useSyncExternalStore((l) => { touchedListeners.add(l); return () => { touchedListeners.delete(l); }; }, () => touched);
/** After a command that rewrites the rules, the tasks it names (or none: the earlier list no longer applies). */
export function reportTouched(argv: string[], stdout: string) {
  const list = touchedTasks(stdout);
  if (list.length || changesCatalog(argv) || argv[0] === 'profile') showTouched(list);
  return list;
}

/* ------------------------------------------------------------------ action warnings */
let actionWarning = '';
const warningListeners = new Set<() => void>();
export function showActionWarning(text: string) {
  actionWarning = text;
  warningListeners.forEach((listener) => listener());
}
export function useActionWarning() {
  return useSyncExternalStore((listener) => {
    warningListeners.add(listener);
    return () => { warningListeners.delete(listener); };
  }, () => actionWarning);
}

/* ------------------------------------------------------------------ actions */
export interface ActionOptions { uploads?: Record<string, string>; success?: string; quiet?: boolean; onDone?: (r: CliResult) => void }

/** Runs a command that changes the project, reports it, then refreshes the views. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const act = useCallback(async (argv: string[], opts: ActionOptions = {}): Promise<CliResult | null> => {
    setBusy(argv.slice(0, 3).join(' '));
    setError(null);
    try {
      const result = await run(argv, opts.uploads, { raw: true });
      const named = reportTouched(argv, result.stdout);
      const revoke = argv[0] === 'docs' && argv[1] === 'share' && argv[2] === 'revoke';
      const relatedShares = revoke ? result.stdout.trim().split('\n').slice(2).join('\n') : '';
      const warnings = [result.stderr.trim(), relatedShares].filter(Boolean).join('\n');
      if (warnings) showActionWarning(warnings);
      const printed = result.stdout.trim().split('\n').slice(0, 2).join(' ').slice(0, 180);
      if (!opts.quiet) toast({ tone: 'success', title: opts.success ?? 'Enregistré', ...(named.length ? { text: `${named.length} tâche(s) consultée(s) sous les règles précédentes : la liste est affichée sur la page.` } : printed ? { text: printed, lang: 'en' as const } : {}) });
      opts.onDone?.(result);
      invalidate(changesCatalog(argv) ? 'all' : 'project');
      return result;
    } catch (caught) {
      const failure = caught instanceof ApiError ? caught : new ApiError(String(caught), 0);
      // A refused command can still have recorded something: task submit keeps a failed pass, task verify its checks.
      if (failure.result) invalidate('project');
      const shown = errorText(failure);
      if (failure.command) showTerminal({ title: 'À faire dans ton terminal', why: shown.text, lang: shown.lang, detail: shown.detail, command: failure.command });
      else { setError(failure); toast({ tone: 'danger', title: 'Commande refusée', text: shown.text.slice(0, 240), lang: shown.lang }); }
      return null;
    } finally {
      setBusy(null);
    }
  }, []);
  return { act, busy, error, clearError: () => setError(null) };
}
