/** Places, their business roles and their navigation counters. */
import { PLACES, PLACE_GROUPS, type Place } from '@/shared/places';
import type { PlaceKey } from '@/shared/pixel/buildings';
import { kingdomStats, notifications } from '@/demo/domain/selectors';
import { list } from '@/demo/domain/engine';
import type { AppState } from '@/demo/domain/types';

type PlaceCount = { n: number; tone: 'danger' | 'warning' | 'info'; label: string };


const count = (n: number, tone: PlaceCount['tone'], singular: string, plural = singular): PlaceCount | null =>
  n > 0 ? { n, tone, label: n === 1 ? singular : plural } : null;


export function placeCounts(s: AppState, notices = notifications(s)): Partial<Record<PlaceKey, PlaceCount | null>> {
  const stats = kingdomStats(s);
  const runs = list(s, 'run', s.session.orgId).filter((r) => r.status === 'running' || r.status === 'error').length;
  const signals = list(s, 'signal', s.session.orgId).filter((signal) => signal.reevaluation === 'proposed').length;
  return {
    blueprint: count(stats.unknowns.length, 'warning', 'inconnue', 'inconnues'),
    conseil: count(stats.pendingDecisions.length + stats.awaitingCouncils.length, 'info', 'à arbitrer'),
    quetes: count(stats.blockedQuests.length, 'danger', 'bloquée', 'bloquées'),
    forge: count(runs, 'info', 'exécution à suivre', 'exécutions à suivre'),
    tour: count(stats.failed.length + stats.stale.length, 'danger', 'contrôle à revoir', 'contrôles à revoir'),
    observatoire: count(signals, 'info', 'signal à évaluer', 'signaux à évaluer'),
    intendance: count(notices.filter((notice) => notice.id.startsWith('int:')).length, 'warning', 'intégration en alerte', 'intégrations en alerte'),
  };
}
export const placeOf = (path: string) => PLACES.find((p) => path.startsWith(p.route)) ?? (path.startsWith('/projets') ? PLACES[0] : path.startsWith('/decisions') ? PLACES[3] : undefined);


export { PLACES, PLACE_GROUPS, type Place };
