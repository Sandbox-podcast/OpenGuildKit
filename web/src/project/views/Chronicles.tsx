/** Chroniques: the history of the project, rebuilt from the task records (openings, consultations, decisions, results). */
import { useCallback, useMemo, useState } from 'react';
import { Badge, Button, Panel } from '@/shared/ui/core';
import { Icon, type PixelIconName } from '@/shared/pixel/icons';
import { batchJson } from '../api';
import { useTasks } from '../data';
import { useQuery } from '../query';
import { fmtWhen } from '../labels';
import { Q } from '../parts';
import type { TaskRecord } from '../types';

interface Event {
  at: string;
  task: string;
  icon: PixelIconName;
  tone: 'success' | 'warning' | 'info' | 'ai' | 'muted';
  title: string;
  detail?: string;
}

function eventsOf(t: TaskRecord): Event[] {
  const out: Event[] = [
    { at: t.created_at, task: t.id, icon: 'quest', tone: 'muted', title: 'Tâche ouverte', detail: t.brief.split('\n')[0] },
  ];
  t.rounds.forEach((r, i) => {
    if (r.decision)
      out.push({
        at: r.decision.at,
        task: t.id,
        icon: r.decision.outcome === 'approved' ? 'lock' : 'replace',
        tone: r.decision.outcome === 'approved' ? 'success' : 'warning',
        title: `Tour ${i + 1} : ${r.decision.outcome === 'approved' ? 'approuvé' : 'renvoyé au Conseil'} par ${r.decision.by}`,
        detail: r.decision.reason,
      });
  });
  if (t.decision)
    out.push({
      at: t.decision.at,
      task: t.id,
      icon: t.decision.outcome === 'approved' ? 'lock' : 'replace',
      tone: t.decision.outcome === 'approved' ? 'success' : 'warning',
      title: t.decision.outcome === 'approved' ? `Approuvée par ${t.decision.by}` : `Renvoyée au Conseil par ${t.decision.by}`,
      detail: `${t.decision.reason}${t.decision.seal ? ` · sceau ${t.decision.seal.slice(0, 12)}` : ''}${t.decision.signature ? ` · signée par ${t.decision.signature.signer}` : ''}`,
    });
  (t.deliverables ?? []).forEach((d) =>
    out.push({
      at: d.created_at,
      task: t.id,
      icon: 'scroll',
      tone: 'info',
      title: `Livrable ${d.deliverable} commencé`,
      detail: d.tool ?? undefined,
    }),
  );
  (t.authorizations ?? []).forEach((a) =>
    out.push({
      at: a.at,
      task: t.id,
      icon: 'external',
      tone: a.decision === 'allow' ? 'warning' : 'muted',
      title: `Action externe ${a.action} sur ${a.target} : ${a.decision === 'allow' ? 'autorisée' : 'refusée'}`,
      detail: `${a.by}, ${a.reason}`,
    }),
  );
  if (t.completed_at) {
    const reserved = t.status === 'done-with-reservations';
    const by = t.result?.closing?.by ? `, clôture confirmée par ${t.result.closing.by}` : '';
    out.push({
      at: t.completed_at,
      task: t.id,
      icon: 'star',
      tone: reserved ? 'warning' : 'success',
      title: reserved ? 'Tâche terminée avec réserves' : 'Tâche terminée',
      detail: `${t.result?.pull_request ?? t.result?.revision ?? ''}${by}` || undefined,
    });
  }
  return out;
}

/** The history reads the records of this many tasks at once, the most recently opened first: one request to the server. */
const CHRONICLE_PAGE = 40;

export function Chronicles() {
  const tasks = useTasks();
  const [task, setTask] = useState('');
  const [shown, setShown] = useState(CHRONICLE_PAGE);
  const all = useMemo(
    () =>
      (tasks.data ?? [])
        .filter((t) => t.created)
        .sort((a, b) => (b.created ?? '').localeCompare(a.created ?? ''))
        .map((t) => t.id),
    [tasks.data],
  );
  const ids = task ? [task] : all.slice(0, shown);
  const key = `chronicles:${ids.join(',')}`;
  const records = useQuery<TaskRecord[]>(
    tasks.data ? key : null,
    useCallback(async () => {
      // Only the dates and decisions: the consultations and reviews stay on the server.
      const records = await batchJson<TaskRecord>(Object.fromEntries(ids.map((id) => [id, ['task', 'show', id, '--json']])), {
        omit: ['consultation', 'review', 'answers', 'scope'],
      });
      return ids.map((id) => records[id]).filter((r): r is TaskRecord => !!r);
    }, [key]),
  );
  const events = useMemo(() => (records.data ?? []).flatMap(eventsOf).sort((a, b) => b.at.localeCompare(a.at)), [records.data]);
  const more = !task && all.length > shown;
  return (
    <div className="page-grid">
      <div className="toolbar">
        <select className="input" aria-label="Tâche" value={task} onChange={(e) => setTask(e.target.value)}>
          <option value="">Toutes les tâches</option>
          {all.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        <span className="small muted">
          Reconstruit à partir des enregistrements locaux des tâches (<code>task show</code>). Les relevés partagés sont dans Documentation.
        </span>
      </div>
      <Q q={records} label="Lecture de l’historique">
        {() => (
          <Panel title={`${events.length} événement(s)`}>
            {!task && all.length > CHRONICLE_PAGE && (
              <p className="small muted">
                Les {Math.min(shown, all.length)} tâches ouvertes le plus récemment, sur {all.length}. Une tâche plus ancienne se choisit
                dans la liste.
              </p>
            )}
            <ol className="plain chronicle">
              {events.map((e, i) => (
                <li key={`${e.task}:${e.at}:${i}`} className={`chronicle-item tone-${e.tone}`}>
                  <span className="chronicle-dot">
                    <Icon name={e.icon} size={14} />
                  </span>
                  <div>
                    <p className="row">
                      <strong>{e.title}</strong>
                      <a className="mono small" href={`#/quetes/${e.task}`}>
                        {e.task}
                      </a>
                    </p>
                    {e.detail && (
                      <p className="small muted" data-own>
                        {e.detail}
                      </p>
                    )}
                    <p className="tiny muted">
                      <Badge tone="muted" icon="clock">
                        {fmtWhen(e.at)}
                      </Badge>
                    </p>
                  </div>
                </li>
              ))}
            </ol>
            {more && (
              <Button onClick={() => setShown((n) => n + CHRONICLE_PAGE)}>
                Lire les {Math.min(CHRONICLE_PAGE, all.length - shown)} tâches précédentes
              </Button>
            )}
          </Panel>
        )}
      </Q>
    </div>
  );
}
