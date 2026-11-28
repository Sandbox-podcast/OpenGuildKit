import type { AppState, DB, EntityKind } from './types';

export const SCHEMA_VERSION = 4;

const KINDS: EntityKind[] = [
  'member',
  'product',
  'project',
  'relation',
  'blueprint',
  'rule',
  'applicability',
  'collection',
  'pack',
  'expert',
  'skill',
  'council',
  'decision',
  'quest',
  'task',
  'deliverable',
  'control',
  'run',
  'result',
  'evidence',
  'finding',
  'approval',
  'exception',
  'competitor',
  'source',
  'signal',
  'opportunity',
  'share',
  'integration',
  'review',
  'event',
];

export const emptyDb = (): DB => Object.fromEntries(KINDS.map((k) => [k, {}])) as unknown as DB;

export function emptyState(): AppState {
  return {
    schema: SCHEMA_VERSION,
    seq: 0,
    orgs: {},
    users: {},
    db: emptyDb(),
    catalogue: { added: [], history: {}, proposals: [], favorites: {} },
    session: { orgId: null, actor: { type: 'system' }, projectId: null },
    prefs: {
      mode: 'explorer',
      motion: 'system',
      sound: false,
      textScale: 1,
      favoriteProjects: [],
      readNotifications: [],
      guideOpen: false,
    },
    demo: { timeOffsetMs: 0, nextFailure: null },
    drafts: {},
    appliedOps: [],
  };
}
