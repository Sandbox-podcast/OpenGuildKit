/**
 * What the tests of components share: a fake local API behind `fetch`, a mount that waits for React, and the gestures
 * of a person (typing, clicking). No browser and no server: happy-dom stands in for the page.
 */
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { vi } from 'vitest';
import { detectSession, type CliResult } from '@/project/api';
import { invalidate } from '@/project/query';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** The result of a command that printed `json`. */
export const ok = (json: unknown): CliResult => ({ code: 0, stdout: JSON.stringify(json), stderr: '', json });

export interface FakeApi {
  /** Every command the page sent to /api/run, one string each (`task route closing-survey --reason …`), batches included. */
  commands: string[];
  /** The commands that start with `prefix`. */
  sent: (prefix: string) => string[];
}

/**
 * Installs the fake API. `commands` answers by the start of the command line (`task route`), the longest start first,
 * with a value or a function of the arguments and the uploaded files; `files` answers the project files the page reads.
 * A command nobody answers fails the test.
 */
export async function fakeApi(commands: Record<string, unknown>, files: Record<string, string> = {}): Promise<FakeApi> {
  const sent: string[] = [];
  const answer = (argv: string[], uploads: Record<string, string> = {}): CliResult => {
    const line = argv.join(' ');
    sent.push(line);
    const start = Object.keys(commands)
      .filter((prefix) => line.startsWith(prefix))
      .sort((a, b) => b.length - a.length)[0];
    if (start === undefined) throw new Error(`the fake API has no answer for: ${line}`);
    const value = commands[start];
    return ok(typeof value === 'function' ? value(argv, uploads) : value);
  };
  const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
  vi.stubGlobal('fetch', async (input: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (input.endsWith('/api/session'))
      return json({
        app: 'openguildkit-ui',
        version: '0.0.0-test',
        token: 'test',
        project: { root: '/tmp/portal', name: 'Portail support', initialized: true },
        human_only: [],
      });
    if (input.endsWith('/api/files/read')) return json({ path: body.path, text: files[body.path] ?? null });
    if (input.endsWith('/api/files/list')) return json({ entries: [] });
    if (body.batch)
      return json({
        results: Object.fromEntries(Object.entries(body.batch as Record<string, string[]>).map(([name, argv]) => [name, answer(argv)])),
      });
    return json(answer(body.argv, body.uploads));
  });
  await detectSession();
  return { commands: sent, sent: (prefix) => sent.filter((line) => line.startsWith(prefix)) };
}

export interface Mounted {
  container: HTMLElement;
  root: Root;
  unmount: () => Promise<void>;
}
const mounted: Mounted[] = [];

/** Renders `ui` into the page and lets its first effects and requests settle. */
export async function mount(ui: ReactNode): Promise<Mounted> {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(ui);
  });
  const handle: Mounted = {
    container,
    root,
    unmount: async () => {
      await act(async () => root.unmount());
      container.remove();
    },
  };
  mounted.push(handle);
  return handle;
}

/** Unmounts what the test mounted, marks the cache of answers stale for the next test, and removes the fake API. */
export async function cleanup() {
  for (const handle of mounted.splice(0)) await handle.unmount();
  invalidate();
  vi.unstubAllGlobals();
  vi.useRealTimers();
}

/** Lets time pass, on the fake clock when the test installed one, and the requests that follow settle. */
export const wait = (ms = 0) =>
  act(async () => {
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(ms);
    else await new Promise((resolve) => setTimeout(resolve, ms));
  });

/** The field a label names: the input, textarea or select its `for` points to, or the one inside it; else an `aria-label`. */
export function field(container: ParentNode, label: string | RegExp): HTMLInputElement & HTMLTextAreaElement & HTMLSelectElement {
  const named = [...container.querySelectorAll('label')].find((l) =>
    typeof label === 'string' ? l.textContent?.trim() === label : label.test(l.textContent ?? ''),
  );
  const labelled = typeof label === 'string' ? container.querySelector(`[aria-label="${label}"]`) : null;
  if (!named && labelled) return labelled as never;
  if (!named) throw new Error(`no label ${String(label)}`);
  const target = named.htmlFor ? document.getElementById(named.htmlFor) : named.querySelector('input, textarea, select');
  if (!target) throw new Error(`label ${String(label)} names no field`);
  return target as never;
}

/** The first button whose text is `name` (or matches it). */
export function button(container: ParentNode, name: string | RegExp): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')].find((b) =>
    typeof name === 'string' ? b.textContent?.trim() === name : name.test(b.textContent ?? ''),
  );
  if (!found) throw new Error(`no button ${String(name)}`);
  return found;
}

/** Types `text` into a field as one change, the way a paste does. */
export async function type(element: HTMLInputElement | HTMLTextAreaElement, text: string) {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const set = Object.getOwnPropertyDescriptor(prototype, 'value')!.set!;
  await act(async () => {
    set.call(element, text);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

export const click = (element: HTMLElement) =>
  act(async () => {
    element.click();
  });
