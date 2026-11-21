/**
 * Command engine. A command is a guarded, atomic mutation of the workspace:
 *   authorize (capability + scope) → guard (business preconditions) → run on an Immer draft.
 * If `run` throws a DomainError, nothing is applied. Every command records audit events (RG-39).
 * The UI calls `check` with the same definition to render enabled/disabled actions (RG-12).
 */
import { produce, type Draft } from 'immer';
import { authorize, type Capability } from './permissions';
import type { Actor, AppState, AuditEvent, EntityKind, EntityMap, ID, Ref } from './types';

export class DomainError extends Error {}
export const fail = (reason: string): never => { throw new DomainError(reason); };

export interface Ctx { now: number; actor: Actor; orgId: ID }
export type Guard<P> = (state: AppState, ctx: Ctx, payload: P) => string | null | undefined | false;

export interface CommandDef<P = unknown, R = unknown> {
  name: string;
  /** capability checked through authorize(); omit for demo/preference commands */
  capability?: Capability | ((p: P, s: AppState) => Capability);
  /** project scope used for authorization and archived-project protection */
  project?: (p: P, s: AppState) => ID | undefined;
  /** commands reserved to a human (approvals, publications) — RG-14 */
  humanOnly?: boolean | ((p: P, s: AppState) => boolean);
  /** commands that do not need an active organisation (entry screen, preferences) */
  global?: boolean;
  guard?: Guard<P>;
  run: (d: Draft<AppState>, ctx: Ctx, p: P) => R;
}
export const command = <P, R = void>(def: CommandDef<P, R>) => def;

export type Check = { ok: true } | { ok: false; reason: string };
export type Outcome<R = unknown> = { ok: true; state: AppState; value: R; duplicate?: boolean } | { ok: false; reason: string; state: AppState };

export const nowOf = (s: AppState) => Date.now() + s.demo.timeOffsetMs;
export function ctxOf(s: AppState): Ctx {
  return { now: nowOf(s), actor: s.session.actor, orgId: s.session.orgId ?? '' };
}

export function check<P>(state: AppState, def: CommandDef<P, unknown>, payload: P): Check {
  const ctx = ctxOf(state);
  if (!def.global && !ctx.orgId) return { ok: false, reason: 'Aucune organisation active.' };
  const humanOnly = typeof def.humanOnly === 'function' ? def.humanOnly(payload, state) : def.humanOnly;
  if (humanOnly && ctx.actor.type !== 'human') {
    return { ok: false, reason: 'Action réservée à un humain identifié : une recommandation d’agent ne remplace pas une validation humaine.' };
  }
  if (def.capability) {
    const cap = typeof def.capability === 'function' ? def.capability(payload, state) : def.capability;
    const decision = authorize(state, ctx.actor, cap, { orgId: ctx.orgId, projectId: def.project?.(payload, state) });
    if (!decision.ok) return { ok: false, reason: decision.reason! };
  }
  try {
    const reason = def.guard?.(state, ctx, payload);
    if (reason) return { ok: false, reason };
  } catch (e) {
    if (e instanceof DomainError) return { ok: false, reason: e.message };
    throw e;
  }
  return { ok: true };
}

/** Executes a command atomically. `opId` makes a retried submission idempotent (RG-42). */
export function execute<P, R>(state: AppState, def: CommandDef<P, R>, payload: P, opId?: string): Outcome<R> {
  if (opId && state.appliedOps.includes(opId)) return { ok: true, state, value: undefined as R, duplicate: true };
  const verdict = check(state, def, payload);
  if (!verdict.ok) return { ok: false, reason: verdict.reason, state };
  const ctx = ctxOf(state);
  let value!: R;
  try {
    const next = produce(state, (d) => {
      value = def.run(d, ctx, payload);
      if (opId) d.appliedOps = [...d.appliedOps.slice(-199), opId];
    });
    return { ok: true, state: next, value };
  } catch (e) {
    if (e instanceof DomainError) return { ok: false, reason: e.message, state };
    throw e;
  }
}

/* ----------------------------------------------------------------- helpers */

export function nextId(d: Draft<AppState>, prefix: string): ID {
  d.seq += 1;
  return `${prefix}-${d.seq.toString(36).padStart(4, '0')}`;
}

export function get<K extends EntityKind>(s: AppState | Draft<AppState>, kind: K, id: ID | undefined): EntityMap[K] | undefined {
  return id ? (s.db[kind] as Record<ID, EntityMap[K]>)[id] : undefined;
}

/** Returns the entity if it exists in the active organisation, otherwise fails (RG-01). */
export function must<K extends EntityKind>(s: AppState | Draft<AppState>, kind: K, id: ID | undefined, orgId?: ID): EntityMap[K] {
  const e = get(s, kind, id) as (EntityMap[K] & { orgId?: ID }) | undefined;
  if (!e) return fail('Objet introuvable : il a peut-être été supprimé ou appartient à une autre organisation.');
  if (orgId && e.orgId && e.orgId !== orgId) return fail("Cet objet n’appartient pas à l’organisation active.");
  return e;
}

export function list<K extends EntityKind>(s: AppState, kind: K, orgId?: ID | null): EntityMap[K][] {
  const all = Object.values(s.db[kind]) as (EntityMap[K] & { orgId?: ID })[];
  return orgId ? all.filter((e) => e.orgId === orgId) : all;
}

export function insert<K extends EntityKind>(d: Draft<AppState>, kind: K, entity: EntityMap[K] & { id: ID }): EntityMap[K] {
  (d.db[kind] as Record<ID, EntityMap[K]>)[entity.id] = entity;
  return entity;
}

export interface EventSpec {
  action: string;
  summary: string;
  object: Ref;
  projectId?: ID;
  justification?: string;
  related?: Ref[];
  provenance?: AuditEvent['provenance'];
  compensates?: ID;
  actor?: Actor;
}
export function emit(d: Draft<AppState>, ctx: Ctx, e: EventSpec): ID {
  const id = nextId(d, 'evt');
  d.db.event[id] = {
    id,
    orgId: ctx.orgId,
    projectId: e.projectId,
    at: ctx.now,
    actor: e.actor ?? ctx.actor,
    action: e.action,
    summary: e.summary,
    object: e.object,
    provenance: e.provenance ?? 'local',
    justification: e.justification,
    related: e.related ?? [],
    compensates: e.compensates,
  };
  return id;
}

export const actorUserId = (ctx: Ctx): ID | null => (ctx.actor.type === 'human' ? ctx.actor.userId : null);
export function requireHuman(ctx: Ctx): ID {
  return actorUserId(ctx) ?? fail('Action réservée à un humain identifié.');
}

export const DAY = 86_400_000;

/** Deep copy usable on Immer drafts (structuredClone rejects proxies). */
export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;
