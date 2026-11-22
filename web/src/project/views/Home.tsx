/** Royaume: the project at a glance, what waits on whom, and the map of places with their counters. */
import { useMemo } from 'react';
import { PLACES } from '@/shared/places';
import { buildingSprite, cottageSprite } from '@/shared/pixel/buildings';
import { mapHeight, MAP_W, PLACE_POS, terrainUrl, territoryRect } from '@/shared/pixel/terrain';
import { Icon, type PixelIconName } from '@/shared/pixel/icons';
import { Badge, Button, KV, Panel, Stat } from '@/shared/ui/core';
import { placeCounts, signalsOf, useOverview, useProfile, type ProjectSignals } from '../data';
import { usePrefs } from '../prefs';
import { useAction } from '../query';
import { RESEARCH, TASK_ORDER, isDone, nextLabel, taskStatus } from '../labels';
import { TaskStatusBadge } from '../parts';
import type { Profile, TaskListItem } from '../types';

const pct = (v: number, of: number) => `${(v / of) * 100}%`;
const HOUSE: Record<string, string> = { draft: '#8fa39b', consulting: '#7fd6ff', 'changes-requested': '#ffc46b', reviewed: '#b9a7ff', approved: '#6EF7C4', done: '#6EF7C4', 'done-with-reservations': '#ffc46b' };

function ProjectMap({ profile, signals }: { profile: Profile | null; signals: ProjectSignals }) {
  const counts = placeCounts(signals);
  const territories = [{ id: 'project', name: profile?.name ?? 'Projet' }, ...(profile?.components ?? []).slice(0, 7).map((c) => ({ id: c.path, name: c.id ?? c.path }))];
  const height = mapHeight(territories.length);
  const terrain = terrainUrl(territories.map(() => ({ color: '#6EF7C4', archived: false })));
  const houses = signals.tasks.slice(0, 12);
  return (
    <div className="map-scroll" role="region" aria-label="Carte du projet" tabIndex={0}>
      <div className="kingdom-map" style={{ aspectRatio: `${MAP_W} / ${height}` }}>
        <img className="pixel map-terrain" src={terrain} alt="" aria-hidden draggable={false} />
        {PLACES.map((p) => {
          const pos = PLACE_POS[p.key];
          const sp = buildingSprite(p.key);
          const c = counts[p.key];
          return (
            <a key={p.key} className="map-place" data-place={p.key} href={`#${p.route}`}
              style={{ left: pct(pos.x, MAP_W), top: pct(pos.y, height), width: pct(sp.w, MAP_W), height: pct(sp.h, height) }}
              aria-label={`${p.name}${c ? ` (${c.n} ${c.label})` : ''}`}>
              <img className="pixel" src={sp.url} alt="" draggable={false} />
              <span className="map-label" aria-hidden="true">{p.name}</span>
              {c && <span className={`map-count ${c.tone}`} aria-hidden>{c.n}</span>}
            </a>
          );
        })}
        {territories.map((t, i) => {
          const r = territoryRect(i, territories.length);
          return (
            <div key={t.id} className="map-territory" style={{ left: pct(r.x, MAP_W), top: pct(r.y, height), width: pct(r.w, MAP_W), height: pct(r.h, height) }}>
              <span className="territory-name pixel-font" style={{ borderColor: '#6EF7C4' }} title={i === 0 ? 'Le projet ouvert par le serveur' : `Composant ${t.id}`}>{t.name}</span>
              {i === 0 && <div className="territory-houses">
                {houses.map((task) => {
                  const sp = cottageSprite(HOUSE[task.status] ?? '#8fa39b', isDone(task.status));
                  return <a key={task.id} href={`#/quetes/${task.id}`} className="map-house" title={`${task.id} : ${taskStatus(task.status).rpg}`} aria-label={`Quête ${task.id}, ${taskStatus(task.status).label}`} style={{ width: `${(sp.w / r.w) * 100}%` }}>
                    <img className="pixel" src={sp.url} alt="" draggable={false} />
                  </a>;
                })}
              </div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface Todo { id: string; who: 'person' | 'agent'; icon: PixelIconName; title: string; detail: string; to: string; tone: 'danger' | 'warning' | 'info' | 'ai' }

function todos(s: ProjectSignals): Todo[] {
  const out: Todo[] = [];
  if (s.checkFailed) out.push({ id: 'check', who: 'person', icon: 'warn', title: 'Instructions à synchroniser', detail: 'AGENTS.md, les réglages de l’hôte ou le verrou du catalogue ne correspondent plus au profil.', to: '/intendance', tone: 'danger' });
  s.blocked.forEach((t) => out.push({ id: `b:${t.id}`, who: 'person', icon: 'ban', title: `Lever les blocages de ${t.id}`, detail: nextLabel(t.next), to: `/conseil/${t.id}#blocages`, tone: 'danger' }));
  s.awaitingDecision.forEach((t) => out.push({ id: `d:${t.id}`, who: 'person', icon: 'lock', title: `Décider de ${t.id}`, detail: 'Les avis sont rendus : validez dans votre terminal ou renvoyez au Conseil.', to: `/conseil/${t.id}#decision`, tone: 'warning' }));
  s.tasks.filter((t) => t.status === 'draft').forEach((t) => out.push({ id: `q:${t.id}`, who: 'person', icon: 'question', title: `Cadrer ${t.id}`, detail: nextLabel(t.next), to: `/conseil/${t.id}`, tone: 'info' }));
  s.tasks.filter((t) => t.status === 'changes-requested').forEach((t) => out.push({ id: `r:${t.id}`, who: 'person', icon: 'replace', title: `Reprendre ${t.id}`, detail: nextLabel(t.next), to: `/conseil/${t.id}`, tone: 'warning' }));
  s.tasks.filter((t) => t.status === 'consulting').forEach((t) => out.push({ id: `c:${t.id}`, who: 'agent', icon: 'council', title: `Avis attendus sur ${t.id}`, detail: nextLabel(t.next), to: `/conseil/${t.id}`, tone: 'ai' }));
  s.toBuild.forEach((t) => out.push({ id: `f:${t.id}`, who: 'agent', icon: 'anvil', title: `Réaliser ${t.id}`, detail: nextLabel(t.next), to: `/forge/${t.id}`, tone: 'ai' }));
  if (s.alertsOpen) out.push({ id: 'alerts', who: 'person', icon: 'shield', title: `${s.alertsOpen} alerte(s) de dépendance à revoir`, detail: 'Confirmez, écartez avec un motif, ou ouvrez une quête de correctif.', to: '/tour/alertes', tone: 'danger' });
  if (s.sharesExpired) out.push({ id: 'shares', who: 'person', icon: 'link', title: `${s.sharesExpired} partage(s) expiré(s)`, detail: 'Retirez l’accès dans Documentalist, puis enregistrez le retrait.', to: '/documentation/partages', tone: 'danger' });
  if (s.marketDue) out.push({ id: 'market', who: 'agent', icon: 'telescope', title: `${s.marketDue} source(s) de veille à relire`, detail: 'Selon la politique de recherche du projet.', to: '/observatoire', tone: 'info' });
  if (s.updates) out.push({ id: 'update', who: 'person', icon: 'download', title: `${s.updates} évolution(s) du catalogue installé`, detail: 'Comparez règle par règle, puis adoptez-les.', to: '/intendance/catalogue', tone: 'warning' });
  if (s.hostMissing) out.push({ id: 'host', who: 'person', icon: 'key', title: `${s.hostMissing} réglage(s) d’hôte manquant(s)`, detail: 'openguildkit host apply écrit les réglages de Claude Code ou Codex.', to: '/intendance/hote', tone: 'warning' });
  return out;
}

export function Home() {
  const overview = useOverview();
  const profile = useProfile();
  const { mode } = usePrefs();
  const signals = useMemo(() => signalsOf(overview.data), [overview.data]);
  const list = todos(signals);
  const { act, busy } = useAction();
  const byStatus = TASK_ORDER.map((status) => ({ status, n: signals.tasks.filter((t) => t.status === status).length }));
  const p = profile.data;

  return (
    <div className="page-grid">
      {mode === 'explorer' && <ProjectMap profile={p ?? null} signals={signals} />}
      <div className="grid-2">
        <Panel title={<><Icon name="flag" size={16} /> À faire maintenant</>} actions={signals.checkFailed ? <Button size="small" variant="primary" busy={busy !== null} onClick={() => void act(['sync'], { success: 'Instructions synchronisées' })}>Synchroniser</Button> : undefined}>
          {overview.data === undefined ? <p className="muted">Lecture du projet…</p> : list.length === 0
            ? <p className="muted">Rien n’attend. Ouvrez une quête pour la prochaine demande.</p>
            : <ul className="plain stack tight todo-list">{list.map((t) => (
              <li key={t.id}><a className={`card todo tone-${t.tone}`} href={`#${t.to}`}>
                <Icon name={t.icon} size={16} />
                <span className="grow"><strong>{t.title}</strong><span className="small muted block">{t.detail}</span></span>
                <Badge tone={t.who === 'person' ? 'warning' : 'ai'} icon={t.who === 'person' ? 'user' : 'ai'}>{t.who === 'person' ? 'Vous' : 'Agent'}</Badge>
              </a></li>
            ))}</ul>}
        </Panel>
        <Panel title={<><Icon name="crown" size={16} /> {p?.name ?? 'Projet'}</>} actions={<a className="btn small" href="#/blueprint">Profil et règles</a>}>
          {p ? <KV items={[
            ['Secteur', p.sector ?? 'general'],
            ['Pile', (p.stack ?? []).join(', ') || '—'],
            ['Composants', p.components?.length ? p.components.map((c) => c.path).join(', ') : 'un seul'],
            ['Packs de règles', String(p.packs?.length ?? 0)],
            ['Cerveaux activés', p.boards?.length ? String(p.boards.length) : 'tous'],
            ['Recherche', RESEARCH[p.research ?? 'local-only']],
            ['Hôte', p.host ?? 'non défini'],
            ['Approbation', p.approval?.mode === 'signed' ? 'signée (SSH)' : 'au terminal'],
          ]} /> : <p className="muted">Lecture du profil…</p>}
        </Panel>
      </div>
      <Panel title={<><Icon name="quest" size={16} /> Quêtes par état</>} actions={<a className="btn small primary" href="#/quetes?nouvelle=1"><Icon name="plus" size={14} /> Nouvelle quête</a>}>
        <div className="stats">{byStatus.map(({ status, n }) => <a key={status} href={`#/quetes?statut=${status}`} className="stat-link"><Stat value={n} label={mode === 'explorer' ? taskStatus(status).rpg : taskStatus(status).label} tone={n ? taskStatus(status).tone : 'muted'} /></a>)}</div>
        {signals.tasks.length > 0 && <table className="data compact"><thead><tr><th>Quête</th><th>État</th><th>Prochaine étape</th></tr></thead>
          <tbody>{signals.tasks.slice(0, 8).map((t: TaskListItem) => <tr key={t.id}><td><a className="mono" href={`#/quetes/${t.id}`}>{t.id}</a><span className="small muted block clamp-1">{t.brief}</span></td><td><TaskStatusBadge status={t.status} /></td><td className="small">{nextLabel(t.next)}</td></tr>)}</tbody>
        </table>}
      </Panel>
      <Panel title={<><Icon name="question" size={16} /> Comment la guilde travaille</>}>
        <ol className="loop-steps">
          <li><strong>Une quête</strong> décrit la demande. L’agent la cadre avec vous par le questionnaire.</li>
          <li><strong>Le Conseil</strong> réunit les cerveaux choisis par le routage. Chacun rend un avis indépendant.</li>
          <li><strong>Vous décidez</strong>, dans votre terminal : l’interface ne valide jamais à votre place.</li>
          <li><strong>La Forge</strong> réalise le périmètre validé, lance les vérifications et rapporte les preuves.</li>
        </ol>
      </Panel>
    </div>
  );
}
