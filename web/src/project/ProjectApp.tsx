/** Routes of the project interface. Each place is its own chunk; a direct link survives a reload. */
import { Suspense, useEffect } from 'react';
import { lazyPlace, preloadWhenIdle, type Place } from '@/shared/lazyPlace';
import { navigate, useRoute } from '@/shared/router';
import { Empty } from '@/shared/ui/core';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';
import { currentSession } from './api';
import { BareShell, ProjectShell } from './ProjectShell';
import { Loading } from './parts';

const named = lazyPlace;
const Home = named(() => import('./views/Home'), 'Home');
const Setup = named(() => import('./views/Blueprint'), 'Setup');
const Blueprint = named(() => import('./views/Blueprint'), 'Blueprint');
const Guild = named(() => import('./views/Guild'), 'Guild');
const BrainSheet = named(() => import('./views/Guild'), 'BrainSheet');
const CouncilList = named(() => import('./views/Council'), 'CouncilList');
const CouncilRoom = named(() => import('./views/Council'), 'CouncilRoom');
const Quests = named(() => import('./views/Quests'), 'Quests');
const QuestSheet = named(() => import('./views/Quests'), 'QuestSheet');
const Library = named(() => import('./views/Library'), 'Library');
const ReferenceSheet = named(() => import('./views/Library'), 'ReferenceSheet');
const Forge = named(() => import('./views/Forge'), 'Forge');
const ForgeTask = named(() => import('./views/Forge'), 'ForgeTask');
const Watchtower = named(() => import('./views/Watchtower'), 'Watchtower');
const Observatory = named(() => import('./views/Observatory'), 'Observatory');
const Docs = named(() => import('./views/Docs'), 'Docs');
const Chronicles = named(() => import('./views/Chronicles'), 'Chronicles');
const Stewardship = named(() => import('./views/Stewardship'), 'Stewardship');
const Arsenal = named(() => import('./views/Arsenal'), 'Arsenal');

const PLACES = [Home, Quests, CouncilRoom, ForgeTask, Library, Guild, Watchtower, Observatory, Docs, Chronicles, Stewardship, Arsenal, Blueprint];
const BY_ROUTE: Record<string, Place[]> = {
  royaume: [Home], blueprint: [Blueprint], guilde: [Guild, BrainSheet], conseil: [CouncilList, CouncilRoom], quetes: [Quests, QuestSheet],
  bibliotheque: [Library, ReferenceSheet], forge: [Forge, ForgeTask], tour: [Watchtower], observatoire: [Observatory],
  documentation: [Docs], chroniques: [Chronicles], intendance: [Stewardship], arsenal: [Arsenal], installation: [Setup],
};

export { adoptServerPrefs } from './prefs';

/** Loads the place of the address being opened, before the first render: the first screen then never waits. */
export function preloadRoute(initialized: boolean) {
  const first = window.location.hash.replace(/^#\/?/, '').split(/[/?]/)[0] || 'royaume';
  return Promise.all((initialized ? BY_ROUTE[first] ?? [Home] : [Setup]).map((place) => place.preload())).catch(() => undefined);
}

export function ProjectApp() {
  const route = useRoute();
  // After the first screen, the other places load in the background: changing place then shows no wait.
  useEffect(() => { preloadWhenIdle(PLACES); }, []);
  const [a, b, c] = route.parts;
  const initialized = currentSession()?.project.initialized ?? false;

  useEffect(() => {
    if (!initialized && a !== 'installation') navigate('/installation', { replace: true });
    else if (initialized && (!a || a === 'installation')) navigate('/royaume', { replace: true });
  }, [a, initialized]);

  if (!initialized) return <BareShell><ErrorBoundary><Suspense fallback={<Loading />}><Setup /></Suspense></ErrorBoundary></BareShell>;

  let page;
  switch (a) {
    case 'royaume': page = <Home />; break;
    case 'blueprint': page = <Blueprint tab={b} />; break;
    case 'guilde': page = b ? <BrainSheet id={b} /> : <Guild />; break;
    case 'conseil': page = b ? <CouncilRoom id={b} /> : <CouncilList />; break;
    case 'quetes': page = b ? <QuestSheet id={b} /> : <Quests />; break;
    case 'bibliotheque': page = b === 'ref' ? <ReferenceSheet id={c} /> : <Library tab={b} />; break;
    case 'forge': page = b && !['livrables', 'outils', 'storybook'].includes(b) ? <ForgeTask id={b} /> : <Forge tab={b} />; break;
    case 'tour': page = <Watchtower tab={b} />; break;
    case 'observatoire': page = <Observatory id={b} />; break;
    case 'documentation': page = <Docs tab={b} />; break;
    case 'chroniques': page = <Chronicles />; break;
    case 'intendance': page = <Stewardship tab={b} />; break;
    case 'arsenal': page = <Arsenal />; break;
    default: page = <Empty title="Lien introuvable">Cette adresse ne correspond à aucun lieu. <a href="#/royaume">Revenir au projet</a></Empty>;
  }
  return <ProjectShell><ErrorBoundary resetKey={route.path}><Suspense fallback={<Loading label="Chargement du lieu" />}>{page}</Suspense></ErrorBoundary></ProjectShell>;
}
