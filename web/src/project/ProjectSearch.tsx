/** Search across the project: places, tasks, brains, references and patterns. Enter opens the first result. */
import { useMemo, useState } from 'react';
import { navigate } from '@/app/router';
import { PLACES } from '@/shared/places';
import { Dialog } from '@/shared/ui/overlay';
import { Icon, type PixelIconName } from '@/shared/pixel/icons';
import { norm } from '@/shared/text';
import { useCli } from './query';
import { useBrains, useTasks } from './data';
import { PROJECT_PLACES } from './ProjectShell';
import type { Pattern, Reference } from './types';

interface Hit { kind: string; icon: PixelIconName; title: string; detail: string; to: string }

export function ProjectSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState('');
  const tasks = useTasks();
  const brains = useBrains();
  const refs = useCli<Reference[]>(open && q.length >= 2 ? ['references', '--json'] : null);
  const patterns = useCli<Pattern[]>(open && q.length >= 2 ? ['patterns', '--json'] : null);
  const hits = useMemo<Hit[]>(() => {
    const words = norm(q).split(/\s+/).filter(Boolean);
    const match = (text: string) => { const t = norm(text); return words.every((w) => t.includes(w)); };
    const out: Hit[] = [];
    PLACES.forEach((p) => { if (!words.length || match(`${p.name} ${PROJECT_PLACES[p.key].role} ${PROJECT_PLACES[p.key].pro}`)) out.push({ kind: 'Lieu', icon: p.icon, title: p.name, detail: PROJECT_PLACES[p.key].role, to: p.route }); });
    if (!words.length) return out;
    (tasks.data ?? []).forEach((t) => { if (match(`${t.id} ${t.brief}`)) out.push({ kind: 'Quête', icon: 'quest', title: t.id, detail: t.brief ?? '', to: `/quetes/${t.id}` }); });
    Object.values(brains.data ?? {}).forEach((b) => { if (match(`${b.id} ${b.title} ${b.description}`)) out.push({ kind: 'Cerveau', icon: 'guild', title: b.title, detail: b.description, to: `/guilde/${b.id}` }); });
    (patterns.data ?? []).forEach((p) => { if (match(`${p.id} ${p.title} ${p.description}`)) out.push({ kind: 'Pattern', icon: 'grid', title: p.title, detail: p.description, to: `/bibliotheque/patterns?q=${encodeURIComponent(p.id)}` }); });
    (refs.data ?? []).forEach((r) => { if (match(`${r.id} ${r.title} ${(r.aliases ?? []).join(' ')} ${r.summary}`)) out.push({ kind: 'Référence', icon: 'book', title: r.title, detail: r.summary, to: `/bibliotheque/ref/${r.id}` }); });
    return out.slice(0, 40);
  }, [q, tasks.data, brains.data, refs.data, patterns.data]);

  const go = (to: string) => { onClose(); setQ(''); navigate(to); };
  return (
    <Dialog open={open} onClose={onClose} title="Rechercher dans le projet">
      <input className="input" autoFocus value={q} placeholder="Quête, cerveau, référence, pattern…" aria-label="Rechercher"
        onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && hits[0]) go(hits[0].to); }} />
      <p className="sr-only" role="status">{q.length >= 2 ? `${hits.length} résultat${hits.length > 1 ? 's' : ''}` : ''}</p>
      <ul className="plain palette-results" aria-label="Résultats">
        {hits.map((h) => (
          <li key={`${h.kind}:${h.to}`}><a className="palette-hit" href={`#${h.to}`} onClick={(e) => { e.preventDefault(); go(h.to); }}>
            <Icon name={h.icon} size={16} /><span className="grow"><strong>{h.title}</strong><span className="tiny muted block clamp-1">{h.detail}</span></span><span className="tiny muted">{h.kind}</span>
          </a></li>
        ))}
        {q.length >= 2 && hits.length === 0 && <li className="muted">Aucun résultat.</li>}
      </ul>
    </Dialog>
  );
}
