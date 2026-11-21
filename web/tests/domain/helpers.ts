import { expect } from 'vitest';
import { check, execute, type CommandDef } from '@/domain/engine';
import { cmd } from '@/domain/commands';
import { emptyState } from '@/domain/state';
import type { Actor, AppState } from '@/domain/types';

export const human = (userId: string): Actor => ({ type: 'human', userId });
export const agent = (key: string): Actor => ({ type: 'agent', expertId: `exp-org-nova-${key}` });

export function as(s: AppState, actor: Actor): AppState {
  return { ...s, session: { ...s.session, actor } };
}

/** Runs a command and fails the test with the domain reason when it is refused. */
export function run<P, R>(s: AppState, def: CommandDef<P, R>, payload: P, actor?: Actor): [AppState, R] {
  const out = execute(actor ? as(s, actor) : s, def, payload);
  if (!out.ok) throw new Error(`${def.name} refusé : ${out.reason}`);
  return [actor ? { ...out.state, session: s.session } : out.state, out.value];
}
export const ok = <P, R>(s: AppState, def: CommandDef<P, R>, payload: P, actor?: Actor) => run(s, def, payload, actor)[0];

/** Asserts that a command is refused and returns the reason shown to the user. */
export function refused<P, R>(s: AppState, def: CommandDef<P, R>, payload: P, actor?: Actor): string {
  const st = actor ? as(s, actor) : s;
  const verdict = check(st, def, payload);
  const out = execute(st, def, payload);
  expect(out.ok).toBe(false);
  expect(verdict.ok).toBe(false);
  expect(out.state).toBe(st);
  return (out as { reason: string }).reason;
}

export function nova(): AppState {
  return ok(emptyState(), cmd.loadDemo, {});
}

export function ticks(s: AppState, n = 8): AppState {
  let cur = s;
  for (let i = 0; i < n; i++) cur = ok(cur, cmd.tick, {});
  return cur;
}

export const latest = <T extends { id: string }>(table: Record<string, T>, pred: (x: T) => boolean): T | undefined =>
  Object.values(table).filter(pred).sort((a, b) => a.id.localeCompare(b.id)).at(-1);
