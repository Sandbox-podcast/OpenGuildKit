/** Chronicles: filterable timeline, decision → evidence trace in both directions, export of a selection and compensations (brief §5.12). */
import { useMemo, useState } from 'react';
import { dispatch, useAppState } from '@/demo/app/store';
import { navigate, setQuery, useRoute } from '@/shared/router';
import { cmd } from '@/demo/domain/commands';
import { COMPENSABLE } from '@/demo/domain/commands/oversight';
import { DAY, get, list, nowOf } from '@/demo/domain/engine';
import { KIND_LABELS, fmtDate, lineage, objectLabel, referenceById } from '@/demo/domain/selectors';
import type { AppState, ID, Ref, RefKind } from '@/demo/domain/types';
import { download, toYaml } from '@/demo/adapters/export';
import { Badge, Checkbox, Empty, Panel, Select, Tabs, TextField } from '@/shared/ui/core';
import { ActorLabel, CmdButton, ObjectLink } from '@/demo/ui/domain';

export function ChroniclesSpace({ tab = 'chronologie' }: { tab?: string }) {
  return (
    <div className="stack">
      <Tabs
        label="Chroniques"
        value={tab}
        onChange={(t) => navigate(`/chroniques/${t}`)}
        tabs={[
          { id: 'chronologie', label: 'Chronologie', icon: 'hourglass' },
          { id: 'trace', label: 'Traçabilité', icon: 'link' },
        ]}
      />
      {tab === 'trace' ? <Trace /> : <Timeline />}
    </div>
  );
}

const ACTION_TYPES: Record<string, string> = {
  blueprint: 'Blueprint',
  rule: 'Règles',
  council: 'Conseil',
  decision: 'Décisions',
  quest: 'Quêtes',
  task: 'Tâches',
  deliverable: 'Livrables',
  run: 'Exécutions',
  result: 'Résultats',
  finding: 'Constats',
  approval: 'Approbations',
  exception: 'Exceptions',
  share: 'Partages',
  signal: 'Veille',
  project: 'Projets',
  member: 'Membres',
  integration: 'Intégrations',
  demo: 'Démonstration',
  export: 'Exports',
  compensation: 'Compensations',
};

function Timeline() {
  const s = useAppState();
  const route = useRoute();
  const all = list(s, 'event', s.session.orgId).sort((a, b) => b.at - a.at);
  const f = {
    projet: route.query.get('projet') ?? '',
    acteur: route.query.get('acteur') ?? '',
    objet: route.query.get('objet') ?? '',
    type: route.query.get('type') ?? '',
    periode: route.query.get('periode') ?? '',
    q: route.query.get('q') ?? '',
  };
  const focus = route.query.get('evenement');
  const now = nowOf(s);
  const events = useMemo(
    () =>
      all.filter(
        (e) =>
          (!f.projet || e.projectId === f.projet) &&
          (!f.acteur ||
            (f.acteur === 'agent'
              ? e.actor.type === 'agent'
              : f.acteur === 'system'
                ? e.actor.type === 'system'
                : e.actor.type === 'human' && e.actor.userId === f.acteur)) &&
          (!f.objet || e.object.kind === f.objet) &&
          (!f.type || e.action.split('.')[0] === f.type) &&
          (!f.periode || e.at >= now - Number(f.periode) * DAY) &&
          (!f.q || e.summary.toLowerCase().includes(f.q.toLowerCase())),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- INTENTIONAL(#522): the filters object is new at each render, its JSON is the key
    [all, JSON.stringify(f), now],
  );
  const [sel, setSel] = useState<ID[]>([]);
  const humans = [...new Set(all.flatMap((e) => (e.actor.type === 'human' ? [e.actor.userId] : [])))];
  const chosen = events.filter((e) => sel.includes(e.id));
  const exportSel = (format: 'json' | 'md' | 'yaml') => {
    const out = dispatch(cmd.recordExport, { what: 'Sélection des Chroniques', format: format.toUpperCase(), count: chosen.length }, {});
    if (!out.ok) return;
    const rows = chosen.map((e) => ({
      date: new Date(e.at).toISOString(),
      acteur:
        e.actor.type === 'human'
          ? s.users[e.actor.userId]?.name
          : e.actor.type === 'agent'
            ? `${s.db.expert[e.actor.expertId]?.name} (agent IA)`
            : 'système',
      type_acteur: e.actor.type,
      action: e.action,
      resume: e.summary,
      objet: `${KIND_LABELS[e.object.kind]} ${objectLabel(s, e.object)}`,
      version: e.object.version ?? null,
      provenance: e.provenance,
      justification: e.justification ?? null,
    }));
    const note = 'Extrait du journal local de démonstration (non inviolable).';
    if (format === 'json')
      download('chroniques.json', 'application/json', JSON.stringify({ format: 'ogk-chroniques/1', note, evenements: rows }, null, 2));
    else if (format === 'yaml') download('chroniques.yaml', 'application/yaml', `# ${note}\n${toYaml(rows)}\n`);
    else
      download(
        'chroniques.md',
        'text/markdown',
        `# Chroniques\n\n> ${note}\n\n${rows.map((r) => `- **${r.date}** — ${r.acteur} (${r.type_acteur}) : ${r.resume}${r.justification ? ` — _${r.justification}_` : ''}`).join('\n')}\n`,
      );
  };
  return (
    <Panel
      title={`Événements (${events.length} / ${all.length})`}
      actions={
        <>
          <span className="small muted">
            {chosen.length} {chosen.length === 1 ? 'événement sélectionné' : 'événements sélectionnés'}
          </span>
          {(['json', 'yaml', 'md'] as const).map((fm) => (
            <CmdButton
              key={fm}
              def={cmd.recordExport}
              payload={{ what: 'Chroniques', format: fm, count: chosen.length }}
              size="small"
              icon="download"
              onRun={() => exportSel(fm)}
              showReason={false}
            >
              {fm.toUpperCase()}
            </CmdButton>
          ))}
        </>
      }
    >
      <div className="collection-bar">
        <div className="field search-field">
          <label className="sr-only" htmlFor="chr-q">
            Rechercher
          </label>
          <input
            id="chr-q"
            type="search"
            placeholder="Rechercher dans les événements"
            defaultValue={f.q}
            onChange={(e) => setQuery({ q: e.target.value })}
          />
        </div>
        <Select
          label={<span className="sr-only">Projet</span>}
          value={f.projet}
          placeholder="Tous les projets"
          onChange={(e) => setQuery({ projet: e.target.value })}
          options={list(s, 'project', s.session.orgId).map((p) => ({ value: p.id, label: p.name }))}
        />
        <Select
          label={<span className="sr-only">Acteur</span>}
          value={f.acteur}
          placeholder="Tous les acteurs"
          onChange={(e) => setQuery({ acteur: e.target.value })}
          options={[
            { value: 'agent', label: 'Agents IA' },
            { value: 'system', label: 'Système' },
            ...humans.map((h) => ({ value: h, label: s.users[h]?.name ?? h })),
          ]}
        />
        <Select
          label={<span className="sr-only">Objet</span>}
          value={f.objet}
          placeholder="Tous les objets"
          onChange={(e) => setQuery({ objet: e.target.value })}
          options={[...new Set(all.map((e) => e.object.kind))].map((k) => ({ value: k, label: KIND_LABELS[k] }))}
        />
        <Select
          label={<span className="sr-only">Type</span>}
          value={f.type}
          placeholder="Tous les types"
          onChange={(e) => setQuery({ type: e.target.value })}
          options={Object.entries(ACTION_TYPES).map(([k, v]) => ({ value: k, label: v }))}
        />
        <Select
          label={<span className="sr-only">Période</span>}
          value={f.periode}
          placeholder="Toute période"
          onChange={(e) => setQuery({ periode: e.target.value })}
          options={[
            { value: '1', label: '24 dernières heures' },
            { value: '7', label: '7 derniers jours' },
            { value: '30', label: '30 derniers jours' },
            { value: '90', label: '90 derniers jours' },
          ]}
        />
      </div>
      <p className="tiny muted">Journal local de démonstration, modifiable dans ce navigateur.</p>
      {events.length === 0 ? (
        <Empty title="Aucun événement pour ces filtres" />
      ) : (
        events.slice(0, 300).map((e) => (
          <div key={e.id} className={`event-row ${focus === e.id ? 'card selected' : ''}`}>
            <div>
              <Checkbox
                label={<span className="tiny">{fmtDate(e.at, true)}</span>}
                checked={sel.includes(e.id)}
                onChange={(ev) => setSel(ev.target.checked ? [...sel, e.id] : sel.filter((x) => x !== e.id))}
              />
            </div>
            <div>
              <div className="row">
                <ActorLabel actor={e.actor} />
                {e.provenance !== 'local' && <Badge tone="ai">{e.provenance}</Badge>}
                {e.compensates && (
                  <Badge tone="warning" icon="replace">
                    compensation
                  </Badge>
                )}
              </div>
              <p style={{ margin: '4px 0' }}>{e.summary}</p>
              {e.justification && (
                <p className="tiny muted" style={{ margin: 0 }}>
                  Justification : {e.justification}
                </p>
              )}
              <div className="row small">
                <ObjectLink to={e.object} />
                {e.related.map((r) => (
                  <ObjectLink key={`${r.kind}${r.id}`} to={r} />
                ))}
              </div>
            </div>
            <div className="stack tight">
              <a className="small" href={`#/chroniques/trace?kind=${e.object.kind}&id=${e.object.id}`}>
                Tracer
              </a>
              {COMPENSABLE.includes(e.action) && !all.some((x) => x.compensates === e.id) && (
                <CmdButton
                  def={cmd.compensateEvent}
                  payload={{ eventId: e.id, reason: '' }}
                  size="small"
                  variant="ghost"
                  icon="replace"
                  success={(r) => `Compensation : ${r}`}
                  showReason={false}
                  confirm={{
                    title: 'Compenser cet événement',
                    message: <p>Un événement compensatoire est ajouté ; l’historique n’est jamais réécrit.</p>,
                    needsReason: true,
                    label: 'Compenser',
                  }}
                >
                  Compenser
                </CmdButton>
              )}
            </div>
          </div>
        ))
      )}
    </Panel>
  );
}

const ORDER: RefKind[] = [
  'blueprint',
  'rule',
  'reference',
  'signal',
  'opportunity',
  'council',
  'decision',
  'quest',
  'deliverable',
  'run',
  'result',
  'evidence',
  'finding',
  'exception',
  'approval',
  'share',
  'review',
  'control',
  'applicability',
];

function canTrace(s: AppState, ref: Ref): boolean {
  const orgId = s.session.orgId;
  if (!orgId || !ref.id || !Object.hasOwn(KIND_LABELS, ref.kind)) return false;
  if (ref.kind === 'org') return ref.id === orgId;
  if (ref.kind === 'user') return list(s, 'member', orgId).some((member) => member.userId === ref.id);
  if (ref.kind === 'reference') return !!referenceById(s, ref.id);
  return get(s, ref.kind, ref.id)?.orgId === orgId;
}

function Trace() {
  const s = useAppState();
  const route = useRoute();
  const requested = route.query.get('id');
  const kind = (requested && (route.query.get('kind') as RefKind)) || 'deliverable';
  const doc = list(s, 'deliverable', s.session.orgId).find((d) => d.docCategory === 'guide' && d.status === 'published');
  const id = requested ?? doc?.id ?? '';
  const start = useMemo(() => {
    const ref: Ref = { kind, id };
    return canTrace(s, ref) ? ref : undefined;
  }, [s, kind, id]);
  const nodes = useMemo(() => (start ? lineage(s, start, 6).filter((node) => canTrace(s, node.ref)) : []), [s, start]);
  const [q, setQ] = useState('');
  const candidates = [
    ...list(s, 'deliverable', s.session.orgId).map((d) => ({ ref: { kind: 'deliverable' as const, id: d.id }, label: d.title })),
    ...list(s, 'decision', s.session.orgId).map((d) => ({
      ref: { kind: 'decision' as const, id: d.id },
      label: `Décision ${d.title} v${d.number}`,
    })),
    ...list(s, 'quest', s.session.orgId).map((x) => ({ ref: { kind: 'quest' as const, id: x.id }, label: `Quête ${x.title}` })),
  ]
    .filter((c) => !q || c.label.toLowerCase().includes(q.toLowerCase()))
    .slice(0, 30);
  const kinds = start && !ORDER.includes(start.kind) ? [start.kind, ...ORDER] : ORDER;
  const columns = kinds.map((k) => ({ k, items: nodes.filter((n) => n.ref.kind === k) })).filter((c) => c.items.length);
  const startOption =
    start && !candidates.some((c) => c.ref.kind === start.kind && c.ref.id === start.id)
      ? [{ value: `${start.kind}:${start.id}`, label: objectLabel(s, start) }]
      : [];
  return (
    <div className="stack">
      <Panel title="Point de départ">
        <div className="grid-2">
          <TextField
            label="Rechercher un objet"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Livrable, décision ou quête"
          />
          <Select
            label="Objet de départ"
            placeholder="Choisir un objet"
            value={start ? `${start.kind}:${start.id}` : ''}
            onChange={(e) => {
              const [k, i] = e.target.value.split(':');
              setQuery({ kind: k, id: i });
            }}
            options={[...startOption, ...candidates.map((c) => ({ value: `${c.ref.kind}:${c.ref.id}`, label: c.label }))]}
          />
        </div>
      </Panel>
      {!start ? (
        <Empty title={requested ? 'Objet introuvable dans cette organisation' : 'Aucun objet sélectionné'} />
      ) : (
        <Panel title={`Liens de "${objectLabel(s, start)}"`}>
          <p className="small muted">
            En amont, consultez les règles et décisions liées. En aval, retrouvez les exécutions, les preuves et les validations.
          </p>
          <div className="trace">
            {columns.map((c) => (
              <section key={c.k} className="trace-col">
                <h3>{KIND_LABELS[c.k]}</h3>
                {c.items.map((n) => (
                  <div key={`${n.ref.kind}${n.ref.id}${n.ref.version ?? ''}`} className={`card ${n.distance === 0 ? 'origin' : ''}`}>
                    <ObjectLink to={n.ref} />
                    <div className="row tiny" style={{ marginTop: 4 }}>
                      <Badge tone={n.direction === 'origine' ? 'warning' : n.direction === 'amont' ? 'info' : 'ai'}>{n.direction}</Badge>
                      {n.distance > 0 && (
                        <button
                          className="linklike"
                          aria-label={`Explorer les liens de ${objectLabel(s, n.ref)}`}
                          onClick={() => setQuery({ kind: n.ref.kind, id: n.ref.id })}
                        >
                          Explorer ses liens
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </section>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
