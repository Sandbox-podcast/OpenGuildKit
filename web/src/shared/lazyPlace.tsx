/**
 * A place loaded on demand that can also be preloaded. Once its module is there, the place renders
 * directly instead of suspending: React 19 holds a suspended screen for about 300 ms before showing it,
 * which a person feels on every change of place.
 */
import { lazy, type ComponentType } from 'react';

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- INTENTIONAL(#522): places take different props
type AnyProps = any;
export type Place = ComponentType<AnyProps> & { preload: () => Promise<unknown> };

export function lazyPlace<M>(load: () => Promise<M>, key: keyof M): Place {
  let loaded: ComponentType<AnyProps> | null = null;
  let pending: Promise<unknown> | null = null;
  const preload = () => (pending ??= load().then((m) => { loaded = m[key] as ComponentType<AnyProps>; }));
  const Lazy = lazy(async () => { await preload(); return { default: loaded! }; });
  const Wrapper = ((props: AnyProps) => {
    const Component = loaded;
    return Component ? <Component {...props} /> : <Lazy {...props} />;
  }) as Place;
  Wrapper.preload = preload;
  return Wrapper;
}

/** Loads the given places once the browser is idle, one after the other. */
export function preloadWhenIdle(places: Place[]) {
  const idle = (cb: () => void) => (typeof window.requestIdleCallback === 'function' ? window.requestIdleCallback(cb, { timeout: 2000 }) : setTimeout(cb, 300));
  idle(() => { places.reduce((chain, place) => chain.then(() => place.preload()).catch(() => undefined), Promise.resolve() as Promise<unknown>); });
}
