/**
 * Application shell shared by RPG and Pro: header (organisation, project, search,
 * notifications, quick actions, identity, mode), navigation by place, illustrated or compact
 * place header, demo guide. Switching mode keeps routes, data, drafts and selection.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { dispatch, useAppState, useStorageProblem, dismissStorageProblem } from './store';
import { navigate, useRoute } from '@/shared/router';
import { routeOf } from '@/demo/app/routes';
import { PLACES, PLACE_GROUPS, placeCounts, placeOf, type Place } from './places';
import { GUIDE } from './guide';
import { CommandPalette } from './CommandPalette';
import { cmd } from '@/demo/domain/commands';
import { hasActiveWork } from '@/demo/domain/commands/oversight';
import { authorize, ROLES, rolesOf, type Capability } from '@/demo/domain/permissions';
import { notifications, fmtDate } from '@/demo/domain/selectors';
import { list } from '@/demo/domain/engine';
import { Icon } from '@/shared/pixel/icons';
import { SceneArt } from '@/shared/pixel/Sprite';
import { Badge, Button, Segmented } from '@/shared/ui/core';
import { Dialog, Drawer, Menu, Toasts } from '@/shared/ui/overlay';
import { ActorLabel, Portrait } from '@/demo/ui/domain';
import { Brand } from '@/shared/Brand';
import { NavigationIcon } from '@/shared/NavigationIcon';
import { setSingleKeyShortcuts, useShortcuts, useSingleKeyShortcuts } from '@/shared/shortcuts';

function useTicker() {
  const s = useAppState();
  const active = hasActiveWork(s);
  useEffect(() => { dispatch(cmd.tick, {}, { silent: true }); }, [s.session.orgId, s.demo.timeOffsetMs]);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => dispatch(cmd.tick, {}, { silent: true }), 750);
    return () => clearInterval(t);
  }, [active]);
}

function useMotionPrefs() {
  const s = useAppState();
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const apply = () => {
      const reduced = s.prefs.motion === 'reduced' || (s.prefs.motion === 'system' && mq.matches);
      document.documentElement.dataset.motion = reduced ? 'reduced' : 'full';
    };
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [s.prefs.motion]);
  useEffect(() => { document.documentElement.style.setProperty('--text-scale', String(s.prefs.textScale)); }, [s.prefs.textScale]);
}

export function Shell({ children, bare }: { children: ReactNode; bare?: boolean }) {
  const s = useAppState();
  const route = useRoute();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const navToggle = useRef<HTMLButtonElement>(null);
  useTicker();
  useMotionPrefs();
  const place = placeOf(route.path);
  const professional = s.prefs.mode === 'focus';
  const project = route.parts[0] === 'projets' ? list(s, 'project', s.session.orgId).find((p) => p.id === route.parts[1]) : undefined;

  useEffect(() => { setNavOpen(false); }, [route.path]);
  useEffect(() => {
    const compact = window.matchMedia('(max-width: 900px)');
    const closeOnResize = () => { if (!compact.matches) setNavOpen(false); };
    compact.addEventListener('change', closeOnResize);
    return () => compact.removeEventListener('change', closeOnResize);
  }, []);
  useEffect(() => {
    if (navOpen) document.getElementById('org-pick-mobile')?.focus({ preventScroll: true });
  }, [navOpen]);

  const closeNavigation = () => {
    setNavOpen(false);
    navToggle.current?.focus();
  };

  useShortcuts({
    openSearch: () => setPaletteOpen(true), go: (to) => navigate(to), help: () => setHelpOpen(true),
    toggleMode: () => dispatch(cmd.setPreference, { mode: s.prefs.mode === 'explorer' ? 'focus' : 'explorer' }, { silent: true }),
  });

  if (bare) return <div className={`app bare mode-${s.prefs.mode}`}>
    <div className="bare-preferences"><ModePicker /></div>
    {children}<Toasts />
  </div>;
  const notifs = notifications(s);
  const counts = placeCounts(s, notifs);
  const unread = notifs.filter((n) => !s.prefs.readNotifications.includes(n.id));
  const guideDone = GUIDE.filter((g) => g.done(s)).length;

  return (
    <div className={`app mode-${s.prefs.mode} ${s.prefs.guideOpen && s.session.orgId ? 'with-guide' : ''}`}>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus(); }}>Aller au contenu</a>
      <header className="topbar">
        <button ref={navToggle} className="btn ghost icon nav-toggle" aria-label={navOpen ? 'Fermer la navigation' : 'Ouvrir la navigation'} aria-controls="main-navigation" aria-expanded={navOpen} onClick={() => { if (navOpen) closeNavigation(); else setNavOpen(true); }} onKeyDown={(event) => { if (event.key === 'Escape') closeNavigation(); }}><Icon name={navOpen ? 'cross' : 'menu'} /></button>
        <a href="#/royaume" className="brand-link" aria-label="Accueil Open Guild Kit"><Brand /></a>
        <ContextPickers />
        <button className="searchbox" onClick={() => setPaletteOpen(true)} aria-keyshortcuts="Control+K">
          <Icon name="search" size={16} /><span>Rechercher</span><kbd>Ctrl K</kbd>
        </button>
        <div className="topbar-actions">
          <QuickActions />
          <button className="btn ghost icon" aria-label={`Notifications (${unread.length} non lue(s))`} onClick={() => setNotifOpen(true)}>
            <Icon name="bell" />{unread.length > 0 && <span className="badge count danger dot-count">{unread.length}</span>}
          </button>
          <ModePicker />
          <IdentityMenu onShortcuts={() => setHelpOpen(true)} />
        </div>
      </header>

      {navOpen && <div className="nav-scrim" aria-hidden="true" onClick={closeNavigation} />}
      <nav id="main-navigation" className={`sidebar ${navOpen ? 'open' : ''}`} aria-label={professional ? 'Navigation principale' : 'Lieux du royaume'} onKeyDown={(event) => { if (navOpen && event.key === 'Escape') closeNavigation(); }}>
        <div className="mobile-context"><ContextPickers mobile /></div>
        {PLACE_GROUPS.map((group) => <div className="nav-group" key={group.name}>
          <p className="nav-group-label">{group.name}</p>
          <ul className="plain">
          {group.keys.map((key) => {
            const p = PLACES.find((candidate) => candidate.key === key)!;
            const c = counts[p.key];
            const current = place?.key === p.key;
            const name = professional ? p.proName : p.name;
            return (
              <li key={p.key}>
                <a href={`#${p.route}`} aria-current={current ? 'page' : undefined} className="nav-item" title={p.role} onClick={() => setNavOpen(false)}>
                  {professional ? <NavigationIcon place={p.key} /> : <Icon name={p.icon} size={20} />}
                  <span className="nav-text"><span className="nav-name">{name}</span>{!professional && <> <span className="nav-role">{p.role}</span></>}</span>
                  {c && <><span className={`badge count ${c.tone}`} title={`${c.n} ${c.label}`} aria-hidden="true">{c.n}</span><span className="sr-only">, {c.n} {c.label}</span></>}
                </a>
              </li>
            );
          })}
          </ul>
        </div>)}
        <span className="nav-room-note" role="note"><Icon name="dice" size={13} /> Démonstration interactive</span>
        <button className="guide-link" aria-label="Parcours de démonstration" aria-expanded={s.prefs.guideOpen} onClick={() => { setNavOpen(false); dispatch(cmd.setPreference, { guideOpen: !s.prefs.guideOpen }, { silent: true }); }}>
          <Icon name="flag" size={16} /> <span className="nav-text">Parcours de démonstration</span> <span className="badge count">{guideDone}/20</span>
        </button>
      </nav>

      <main id="main" tabIndex={-1} className="main" inert={navOpen}>
        <StorageBanner />
        {place && <PlaceHeader place={place} title={project?.name ?? (route.path === '/royaume/projets' ? 'Projets' : professional ? place.proName : place.name)} compact={!!project || route.path === '/royaume/projets' || route.path === '/guilde' || (route.parts[0] === 'conseil' && !!route.parts[1])} />}
        {children}
      </main>

      {s.prefs.guideOpen && s.session.orgId && <GuidePanel />}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <NotificationsDrawer open={notifOpen} onClose={() => setNotifOpen(false)} />
      <ShortcutsDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
      <Toasts />
    </div>
  );
}

function PlaceHeader({ place, title, compact }: { place: Place; title: string; compact: boolean }) {
  const s = useAppState();
  const busy = place.key === 'forge' && list(s, 'run', s.session.orgId).some((r) => r.status === 'running');
  const illustrated = s.prefs.mode === 'explorer' && !compact;
  return (
    <header className={`place-heading ${illustrated ? 'illustrated' : ''}`}>
      <div className="place-heading-copy">
        {s.prefs.mode === 'explorer' && <p className="place-heading-label"><Icon name={place.icon} size={16} />{place.role}</p>}
        <h1>{title}</h1>
        {busy && <Badge tone="ai" icon="play">Exécution en cours</Badge>}
      </div>
      {illustrated && <div className="place-heading-art" aria-hidden="true"><SceneArt place={place.key} /></div>}
    </header>
  );
}

function ModePicker() {
  const { prefs } = useAppState();
  const professional = prefs.mode === 'focus';
  const setMode = (mode: 'explorer' | 'focus') => dispatch(cmd.setPreference, { mode }, { silent: true });
  return <div className="appearance-picker">
    <Segmented label="Style de l'interface" value={prefs.mode} onChange={setMode} options={[{ value: 'explorer', label: 'RPG' }, { value: 'focus', label: 'Pro' }]} />
    <button className="appearance-compact" role="switch" aria-checked={professional} aria-label="Mode Pro" onClick={() => setMode(professional ? 'explorer' : 'focus')}>
      <span aria-hidden="true">{professional ? 'Pro' : 'RPG'}</span><span aria-hidden="true" className="appearance-dot" />
    </button>
  </div>;
}

function ContextPickers({ mobile = false }: { mobile?: boolean }) {
  const s = useAppState();
  const orgs = Object.values(s.orgs);
  const projects = list(s, 'project', s.session.orgId);
  if (!s.session.orgId) return null;
  const orgPicker = mobile ? 'org-pick-mobile' : 'org-pick';
  const projectPicker = mobile ? 'project-pick-mobile' : 'project-pick';
  return (
    <div className="pickers">
      <label htmlFor={orgPicker}>Organisation</label>
      <select id={orgPicker} value={s.session.orgId} onChange={(e) => { if (e.target.value === '__new') navigate('/entree'); else { dispatch(cmd.switchOrg, { orgId: e.target.value }, { silent: true }); navigate('/royaume'); } }}>
        {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        <option value="__new">Changer ou créer une organisation</option>
      </select>
      <label htmlFor={projectPicker}>Projet actif</label>
      <select id={projectPicker} value={s.session.projectId ?? ''} onChange={(e) => dispatch(cmd.setProjectContext, { projectId: e.target.value || null }, { silent: true })}>
        <option value="">Tous les projets</option>
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}{p.status === 'archived' ? ' (archivé)' : ''}</option>)}
      </select>
    </div>
  );
}

function QuickActions() {
  const s = useAppState();
  const projectId = s.session.projectId ?? undefined;
  const allowed = (cap: Capability) => s.session.orgId ? authorize(s, s.session.actor, cap, { orgId: s.session.orgId, projectId }) : { ok: false, reason: 'Aucune organisation.' };
  const items: { label: string; to: string; cap: Capability }[] = [
    { label: 'Nouvelle quête', to: '/quetes?nouvelle=1', cap: 'edit' },
    { label: 'Nouveau projet', to: '/royaume/projets?nouveau=1', cap: 'edit' },
    { label: 'Préparer un Conseil', to: '/conseil?nouveau=1', cap: 'propose' },
    { label: 'Nouveau livrable', to: '/forge/studio?nouveau=1', cap: 'edit' },
    { label: 'Faire évoluer le Blueprint', to: '/blueprint/structure', cap: 'propose' },
    { label: 'Importer des références', to: '/bibliotheque/import', cap: 'configure_org' },
  ];
  return (
    <Menu label="Actions rapides" align="right" trigger={(t) => <button className="btn small" aria-label="Créer" {...t}><Icon name="plus" size={14} /><span className="quick-action-label">Créer</span></button>}>
      {(close) => items.map((it) => {
        const d = allowed(it.cap);
        return (
          <button key={it.label} disabled={!d.ok} title={d.reason} onClick={() => { close(); navigate(it.to); }} role="menuitem">
            <Icon name={d.ok ? 'plus' : 'lock'} size={12} /><span>{it.label}{!d.ok && <span className="tiny muted" style={{ display: 'block' }}>{d.reason}</span>}</span>
          </button>
        );
      })}
    </Menu>
  );
}

function IdentityMenu({ onShortcuts }: { onShortcuts: () => void }) {
  const s = useAppState();
  const members = list(s, 'member', s.session.orgId);
  const humans = [...new Set(members.map((m) => m.userId))];
  const experts = list(s, 'expert', s.session.orgId).filter((e) => e.active);
  const actor = s.session.actor;
  const portrait = actor.type === 'human' ? s.users[actor.userId]?.portrait : actor.type === 'agent' ? s.db.expert[actor.expertId]?.key : 'human-1';
  const roleText = actor.type === 'human' && s.session.orgId ? rolesOf(s, actor.userId, s.session.orgId).map((r) => ROLES[r].short).join(', ') : actor.type === 'agent' ? 'Agent IA' : '';
  return (
    <Menu label="Identité de démonstration" align="right" trigger={(t) => (
      <button className="identity" {...t} aria-label="Identité de démonstration et changement d’acteur">
        {portrait && <Portrait k={portrait} size={28} />}<span className="identity-text"><span>{actor.type === 'human' ? s.users[actor.userId]?.name : actor.type === 'agent' ? s.db.expert[actor.expertId]?.name : 'Système'}</span><span className="tiny muted">{roleText}</span></span>
      </button>
    )}>
      {(close) => (
        <>
          <p className="menu-label">Démonstration · changer d’acteur</p>
          {humans.map((id) => (
            <button key={id} role="menuitemradio" aria-checked={actor.type === 'human' && actor.userId === id} onClick={() => { dispatch(cmd.setActor, { actor: { type: 'human', userId: id } }, { success: `Vous agissez maintenant comme ${s.users[id]?.name}` }); close(); }}>
              <Portrait k={s.users[id]?.portrait ?? 'human-1'} size={20} />{s.users[id]?.name}<span className="tiny muted">{rolesOf(s, id, s.session.orgId!).map((r) => ROLES[r].short).join(', ')}</span>
            </button>
          ))}
          <p className="menu-label">Agents IA (pour éprouver les garde-fous)</p>
          {experts.slice(0, 14).map((e) => (
            <button key={e.id} role="menuitemradio" aria-checked={actor.type === 'agent' && actor.expertId === e.id} onClick={() => { dispatch(cmd.setActor, { actor: { type: 'agent', expertId: e.id } }, { success: `Vous agissez comme l’agent ${e.name} : les validations humaines vous seront refusées.` }); close(); }}>
              <Portrait k={e.key} size={20} />{e.name}<span className="ai-mark">IA</span>
            </button>
          ))}
          <p className="menu-label">Préférences</p>
          <a href="#/intendance/preferences" onClick={close}><Icon name="settings" size={12} /> Préférences et accessibilité</a>
          <button role="menuitem" onClick={() => { close(); onShortcuts(); }}><Icon name="settings" size={12} /> Raccourcis clavier</button>
          <a href="#/intendance/demo" onClick={close}><Icon name="dice" size={12} /> Paramètres de démonstration</a>
        </>
      )}
    </Menu>
  );
}

function NotificationsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useAppState();
  const notifs = useMemo(() => notifications(s), [s]);
  return (
    <Drawer open={open} onClose={onClose} title="Notifications locales">
      <p className="small muted">Calculées à partir des objets de l’organisation. Aucun courriel n’est envoyé.</p>
      <div className="row" style={{ marginBottom: 10 }}>
        <Button size="small" onClick={() => dispatch(cmd.markNotificationsRead, { ids: notifs.map((n) => n.id) }, { silent: true })}>Tout marquer comme lu</Button>
        <a href="#/intendance/notifications" onClick={onClose} className="small">Régler les notifications</a>
      </div>
      {notifs.length === 0 && <p className="muted">Rien à signaler.</p>}
      <ul className="plain stack tight">
        {notifs.map((n) => {
          const read = s.prefs.readNotifications.includes(n.id);
          return (
            <li key={n.id}>
              <a className="card" href={`#${typeof n.to === 'string' ? n.to : routeOf(n.to)}`} onClick={() => { dispatch(cmd.markNotificationsRead, { ids: [n.id] }, { silent: true }); onClose(); }} style={{ opacity: read ? 0.7 : 1 }}>
                <div className="row between"><Badge tone={n.tone} icon={n.tone === 'danger' ? 'warn' : n.tone === 'ai' ? 'ai' : 'bell'}>{read ? 'Lu' : 'Nouveau'}</Badge><span className="tiny muted">{fmtDate(n.at, true)}</span></div>
                <p style={{ margin: '6px 0 0' }}>{n.text}</p>
              </a>
            </li>
          );
        })}
      </ul>
    </Drawer>
  );
}

function GuidePanel() {
  const s = useAppState();
  const isNova = s.session.orgId === 'org-nova';
  return (
    <aside className="guide" aria-label="Parcours de démonstration">
      <header className="row between">
        <h2 className="pixel-font" style={{ margin: 0, fontSize: '1rem' }}><Icon name="flag" size={14} /> Parcours de démonstration</h2>
        <Button variant="ghost" icon="close" size="small" aria-label="Masquer le parcours" onClick={() => dispatch(cmd.setPreference, { guideOpen: false }, { silent: true })} />
      </header>
      <p className="tiny muted">« Permettre à un administrateur d’exporter les données de ses clients. » Chaque étape est cochée d’après les objets réels.</p>
      {!isNova && <p className="small">Ce parcours se déroule dans l’organisation de démonstration « Atelier Nova ». <a href="#/entree">Ouvrir l’écran d’entrée</a></p>}
      <ol className="plain guide-steps">
        {GUIDE.map((g) => {
          const done = isNova && g.done(s);
          return (
            <li key={g.n} className={done ? 'done' : ''}>
              <a href={`#${g.to}`}><span className="step-n">{done ? <Icon name="check" size={12} label="fait" /> : g.n}</span><span><strong>{g.title}</strong><span className="tiny muted" style={{ display: 'block' }}>{g.where} — {g.hint}</span></span></a>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const single = useSingleKeyShortcuts();
  return (
    <Dialog open={open} onClose={onClose} title="Raccourcis clavier">
      <label className="row small"><input type="checkbox" checked={single} onChange={(e) => setSingleKeyShortcuts(e.target.checked)} /> Raccourcis à une touche (<kbd>/</kbd>, <kbd>g</kbd>, <kbd>m</kbd>, <kbd>?</kbd>) ; <kbd>Ctrl</kbd> + <kbd>K</kbd> reste actif</label>
      <table className="data">
        <tbody>
          <tr><td><kbd>Ctrl</kbd> + <kbd>K</kbd> ou <kbd>/</kbd></td><td>Recherche et palette de commandes</td></tr>
          <tr><td><kbd>g</kbd> puis lettre</td><td>Aller à un lieu : {PLACES.map((p) => `${p.shortcut} ${p.name}`).join(' · ')}</td></tr>
          <tr><td><kbd>m</kbd></td><td>Changer de style, RPG ou Pro</td></tr>
          <tr><td><kbd>?</kbd></td><td>Afficher cette aide</td></tr>
          <tr><td><kbd>Échap</kbd></td><td>Fermer une fenêtre, un menu ou un tiroir</td></tr>
          <tr><td>Flèches</td><td>Changer d’onglet, déplacer une carte sélectionnée sur le tableau des quêtes</td></tr>
        </tbody>
      </table>
    </Dialog>
  );
}

function StorageBanner() {
  const problem = useStorageProblem();
  if (!problem) return null;
  return (
    <div className="notice warn" role="alert">
      <Icon name="warn" size={16} />
      <div className="grow">{problem} <a href="#/intendance/donnees">Exporter une sauvegarde ou réinitialiser</a></div>
      <Button size="small" variant="ghost" onClick={dismissStorageProblem}>Masquer</Button>
    </div>
  );
}

export { ActorLabel };
