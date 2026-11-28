/** Search and command palette: open a place, a project, a reference, a quest, a decision, a document or run an allowed action. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { dispatch, useAppState } from './store';
import { navigate } from '@/shared/router';
import { routeOf } from '@/demo/app/routes';
import { PLACES } from './places';
import { searchAll } from './search';
import { cmd } from '@/demo/domain/commands';
import { authorize, type Capability } from '@/demo/domain/permissions';
import { Icon, type PixelIconName } from '@/shared/pixel/icons';
import { Dialog } from '@/shared/ui/overlay';

interface Item {
  id: string;
  group: string;
  label: string;
  detail?: string;
  icon: PixelIconName;
  run: () => void;
  disabled?: string;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useAppState();
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    if (open) {
      setQ('');
      setActive(0);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const go = (to: string) => () => {
      onClose();
      navigate(to);
    };
    const cap = (c: Capability) =>
      s.session.orgId
        ? authorize(s, s.session.actor, c, { orgId: s.session.orgId, projectId: s.session.projectId ?? undefined })
        : { ok: false, reason: 'Aucune organisation active.' };
    const actions: (Omit<Item, 'disabled'> & { cap?: Capability })[] = [
      { id: 'a-quest', group: 'Actions', label: 'Créer une quête', icon: 'plus', run: go('/quetes?nouvelle=1'), cap: 'edit' },
      { id: 'a-project', group: 'Actions', label: 'Créer un projet', icon: 'plus', run: go('/royaume/projets?nouveau=1'), cap: 'edit' },
      {
        id: 'a-council',
        group: 'Actions',
        label: 'Préparer une session du Conseil',
        icon: 'council',
        run: go('/conseil?nouveau=1'),
        cap: 'propose',
      },
      { id: 'a-deliv', group: 'Actions', label: 'Créer un livrable', icon: 'anvil', run: go('/forge/studio?nouveau=1'), cap: 'edit' },
      {
        id: 'a-import',
        group: 'Actions',
        label: 'Importer des références',
        icon: 'upload',
        run: go('/bibliotheque/import'),
        cap: 'configure_org',
      },
      {
        id: 'a-export',
        group: 'Actions',
        label: 'Exporter le profil (Blueprint)',
        icon: 'download',
        run: go('/blueprint/export'),
        cap: 'export',
      },
      {
        id: 'a-mode',
        group: 'Actions',
        label: `Passer en mode ${s.prefs.mode === 'explorer' ? 'Pro' : 'RPG'}`,
        icon: s.prefs.mode === 'explorer' ? 'focus' : 'map',
        run: () => {
          dispatch(cmd.setPreference, { mode: s.prefs.mode === 'explorer' ? 'focus' : 'explorer' }, { silent: true });
          onClose();
        },
      },
      {
        id: 'a-guide',
        group: 'Démonstration',
        label: 'Afficher le parcours de démonstration',
        icon: 'flag',
        run: () => {
          dispatch(cmd.setPreference, { guideOpen: true }, { silent: true });
          onClose();
        },
      },
      {
        id: 'a-actor',
        group: 'Démonstration',
        label: 'Changer d’acteur (paramètres de démonstration)',
        icon: 'user',
        run: go('/intendance/demo'),
      },
    ];
    const allowedActions: Item[] = actions.map(({ cap: c, ...a }) => {
      const d = c ? cap(c) : { ok: true };
      return { ...a, disabled: d.ok ? undefined : (d as { reason?: string }).reason };
    });
    const places: Item[] = PLACES.map((p) => ({
      id: `p-${p.key}`,
      group: 'Lieux',
      label: p.name,
      detail: p.role,
      icon: p.icon,
      run: go(p.route),
    }));
    if (!q.trim()) return [...places, ...allowedActions];
    const nq = q.toLowerCase();
    const hits: Item[] = searchAll(s, q, 24).map((h) => ({
      id: `${h.ref.kind}-${h.ref.id}`,
      group: 'Résultats',
      label: h.title,
      detail: h.subtitle,
      icon:
        h.ref.kind === 'reference'
          ? 'book'
          : h.ref.kind === 'quest'
            ? 'quest'
            : h.ref.kind === 'decision' || h.ref.kind === 'council'
              ? 'council'
              : h.ref.kind === 'expert'
                ? 'ai'
                : 'link',
      run: go(routeOf(h.ref)),
    }));
    return [
      ...places.filter((p) => p.label.toLowerCase().includes(nq) || p.detail!.toLowerCase().includes(nq)),
      ...allowedActions.filter((a) => a.label.toLowerCase().includes(nq)),
      ...hits,
    ];
  }, [q, s, onClose]);

  useEffect(() => {
    setActive(0);
  }, [q]);
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [active]);
  const enabled = items.filter((i) => !i.disabled);

  return (
    <Dialog open={open} onClose={onClose} title="Rechercher ou agir" wide>
      <div className="field">
        <label htmlFor="palette-q" className="sr-only">
          Recherche
        </label>
        <input
          id="palette-q"
          autoFocus
          value={q}
          placeholder="Nom, sigle (RGPD, SemVer, ASVS…), quête, décision, document…"
          role="combobox"
          aria-expanded
          aria-controls="palette-list"
          aria-activedescendant={enabled[active] ? `pal-${enabled[active].id}` : undefined}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, enabled.length - 1));
            }
            if (e.key === 'ArrowUp') {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            }
            if (e.key === 'Enter') {
              e.preventDefault();
              enabled[active]?.run();
            }
          }}
        />
      </div>
      <ul id="palette-list" role="listbox" ref={listRef} className="plain palette-list" aria-label="Résultats">
        {items.length === 0 && (
          <li className="muted" style={{ padding: 12 }}>
            Aucun résultat pour « {q} ». Essayez un sigle ou une partie du nom.
          </li>
        )}
        {items.map((it, i) => {
          const first = i === 0 || items[i - 1].group !== it.group;
          const idx = enabled.indexOf(it);
          return (
            <li key={it.id} role="presentation">
              {first && <p className="menu-label">{it.group}</p>}
              <button
                id={`pal-${it.id}`}
                role="option"
                aria-selected={idx === active}
                aria-disabled={!!it.disabled}
                disabled={!!it.disabled}
                className="palette-item"
                onMouseEnter={() => idx >= 0 && setActive(idx)}
                onClick={it.run}
              >
                <Icon name={it.disabled ? 'lock' : it.icon} size={14} />
                <span className="grow">
                  <span>{it.label}</span>
                  {(it.detail || it.disabled) && (
                    <span className="tiny muted" style={{ display: 'block' }}>
                      {it.disabled ?? it.detail}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Dialog>
  );
}
