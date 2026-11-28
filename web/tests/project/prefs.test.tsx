// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { detectSession } from '@/project/api';
import { adoptServerPrefs, rememberName, rememberedName, setPrefs, usePrefs } from '@/project/prefs';
import { setSingleKeyShortcuts, useSingleKeyShortcuts } from '@/shared/shortcuts';
import { cleanup, mount, wait } from './views/harness';

afterEach(cleanup);

/** A fake server that hands out `kept` in its session and records every body sent to /api/prefs. */
async function server(kept: Record<string, string>) {
  const saved: unknown[] = [];
  const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } });
  vi.stubGlobal('fetch', async (input: string, init?: RequestInit) => {
    if (input.endsWith('/api/session'))
      return json({
        app: 'openguildkit-ui',
        version: '0',
        token: 't',
        project: { root: '/p', name: 'P', initialized: true },
        prefs: kept,
        human_only: [],
      });
    const body = JSON.parse(String(init?.body));
    saved.push(body.prefs);
    return json({ prefs: { ...kept, ...body.prefs } });
  });
  const session = await detectSession();
  return { session: session!, saved };
}

function Shown() {
  const prefs = usePrefs();
  const single = useSingleKeyShortcuts();
  return <p>{`${prefs.mode} ${prefs.motion} ${single ? 'on' : 'off'}`}</p>;
}

describe('preferences kept by the project', () => {
  /** Issue #463: a new launch is a new origin, whose storage is empty: the page came back in RPG, with its animations. */
  it('opens with what the project kept, without sending it back', async () => {
    const { session, saved } = await server({ mode: 'focus', motion: 'reduced', shortcuts: 'off', decider: 'Camille' });
    adoptServerPrefs(session.prefs!);
    const { container } = await mount(<Shown />);
    expect(container.textContent).toBe('focus reduced off');
    expect(rememberedName('decider')).toBe('Camille');
    expect(saved).toEqual([]);
  });

  it('sends each change to the project, a typed name once the typing pauses', async () => {
    vi.useFakeTimers();
    try {
      const { session, saved } = await server({});
      adoptServerPrefs(session.prefs!);
      setPrefs({ mode: 'explorer' });
      setSingleKeyShortcuts(true);
      for (const name of ['C', 'CM']) rememberName('signer', name);
      rememberName('filter', 'not a preference');
      await vi.advanceTimersByTimeAsync(700);
      expect(saved).toEqual([{ mode: 'explorer' }, { shortcuts: 'on' }, { signer: 'CM' }]);
    } finally {
      vi.useRealTimers();
    }
    await wait();
  });
});
