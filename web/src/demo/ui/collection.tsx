/** Shared list pattern: search, filters, sort and grouping, with filters kept in the URL. */
import { useMemo, type ReactNode } from 'react';
import { setQuery, useRoute } from '@/shared/router';
import { norm } from '@/shared/text';
import { Icon } from '@/shared/pixel/icons';

export interface FilterDef<T> { key: string; label: string; options: { value: string; label: string }[]; test: (item: T, value: string) => boolean }
export interface SortDef<T> { key: string; label: string; compare: (a: T, b: T) => number }

export function useCollection<T>(items: T[], opts: { text: (t: T) => string; filters?: FilterDef<T>[]; sorts?: SortDef<T>[]; prefix?: string }) {
  const route = useRoute();
  const p = opts.prefix ?? '';
  const q = route.query.get(`${p}q`) ?? '';
  const sortKey = route.query.get(`${p}tri`) ?? opts.sorts?.[0]?.key ?? '';
  const active = Object.fromEntries((opts.filters ?? []).map((f) => [f.key, route.query.get(`${p}${f.key}`) ?? '']));
  const result = useMemo(() => {
    const tokens = norm(q).split(/\s+/).filter(Boolean);
    let out = items.filter((it) => {
      const text = norm(opts.text(it));
      return tokens.every((t) => text.includes(t)) && (opts.filters ?? []).every((f) => !active[f.key] || f.test(it, active[f.key]));
    });
    const sort = opts.sorts?.find((s) => s.key === sortKey);
    if (sort) out = [...out].sort(sort.compare);
    return out;
  }, [items, q, sortKey, JSON.stringify(active)]); // eslint-disable-line react-hooks/exhaustive-deps -- INTENTIONAL(#522): the active filters object is new at each render, its JSON is the key
  return { items: result, q, sortKey, active, prefix: p };
}

export function CollectionBar<T>({ c, filters = [], sorts = [], placeholder = 'Rechercher…', children, total }: { c: ReturnType<typeof useCollection<T>>; filters?: FilterDef<T>[]; sorts?: SortDef<T>[]; placeholder?: string; children?: ReactNode; total: number }) {
  const p = c.prefix;
  const activeCount = Object.values(c.active).filter(Boolean).length;
  return (
    <div className="collection-bar">
      <div className="field search-field">
        <label className="sr-only" htmlFor={`${p}search`}>{placeholder}</label>
        <input id={`${p}search`} type="search" placeholder={placeholder} defaultValue={c.q} onChange={(e) => setQuery({ [`${p}q`]: e.target.value })} />
      </div>
      {filters.map((f) => (
        <div className="field compact" key={f.key}>
          <label className="sr-only" htmlFor={`${p}f-${f.key}`}>{f.label}</label>
          <select id={`${p}f-${f.key}`} value={c.active[f.key]} onChange={(e) => setQuery({ [`${p}${f.key}`]: e.target.value })}>
            <option value="">{f.label} : tous</option>
            {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      ))}
      {sorts.length > 1 && (
        <div className="field compact">
          <label className="sr-only" htmlFor={`${p}sort`}>Trier</label>
          <select id={`${p}sort`} value={c.sortKey} onChange={(e) => setQuery({ [`${p}tri`]: e.target.value })}>{sorts.map((s) => <option key={s.key} value={s.key}>Tri : {s.label}</option>)}</select>
        </div>
      )}
      {activeCount > 0 && <button className="linklike small" onClick={() => setQuery(Object.fromEntries(filters.map((f) => [`${p}${f.key}`, null])))}><Icon name="close" size={10} /> Effacer les filtres</button>}
      <span className="small muted" aria-live="polite">{c.items.length} / {total}</span>
      <div className="row" style={{ marginLeft: 'auto' }}>{children}</div>
    </div>
  );
}

export function groupBy<T>(items: T[], key: (t: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  items.forEach((it) => { const k = key(it); m.set(k, [...(m.get(k) ?? []), it]); });
  return [...m.entries()];
}
