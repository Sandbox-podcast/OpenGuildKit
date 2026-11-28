/**
 * Hash router: works on any static host, supports direct links, back/forward and reload of a
 * detail page. A dirty-form guard protects unsaved changes when the context changes.
 */
import { useEffect, useSyncExternalStore } from 'react';

export interface Route { path: string; parts: string[]; query: URLSearchParams }

const parse = (): Route => {
  const raw = window.location.hash.slice(1) || '/';
  const separator = raw.indexOf('?');
  const rawPath = separator === -1 ? raw : raw.slice(0, separator);
  const query = new URLSearchParams(separator === -1 ? '' : raw.slice(separator + 1));
  try {
    const path = decodeURI(rawPath);
    return { path, parts: path.split('/').filter(Boolean), query };
  } catch {
    return { path: '/introuvable', parts: ['introuvable'], query };
  }
};
let route = typeof window === 'undefined' ? { path: '/', parts: [], query: new URLSearchParams() } : parse();
let lastHash = typeof window === 'undefined' ? '' : window.location.hash;
let navigationFocus: { hash: string; target: HTMLElement } | undefined;
const listeners = new Set<() => void>();
const dirty = new Set<string>();

const DIRTY_MESSAGE = 'Des modifications ne sont pas enregistrées. Quitter cette vue quand même ? Les brouillons enregistrés restent disponibles.';

if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', () => {
    const focus = navigationFocus?.hash === window.location.hash ? navigationFocus.target : undefined;
    navigationFocus = undefined;
    if (dirty.size && !window.confirm(DIRTY_MESSAGE)) {
      history.replaceState(null, '', lastHash || '#/');
      return;
    }
    const nextRoute = parse();
    const pathChanged = nextRoute.path !== route.path;
    lastHash = window.location.hash;
    route = nextRoute;
    listeners.forEach((l) => l());
    if (focus?.isConnected) {
      if (pathChanged) window.scrollTo({ top: 0 });
      focus.focus();
    } else if (pathChanged) {
      const main = document.getElementById('main');
      if (main) { main.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); }
    }
  });
  window.addEventListener('beforeunload', (e) => { if (dirty.size) { e.preventDefault(); e.returnValue = ''; } });
}

export const useRoute = () => useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => route);

export function navigate(to: string, opts: { replace?: boolean; focus?: HTMLElement } = {}) {
  const hash = `#${to.startsWith('/') ? to : `/${to}`}`;
  if (hash === window.location.hash) return;
  navigationFocus = opts.focus ? { hash, target: opts.focus } : undefined;
  if (opts.replace) { history.replaceState(null, '', hash); window.dispatchEvent(new HashChangeEvent('hashchange')); }
  else window.location.hash = hash;
}

/** Updates query parameters of the current route (filters, tabs) without losing the rest. */
export function setQuery(patch: Record<string, string | null | undefined>) {
  const q = new URLSearchParams(route.query);
  Object.entries(patch).forEach(([k, v]) => (v === null || v === undefined || v === '' ? q.delete(k) : q.set(k, v)));
  const s = q.toString();
  navigate(`${route.path}${s ? `?${s}` : ''}`, { replace: true });
}

/** Registers a form as dirty while `isDirty` is true. */
export function useDirtyGuard(key: string, isDirty: boolean) {
  useEffect(() => {
    if (isDirty) dirty.add(key); else dirty.delete(key);
    return () => { dirty.delete(key); };
  }, [key, isDirty]);
}
