/** Project data every place reads, loaded in one batch and kept in the shared cache. */
import { useCallback } from 'react';
import { ApiError, batch, cliMessage, readJson, type CliResult } from './api';
import { useCli, useQuery, type Query } from './query';
import type { AlertRegister, Brain, Guard, HostControl, MarketDue, Profile, Share, StaleTask, TaskListItem, Update } from './types';
import type { PlaceKey } from '@/shared/pixel/buildings';
import { isBlocked, shareState } from './labels';

export const ARGV = {
  tasks: ['task', 'list', '--json'],
  check: ['check'],
  alerts: ['alerts', 'list', '--json'],
  shares: ['docs', 'share', 'list', '--json'],
  due: ['market', 'due', '--all', '--json'],
  update: ['update', '--json'],
  host: ['host', 'check', '--json'],
  guard: ['guard', '--json'],
  brains: ['brains', '--json'],
} as const satisfies Record<string, string[]>;

/** One part of the overview batch: its JSON, or the command's failure. */
function useOverviewPart<T>(name: OverviewPart): Query<T> {
  const overview = useOverview();
  const r = overview.data?.[name];
  const failed = r && (r.code !== 0 || r.json == null);
  return {
    data: r && !failed ? r.json as T : undefined,
    error: failed ? new ApiError(cliMessage(r), 200, r.command ?? null, r) : overview.error,
    loading: overview.data === undefined && !overview.error,
    reload: overview.reload,
  };
}

export const useTasks = () => useOverviewPart<TaskListItem[]>('tasks');
export const useAlerts = () => useOverviewPart<AlertRegister>('alerts');
export const useShares = () => useOverviewPart<Share[]>('shares');
export const useMarketDue = () => useOverviewPart<MarketDue>('due');
export const useUpdate = () => useOverviewPart<Update>('update');
export const useHost = () => useOverviewPart<HostControl[]>('host');
/** The brains only change with the catalog: kept out of the overview, which reloads after each action. */
export const useBrains = () => useCli<Record<string, Brain>>([...ARGV.brains]);
export const useGuard = () => useCli<Guard>([...ARGV.guard]);
/** `check` answers through its exit code: the full result, success or not. */
export function useCheck(): Query<CliResult> {
  const overview = useOverview();
  return { data: overview.data?.check, error: overview.error, loading: overview.data === undefined && !overview.error, reload: overview.reload };
}

export function useProfile() {
  return useQuery<Profile | null>('file:profile', useCallback(async () => {
    try { return await readJson<Profile>('.openguildkit/project.json'); } catch { return null; }
  }, []));
}

export const boardTitle = (brains: Record<string, Brain> | undefined, id: string) => brains?.[id]?.title ?? id;

const OVERVIEW = ['tasks', 'check', 'alerts', 'shares', 'due', 'update', 'host'] as const;
type OverviewPart = (typeof OVERVIEW)[number];

/**
 * One request for what the shell and most places read: after an action, it is the only one to reload them.
 * Failures stay per command (an empty project has no market dossier).
 */
export function useOverview() {
  return useQuery<Record<string, CliResult>>('overview', useCallback(() => batch(Object.fromEntries(OVERVIEW.map((name) => [name, [...ARGV[name]]]))), []));
}

type Count = { n: number; tone: 'danger' | 'warning' | 'info'; label: string };
const count = (n: number, tone: Count['tone'], one: string, many = one): Count | null => (n > 0 ? { n, tone, label: n === 1 ? one : many } : null);

export interface ProjectSignals {
  tasks: TaskListItem[];
  checkFailed: boolean;
  alertsOpen: number;
  sharesExpired: number;
  marketDue: number;
  updates: number;
  staleTasks: StaleTask[];
  hostMissing: number;
  blocked: TaskListItem[];
  awaitingDecision: TaskListItem[];
  toBuild: TaskListItem[];
}

export function signalsOf(overview: Record<string, CliResult> | undefined): ProjectSignals {
  const json = <T,>(key: string, fallback: T): T => (overview?.[key]?.code === 0 && overview[key].json != null ? overview[key].json as T : fallback);
  const tasks = json<TaskListItem[]>('tasks', []);
  const alerts = json<AlertRegister | null>('alerts', null);
  const update = json<Update | null>('update', null);
  return {
    tasks,
    checkFailed: !!overview?.check && overview.check.code !== 0,
    alertsOpen: (alerts?.summary.by_status.open ?? 0) + (alerts?.summary.by_status.confirmed ?? 0),
    sharesExpired: json<Share[]>('shares', []).filter((s) => shareState(s.state) === 'expired').length,
    marketDue: json<MarketDue | null>('due', null)?.due.length ?? 0,
    updates: update?.changes.length ?? 0,
    staleTasks: update?.stale_tasks ?? [],
    hostMissing: json<HostControl[]>('host', []).filter((c) => c.status === 'missing').length,
    blocked: tasks.filter((t) => isBlocked(t.next)),
    awaitingDecision: tasks.filter((t) => t.status === 'reviewed' && !isBlocked(t.next)),
    toBuild: tasks.filter((t) => t.status === 'approved'),
  };
}

export function placeCounts(s: ProjectSignals): Partial<Record<PlaceKey, Count | null>> {
  const consulting = s.tasks.filter((t) => t.status === 'consulting' || t.status === 'changes-requested').length;
  return {
    blueprint: count(s.checkFailed ? 1 : 0, 'danger', 'instructions à synchroniser'),
    conseil: count(consulting + s.awaitingDecision.length, 'info', 'à arbitrer'),
    quetes: count(s.blocked.length, 'danger', 'bloquée', 'bloquées'),
    forge: count(s.toBuild.length, 'info', 'quête à réaliser', 'quêtes à réaliser'),
    tour: count(s.alertsOpen, 'danger', 'alerte à revoir', 'alertes à revoir'),
    observatoire: count(s.marketDue, 'info', 'source à relire', 'sources à relire'),
    documentation: count(s.sharesExpired, 'danger', 'partage expiré', 'partages expirés'),
    intendance: count(s.updates + s.hostMissing, 'warning', 'réglage à revoir', 'réglages à revoir'),
  };
}
