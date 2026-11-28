/**
 * Safe content rendering: Markdown is parsed into React elements (never injected as HTML),
 * links are limited to http(s), landing pages render in a sandboxed iframe without scripts.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { diffLines } from 'diff';
import { landingBody, standaloneHtml } from '@/demo/adapters/export';
import type { Content } from '@/demo/domain/types';
import { useAppState } from '@/demo/app/store';
import { Icon } from '@/shared/pixel/icons';
import { Button, Segmented } from '@/shared/ui/core';
import { Markdown } from '@/shared/ui/markdown';

export { Markdown };


/* ------------------------------------------------------------------ diff */
export function contentText(c: Content): string {
  switch (c.kind) {
    case 'markdown': return c.body;
    case 'api': return c.spec;
    case 'files': return c.files.map((f) => `── ${f.path}\n${f.body}`).join('\n');
    default: return JSON.stringify(c, null, 2);
  }
}
export function DiffView({ before, after, labels }: { before: string; after: string; labels: [string, string] }) {
  const parts = useMemo(() => diffLines(before, after), [before, after]);
  const added = parts.filter((p) => p.added).reduce((n, p) => n + (p.count ?? 0), 0);
  const removed = parts.filter((p) => p.removed).reduce((n, p) => n + (p.count ?? 0), 0);
  return (
    <div className="stack tight">
      <p className="small muted" aria-live="polite">Comparaison {labels[0]} → {labels[1]} : <span style={{ color: 'var(--success)' }}>+{added} ligne(s)</span>, <span style={{ color: 'var(--danger)' }}>−{removed} ligne(s)</span></p>
      <div className="diff" role="region" aria-label={`Différences entre ${labels[0]} et ${labels[1]}`}>
        {parts.flatMap((p, i) => p.value.replace(/\n$/, '').split('\n').map((line, j) => (
          <div key={`${i}-${j}`} className={`line ${p.added ? 'add' : p.removed ? 'del' : ''}`}>
            <span className="mark" aria-hidden>{p.added ? '+' : p.removed ? '−' : ' '}</span>
            <span>{p.added && <span className="sr-only">ajouté : </span>}{p.removed && <span className="sr-only">retiré : </span>}{line}</span>
          </div>
        )))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ demo components shown in galleries */
type Props = Record<string, string | boolean>;
const STATE_UI: Record<string, { icon: Parameters<typeof Icon>[0]['name']; tone: string }> = {
  idle: { icon: 'download', tone: 'var(--accent)' }, pending: { icon: 'clock', tone: 'var(--data)' }, ready: { icon: 'check', tone: 'var(--success)' },
  expired: { icon: 'stale', tone: 'var(--warning)' }, error: { icon: 'warn', tone: 'var(--danger)' }, disabled: { icon: 'lock', tone: 'var(--muted)' },
  new: { icon: 'star', tone: 'var(--ai)' }, success: { icon: 'check', tone: 'var(--success)' }, warning: { icon: 'warn', tone: 'var(--warning)' },
};
function LongActionButton({ props }: { props: Props }) {
  const st = String(props.state ?? 'idle');
  const ui = STATE_UI[st] ?? STATE_UI.idle;
  return (
    <div className="stack tight" style={{ alignItems: 'flex-start' }}>
      <button className={`btn ${st === 'idle' ? 'primary' : ''}`} disabled={!!props.disabled} aria-busy={st === 'pending' || undefined} style={st !== 'idle' && !props.disabled ? { color: ui.tone } : undefined}>
        <Icon name={ui.icon} size={16} />{String(props.label ?? 'Action')}
      </button>
      <span className="tiny muted" aria-live="polite">Annonce : « {String(props.label)} »</span>
    </div>
  );
}
function DocumentCard({ props }: { props: Props }) {
  const st = String(props.state ?? 'idle');
  return (
    <div className="card" style={{ maxWidth: 260, borderLeft: `4px solid ${(STATE_UI[st] ?? STATE_UI.idle).tone}` }}>
      <strong>{String(props.label)}</strong>
      <p className="small muted" style={{ margin: 0 }}>{st === 'new' ? '(couleur seule : défaut signalé par CTL-A11Y)' : st === 'pending' ? 'Préparation…' : 'PDF · 120 Ko'}</p>
    </div>
  );
}
function ColorTokens({ props }: { props: Props }) {
  const st = String(props.state ?? 'success');
  const ui = STATE_UI[st] ?? STATE_UI.success;
  return <span className="badge" style={{ color: ui.tone, background: 'rgba(255,255,255,0.06)' }}><Icon name={ui.icon} size={12} />{String(props.label)}</span>;
}
const DEMO: Record<string, (p: { props: Props }) => ReactNode> = { ExportButton: LongActionButton, LongActionButton, DocumentCard, ColorTokens };

export function ComponentStage({ content }: { content: Extract<Content, { kind: 'component' }> }) {
  const [i, setI] = useState(0);
  const v = content.variants[Math.min(i, content.variants.length - 1)];
  const Comp = DEMO[content.name] ?? LongActionButton;
  return (
    <div className="gallery">
      <nav className="gallery-nav" aria-label={`États de ${content.name}`}>
        {content.variants.map((x, n) => <button key={x.name} aria-current={n === i ? 'true' : undefined} onClick={() => setI(n)}>{x.name}</button>)}
      </nav>
      <div className="gallery-stage">
        <div className="gallery-canvas"><Comp props={v.props} /></div>
        <table className="data small"><thead><tr><th>Propriété</th><th>Valeur</th></tr></thead><tbody>{Object.entries(v.props).map(([k, val]) => <tr key={k}><td className="mono">{k}</td><td className="mono">{String(val)}</td></tr>)}</tbody></table>
        <p className="small muted">{content.description}</p>
        <ul className="bullets small">{content.checks.map((c) => <li key={c}>{c}</li>)}</ul>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ previews */
export function ContentPreview({ content, title }: { content: Content; title: string }) {
  const s = useAppState();
  switch (content.kind) {
    case 'markdown': return <Markdown text={content.body} />;
    case 'files': return <FilesView files={content.files} />;
    case 'api': return <ApiView spec={content.spec} />;
    case 'component': return <ComponentStage content={content} />;
    case 'gallery': {
      const comps = content.componentIds.map((id) => s.db.deliverable[id]).filter(Boolean);
      return (
        <div className="stack">
          <p className="muted">{content.intro}</p>
          {comps.length === 0 && <p className="small muted">Aucun composant rattaché à la galerie.</p>}
          {comps.map((d) => { const v = d.versions.find((x) => x.number === d.current)!; return v.content.kind === 'component' ? <section key={d.id}><h3>{d.title} <span className="version">v{d.current}</span></h3><ComponentStage content={v.content} /></section> : null; })}
        </div>
      );
    }
    case 'roadmap': return (
      <div className="roadmap">{content.items.map((it) => <div key={it.title} className="card"><span className="version">{it.horizon}</span><h3 style={{ marginTop: 6 }}>{it.title}</h3><p className="small" style={{ color: 'var(--success)', margin: 0 }}>{it.status}</p><p className="small muted">{it.note}</p></div>)}</div>
    );
    case 'landing': return <LandingFrame content={content} title={title} />;
    case 'slides': return <SlideDeck slides={content.slides} />;
    case 'storyboard': return <Storyboard scenes={content.scenes} />;
  }
}

function FilesView({ files }: { files: { path: string; language: string; body: string }[] }) {
  const [i, setI] = useState(0);
  const f = files[Math.min(i, files.length - 1)];
  return (
    <div className="stack tight">
      <div className="seg" role="group" aria-label="Fichiers">{files.map((x, n) => <button key={x.path} aria-pressed={n === i} onClick={() => setI(n)}><Icon name="scroll" size={12} />{x.path}</button>)}</div>
      <pre className="code" aria-label={f.path}><code>{f.body}</code></pre>
      <p className="tiny muted">Proposition locale : rien n’a été envoyé vers un dépôt distant.</p>
    </div>
  );
}

function ApiView({ spec }: { spec: string }) {
  const ops = [...spec.matchAll(/^ {2}(\/[^:]+):\n((?: {4}.*\n?)+)/gm)].flatMap((m) => [...m[2].matchAll(/^ {4}(get|post|put|patch|delete):\n {6}summary: (.*)$/gm)].map((o) => ({ path: m[1], method: o[1].toUpperCase(), summary: o[2] })));
  return (
    <div className="stack">
      {ops.length > 0 && <table className="data"><thead><tr><th>Méthode</th><th>Chemin</th><th>Résumé</th></tr></thead><tbody>{ops.map((o) => <tr key={o.method + o.path}><td className="mono" style={{ color: 'var(--accent)' }}>{o.method}</td><td className="mono">{o.path}</td><td>{o.summary}</td></tr>)}</tbody></table>}
      <pre className="code"><code>{spec}</code></pre>
    </div>
  );
}

function LandingFrame({ content, title }: { content: Extract<Content, { kind: 'landing' }>; title: string }) {
  const [device, setDevice] = useState<'desktop' | 'mobile'>('desktop');
  const doc = useMemo(() => standaloneHtml(title, landingBody(content), 'Aperçu local de démonstration'), [content, title]);
  return (
    <div className="stack tight">
      <Segmented label="Format d’aperçu" value={device} onChange={setDevice} options={[{ value: 'desktop', label: 'Ordinateur' }, { value: 'mobile', label: 'Mobile' }]} />
      <iframe title={`Aperçu : ${title}`} sandbox="" srcDoc={doc} className="landing-frame" style={{ width: device === 'mobile' ? 375 : '100%' }} />
      <p className="tiny muted">Aperçu isolé (iframe sans script). Aucune page n’est publiée.</p>
    </div>
  );
}

export function SlideDeck({ slides }: { slides: { title: string; bullets: string[]; note: string }[] }) {
  const [i, setI] = useState(0);
  const sl = slides[Math.min(i, slides.length - 1)];
  useEffect(() => { setI(0); }, [slides.length]);
  return (
    <div className="deck" onKeyDown={(e) => { if (e.key === 'ArrowRight') setI((x) => Math.min(x + 1, slides.length - 1)); if (e.key === 'ArrowLeft') setI((x) => Math.max(x - 1, 0)); }}>
      <div className="slide-stage" tabIndex={0} aria-roledescription="diapositive" aria-label={`Diapositive ${i + 1} sur ${slides.length}`}>
        <span className="small muted">{i + 1} / {slides.length}</span>
        <h3>{sl.title}</h3>
        <ul className="bullets">{sl.bullets.map((b) => <li key={b}>{b}</li>)}</ul>
      </div>
      {sl.note && <p className="small muted">Note de l’orateur : {sl.note}</p>}
      <div className="row">
        <Button size="small" icon="chevron" onClick={() => setI((x) => Math.max(x - 1, 0))} disabled={i === 0} aria-label="Diapositive précédente" style={{ transform: 'scaleX(-1)' }} />
        <Button size="small" icon="chevron" onClick={() => setI((x) => Math.min(x + 1, slides.length - 1))} disabled={i === slides.length - 1} aria-label="Diapositive suivante" />
        <span className="tiny muted">Flèches du clavier pour naviguer</span>
      </div>
    </div>
  );
}

function Storyboard({ scenes }: { scenes: { title: string; seconds: number; visual: string; voice: string }[] }) {
  const total = scenes.reduce((a, s) => a + s.seconds, 0) || 1;
  let t = 0;
  return (
    <div className="stack">
      <div className="timeline-bar" role="img" aria-label={`Chronologie de ${total} secondes`}>
        {scenes.map((s, i) => <span key={i} style={{ flexGrow: s.seconds }} title={`${s.title} — ${s.seconds} s`}>{i + 1}</span>)}
      </div>
      <ol className="scenes">
        {scenes.map((s, i) => { const start = t; t += s.seconds; return (
          <li key={i} className="card"><div className="row between"><strong>{i + 1}. {s.title}</strong><span className="version">{start}–{t} s</span></div><p className="small" style={{ margin: '6px 0 2px' }}><Icon name="eye" size={12} /> {s.visual}</p><p className="small muted" style={{ margin: 0 }}>« {s.voice} »</p></li>
        ); })}
      </ol>
      <p className="tiny muted">Storyboard et chronologie ; aucun fichier vidéo n’est généré dans la démonstration.</p>
    </div>
  );
}
