/** Guilde: the professional brains, their specialist lenses, what they ask and how they decide. */
import { Badge, Empty, Panel } from '@/shared/ui/core';
import { Icon } from '@/shared/pixel/icons';
import { useBrains, useProfile } from '../data';
import { useCliResult } from '../query';
import { ExternalLink, Pre, Q } from '../parts';
import { BRAIN_FR, brainName } from '../labels';
import { usePrefs } from '../prefs';
import { useWords } from '../words';

export function Guild() {
  const brains = useBrains();
  const profile = useProfile();
  const { mode } = usePrefs();
  const w = useWords();
  const enabled = profile.data?.boards ?? [];
  const required = profile.data?.required_boards ?? [];
  return (
    <div className="page-grid">
      <p className="small muted">Chaque cerveau rassemble des {w.lenses} de métier, pas un oracle : l’agent l’applique à la tâche et la CLI vérifie que chaque cerveau choisi a répondu. {enabled.length ? `${enabled.length} cerveau(x) activé(s) dans le profil.` : 'Le profil active tous les cerveaux.'}</p>
      <Q q={brains}>{(all) => (
        <ul className={`plain brain-grid ${mode === 'explorer' ? 'rpg' : ''}`}>{Object.values(all).map((b) => {
          const on = !enabled.length || enabled.includes(b.id);
          return (
            <li key={b.id}><a className={`card brain-card ${on ? '' : 'off'}`} href={`#/guilde/${b.id}`}>
              <span className="row between"><span className="brain-emblem"><Icon name="guild" size={18} /></span>
                <span className="row">{required.includes(b.id) && <Badge tone="info" icon="lock">obligatoire</Badge>}{!on && <Badge tone="muted">désactivé</Badge>}</span></span>
              <strong lang={BRAIN_FR[b.id] ? undefined : 'en'}>{brainName(b.id, b.title)}</strong>
              <span className="small muted clamp-3" lang="en">{b.description}</span>
              <span className="tiny">{b.review?.specialists.length ?? 0} {w.lenses} · {b.questions.length} questions</span>
            </a></li>
          );
        })}</ul>
      )}</Q>
    </div>
  );
}

export function BrainSheet({ id }: { id: string }) {
  const brains = useBrains();
  const knowledge = useCliResult(['brains', '--id', id]);
  const w = useWords();
  return (
    <Q q={brains}>{(all) => {
      const b = all[id];
      if (!b) return <Empty title="Cerveau introuvable"><a href="#/guilde">Revenir à la Guilde</a></Empty>;
      return (
        <div className="page-grid">
          <p><a href="#/guilde"><Icon name="chevron" size={12} /> Guilde</a></p>
          <Panel title={<span lang={BRAIN_FR[b.id] ? undefined : 'en'}>{brainName(b.id, b.title)}</span>}><p lang="en">{b.description}</p>
            <p className="small"><strong>Expertises :</strong> <span lang="en">{b.expertises.join(' · ')}</span></p>
            <p className="tiny muted">Déclencheurs dans un brief : <span lang="en">{b.triggers.join(', ')}</span></p></Panel>
          <div className="grid-2">
            <Panel title={`${w.Lenses} (${b.review?.specialists.length ?? 0})`}>
              <ul className="plain stack tight">{b.review?.specialists.map((s) => <li key={s.id} className="card" lang="en"><strong>{s.title}</strong><span className="small muted">{s.focus}</span><span className="mono tiny">{s.id}</span></li>)}</ul>
            </Panel>
            <Panel title="Ce que ce cerveau demande">
              <ul className="small" lang="en">{b.questions.map((q) => <li key={q}>{q}</li>)}</ul>
              {b.review && <>
                <h3 className="h-card">Preuves attendues</h3><ul className="small" lang="en">{b.review.evidence.map((e) => <li key={e}>{e}</li>)}</ul>
                <h3 className="h-card">Défis</h3><ul className="small" lang="en">{b.review.challenge.map((e) => <li key={e}>{e}</li>)}</ul>
                <h3 className="h-card">Critères de décision</h3><ul className="small" lang="en">{b.review.decision_criteria.map((e) => <li key={e}>{e}</li>)}</ul>
              </>}
            </Panel>
          </div>
          <Panel title="Connaissances : méthodes et références">
            <Q q={knowledge}>{(r) => <Pre text={r.stdout || r.stderr} />}</Q>
          </Panel>
          {b.sources.length > 0 && <Panel title="Sources"><ul lang="en">{b.sources.map((s) => <li key={s.url}><ExternalLink href={s.url}>{s.title}</ExternalLink></li>)}</ul></Panel>}
        </div>
      );
    }}</Q>
  );
}
