/**
 * Interactive kingdom map. Places and territories are real buttons/links over a decorative
 * terrain; every badge is derived from objects and opens the exact item it reports.
 */
import { useAppState } from '@/app/store';
import { routeOf } from '@/app/router';
import { PLACES, placeCounts } from '@/app/places';
import { list } from '@/domain/engine';
import { latestResults, objectLabel } from '@/domain/selectors';
import { buildingSprite, cottageSprite, territoryAccent } from '@/shared/pixel/buildings';
import { mapHeight, MAP_W, PLACE_POS, terrainUrl, territoryRect } from '@/shared/pixel/terrain';
import { Icon } from '@/shared/pixel/icons';
import type { ID, Ref } from '@/domain/types';

const pct = (v: number, of: number) => `${(v / of) * 100}%`;

export function KingdomMap({ selected, onSelect }: { selected: string | null; onSelect: (key: string) => void }) {
  const s = useAppState();
  const counts = placeCounts(s);
  const orgId = s.session.orgId;
  const products = list(s, 'product', orgId).sort((a, b) => a.territory - b.territory);
  const projects = list(s, 'project', orgId);
  const runs = list(s, 'run', orgId);
  const forging = runs.some((r) => r.status === 'running');
  const councilLive = list(s, 'council', orgId).some((c) => c.status === 'running');
  const terrain = terrainUrl(products.map((p) => ({ color: territoryAccent(p.color), archived: !projects.some((x) => x.productId === p.id && x.status === 'active') })));
  const height = mapHeight(products.length);
  const results = latestResults(s);
  const findings = list(s, 'finding', orgId);
  const quests = list(s, 'quest', orgId);

  const alertsFor = (productId: ID): { ref: Ref; label: string }[] => {
    const pids = new Set(projects.filter((p) => p.productId === productId).map((p) => p.id));
    const out: { ref: Ref; label: string }[] = [];
    results.filter((r) => pids.has(r.projectId) && r.outcome === 'failed').forEach((r) => {
      const f = findings.find((x) => x.resultId === r.id && x.status !== 'resolved');
      out.push({ ref: f ? { kind: 'finding', id: f.id } : { kind: 'result', id: r.id }, label: f ? `Constat : ${f.title}` : objectLabel(s, { kind: 'result', id: r.id }) });
    });
    quests.filter((q) => pids.has(q.projectId) && q.status === 'blocked').forEach((q) => out.push({ ref: { kind: 'quest', id: q.id }, label: `Quête bloquée : ${q.title}` }));
    runs.filter((r) => pids.has(r.projectId) && r.status === 'error').forEach((r) => out.push({ ref: { kind: 'run', id: r.id }, label: `Erreur d’exécution : ${r.title}` }));
    return out;
  };

  return (
    <div className="map-scroll" role="region" aria-label="Carte interactive" tabIndex={0}>
    <div className="kingdom-map" style={{ aspectRatio: `${MAP_W} / ${height}` }}>
      <img className="pixel map-terrain" src={terrain} alt="" aria-hidden draggable={false} />
      {PLACES.map((p) => {
        const pos = PLACE_POS[p.key];
        const sp = buildingSprite(p.key);
        const c = counts[p.key];
        const busy = (p.key === 'forge' && forging) || (p.key === 'conseil' && councilLive);
        return (
          <a key={p.key} className={`map-place ${busy ? 'busy' : ''}`} data-place={p.key} href={`#${p.route}`}
            style={{ left: pct(pos.x, MAP_W), top: pct(pos.y, height), width: pct(sp.w, MAP_W), height: pct(sp.h, height) }}
            aria-label={`${p.name}, ${p.role}${c ? ` (${c.n} ${c.label})` : ''}`}>
            <img className="pixel" src={sp.url} alt="" draggable={false} />
            {busy && p.key === 'forge' && <span className="map-smoke" aria-hidden />}
            {busy && p.key === 'conseil' && <span className="map-glow" aria-hidden />}
            <span className="map-label" aria-hidden="true">{p.name}</span>
            {c && <span className={`map-count ${c.tone}`} aria-hidden>{c.n}</span>}
          </a>
        );
      })}
      {products.map((prd, i) => {
        const r = territoryRect(i, products.length);
        const mine = projects.filter((x) => x.productId === prd.id);
        const alerts = alertsFor(prd.id);
        const accent = territoryAccent(prd.color);
        return (
          <div key={prd.id} className={`map-territory ${selected === prd.id ? 'selected' : ''}`} style={{ left: pct(r.x, MAP_W), top: pct(r.y, height), width: pct(r.w, MAP_W), height: pct(r.h, height) }}>
            <button className="territory-name pixel-font" style={{ borderColor: accent }} onClick={() => onSelect(prd.id)} aria-pressed={selected === prd.id} aria-label={`Territoire ${prd.name} : ${mine.length} projet(s)${alerts.length ? `, ${alerts.length} alerte(s)` : ''}`}>{prd.name}</button>
            <div className="territory-houses">
              {mine.map((pr) => {
                const sp = cottageSprite(accent, pr.status === 'archived');
                return (
                  <a key={pr.id} href={`#/projets/${pr.id}`} className="map-house" title={`${pr.name}${pr.status === 'archived' ? ' (archivé)' : ''}`} aria-label={`Projet ${pr.name}${pr.status === 'archived' ? ', archivé' : ''}`} style={{ width: `${(sp.w / r.w) * 100}%` }}>
                    <img className="pixel" src={sp.url} alt="" draggable={false} />
                  </a>
                );
              })}
            </div>
            {alerts.length > 0 && (
              <a className="map-alert" href={`#${routeOf(alerts[0].ref)}`} title={alerts.map((a) => a.label).join('\n')} aria-label={`${alerts.length} alerte(s) sur ${prd.name} : ${alerts[0].label}`}>
                <Icon name="warn" size={12} />{alerts.length}
              </a>
            )}
          </div>
        );
      })}
    </div>
    </div>
  );
}
