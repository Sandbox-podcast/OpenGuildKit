/** Quests: board, list and calendar, quest sheet with closure checklist, tasks and dependencies (brief §5.7). */
import { useState } from 'react';
import { NotFound } from '@/demo/app/App';
import { can, dispatch, newOpId, useAppState } from '@/demo/app/store';
import { setQuery, useRoute } from '@/shared/router';
import { routeOf } from '@/demo/app/routes';
import { cmd } from '@/demo/domain/commands';
import { list } from '@/demo/domain/engine';
import { stateDef, transitionsFrom, type TransitionDef } from '@/demo/domain/machines';
import { toast } from '@/shared/ui/toast';
import { DELIVERABLE_TYPES, closureReport, fmtDate, latestResults, questProgress, resultFreshness } from '@/demo/domain/selectors';
import type { DeliverableType, ID, Quest, QuestState, QuestType } from '@/demo/domain/types';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Checkbox, Empty, KV, Notice, Panel, Progress, Segmented, Select, TextArea, TextField } from '@/shared/ui/core';
import { CollectionBar, groupBy, useCollection } from '@/demo/ui/collection';
import { ConfirmDialog, Dialog } from '@/shared/ui/overlay';
import {
  ActorLabel,
  ApprovalList,
  ApproverPicker,
  CmdButton,
  Lifecycle,
  ObjectLink,
  Person,
  SimBadge,
  StatusBadge,
  Version,
} from '@/demo/ui/domain';

const COLUMNS: QuestState[] = ['todo', 'ready', 'doing', 'blocked', 'review', 'done', 'cancelled'];
const TYPES: QuestType[] = ['fonctionnalité', 'correction', 'sécurité', 'documentation', 'design', 'performance', 'campagne'];
const SKILL_FOR: Partial<Record<DeliverableType, string>> = {
  spec: 'spec',
  adr: 'adr',
  code: 'code',
  tests: 'tests',
  component: 'ui',
  gallery: 'gallery',
  api: 'api',
  doc: 'doc',
  changelog: 'changelog',
  roadmap: 'roadmap',
  landing: 'landing',
  presentation: 'slides',
  video: 'video',
};

export function QuestsSpace() {
  const s = useAppState();
  const route = useRoute();
  const view = route.query.get('vue') ?? 'tableau';
  const quests = list(s, 'quest', s.session.orgId);
  const projects = list(s, 'project', s.session.orgId);
  const filters = [
    {
      key: 'projet',
      label: 'Projet',
      options: projects.map((p) => ({ value: p.id, label: p.name })),
      test: (q: Quest, v: string) => q.projectId === v,
    },
    { key: 'type', label: 'Type', options: TYPES.map((t) => ({ value: t, label: t })), test: (q: Quest, v: string) => q.type === v },
    {
      key: 'priorite',
      label: 'Priorité',
      options: ['P1', 'P2', 'P3', 'P4'].map((p) => ({ value: p, label: p })),
      test: (q: Quest, v: string) => q.priority === v,
    },
    {
      key: 'origine',
      label: 'Origine',
      options: [
        { value: 'decision', label: 'Décision' },
        { value: 'direct', label: 'Création directe' },
        { value: 'finding', label: 'Constat' },
        { value: 'signal', label: 'Signal' },
      ],
      test: (q: Quest, v: string) => q.origin === v,
    },
    {
      key: 'responsable',
      label: 'Responsable',
      options: [...new Set(quests.map((q) => q.ownerId).filter(Boolean))].map((id) => ({ value: id!, label: s.users[id!]?.name ?? id! })),
      test: (q: Quest, v: string) => q.ownerId === v,
    },
  ];
  const sorts = [
    { key: 'ordre', label: 'Ordre', compare: (a: Quest, b: Quest) => a.order - b.order },
    { key: 'priorite', label: 'Priorité', compare: (a: Quest, b: Quest) => a.priority.localeCompare(b.priority) },
    { key: 'echeance', label: 'Échéance', compare: (a: Quest, b: Quest) => (a.due ?? '9').localeCompare(b.due ?? '9') },
    { key: 'titre', label: 'Titre', compare: (a: Quest, b: Quest) => a.title.localeCompare(b.title) },
  ];
  const c = useCollection(quests, { text: (q) => `${q.title} ${q.objective} ${q.type}`, filters, sorts });
  const [creating, setCreating] = useState(route.query.get('nouvelle') === '1');
  return (
    <Panel
      title="Quêtes"
      actions={
        <>
          <Segmented
            label="Vue"
            value={view}
            onChange={(v) => setQuery({ vue: v })}
            options={[
              { value: 'tableau', label: 'Tableau', icon: 'grid' },
              { value: 'liste', label: 'Liste', icon: 'list' },
              { value: 'calendrier', label: 'Calendrier', icon: 'calendar' },
            ]}
          />
          <CmdButton
            def={cmd.createQuest}
            payload={{
              projectId: s.session.projectId ?? projects[0]?.id ?? '',
              title: 'xxxx',
              objective: 'xxxxxxxxxx',
              type: 'fonctionnalité',
              priority: 'P2',
              criteria: [],
              expectedDeliverables: [],
              controlIds: [],
            }}
            variant="primary"
            icon="plus"
            onRun={() => setCreating(true)}
          >
            Nouvelle quête
          </CmdButton>
        </>
      }
    >
      <CollectionBar c={c} filters={filters} sorts={sorts} total={quests.length} placeholder="Rechercher une quête" />
      {c.items.length === 0 ? (
        <Empty title="Aucune quête ne correspond">Modifiez les filtres ou créez une quête.</Empty>
      ) : view === 'liste' ? (
        <QuestList quests={c.items} groupKey={route.query.get('groupe') ?? 'projet'} />
      ) : view === 'calendrier' ? (
        <Calendar quests={c.items} />
      ) : (
        <Board quests={c.items} />
      )}
      <QuestForm
        open={creating}
        onClose={() => {
          setCreating(false);
          setQuery({ nouvelle: null });
        }}
      />
    </Panel>
  );
}

/** The transition that moves a quest from its state to a target column, if any. */
const transitionTo = (from: QuestState, to: QuestState): TransitionDef | undefined =>
  transitionsFrom('quest', from).find((t) => t.to === to);

function Board({ quests }: { quests: Quest[] }) {
  const s = useAppState();
  const [drag, setDrag] = useState<ID | null>(null);
  const [over, setOver] = useState<QuestState | null>(null);
  const [pending, setPending] = useState<{ q: Quest; t: TransitionDef } | null>(null);
  const move = (q: Quest, to: QuestState) => {
    if (q.status === to) return;
    const t = transitionTo(q.status, to);
    if (!t) {
      // No direct move: closing still goes through its guard so the precise blocking reason is shown (RG-24).
      if (to === 'done') {
        dispatch(cmd.transition, { kind: 'quest', id: q.id, action: 'close' }, {});
        return;
      }
      const possible = transitionsFrom('quest', q.status)
        .map((x) => `${x.label} (→ ${stateDef('quest', x.to).label})`)
        .join(', ');
      toast({
        tone: 'danger',
        title: 'Déplacement impossible',
        text: `Aucune transition de « ${stateDef('quest', q.status).label} » vers « ${stateDef('quest', to).label} ». Possibles : ${possible || 'aucune'}.`,
      });
      return;
    }
    if (t.needsReason) {
      setPending({ q, t });
      return;
    }
    dispatch(cmd.transition, { kind: 'quest', id: q.id, action: t.action }, { success: `${t.label} : « ${q.title} »` });
  };
  return (
    <>
      <p className="tiny muted">
        Glissez une carte, ou sélectionnez-la et utilisez <kbd>Alt</kbd>+<kbd>←</kbd>/<kbd>→</kbd> (ou le menu « Déplacer »). Une transition
        impossible explique sa cause.
      </p>
      <div className="board">
        {COLUMNS.map((col) => {
          const items = quests.filter((q) => q.status === col);
          const d = stateDef('quest', col);
          return (
            <section
              key={col}
              className={`board-col ${over === col ? 'drop' : ''}`}
              aria-label={`${d.label} (${items.length})`}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(col);
              }}
              onDragLeave={() => setOver(null)}
              onDrop={(e) => {
                e.preventDefault();
                setOver(null);
                const q = quests.find((x) => x.id === drag);
                if (q) move(q, col);
                setDrag(null);
              }}
            >
              <h3>
                <Icon name={d.icon} size={14} />
                {d.label}
                <span className="badge count">{items.length}</span>
              </h3>
              {items.map((q) => (
                <QuestCard key={q.id} q={q} draggingId={drag} onDrag={setDrag} onMove={(to) => move(q, to)} />
              ))}
              {items.length === 0 && (
                <p className="tiny muted" style={{ textAlign: 'center' }}>
                  Aucune quête
                </p>
              )}
            </section>
          );
        })}
      </div>
      {pending && (
        <ConfirmDialog
          open
          title={`${pending.t.label} « ${pending.q.title} »`}
          needsReason
          confirmLabel={pending.t.label}
          danger={pending.t.danger}
          onClose={() => setPending(null)}
          onConfirm={(reason) => {
            dispatch(
              cmd.transition,
              { kind: 'quest', id: pending.q.id, action: pending.t.action, reason },
              { success: `${pending.t.label} : fait` },
            );
            setPending(null);
          }}
        />
      )}
      <span className="sr-only" aria-live="assertive">
        {drag ? `Carte ${s.db.quest[drag]?.title} saisie` : ''}
      </span>
    </>
  );
}

function QuestCard({
  q,
  draggingId,
  onDrag,
  onMove,
}: {
  q: Quest;
  draggingId: ID | null;
  onDrag: (id: ID | null) => void;
  onMove: (to: QuestState) => void;
}) {
  const s = useAppState();
  const pr = questProgress(s, q);
  const [menu, setMenu] = useState(false);
  const idx = COLUMNS.indexOf(q.status);
  return (
    <article
      className="card quest-card"
      draggable
      aria-grabbed={draggingId === q.id}
      tabIndex={0}
      aria-label={`${q.title}, ${stateDef('quest', q.status).label}, priorité ${q.priority}`}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', q.id);
        onDrag(q.id);
      }}
      onDragEnd={() => onDrag(null)}
      onKeyDown={(e) => {
        if (e.altKey && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
          e.preventDefault();
          onMove(COLUMNS[Math.max(0, Math.min(COLUMNS.length - 1, idx + (e.key === 'ArrowRight' ? 1 : -1)))]);
        }
      }}
    >
      <a href={`#/quetes/${q.id}`} style={{ color: 'var(--text)', fontWeight: 600 }}>
        {q.title}
      </a>
      <div className="meta">
        <Badge tone={q.priority === 'P1' ? 'danger' : q.priority === 'P2' ? 'warning' : 'neutral'}>{q.priority}</Badge>
        <span className="muted">{q.type}</span>
        {q.due && (
          <span className="muted">
            <Icon name="calendar" size={10} /> {new Date(q.due).toLocaleDateString('fr-FR')}
          </span>
        )}
        {q.origin === 'decision' && (
          <Badge tone="ai" icon="council">
            décision
          </Badge>
        )}
        {q.origin === 'finding' && (
          <Badge tone="danger" icon="warn">
            constat
          </Badge>
        )}
      </div>
      {q.status === 'blocked' && q.statusReason && (
        <p className="tiny" style={{ color: 'var(--danger)', margin: '4px 0 0' }}>
          <Icon name="lock" size={10} /> {q.statusReason}
        </p>
      )}
      <div style={{ marginTop: 6 }}>
        <Progress value={pr.pct} label={`Avancement de ${q.title}`} />
      </div>
      <div className="row between" style={{ marginTop: 4 }}>
        <span className="tiny muted">{s.db.project[q.projectId]?.name}</span>
        <button className="linklike tiny" aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
          Déplacer…
        </button>
      </div>
      {menu && (
        <div className="stack tight" style={{ marginTop: 4 }}>
          <Lifecycle kind="quest" id={q.id} state={q.status} compact />
        </div>
      )}
    </article>
  );
}

function QuestList({ quests, groupKey }: { quests: Quest[]; groupKey: string }) {
  const s = useAppState();
  const groups = groupBy(quests, (q) =>
    groupKey === 'type'
      ? q.type
      : groupKey === 'etat'
        ? stateDef('quest', q.status).label
        : groupKey === 'responsable'
          ? (s.users[q.ownerId ?? '']?.name ?? 'Non assigné')
          : (s.db.project[q.projectId]?.name ?? '—'),
  );
  return (
    <div className="stack">
      <Segmented
        label="Regrouper par"
        value={groupKey}
        onChange={(v) => setQuery({ groupe: v })}
        options={[
          { value: 'projet', label: 'Projet' },
          { value: 'type', label: 'Type' },
          { value: 'etat', label: 'État' },
          { value: 'responsable', label: 'Responsable' },
        ]}
      />
      {groups.map(([g, items]) => (
        <section key={g}>
          <h3>
            {g} <span className="badge count">{items.length}</span>
          </h3>
          <table className="data responsive">
            <thead>
              <tr>
                <th>Quête</th>
                <th>État</th>
                <th>Priorité</th>
                <th>Échéance</th>
                <th>Responsable</th>
                <th>Avancement</th>
              </tr>
            </thead>
            <tbody>
              {items.map((q) => {
                const pr = questProgress(s, q);
                return (
                  <tr key={q.id}>
                    <td data-label="Quête">
                      <a href={`#/quetes/${q.id}`}>{q.title}</a>
                    </td>
                    <td data-label="État">
                      <StatusBadge kind="quest" state={q.status} />
                    </td>
                    <td data-label="Priorité">{q.priority}</td>
                    <td data-label="Échéance">{q.due ? new Date(q.due).toLocaleDateString('fr-FR') : '—'}</td>
                    <td data-label="Responsable">
                      <Person id={q.ownerId} />
                    </td>
                    <td data-label="Avancement" style={{ minWidth: 120 }}>
                      <Progress value={pr.pct} label={`Avancement ${q.title}`} />
                      <span className="tiny muted">
                        {pr.done}/{pr.total}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

function Calendar({ quests }: { quests: Quest[] }) {
  const s = useAppState();
  const now = new Date(Date.now() + s.demo.timeOffsetMs);
  const [offset, setOffset] = useState(0);
  const month = new Date(now.getFullYear(), now.getMonth() + offset, 1);
  const start = new Date(month);
  start.setDate(1 - ((month.getDay() + 6) % 7));
  const days = Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const noDue = quests.filter((q) => !q.due);
  return (
    <div className="stack">
      <div className="row between">
        <Button size="small" onClick={() => setOffset((o) => o - 1)} aria-label="Mois précédent">
          ‹
        </Button>
        <h3 style={{ margin: 0, textTransform: 'capitalize' }}>{month.toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })}</h3>
        <Button size="small" onClick={() => setOffset((o) => o + 1)} aria-label="Mois suivant">
          ›
        </Button>
      </div>
      <div className="calendar" role="grid" aria-label="Échéances des quêtes">
        {['lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.', 'dim.'].map((d) => (
          <div key={d} className="dow" role="columnheader">
            {d}
          </div>
        ))}
        {days.map((d) => {
          const items = quests.filter((q) => q.due === key(d));
          return (
            <div
              key={key(d)}
              role="gridcell"
              className={`day ${d.getMonth() !== month.getMonth() ? 'other' : ''} ${key(d) === key(now) ? 'today' : ''}`}
              aria-label={`${d.toLocaleDateString('fr-FR')} : ${items.length} quête(s)`}
            >
              <span className="tiny">{d.getDate()}</span>
              {items.map((q) => (
                <a
                  key={q.id}
                  href={`#/quetes/${q.id}`}
                  title={q.title}
                  style={{
                    borderLeftColor: `var(--${stateDef('quest', q.status).tone === 'danger' ? 'danger' : stateDef('quest', q.status).tone === 'success' ? 'success' : 'data'})`,
                  }}
                >
                  {q.title}
                </a>
              ))}
            </div>
          );
        })}
      </div>
      {noDue.length > 0 && (
        <p className="small muted">
          Sans échéance :{' '}
          {noDue.map((q) => (
            <a key={q.id} href={`#/quetes/${q.id}`} style={{ marginRight: 8 }}>
              {q.title}
            </a>
          ))}
        </p>
      )}
    </div>
  );
}

function QuestForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useAppState();
  const route = useRoute();
  const projects = list(s, 'project', s.session.orgId).filter((p) => p.status === 'active');
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : undefined;
  const [opId] = useState(newOpId);
  const [v, setV] = useState({
    projectId: route.query.get('projet') ?? s.session.projectId ?? projects[0]?.id ?? '',
    title: route.query.get('titre') ?? '',
    objective: '',
    type: 'fonctionnalité' as QuestType,
    ownerId: me,
    priority: 'P2' as Quest['priority'],
    due: '',
    criteria: '',
    expected: ['spec'] as DeliverableType[],
    controls: [] as string[],
  });
  const [err, setErr] = useState<string | null>(null);
  const originRef = route.query.get('signal') ? { kind: 'signal' as const, id: route.query.get('signal')! } : undefined;
  const submit = () => {
    const out = dispatch(
      cmd.createQuest,
      {
        projectId: v.projectId,
        title: v.title,
        objective: v.objective,
        type: v.type,
        ownerId: v.ownerId,
        priority: v.priority,
        due: v.due || undefined,
        criteria: v.criteria.split('\n'),
        expectedDeliverables: v.expected,
        controlIds: v.controls,
        originRef,
        origin: originRef ? 'signal' : 'direct',
      },
      { opId, silent: true, success: 'Quête créée' },
    );
    if (!out.ok) {
      setErr(out.reason);
      return;
    }
    onClose();
    location.hash = `#/quetes/${out.value}`;
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      wide
      title="Nouvelle quête"
      footer={
        <>
          <Button onClick={onClose}>Annuler</Button>
          <Button variant="primary" onClick={submit}>
            Créer la quête
          </Button>
        </>
      }
    >
      {err && <Notice tone="danger">{err}</Notice>}
      {originRef && (
        <Notice tone="ai">
          Origine : signal de veille <ObjectLink to={originRef} />
        </Notice>
      )}
      <div className="form-grid">
        <TextField
          className="full"
          label="Titre"
          value={v.title}
          onChange={(e) => setV({ ...v, title: e.target.value })}
          error={err && /Titre/.test(err) ? err : null}
        />
        <TextArea
          className="full"
          label="Objectif métier"
          value={v.objective}
          onChange={(e) => setV({ ...v, objective: e.target.value })}
          error={err && /objectif/.test(err) ? err : null}
        />
        <Select
          label="Projet"
          value={v.projectId}
          onChange={(e) => setV({ ...v, projectId: e.target.value })}
          options={projects.map((p) => ({ value: p.id, label: p.name }))}
        />
        <Select
          label="Type"
          value={v.type}
          onChange={(e) => setV({ ...v, type: e.target.value as QuestType })}
          options={TYPES.map((t) => ({ value: t, label: t }))}
        />
        <Select
          label="Responsable"
          value={v.ownerId ?? ''}
          placeholder="Non assigné"
          onChange={(e) => setV({ ...v, ownerId: e.target.value || undefined })}
          options={[...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))].map((id) => ({
            value: id,
            label: s.users[id]?.name ?? id,
          }))}
        />
        <Select
          label="Priorité"
          value={v.priority}
          onChange={(e) => setV({ ...v, priority: e.target.value as Quest['priority'] })}
          options={['P1', 'P2', 'P3', 'P4'].map((p) => ({ value: p, label: p }))}
        />
        <TextField label="Échéance" type="date" value={v.due} onChange={(e) => setV({ ...v, due: e.target.value })} />
        <TextArea
          className="full"
          label="Critères d’acceptation (un par ligne)"
          value={v.criteria}
          onChange={(e) => setV({ ...v, criteria: e.target.value })}
        />
        <fieldset className="full field" style={{ border: 0, padding: 0 }}>
          <legend className="label">Livrables attendus</legend>
          <div className="choice-group">
            {(Object.keys(DELIVERABLE_TYPES) as DeliverableType[]).map((t) => (
              <label key={t} className="choice">
                <input
                  type="checkbox"
                  checked={v.expected.includes(t)}
                  onChange={(e) => setV({ ...v, expected: e.target.checked ? [...v.expected, t] : v.expected.filter((x) => x !== t) })}
                />
                <span>{DELIVERABLE_TYPES[t].label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="full field" style={{ border: 0, padding: 0 }}>
          <legend className="label">Contrôles requis</legend>
          <div className="choice-group">
            {list(s, 'control', s.session.orgId).map((c) => (
              <label key={c.id} className="choice">
                <input
                  type="checkbox"
                  checked={v.controls.includes(c.id)}
                  onChange={(e) =>
                    setV({ ...v, controls: e.target.checked ? [...v.controls, c.id] : v.controls.filter((x) => x !== c.id) })
                  }
                />
                <span>
                  {c.code} {c.blocking ? '(bloquant)' : ''}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ sheet */
export function QuestSheet({ id }: { id: ID }) {
  const s = useAppState();
  const q = s.db.quest[id];
  if (!q || q.orgId !== s.session.orgId) return <NotFound what="Quête" />;
  const report = closureReport(s, q.id);
  const pr = questProgress(s, q);
  const events = list(s, 'event', s.session.orgId)
    .filter((e) => e.object.id === q.id || e.related.some((r) => r.id === q.id))
    .sort((a, b) => b.at - a.at);
  const members = [...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))];
  return (
    <div className="stack">
      <Panel title={q.title} actions={<Lifecycle kind="quest" id={q.id} state={q.status} />}>
        {q.statusReason && (
          <Notice tone={q.status === 'blocked' ? 'danger' : 'warn'} title="Motif :">
            {q.statusReason}
          </Notice>
        )}
        <p>{q.objective}</p>
        <KV
          items={[
            [
              'Origine',
              q.originRef ? (
                <>
                  <ObjectLink to={q.originRef} />{' '}
                  {q.decisionId && q.originRef.kind !== 'decision' && <ObjectLink to={{ kind: 'decision', id: q.decisionId }} />}
                </>
              ) : (
                'Création directe (rattachée à son projet)'
              ),
            ],
            ['Projet', <ObjectLink to={{ kind: 'project', id: q.projectId }} />],
            [
              'Responsable',
              <span className="row">
                <Person id={q.ownerId} />
                <select
                  aria-label="Changer le responsable"
                  value={q.ownerId ?? ''}
                  onChange={(e) =>
                    dispatch(
                      cmd.updateQuest,
                      { id: q.id, patch: { ownerId: e.target.value || undefined } },
                      { success: 'Responsable modifié' },
                    )
                  }
                  disabled={!can(cmd.updateQuest, { id: q.id, patch: {} }).ok}
                  style={{ background: 'var(--bg-deep)', color: 'var(--text)', border: 0, padding: 4 }}
                >
                  <option value="">Non assigné</option>
                  {members.map((m) => (
                    <option key={m} value={m}>
                      {s.users[m]?.name}
                    </option>
                  ))}
                </select>
              </span>,
            ],
            ['Priorité · type', `${q.priority} · ${q.type}`],
            ['Échéance', q.due ? new Date(q.due).toLocaleDateString('fr-FR') : '—'],
            [
              'Avancement',
              <div style={{ maxWidth: 260 }}>
                <Progress value={pr.pct} label="Avancement" />
                <span className="tiny muted">
                  {pr.done}/{pr.total} conditions — indicatif, ne remplace pas la vérification de clôture
                </span>
              </div>,
            ],
          ]}
        />
      </Panel>
      <div className="grid-2">
        <Panel title="Conditions de clôture" tone={report.some((i) => i.status === 'missing') ? 'warn' : 'success'}>
          <ul className="plain closure">
            {report.map((i) => (
              <li key={i.key}>
                <span className={i.status}>
                  <Icon
                    name={i.status === 'ok' ? 'check' : i.status === 'waived' ? 'shield' : i.status === 'info' ? 'dot' : 'cross'}
                    size={14}
                    label={
                      i.status === 'ok'
                        ? 'satisfait'
                        : i.status === 'waived'
                          ? 'couvert par une exception'
                          : i.status === 'info'
                            ? 'informatif'
                            : 'manquant'
                    }
                  />
                </span>
                <span>
                  <strong className="small">{i.label}</strong>
                  <span className="small muted" style={{ display: 'block' }}>
                    {i.detail}
                  </span>
                  {i.fix && (
                    <a className="small" href={`#${typeof i.fix.to === 'string' ? i.fix.to : routeOf(i.fix.to)}`}>
                      {i.fix.label} →
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
        <Criteria q={q} />
      </div>
      <Tasks q={q} />
      <div className="grid-2">
        <QuestDeliverables q={q} />
        <QuestControls q={q} />
      </div>
      <div className="grid-2">
        <Panel title="Validations">
          <ApprovalList subject={{ kind: 'quest', id: q.id }} />
          <RequestClosure q={q} />
        </Panel>
        <Comments q={q} />
      </div>
      <Panel title="Historique">
        <ul className="plain timeline">
          {events.map((e) => (
            <li key={e.id}>
              <span className="tiny muted">{fmtDate(e.at, true)}</span> <ActorLabel actor={e.actor} /> {e.summary}
              {e.justification && <span className="tiny muted"> — {e.justification}</span>}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function Criteria({ q }: { q: Quest }) {
  const [text, setText] = useState('');
  return (
    <Panel title={`Critères d’acceptation (${q.criteria.filter((c) => c.met).length}/${q.criteria.length})`}>
      <ul className="plain stack tight">
        {q.criteria.map((c) => (
          <li key={c.id} className="row between">
            <Checkbox
              label={
                <span>
                  {c.text}
                  {c.required && <span className="tiny muted"> (requis)</span>}
                </span>
              }
              checked={c.met}
              onChange={(e) => dispatch(cmd.setCriterion, { questId: q.id, criterionId: c.id, met: e.target.checked }, {})}
            />
            <button
              className="btn ghost icon small"
              aria-label={`Retirer le critère ${c.text}`}
              onClick={() => dispatch(cmd.setCriterion, { questId: q.id, criterionId: c.id, remove: true }, {})}
            >
              <Icon name="trash" size={12} />
            </button>
          </li>
        ))}
      </ul>
      <div className="row" style={{ marginTop: 6 }}>
        <div className="grow">
          <TextField label="Nouveau critère" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
        <CmdButton
          def={cmd.setCriterion}
          payload={{ questId: q.id, text }}
          size="small"
          success="Critère ajouté"
          onDone={() => setText('')}
        >
          Ajouter
        </CmdButton>
      </div>
    </Panel>
  );
}

function Tasks({ q }: { q: Quest }) {
  const s = useAppState();
  const tasks = list(s, 'task', s.session.orgId)
    .filter((t) => t.questId === q.id)
    .sort((a, b) => a.order - b.order);
  const [titles, setTitles] = useState('');
  const [dep, setDep] = useState<Record<string, string>>({});
  const members = [...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))];
  return (
    <Panel title={`Tâches (${tasks.filter((t) => t.status === 'done').length}/${tasks.length})`}>
      {tasks.length === 0 && <p className="small muted">Aucune tâche : décomposez la quête ci-dessous.</p>}
      {tasks.map((t, i) => (
        <div key={t.id} className="task-row">
          <div>
            <div className="row">
              <StatusBadge kind="task" state={t.status} />
              <strong className="small">{t.title}</strong>
            </div>
            <div className="row tiny" style={{ marginTop: 4 }}>
              <span className="muted">Assignée à</span>
              <select
                aria-label={`Assigner ${t.title}`}
                value={t.assigneeId ?? ''}
                onChange={(e) => dispatch(cmd.updateTask, { id: t.id, assigneeId: e.target.value || null }, {})}
                style={{ background: 'var(--bg-deep)', color: 'var(--text)', border: 0 }}
              >
                <option value="">personne</option>
                {members.map((m) => (
                  <option key={m} value={m}>
                    {s.users[m]?.name}
                  </option>
                ))}
              </select>
              {t.dependsOn.length > 0 && <span className="muted">· dépend de :</span>}
              {t.dependsOn.map((d) => (
                <span key={d} className="chip">
                  {s.db.task[d]?.title}
                  <button
                    className="linklike"
                    aria-label={`Retirer la dépendance ${s.db.task[d]?.title}`}
                    onClick={() => dispatch(cmd.setDependency, { taskId: t.id, dependsOn: d, add: false }, {})}
                  >
                    <Icon name="close" size={9} />
                  </button>
                </span>
              ))}
              <select
                aria-label={`Ajouter une dépendance à ${t.title}`}
                value={dep[t.id] ?? ''}
                onChange={(e) => {
                  setDep({ ...dep, [t.id]: '' });
                  if (e.target.value)
                    dispatch(cmd.setDependency, { taskId: t.id, dependsOn: e.target.value, add: true }, { success: 'Dépendance ajoutée' });
                }}
                style={{ background: 'var(--bg-deep)', color: 'var(--text)', border: 0 }}
              >
                <option value="">+ dépendance…</option>
                {tasks
                  .filter((x) => x.id !== t.id && !t.dependsOn.includes(x.id))
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.title}
                    </option>
                  ))}
              </select>
              {i > 0 && (
                <button
                  className="linklike"
                  onClick={() => {
                    dispatch(cmd.updateTask, { id: t.id, order: tasks[i - 1].order }, { silent: true });
                    dispatch(cmd.updateTask, { id: tasks[i - 1].id, order: t.order }, { silent: true });
                  }}
                  aria-label={`Monter ${t.title}`}
                >
                  ↑
                </button>
              )}
            </div>
            {t.statusReason && (
              <p className="tiny" style={{ color: 'var(--danger)', margin: '2px 0 0' }}>
                {t.statusReason}
              </p>
            )}
          </div>
          <Lifecycle kind="task" id={t.id} state={t.status} compact />
        </div>
      ))}
      <div className="row" style={{ marginTop: 8 }}>
        <div className="grow">
          <TextArea label="Décomposer : nouvelles tâches (une par ligne)" value={titles} onChange={(e) => setTitles(e.target.value)} />
        </div>
        <CmdButton
          def={cmd.addTasks}
          payload={{ questId: q.id, titles: titles.split('\n') }}
          size="small"
          success={(ids) => `${(ids as string[]).length} tâche(s) ajoutée(s)`}
          onDone={() => setTitles('')}
        >
          Ajouter
        </CmdButton>
      </div>
    </Panel>
  );
}

function QuestDeliverables({ q }: { q: Quest }) {
  const s = useAppState();
  const linked = q.deliverableIds.map((id) => s.db.deliverable[id]).filter(Boolean);
  const candidates = list(s, 'deliverable', s.session.orgId).filter((d) => d.projectId === q.projectId && !q.deliverableIds.includes(d.id));
  const [pick, setPick] = useState('');
  const runningSkills = list(s, 'run', s.session.orgId).filter((r) => r.questId === q.id && r.kind === 'skill' && r.status === 'running');
  const missingTypes = q.expectedDeliverables.filter((t) => !linked.some((d) => d.type === t));
  const prepareAll = () =>
    missingTypes.forEach((type) => {
      const sk = SKILL_FOR[type];
      if (sk)
        dispatch(
          cmd.launchSkill,
          { skillId: `skl-${sk}-${s.session.orgId}`, questId: q.id, type },
          { success: `Préparation : ${DELIVERABLE_TYPES[type].label}` },
        );
    });
  const submitAll = () =>
    linked
      .filter((d) => d.status === 'draft')
      .forEach((d) =>
        dispatch(
          cmd.transition,
          { kind: 'deliverable', id: d.id, action: 'submit', approverId: undefined },
          { success: `${d.title} soumis en revue` },
        ),
      );
  return (
    <Panel
      title="Livrables"
      actions={
        <>
          {runningSkills.length > 0 && (
            <Badge tone="ai" icon="play">
              {runningSkills.length} en préparation <span className="anvil-work" />
            </Badge>
          )}
          <SimBadge />
        </>
      }
    >
      <p className="small muted">Attendus : {q.expectedDeliverables.map((t) => DELIVERABLE_TYPES[t].label).join(', ') || '—'}</p>
      <ul className="plain stack tight">
        {linked.map((d) => (
          <li key={d.id} className="row between">
            <span className="row">
              <a href={`#/forge/livrables/${d.id}`}>{d.title}</a>
              <Version n={d.current} />
              <StatusBadge kind="deliverable" state={d.status} />
              {d.versions.some((v) => v.proposal) && (
                <Badge tone="info" icon="spark">
                  proposition
                </Badge>
              )}
            </span>
            <button
              className="btn ghost icon small"
              aria-label={`Détacher ${d.title}`}
              onClick={() => dispatch(cmd.linkToQuest, { questId: q.id, kind: 'deliverable', id: d.id, link: false }, {})}
            >
              <Icon name="close" size={10} />
            </button>
          </li>
        ))}
      </ul>
      <div className="row" style={{ marginTop: 8 }}>
        {missingTypes.length > 0 && (
          <CmdButton
            def={cmd.launchSkill}
            payload={{ skillId: `skl-${SKILL_FOR[missingTypes[0]]}-${s.session.orgId}`, questId: q.id, type: missingTypes[0] }}
            variant="ai"
            icon="anvil"
            onRun={prepareAll}
          >
            Préparer les livrables attendus ({missingTypes.length})
          </CmdButton>
        )}
        {linked.some((d) => d.status === 'draft') && (
          <CmdButton
            def={cmd.transition}
            payload={{ kind: 'deliverable', id: linked.find((d) => d.status === 'draft')!.id, action: 'submit' }}
            icon="eye"
            onRun={submitAll}
          >
            Soumettre les brouillons en revue
          </CmdButton>
        )}
      </div>
      {candidates.length > 0 && (
        <div className="row" style={{ marginTop: 8 }}>
          <Select
            label="Rattacher un livrable existant"
            value={pick}
            placeholder="Choisir…"
            onChange={(e) => setPick(e.target.value)}
            options={candidates.map((d) => ({ value: d.id, label: d.title }))}
          />
          <CmdButton
            def={cmd.linkToQuest}
            payload={{ questId: q.id, kind: 'deliverable', id: pick, link: true }}
            size="small"
            success="Livrable rattaché"
          >
            Rattacher
          </CmdButton>
        </div>
      )}
    </Panel>
  );
}

function QuestControls({ q }: { q: Quest }) {
  const s = useAppState();
  const results = latestResults(s, q.projectId);
  const controls = q.controlIds.map((id) => s.db.control[id]).filter(Boolean);
  const dels = q.deliverableIds.map((id) => s.db.deliverable[id]).filter(Boolean);
  const [pick, setPick] = useState('');
  return (
    <Panel title="Contrôles">
      {controls.length === 0 && <p className="small muted">Aucun contrôle requis.</p>}
      {controls.map((c) => (
        <div key={c.id} className="card" style={{ margin: 3 }}>
          <div className="row between">
            <strong className="small">
              {c.code} — {c.name}
            </strong>
            {c.blocking ? (
              <Badge tone="danger" icon="lock">
                bloquant
              </Badge>
            ) : (
              <Badge tone="muted">informatif</Badge>
            )}
          </div>
          {dels
            .filter((d) => c.appliesTo.includes(d.type))
            .map((d) => {
              const r = results.find((x) => x.controlId === c.id && x.inputs.subject?.deliverableId === d.id);
              const running = list(s, 'run', s.session.orgId).find(
                (x) => x.controlId === c.id && x.inputs.subject?.deliverableId === d.id && x.status === 'running',
              );
              return (
                <div key={d.id} className="row between small" style={{ marginTop: 6 }}>
                  <span className="row">
                    {d.title} <Version n={d.current} />
                    {r ? (
                      <>
                        <StatusBadge kind="result" state={r.outcome} />
                        <StatusBadge kind="freshness" state={resultFreshness(s, r).state} />
                      </>
                    ) : (
                      <Badge tone="neutral" icon="question">
                        Non évalué
                      </Badge>
                    )}
                    {running && (
                      <Badge tone="ai" icon="play">
                        en cours
                      </Badge>
                    )}
                  </span>
                  <CmdButton
                    def={cmd.launchControl}
                    payload={{ controlId: c.id, deliverableId: d.id, questId: q.id }}
                    size="small"
                    icon="play"
                    success="Contrôle lancé (simulation)"
                  >
                    {r ? 'Relancer' : 'Lancer'}
                  </CmdButton>
                </div>
              );
            })}
          {!dels.some((d) => c.appliesTo.includes(d.type)) && (
            <p className="tiny muted" style={{ margin: '4px 0 0' }}>
              S’applique aux livrables de type {c.appliesTo.map((t) => DELIVERABLE_TYPES[t].label).join(', ')} : aucun n’est rattaché.
            </p>
          )}
        </div>
      ))}
      <div className="row" style={{ marginTop: 8 }}>
        <Select
          label="Exiger un contrôle"
          value={pick}
          placeholder="Choisir…"
          onChange={(e) => setPick(e.target.value)}
          options={list(s, 'control', s.session.orgId)
            .filter((c) => !q.controlIds.includes(c.id))
            .map((c) => ({ value: c.id, label: `${c.code} — ${c.name}` }))}
        />
        <CmdButton
          def={cmd.linkToQuest}
          payload={{ questId: q.id, kind: 'control', id: pick, link: true }}
          size="small"
          success="Contrôle exigé"
        >
          Ajouter
        </CmdButton>
      </div>
    </Panel>
  );
}

function RequestClosure({ q }: { q: Quest }) {
  const s = useAppState();
  const [approver, setApprover] = useState<string | undefined>();
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : undefined;
  if (!q.needsHumanApproval) return <p className="small muted">Le profil n’exige pas de validation humaine distincte pour cette quête.</p>;
  return (
    <div className="stack tight" style={{ marginTop: 8 }}>
      <ApproverPicker value={approver} onChange={setApprover} exclude={me} />
      <CmdButton
        def={cmd.requestApproval}
        payload={{ subject: { kind: 'quest', id: q.id }, purpose: 'clôture', approverId: approver }}
        size="small"
        icon="shield"
        success="Validation de clôture demandée"
      >
        Demander la validation de clôture
      </CmdButton>
    </div>
  );
}

function Comments({ q }: { q: Quest }) {
  const [text, setText] = useState('');
  return (
    <Panel title={`Commentaires (${q.comments.length})`}>
      <ul className="plain stack tight">
        {q.comments.map((c) => (
          <li key={c.id} className="card">
            <div className="row between">
              <Person id={c.authorId} />
              <span className="tiny muted">{fmtDate(c.at, true)}</span>
            </div>
            <p className="small" style={{ margin: '4px 0 0' }}>
              {c.text}
            </p>
          </li>
        ))}
      </ul>
      <TextArea label="Ajouter un commentaire" value={text} onChange={(e) => setText(e.target.value)} />
      <CmdButton
        def={cmd.addComment}
        payload={{ questId: q.id, text }}
        size="small"
        success="Commentaire ajouté"
        onDone={() => setText('')}
      >
        Publier le commentaire
      </CmdButton>
    </Panel>
  );
}
