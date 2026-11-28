/** Bibliothèque: the reference library, the stack patterns, the rule packs and the sectors of the catalog. */
import { useMemo } from 'react';
import { setQuery, useRoute } from '@/shared/router';
import { Badge, Empty, KV, Panel, Tabs } from '@/shared/ui/core';
import { Icon } from '@/shared/pixel/icons';
import { norm } from '@/shared/text';
import { useProfile } from '../data';
import { useCli } from '../query';
import { ExternalLink, Q, TableBox } from '../parts';
import type { Catalog, Pattern, Reference, RulePlan } from '../types';

const PAGE = 60;

export function Library({ tab = 'references' }: { tab?: string }) {
  return (
    <div className="page-grid">
      <Tabs
        label="Bibliothèque"
        value={tab}
        onChange={(t) => {
          window.location.hash = `#/bibliotheque/${t}`;
        }}
        tabs={[
          { id: 'references', label: 'Références', icon: 'book' },
          { id: 'patterns', label: 'Modèles de projet', icon: 'grid' },
          { id: 'packs', label: 'Packs de règles', icon: 'scroll' },
          { id: 'secteurs', label: 'Secteurs', icon: 'map' },
        ]}
      />
      {tab === 'patterns' ? <Patterns /> : tab === 'packs' ? <Packs /> : tab === 'secteurs' ? <Sectors /> : <References />}
    </div>
  );
}

function useFilter() {
  const route = useRoute();
  return {
    q: route.query.get('q') ?? '',
    family: route.query.get('famille') ?? '',
    brain: route.query.get('cerveau') ?? '',
    page: Number(route.query.get('page') ?? 1),
  };
}

function References() {
  const refs = useCli<Reference[]>(['references', '--json']);
  const { q, family, brain, page } = useFilter();
  const families = useMemo(
    () => [...new Map((refs.data ?? []).map((r) => [r.family, r.family_title])).entries()].sort((a, b) => a[1].localeCompare(b[1])),
    [refs.data],
  );
  const brains = useMemo(() => [...new Set((refs.data ?? []).flatMap((r) => r.brains ?? []))].sort(), [refs.data]);
  const shown = useMemo(() => {
    const words = norm(q).split(/\s+/).filter(Boolean);
    return (refs.data ?? []).filter(
      (r) =>
        (!family || r.family === family) &&
        (!brain || (r.brains ?? []).includes(brain)) &&
        words.every((w) =>
          norm(`${r.id} ${r.title} ${(r.aliases ?? []).join(' ')} ${r.summary} ${r.applies_when} ${r.category}`).includes(w),
        ),
    );
  }, [refs.data, q, family, brain]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  return (
    <>
      <div className="toolbar">
        <input
          className="input"
          type="search"
          placeholder="Norme, méthode, sigle…"
          aria-label="Rechercher une référence"
          value={q}
          onChange={(e) => setQuery({ q: e.target.value, page: null })}
        />
        <select className="input" aria-label="Famille" value={family} onChange={(e) => setQuery({ famille: e.target.value, page: null })}>
          <option value="">Toutes les familles</option>
          {families.map(([id, title]) => (
            <option key={id} value={id}>
              {title}
            </option>
          ))}
        </select>
        <select className="input" aria-label="Cerveau" value={brain} onChange={(e) => setQuery({ cerveau: e.target.value, page: null })}>
          <option value="">Tous les cerveaux</option>
          {brains.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
        <span className="small muted">
          {shown.length} / {refs.data?.length ?? '…'} références
        </span>
      </div>
      <Q q={refs} label="Lecture de la bibliothèque">
        {() =>
          shown.length === 0 ? (
            <Empty title="Aucune référence">Essaie un autre mot ou retire un filtre.</Empty>
          ) : (
            <>
              <ul className="plain ref-grid">
                {shown.slice((page - 1) * PAGE, page * PAGE).map((r) => (
                  <li key={r.id}>
                    <a className="card ref-card" href={`#/bibliotheque/ref/${r.id}`}>
                      <span className="row between">
                        <Badge>{r.family_title}</Badge>
                        <span className="tiny muted">{r.kind}</span>
                      </span>
                      <strong lang="en">{r.title}</strong>
                      <span className="small muted clamp-3" lang="en">
                        {r.summary}
                      </span>
                      <span className="tiny muted">{(r.brains ?? []).join(' · ')}</span>
                    </a>
                  </li>
                ))}
              </ul>
              {pages > 1 && (
                <nav className="row pager" aria-label="Pages">
                  {Array.from({ length: pages }, (_, i) => (
                    <button
                      key={i}
                      className={`btn small ${page === i + 1 ? 'primary' : ''}`}
                      aria-current={page === i + 1 ? 'page' : undefined}
                      onClick={() => setQuery({ page: String(i + 1) })}
                    >
                      {i + 1}
                    </button>
                  ))}
                </nav>
              )}
            </>
          )
        }
      </Q>
    </>
  );
}

export function ReferenceSheet({ id }: { id?: string }) {
  const refs = useCli<Reference[]>(['references', '--json']);
  return (
    <Q q={refs}>
      {(list) => {
        const r = list.find((x) => x.id === id || (x.aliases ?? []).includes(id ?? ''));
        if (!r)
          return (
            <Empty title="Référence introuvable">
              <a href="#/bibliotheque">Revenir à la bibliothèque</a>
            </Empty>
          );
        return (
          <div className="page-grid">
            <p>
              <a href="#/bibliotheque">
                <Icon name="chevron" size={12} /> Bibliothèque
              </a>
            </p>
            <Panel title={<span lang="en">{r.title}</span>}>
              <p lang="en">{r.summary}</p>
              <KV
                items={[
                  [
                    'Quand l’appliquer',
                    <span key="when" lang="en">
                      {r.applies_when}
                    </span>,
                  ],
                  ['Famille', r.family_title],
                  ['Catégorie', r.category],
                  ['Nature', r.kind],
                  [
                    'Cerveaux',
                    (r.brains ?? []).map((b) => (
                      <a key={b} className="target-link" href={`#/guilde/${b}`}>
                        {b}
                      </a>
                    )),
                  ],
                  ['Statut', r.status],
                  ['Identifiant', <code key="id">{r.id}</code>],
                  ...(r.aliases?.length ? [['Alias', r.aliases.join(', ')] as [string, string]] : []),
                ]}
              />
            </Panel>
            <Panel title="Sources">
              <p className="small muted">
                Ce sont des pistes à examiner : l’agent les traite comme des données tant qu’il ne les a pas lues.
              </p>
              <ul lang="en">
                {r.sources.map((s) => (
                  <li key={s.url}>
                    <ExternalLink href={s.url}>{s.title}</ExternalLink>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        );
      }}
    </Q>
  );
}

function Patterns() {
  const patterns = useCli<Pattern[]>(['patterns', '--json']);
  const profile = useProfile();
  const { q } = useFilter();
  const active = new Set((profile.data?.patterns ?? []).map((p) => (typeof p === 'string' ? p : p.id)));
  const shown = (patterns.data ?? []).filter(
    (p) => !q || norm(`${p.id} ${p.title} ${p.description} ${p.roles.join(' ')}`).includes(norm(q)),
  );
  return (
    <>
      <div className="toolbar">
        <input
          className="input"
          type="search"
          placeholder="Pile, méthode, rôle…"
          aria-label="Rechercher un modèle de projet"
          value={q}
          onChange={(e) => setQuery({ q: e.target.value })}
        />
        <span className="small muted">
          {shown.length} modèles de projet · {active.size} actif(s) dans le profil
        </span>
      </div>
      <Q q={patterns}>
        {() => (
          <ul className="plain ref-grid">
            {shown.map((p) => (
              <li key={p.id} className={`card ref-card ${active.has(p.id) ? 'active' : ''}`}>
                <span className="row between">
                  <span className="mono tiny">{p.id}</span>
                  {active.has(p.id) && (
                    <Badge tone="success" icon="check">
                      actif
                    </Badge>
                  )}
                </span>
                <strong lang="en">{p.title}</strong>
                <span className="small muted clamp-3" lang="en">
                  {p.description}
                </span>
                <span className="tiny">
                  Packs : {p.packs.join(', ') || '—'} · rôles : {p.roles.join(', ') || '—'}
                </span>
                {p.sources[0] && (
                  <span className="tiny" lang="en">
                    <ExternalLink href={p.sources[0].url}>{p.sources[0].title}</ExternalLink>
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Q>
    </>
  );
}

function Packs() {
  const catalog = useCli<Catalog>(['catalog', '--json']);
  const plan = useCli<RulePlan>(['preview', '--json']);
  const { q } = useFilter();
  const inForce = new Map((plan.data?.packs ?? []).map((p) => [p.id, p]));
  const packs = Object.values(catalog.data?.packs ?? {})
    .filter((p) => !q || norm(`${p.id} ${p.title} ${p.description}`).includes(norm(q)))
    .sort((a, b) => Number(inForce.has(b.id)) - Number(inForce.has(a.id)) || a.title.localeCompare(b.title));
  return (
    <>
      <div className="toolbar">
        <input
          className="input"
          type="search"
          placeholder="Pack…"
          aria-label="Rechercher un pack"
          value={q}
          onChange={(e) => setQuery({ q: e.target.value })}
        />
        <span className="small muted">
          {packs.length} packs · {inForce.size} en vigueur
        </span>
      </div>
      <Q q={catalog}>
        {() => (
          <div className="stack">
            {packs.map((p) => {
              const force = inForce.get(p.id);
              return (
                <details key={p.id} className={`card pack ${force ? 'active' : ''}`}>
                  <summary>
                    <strong lang="en">{p.title}</strong>{' '}
                    <span className="mono tiny">
                      {p.id} {p.version}
                    </span>{' '}
                    {force && (
                      <Badge tone="success" icon="check">
                        en vigueur
                      </Badge>
                    )}{' '}
                    <span className="tiny muted">{p.rules.length} règle(s)</span>
                  </summary>
                  <p className="small" lang="en">
                    {p.description}
                  </p>
                  {force && <p className="tiny muted">Origine : {force.provenance.join(' · ')}</p>}
                  <TableBox label={`Règles de ${p.title}`}>
                    <table className="data compact">
                      <thead>
                        <tr>
                          <th>Règle</th>
                          <th>Consigne</th>
                          <th>Vérification</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.rules.map((r) => (
                          <tr key={r.id}>
                            <td className="mono tiny" lang="en">
                              {r.id}
                            </td>
                            <td className="small" lang="en">
                              {r.instruction}
                            </td>
                            <td className="small muted" lang="en">
                              {r.verification}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableBox>
                  {p.sources.length > 0 && (
                    <p className="tiny" lang="en">
                      {p.sources.map((s) => (
                        <ExternalLink key={s.url} href={s.url}>
                          {s.title}
                        </ExternalLink>
                      ))}
                    </p>
                  )}
                </details>
              );
            })}
          </div>
        )}
      </Q>
    </>
  );
}

function Sectors() {
  const catalog = useCli<Catalog>(['catalog', '--json']);
  const profile = useProfile();
  return (
    <Q q={catalog}>
      {(c) => (
        <div className="grid-2">
          {Object.values(c.sectors).map((s) => (
            <Panel
              key={s.id}
              title={
                <>
                  <span lang="en">{s.title}</span>{' '}
                  {profile.data?.sector === s.id && (
                    <Badge tone="success" icon="check">
                      secteur du projet
                    </Badge>
                  )}
                </>
              }
            >
              <p className="small" lang="en">
                {s.description}
              </p>
              <ul className="small" lang="en">
                {s.context.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              {s.sources.length > 0 && (
                <p className="tiny" lang="en">
                  {s.sources.map((x) => (
                    <ExternalLink key={x.url} href={x.url}>
                      {x.title}
                    </ExternalLink>
                  ))}
                </p>
              )}
            </Panel>
          ))}
        </div>
      )}
    </Q>
  );
}
