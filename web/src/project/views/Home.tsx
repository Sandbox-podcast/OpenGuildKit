/** Royaume: the project at a glance, what waits on whom, and the map of places with their counters. */
import { useMemo } from 'react';
import { PLACES } from '@/shared/places';
import { buildingSprite, cottageSprite } from '@/shared/pixel/buildings';
import { mapHeight, MAP_W, PLACE_POS, terrainUrl, territoryRect } from '@/shared/pixel/terrain';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, KV, Panel, Stat } from '@/shared/ui/core';
import { placeCounts, signalsOf, useOverview, useProfile, type ProjectSignals } from '../data';
import { usePrefs } from '../prefs';
import { useAction } from '../query';
import { RESEARCH, isDone, nextLabel, nextLang, statusesOf, taskStatus } from '../labels';
import { todos } from '../todo';
import { TableBox, TaskStatusBadge } from '../parts';
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
              style={{ left: pct(pos.x, MAP_W), top: pct(pos.y, height), width: pct(sp.w, MAP_W), height: pct(sp.h, height) }}>
              <img className="pixel" src={sp.url} alt="" draggable={false} />
              <span className="map-label">{p.name}</span>
              {c && <><span className={`map-count ${c.tone}`} aria-hidden>{c.n}</span><span className="sr-only"> ({c.n} {c.label})</span></>}
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
                  return <a key={task.id} href={`#/quetes/${task.id}`} className="map-house project-house" title={`${task.id} : ${taskStatus(task.status).rpg}`} aria-label={`Quête ${task.id}, ${taskStatus(task.status).label}`} style={{ width: `${(sp.w / r.w) * 100}%` }}>
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

export function Home() {
  const overview = useOverview();
  const profile = useProfile();
  const { mode } = usePrefs();
  const signals = useMemo(() => signalsOf(overview.data), [overview.data]);
  const list = todos(signals);
  const { act, busy } = useAction();
  const byStatus = statusesOf(signals.tasks).map((status) => ({ status, n: signals.tasks.filter((t) => t.status === status).length }));
  const p = profile.data;

  return (
    <div className="page-grid">
      {mode === 'explorer' && <ProjectMap profile={p ?? null} signals={signals} />}
      <div className="grid-2">
        <Panel title={<><Icon name="flag" size={16} /> À faire maintenant</>} actions={signals.instructionsDrift ? <Button size="small" variant="primary" busy={busy !== null} onClick={() => void act(['sync'], { success: 'Instructions synchronisées' })}>Synchroniser</Button> : undefined}>
          {overview.data === undefined ? <p className="muted">Lecture du projet…</p> : list.length === 0
            ? <p className="muted">Rien n’attend. Ouvrez une quête pour la prochaine demande.</p>
            : <ul className="plain stack tight todo-list">{list.map((t) => (
              <li key={t.id}><a className={`card todo tone-${t.tone}`} href={`#${t.to}`}>
                <Icon name={t.icon} size={16} />
                <span className="grow"><strong>{t.title}</strong><span className="small muted block" lang={t.lang}>{t.detail}</span></span>
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
        {signals.tasks.length > 0 && <TableBox label="Quêtes récentes"><table className="data compact"><thead><tr><th>Quête</th><th>État</th><th>Prochaine étape</th></tr></thead>
          <tbody>{signals.tasks.slice(0, 8).map((t: TaskListItem) => <tr key={t.id}><td><a className="mono" href={`#/quetes/${t.id}`}>{t.id}</a><span className="small muted block clamp-1">{t.brief}</span></td><td><TaskStatusBadge status={t.status} /></td><td className="small" lang={nextLang(t.next)}>{nextLabel(t.next)}</td></tr>)}</tbody>
        </table></TableBox>}
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
