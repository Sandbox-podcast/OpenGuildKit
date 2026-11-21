/** Display preferences of the project interface, kept in this browser only. */
import { useSyncExternalStore } from 'react';

export interface Prefs { mode: 'explorer' | 'focus'; motion: 'system' | 'reduced' }
const KEY = 'ogk-ui:prefs';
const read = (): Prefs => {
  try { return { mode: 'explorer', motion: 'system', ...JSON.parse(localStorage.getItem(KEY) ?? '{}') } as Prefs; }
  catch { return { mode: 'explorer', motion: 'system' }; }
};
let prefs = read();
const listeners = new Set<() => void>();

export function setPrefs(patch: Partial<Prefs>) {
  prefs = { ...prefs, ...patch };
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* private mode: keep it for this visit */ }
  listeners.forEach((l) => l());
}
export const usePrefs = () => useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l); }; }, () => prefs);
