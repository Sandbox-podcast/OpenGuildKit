/**
 * Shell of the project interface: the same header, places and RPG / Pro styles as the demo, fed by the
 * project the local server opened. Counters come from the CLI; nothing here is simulated.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { navigate, useRoute } from '@/app/router';
import { Brand } from '@/app/Brand';
import { NavigationIcon } from '@/app/NavigationIcon';
import { PLACES, PLACE_GROUPS, type Place } from '@/shared/places';
import type { PlaceKey } from '@/shared/pixel/buildings';
import { Icon } from '@/shared/pixel/icons';
import { SceneArt } from '@/shared/pixel/Sprite';
import { Button, Notice, Segmented } from '@/shared/ui/core';
import { Toasts } from '@/shared/ui/overlay';
import { currentSession } from './api';
import { invalidate, showActionWarning, useActionWarning } from './query';
import { placeCounts, signalsOf, useOverview, useProfile } from './data';
import { setPrefs, usePrefs } from './prefs';
import { Pre, ServerWords, TerminalDialog, TouchedNotice } from './parts';
import { errorText } from './refusals';
import { ProjectSearch } from './ProjectSearch';
import { useShortcuts } from '@/shared/shortcuts';

/** The line under each place in the RPG navigation of a project; the Pro names are shared (shared/places.ts). */
export const PROJECT_PLACES: Record<PlaceKey, { role: string }> = {
  royaume: { role: 'Vue du projet' },
  blueprint: { role: 'Profil et règles' },
  guilde: { role: 'Cerveaux métier' },
  conseil: { role: 'Consultation et décision' },
  quetes: { role: 'Tâches du projet' },
  bibliotheque: { role: 'Références et packs' },
  forge: { role: 'Réalisation et outils' },
  tour: { role: 'Contrôles et alertes' },
  observatoire: { role: 'Marché et veille' },
  documentation: { role: 'Export et partages' },
  chroniques: { role: 'Historique' },
  intendance: { role: 'Hôte et catalogue' },
  arsenal: { role: 'Fonctionnalités et MCP' },
};

export const placeName = (p: Place, pro: boolean) => (pro ? p.proName : p.name);
const placeOf = (path: string) => PLACES.find((p) => path.startsWith(p.route));

function useMotion() {
  const { motion } = usePrefs();
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const apply = () => { document.documentElement.dataset.motion = motion === 'reduced' || (motion === 'system' && mq.matches) ? 'reduced' : 'full'; };
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [motion]);
}

function ModePicker() {
  const { mode } = usePrefs();
  const pro = mode === 'focus';
  return <div className="appearance-picker">
    <Segmented label="Style de l'interface" value={mode} onChange={(m) => setPrefs({ mode: m })} options={[{ value: 'explorer', label: 'RPG' }, { value: 'focus', label: 'Pro' }]} />
    <button className="appearance-compact" role="switch" aria-checked={pro} aria-label="Mode Pro" onClick={() => setPrefs({ mode: pro ? 'explorer' : 'focus' })}>
      <span aria-hidden="true">{pro ? 'Pro' : 'RPG'}</span><span aria-hidden="true" className="appearance-dot" />
    </button>
  </div>;
}

/** Shell of the setup screen: the project has no profile yet, so it reads nothing. */
export function BareShell({ children }: { children: ReactNode }) {
  const { mode } = usePrefs();
  useMotion();
  return <div className={`app bare mode-${mode}`}><div className="bare-preferences"><ModePicker /></div>{children}<TerminalDialog /><Toasts /></div>;
}

export function ProjectShell({ children }: { children: ReactNode }) {
  const actionWarning = useActionWarning();
  const { mode } = usePrefs();
  const pro = mode === 'focus';
  const route = useRoute();
  const session = currentSession();
  const overview = useOverview();
  const profile = useProfile();
  const signals = useMemo(() => signalsOf(overview.data), [overview.data]);
  const counts = placeCounts(signals);
  const [navOpen, setNavOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const navToggle = useRef<HTMLButtonElement>(null);
  const place = placeOf(route.path);
  useMotion();

  useEffect(() => { setNavOpen(false); }, [route.path]);
  useShortcuts({ openSearch: () => setSearchOpen(true), go: (to) => navigate(to), toggleMode: () => setPrefs({ mode: pro ? 'explorer' : 'focus' }) });

  // Work done in a terminal (an approval, a waiver) shows up when the person comes back to the page.
  // A quick switch of tabs does not reload everything.
  useEffect(() => {
    let hiddenAt = 0;
    const onFocus = () => {
      if (document.visibilityState === 'hidden') { hiddenAt = Date.now(); return; }
      if (Date.now() - hiddenAt > 1500) invalidate();
    };
    document.addEventListener('visibilitychange', onFocus);
    return () => document.removeEventListener('visibilitychange', onFocus);
  }, []);

  const closeNavigation = () => { setNavOpen(false); navToggle.current?.focus(); };
  return (
    <div className={`app project-app mode-${mode}`}>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus(); }}>Aller au contenu</a>
      <header className="topbar">
        <button ref={navToggle} className="btn ghost icon nav-toggle" aria-label={navOpen ? 'Fermer la navigation' : 'Ouvrir la navigation'} aria-controls="main-navigation" aria-expanded={navOpen} onClick={() => (navOpen ? closeNavigation() : setNavOpen(true))}><Icon name={navOpen ? 'cross' : 'menu'} /></button>
        <a href="#/royaume" className="brand-link" aria-label="Accueil du projet"><Brand /></a>
        <div className="project-chip" title={session?.project.root}>
          <Icon name="crown" size={14} />
          <span className="project-chip-name">{profile.data?.name ?? session?.project.name}</span>
          <span className="badge tone-success project-chip-live">Projet réel</span>
        </div>
        <button className="searchbox" onClick={() => setSearchOpen(true)} aria-keyshortcuts="Control+K">
          <Icon name="search" size={16} /><span>Rechercher</span><kbd>Ctrl K</kbd>
        </button>
        <div className="topbar-actions">
          <Button size="small" variant="ghost" icon="replace" onClick={() => invalidate()} aria-label="Actualiser les données du projet">Actualiser</Button>
          <ModePicker />
        </div>
      </header>

      {navOpen && <div className="nav-scrim" aria-hidden="true" onClick={closeNavigation} />}
      <nav id="main-navigation" className={`sidebar ${navOpen ? 'open' : ''}`} aria-label={pro ? 'Navigation principale' : 'Lieux du royaume'} onKeyDown={(e) => { if (navOpen && e.key === 'Escape') closeNavigation(); }}>
        {PLACE_GROUPS.map((group) => <div className="nav-group" key={group.name}>
          <p className="nav-group-label">{group.name}</p>
          <ul className="plain">
            {group.keys.map((key) => {
              const p = PLACES.find((c) => c.key === key)!;
              const c = counts[p.key];
              const name = placeName(p, pro);
              const role = PROJECT_PLACES[p.key].role;
              return (
                <li key={p.key}>
                  <a href={`#${p.route}`} aria-current={place?.key === p.key ? 'page' : undefined} className="nav-item" title={role} onClick={() => setNavOpen(false)}>
                    {pro ? <NavigationIcon place={p.key} /> : <Icon name={p.icon} size={20} />}
                    <span className="nav-text"><span className="nav-name">{name}</span>{!pro && <> <span className="nav-role">{role}</span></>}</span>
                    {c && <><span className={`badge count ${c.tone}`} title={`${c.n} ${c.label}`} aria-hidden="true">{c.n}</span><span className="sr-only">, {c.n} {c.label}</span></>}
                  </a>
                </li>
              );
            })}
          </ul>
        </div>)}
        <span className="nav-room-note" role="note"><Icon name="shield" size={13} /> OpenGuildKit {session?.version} · 127.0.0.1</span>
      </nav>

      <main id="main" tabIndex={-1} className="main" inert={navOpen}>
        {overview.error && <div className="notice danger" role="alert"><Icon name="warn" size={16} /><div><span lang={errorText(overview.error).lang}>{errorText(overview.error).text}</span><ServerWords detail={errorText(overview.error).detail} /></div></div>}
        {place && <PlaceHeader place={place} pro={pro} compact={route.parts.length > 1} />}
        <TouchedNotice />
        {actionWarning && <Notice tone="warn" title="Avertissements de la commande">
          <Pre text={actionWarning} />
          <Button size="small" onClick={() => showActionWarning('')}>Masquer les avertissements</Button>
        </Notice>}
        {children}
      </main>
      <ProjectSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
      <TerminalDialog />
      <Toasts />
    </div>
  );
}

function PlaceHeader({ place, pro, compact }: { place: Place; pro: boolean; compact: boolean }) {
  const illustrated = !pro && !compact;
  return (
    <header className={`place-heading ${illustrated ? 'illustrated' : ''}`}>
      <div className="place-heading-copy">
        {!pro && <p className="place-heading-label"><Icon name={place.icon} size={16} />{PROJECT_PLACES[place.key].role}</p>}
        <h1>{placeName(place, pro)}</h1>
      </div>
      {illustrated && <div className="place-heading-art" aria-hidden="true"><SceneArt place={place.key} /></div>}
    </header>
  );
}
