/**
 * Preferences of the project interface: display (style, motion), single-key shortcuts and the names the forms
 * remember. The project keeps them (`POST /api/prefs`, #463), because the browser keeps its storage per origin and the
 * host name changes at each launch; this browser keeps a copy too, read until the session brings the project's.
 */
import { useSyncExternalStore } from 'react';
import { persistSingleKeyShortcuts, setSingleKeyShortcuts } from '@/shared/shortcuts';
import { currentSession, savePrefs, type ServerPrefs } from './api';

export interface Prefs { mode: 'explorer' | 'focus'; motion: 'system' | 'reduced' }
const KEY = 'ogk-ui:prefs';
const read = (): Prefs => {
  try { return { mode: 'explorer', motion: 'system', ...JSON.parse(localStorage.getItem(KEY) ?? '{}') } as Prefs; }
  catch { return { mode: 'explorer', motion: 'system' }; }
};
let prefs = read();
const listeners = new Set<() => void>();
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
const notify = () => listeners.forEach((l) => l());

/** Sends a change to the project; a refusal (a name too long) or a stopped server leaves this browser's copy. */
function keep(patch: ServerPrefs) {
  if (currentSession()) void savePrefs(patch).catch(() => undefined);
}

function store(patch: Partial<Prefs>) {
  prefs = { ...prefs, ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* private mode: keep it for this visit */ }
  notify();
}

export function setPrefs(patch: Partial<Prefs>) {
  store(patch);
  keep(patch);
}
export const usePrefs = () => useSyncExternalStore(subscribe, () => prefs);

/** The names a form remembers (the decision owner, the signer), shared by every form of the page. */
const NAMES = ['decider', 'signer'] as const;
const names = new Map<string, string>();
const typing = new Map<string, ReturnType<typeof setTimeout>>();
export function rememberedName(key: string, initial = '') {
  if (!names.has(key)) {
    try { names.set(key, localStorage.getItem(`ogk-ui:${key}`) ?? initial); } catch { names.set(key, initial); }
  }
  return names.get(key)!;
}
export function rememberName(key: string, value: string, send = true) {
  names.set(key, value);
  try { localStorage.setItem(`ogk-ui:${key}`, value); } catch { /* private mode */ }
  notify();
  if (!send || !(NAMES as readonly string[]).includes(key)) return;
  // A name is typed letter by letter: the project receives it once the typing pauses.
  clearTimeout(typing.get(key));
  typing.set(key, setTimeout(() => keep({ [key]: value }), 600));
}
export const useRememberedName = (key: string, initial = '') => useSyncExternalStore(subscribe, () => rememberedName(key, initial));

/** Takes the preferences the project kept, from the session, before the first render; what it lacks stays as is. */
export function adoptServerPrefs(kept: ServerPrefs) {
  const display: Partial<Prefs> = {};
  if (kept.mode) display.mode = kept.mode;
  if (kept.motion) display.motion = kept.motion;
  store(display);
  // Before the project receives the changes: taking its own value back does not send it.
  if (kept.shortcuts) setSingleKeyShortcuts(kept.shortcuts === 'on');
  for (const key of NAMES) if (kept[key] !== undefined) rememberName(key, kept[key]!, false);
  persistSingleKeyShortcuts((on) => keep({ shortcuts: on ? 'on' : 'off' }));
}
