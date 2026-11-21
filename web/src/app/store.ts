/**
 * Application store: one immutable workspace, mutated only through domain commands.
 * Every view reads the same state, so a mutation updates all of them (RG-40).
 */
import { useSyncExternalStore } from 'react';
import { check, execute, type CommandDef, type Outcome } from '@/domain/engine';
import { loadWorkspace, saveWorkspace } from '@/adapters/storage';
import type { AppState } from '@/domain/types';
import { toast } from '@/shared/ui/toast';
import { playSound } from '@/shared/sound';

const initial = loadWorkspace();
let state: AppState = initial.state;
let storageProblem: string | null = initial.problem ?? null;
const listeners = new Set<() => void>();
let saveTimer: ReturnType<typeof setTimeout> | undefined;

function emit() { listeners.forEach((l) => l()); }

function flushSave() {
  if (saveTimer === undefined) return;
  clearTimeout(saveTimer);
  saveTimer = undefined;
  const res = saveWorkspace(state);
  const next = res.ok ? null : res.reason;
  if (next !== storageProblem) { storageProblem = next; emit(); }
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushSave, 250);
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', flushSave);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushSave();
  });
}

export const getState = () => state;
export const subscribe = (l: () => void) => { listeners.add(l); return () => listeners.delete(l); };
export const useAppState = () => useSyncExternalStore(subscribe, getState);
export const useStorageProblem = () => useSyncExternalStore(subscribe, () => storageProblem);
export const dismissStorageProblem = () => { storageProblem = null; emit(); };

export interface DispatchOptions { opId?: string; success?: string | ((value: unknown) => string); silent?: boolean }

/** Executes a command; refusals are reported with their reason, nothing is applied. */
export function dispatch<P, R>(def: CommandDef<P, R>, payload: P, opts: DispatchOptions = {}): Outcome<R> {
  const out = execute(state, def, payload, opts.opId);
  if (!out.ok) {
    if (!opts.silent) toast({ tone: 'danger', title: 'Action refusée', text: out.reason });
    return out;
  }
  if (out.state !== state) {
    state = out.state;
    emit();
    scheduleSave();
  }
  if (opts.success && !out.duplicate) {
    toast({ tone: 'success', title: typeof opts.success === 'function' ? opts.success(out.value) : opts.success });
    if (state.prefs.sound) playSound('success');
  }
  if (out.duplicate && !opts.silent) toast({ tone: 'info', title: 'Déjà enregistré', text: 'Cette opération a déjà été appliquée ; rien n’a été dupliqué.' });
  return out;
}

export const can = <P>(def: CommandDef<P, unknown>, payload: P) => check(state, def, payload);

/** Replaces the whole workspace (import or reset), after explicit confirmation in the UI. */
export function replaceState(next: AppState) {
  state = next;
  emit();
  scheduleSave();
}

export const newOpId = () => `op-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
