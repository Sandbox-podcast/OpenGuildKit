/**
 * Keyboard shortcuts of both shells (the demo and a project): Ctrl+K or Cmd+K opens the search; the single-key
 * shortcuts (/ search, g then a letter to change place, m to change style, ? help) can be turned off, as WCAG 2.1.4
 * asks, and the choice is kept in this browser (and by the project, for the project interface).
 */
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { PLACES } from './places';

const KEY = 'ogk-ui:single-key-shortcuts';
const read = () => {
  try {
    return localStorage.getItem(KEY) !== 'off';
  } catch {
    return true;
  }
};
let enabled = read();
const listeners = new Set<() => void>();

let persist: ((on: boolean) => void) | null = null;

/** Where a person's choice also goes: the project interface keeps it on the server (#463). */
export function persistSingleKeyShortcuts(save: (on: boolean) => void) {
  persist = save;
}

export function setSingleKeyShortcuts(on: boolean) {
  enabled = on;
  try {
    localStorage.setItem(KEY, on ? 'on' : 'off');
  } catch {
    /* private mode: kept for this visit */
  }
  listeners.forEach((l) => l());
  persist?.(on);
}
export const useSingleKeyShortcuts = () =>
  useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => {
        listeners.delete(l);
      };
    },
    () => enabled,
  );

interface ShortcutActions {
  openSearch: () => void;
  toggleMode: () => void;
  go: (route: string) => void;
  help?: () => void;
}

/** What a key does, given whether single keys are on and when the last `g` was pressed; null when nothing. */
export function shortcutFor(
  e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean },
  single: boolean,
  sinceG: number,
): { action: 'search' | 'mode' | 'help' | 'prefix' } | { action: 'go'; route: string } | null {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') return { action: 'search' };
  if (!single || e.ctrlKey || e.metaKey || e.altKey) return null;
  if (sinceG < 1200) {
    const place = PLACES.find((p) => p.shortcut === e.key.toLowerCase());
    if (place) return { action: 'go', route: place.route };
  }
  if (e.key === '/') return { action: 'search' };
  if (e.key === '?') return { action: 'help' };
  if (e.key === 'g') return { action: 'prefix' };
  if (e.key === 'm') return { action: 'mode' };
  return null;
}

/** Listens to the keyboard for a shell. Single keys never act while the person types or a dialog is open. */
export function useShortcuts(actions: ShortcutActions) {
  const single = useSingleKeyShortcuts();
  const prefix = useRef(0);
  const latest = useRef(actions);
  latest.current = actions;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable;
      const blocked = typing || !!document.querySelector('dialog[open]');
      const shortcut = shortcutFor(e, single && !blocked, Date.now() - prefix.current);
      if (!shortcut) return;
      const run = latest.current;
      if (shortcut.action === 'search') {
        e.preventDefault();
        run.openSearch();
        return;
      }
      if (shortcut.action === 'prefix') {
        prefix.current = Date.now();
        return;
      }
      prefix.current = 0;
      if (shortcut.action === 'go') run.go(shortcut.route);
      else if (shortcut.action === 'mode') run.toggleMode();
      else if (shortcut.action === 'help') run.help?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [single]);
}
