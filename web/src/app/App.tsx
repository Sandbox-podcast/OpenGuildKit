/** Route table. Every route works by direct link and survives a reload. */
import { Suspense, useEffect } from 'react';
import { lazyPlace, preloadWhenIdle, type Place } from '@/shared/lazyPlace';
import { useAppState } from './store';
import { navigate, useRoute } from './router';
import { Shell } from './Shell';
import { Empty } from '@/shared/ui/core';
import { ErrorBoundary } from '@/shared/ui/ErrorBoundary';

// Each place is its own chunk: the first screen downloads only what it shows.
const named = lazyPlace;
const Entry = named(() => import('@/features/entry/Entry'), 'Entry');
const Onboarding = named(() => import('@/features/entry/Entry'), 'Onboarding');
const Kingdom = named(() => import('@/features/kingdom/Kingdom'), 'Kingdom');
const ProjectSheet = named(() => import('@/features/kingdom/Kingdom'), 'ProjectSheet');
const ProjectsView = named(() => import('@/features/kingdom/Kingdom'), 'ProjectsView');
const BlueprintSpace = named(() => import('@/features/blueprint/Blueprint'), 'BlueprintSpace');
const ExpertSheet = named(() => import('@/features/guild/Guild'), 'ExpertSheet');
const GuildSpace = named(() => import('@/features/guild/Guild'), 'GuildSpace');
const CouncilList = named(() => import('@/features/council/Council'), 'CouncilList');
const CouncilRoom = named(() => import('@/features/council/Council'), 'CouncilRoom');
const DecisionPage = named(() => import('@/features/council/Council'), 'DecisionPage');
const QuestSheet = named(() => import('@/features/quests/Quests'), 'QuestSheet');
const QuestsSpace = named(() => import('@/features/quests/Quests'), 'QuestsSpace');
const LibrarySpace = named(() => import('@/features/library/Library'), 'LibrarySpace');
const ReferenceSheet = named(() => import('@/features/library/Library'), 'ReferenceSheet');
const DeliverablePage = named(() => import('@/features/forge/Forge'), 'DeliverablePage');
const ForgeSpace = named(() => import('@/features/forge/Forge'), 'ForgeSpace');
const RunPage = named(() => import('@/features/forge/Forge'), 'RunPage');
const WatchtowerSpace = named(() => import('@/features/watchtower/Watchtower'), 'WatchtowerSpace');
const ObservatorySpace = named(() => import('@/features/observatory/Observatory'), 'ObservatorySpace');
const DocsSpace = named(() => import('@/features/docs/Docs'), 'DocsSpace');
const SharePage = named(() => import('@/features/docs/Docs'), 'SharePage');
const ChroniclesSpace = named(() => import('@/features/chronicles/Chronicles'), 'ChroniclesSpace');
const StewardshipSpace = named(() => import('@/features/stewardship/Stewardship'), 'StewardshipSpace');
const ArsenalSpace = named(() => import('@/features/arsenal/Arsenal'), 'ArsenalSpace');
const Wait = () => <p className="muted loading-line" role="status">Chargement du lieu…</p>;

const PLACES = [Kingdom, BlueprintSpace, GuildSpace, CouncilRoom, QuestsSpace, LibrarySpace, ForgeSpace, WatchtowerSpace, ObservatorySpace, DocsSpace, ChroniclesSpace, StewardshipSpace, ArsenalSpace];

/** Loads the screen of the address being opened before the first render, so it does not wait. */
export function preloadRoute() {
  const first = window.location.hash.replace(/^#\/?/, '').split(/[/?]/)[0];
  const place = ({ '': Kingdom, royaume: Kingdom, entree: Entry, onboarding: Onboarding, blueprint: BlueprintSpace, guilde: GuildSpace, conseil: CouncilList, quetes: QuestsSpace, bibliotheque: LibrarySpace, forge: ForgeSpace, tour: WatchtowerSpace, observatoire: ObservatorySpace, documentation: DocsSpace, chroniques: ChroniclesSpace, intendance: StewardshipSpace, arsenal: ArsenalSpace } as Record<string, Place>)[first];
  return (place?.preload() ?? Promise.resolve()).catch(() => undefined);
}

export function App() {
  const s = useAppState();
  useEffect(() => { preloadWhenIdle(PLACES); }, []);
  const route = useRoute();
  const [a, b, c] = route.parts;
  const hasOrg = !!s.session.orgId && !!s.orgs[s.session.orgId];
  const onboarding = hasOrg && s.orgs[s.session.orgId!].onboarding.status !== 'done';

  useEffect(() => {
    if (a === 'partage') return;
    if (!hasOrg && a !== 'entree') navigate('/entree', { replace: true });
    else if (onboarding && a !== 'onboarding' && a !== 'entree') navigate('/onboarding', { replace: true });
    else if (hasOrg && !a) navigate('/royaume', { replace: true });
  }, [a, hasOrg, onboarding]);

  if (a === 'partage') return <Shell bare><Suspense fallback={<Wait />}><SharePage token={b ?? ''} /></Suspense></Shell>;
  if (a === 'entree' || !hasOrg) return <Shell bare><Suspense fallback={<Wait />}><Entry /></Suspense></Shell>;
  if (a === 'onboarding' || onboarding) return <Shell bare><Suspense fallback={<Wait />}><Onboarding /></Suspense></Shell>;

  let page;
  switch (a) {
    case 'royaume': page = b === 'projets' ? <ProjectsView /> : <Kingdom />; break;
    case 'projets': page = <ProjectSheet id={b} />; break;
    case 'blueprint': page = <BlueprintSpace tab={b} />; break;
    case 'guilde': page = b && b !== 'equipe' ? <ExpertSheet id={b} /> : <GuildSpace tab={b} />; break;
    case 'conseil': page = b ? <CouncilRoom id={b} /> : <CouncilList />; break;
    case 'decisions': page = <DecisionPage id={b} />; break;
    case 'quetes': page = b ? <QuestSheet id={b} /> : <QuestsSpace />; break;
    case 'bibliotheque': page = b === 'ref' ? <ReferenceSheet id={c} /> : <LibrarySpace tab={b} />; break;
    case 'forge': page = b === 'executions' && c ? <RunPage id={c} /> : b === 'livrables' && c ? <DeliverablePage id={c} /> : <ForgeSpace tab={b} />; break;
    case 'tour': page = <WatchtowerSpace tab={b} id={c} />; break;
    case 'observatoire': page = <ObservatorySpace tab={b} id={c} />; break;
    case 'documentation': page = <DocsSpace tab={b} />; break;
    case 'chroniques': page = <ChroniclesSpace tab={b} />; break;
    case 'intendance': page = <StewardshipSpace tab={b} />; break;
    case 'arsenal': page = <ArsenalSpace />; break;
    default: page = <Empty title="Lien introuvable">Cette adresse ne correspond à aucun lieu. <a href="#/royaume">Revenir au Royaume</a></Empty>;
  }
  return <Shell><ErrorBoundary resetKey={route.path}><Suspense fallback={<Wait />}>{page}</Suspense></ErrorBoundary></Shell>;
}

/** Shown when an object of a link does not exist (deleted, other organisation, typo). */
export function NotFound({ what }: { what: string }) {
  return <Empty title={`${what} introuvable`}>L’objet n’existe pas dans l’organisation active : il a peut-être été supprimé, ou appartient à une autre organisation. <a href="#/royaume">Revenir au Royaume</a></Empty>;
}
