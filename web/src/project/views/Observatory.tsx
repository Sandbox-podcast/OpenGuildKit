/** Observatoire: market dossiers with dated, sourced observations, their gaps, and the competitor watch. */
import { useCallback, useState } from 'react';
import { navigate } from '@/app/router';
import { Badge, Button, Empty, Notice, Panel } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Icon } from '@/shared/pixel/icons';
import { listFiles, readText } from '../api';
import { useMarketDue, useProfile } from '../data';
import { useAction, useCli, useQuery } from '../query';
import { RESEARCH, daysSince, fmtDay } from '../labels';
import { ActionForm, ExternalLink, Q, useRemembered } from '../parts';
import type { Dossier } from '../types';

const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function Observatory({ id }: { id?: string }) {
  const dossiers = useQuery<string[]>('market-dossiers', useCallback(async () => (await listFiles('.openguildkit/market')).filter((e) => e.name.endsWith('.json')).map((e) => e.name.replace(/\.json$/, '')), []));
  const due = useMarketDue();
  const profile = useProfile();
  const [creating, setCreating] = useState(false);
  const { act, busy } = useAction();
  const current = id ?? dossiers.data?.[0];
  return (
    <div className="page-grid">
      <Notice tone="info">Produit et Marketing jugent une fonctionnalité face à ce que le marché propose déjà. Le dossier garde cette comparaison dans le projet, avec des sources datées, pour que chaque consultation la réutilise. Recherche du projet : <strong>{RESEARCH[profile.data?.research ?? 'local-only']}</strong>. La CLI n’ouvre jamais le réseau.</Notice>
      <div className="toolbar">
        <Q q={dossiers}>{(list) => <nav className="row" aria-label="Dossiers">{list.map((d) => <a key={d} className={`btn small ${d === current ? 'primary' : ''}`} href={`#/observatoire/${d}`}>{d}</a>)}</nav>}</Q>
        <span className="grow" />
        <Button icon="plus" onClick={() => setCreating(true)}>Nouveau dossier</Button>
      </div>
      {(due.data?.due.length ?? 0) > 0 && <Panel title={`Veille : ${due.data!.due.length} source(s) à relire`} tone="ai">
        <ul className="plain stack tight">{due.data!.due.map((d) => <li key={d.url} className="row between"><span><strong>{d.competitor}</strong> · {d.kind} · <ExternalLink href={d.url} /> <span className="tiny muted">({d.dossier})</span></span>
          <Button size="small" busy={busy !== null} onClick={() => void act(['market', 'checked', d.dossier, '--url', d.url], { success: 'Source marquée relue' })}>Relue, rien de neuf</Button></li>)}</ul>
        <p className="tiny muted">L’agent ne les consulte que si la politique de recherche le permet. Un changement retenu s’enregistre dans le dossier avec la personne qui l’a vérifié.</p>
      </Panel>}
      {current ? <DossierView id={current} /> : dossiers.data && <Empty title="Aucun dossier de marché" action={<Button variant="primary" onClick={() => setCreating(true)}>Créer un dossier</Button>}>Un dossier compare la fonctionnalité aux concurrents directs et aux substituts (un tableur, un courriel, ne rien faire).</Empty>}
      <Dialog open={creating} onClose={() => setCreating(false)} title="Nouveau dossier de marché">
        <ActionForm busy={busy !== null} submit="Créer" fields={[
          { name: 'id', label: 'Identifiant', required: true, placeholder: 'support-portals', hint: 'Minuscules et tirets.', check: (v) => (SLUG.test(v) ? null : 'Minuscules, chiffres et tirets simples, sans espace ni accent, comme support-portals.') },
          { name: 'title', label: 'Titre', required: true },
          { name: 'market', label: 'Marché', required: true, placeholder: 'Éditeurs B2B en France' },
          { name: 'audience', label: 'Public', required: true },
          { name: 'feature', label: 'Fonctionnalité comparée', required: true },
        ]} onSubmit={async (v) => {
          if (await act(['market', 'new', v.id, '--title', v.title, '--market', v.market, '--audience', v.audience, '--feature', v.feature], { success: 'Dossier créé' })) { setCreating(false); navigate(`/observatoire/${v.id}`); }
        }} />
      </Dialog>
    </div>
  );
}

function DossierView({ id }: { id: string }) {
  const dossier = useQuery<Dossier>(`file:market:${id}`, useCallback(async () => JSON.parse(await readText(`.openguildkit/market/${id}.json`)) as Dossier, [id]));
  const gaps = useCli<{ dossier: string; gaps: string[] }>(['market', 'check', id, '--json']);
  const [form, setForm] = useState<null | 'competitor' | 'observe' | 'unknown' | 'watch' | 'change'>(null);
  const [by, setBy] = useRemembered('decider');
  const { act, busy } = useAction();
  const close = () => setForm(null);
  const competitors = (dossier.data?.competitors ?? []).map((c) => ({ value: c.id, label: c.name }));
  const submit = async (argv: string[]) => { if (await act(['market', ...argv], { success: 'Dossier mis à jour' })) close(); };

  return (
    <Q q={dossier}>{(d) => (
      <div className="page-grid">
        <Panel title={d.title}>
          <p className="small"><strong>Marché :</strong> {d.market} · <strong>Public :</strong> {d.audience} · <strong>Fonctionnalité :</strong> {d.feature}</p>
          <p className="small muted">Un avis cite une observation avec <code>market:{id}/IDENTIFIANT</code> ; la CLI refuse une référence absente du dossier joint.</p>
          <div className="row">
            <Button size="small" icon="plus" onClick={() => setForm('competitor')}>Concurrent</Button>
            <Button size="small" icon="plus" onClick={() => setForm('observe')}>Observation</Button>
            <Button size="small" icon="plus" onClick={() => setForm('unknown')}>Inconnue</Button>
            <Button size="small" icon="eye" onClick={() => setForm('watch')}>Suivre une page</Button>
            <Button size="small" icon="history" onClick={() => setForm('change')}>Changement vérifié</Button>
            {d.watch && <Button size="small" variant="ghost" busy={busy !== null} onClick={() => void act(['market', d.watch!.paused ? 'resume' : 'pause', id], { success: d.watch!.paused ? 'Veille reprise' : 'Veille en pause' })}>{d.watch.paused ? 'Reprendre la veille' : 'Mettre la veille en pause'}</Button>}
          </div>
        </Panel>
        {gaps.data && gaps.data.gaps.length > 0 && <Notice tone="warn" title="Lacunes du dossier :"><ul>{gaps.data.gaps.map((g) => <li key={g}>{g}</li>)}</ul></Notice>}
        <div className="grid-2">
          <Panel title={`Concurrents et substituts (${d.competitors.length})`}>
            <ul className="plain stack tight">{d.competitors.map((c) => <li key={c.id} className="card"><span className="row between"><strong>{c.name}</strong><Badge tone={c.kind === 'direct' ? 'info' : 'muted'}>{c.kind === 'direct' ? 'direct' : 'substitut'}</Badge></span>{c.segment && <span className="small muted">{c.segment}</span>}<span className="mono tiny">{c.id}</span></li>)}</ul>
          </Panel>
          <Panel title={`Observations (${d.observations.length})`}>
            <ul className="plain stack tight">{d.observations.map((o) => { const age = daysSince(o.source.date); return <li key={o.id} className="card">
              <span className="row between"><span className="mono tiny">market:{id}/{o.id}</span><Badge tone={age > 180 ? 'warning' : 'muted'} icon="clock">{age} j</Badge></span>
              <span>{o.claim}</span><span className="tiny muted">{d.competitors.find((c) => c.id === o.competitor)?.name ?? o.competitor} · {o.source.ref} · {fmtDay(o.source.date)}</span></li>; })}</ul>
          </Panel>
        </div>
        <div className="grid-2">
          <Panel title={`Inconnues (${d.unknowns.length})`}>
            <ul className="plain stack tight">{d.unknowns.map((u) => <li key={u} className="row between"><span className="small">{u}</span><Button size="small" variant="ghost" aria-label={`Retirer ${u}`} onClick={() => void act(['market', 'unknown', id, '--text', u, '--remove'], { success: 'Inconnue retirée' })}><Icon name="cross" size={12} /></Button></li>)}</ul>
          </Panel>
          <Panel title={`Veille ${d.watch ? `tous les ${d.watch.every_days} jours${d.watch.paused ? ' (en pause)' : ''}` : 'non configurée'}`}>
            {d.watch && <>
              <ul className="plain stack tight">{d.watch.sources.map((s) => <li key={s.url} className="small"><strong>{s.competitor}</strong> · {s.kind} · <ExternalLink href={s.url} /> <span className="tiny muted">relue : {s.last_checked ? fmtDay(s.last_checked) : 'jamais'}</span></li>)}</ul>
              {d.watch.changes.length > 0 && <><h3 className="h-card">Changements retenus</h3><ol className="small">{d.watch.changes.map((c, i) => <li key={i}><span className="mono tiny">market:{id}/change-{i + 1}</span> {c.what} <span className="tiny muted">({c.competitor}, {fmtDay(c.date)}, vérifié par {c.verified_by})</span></li>)}</ol></>}
            </>}
          </Panel>
        </div>
        <Dialog open={!!form} onClose={close} title={{ competitor: 'Ajouter un concurrent', observe: 'Enregistrer une observation', unknown: 'Ajouter une inconnue', watch: 'Suivre une page publique', change: 'Enregistrer un changement vérifié' }[form ?? 'competitor']}>
          {form === 'competitor' && <ActionForm busy={busy !== null} submit="Ajouter" fields={[
            { name: 'competitor', label: 'Identifiant', required: true, placeholder: 'vendor-a' }, { name: 'name', label: 'Nom', required: true },
            { name: 'kind', label: 'Type', required: true, options: [{ value: 'direct', label: 'Concurrent direct' }, { value: 'substitute', label: 'Substitut' }] }, { name: 'segment', label: 'Segment servi' },
          ]} onSubmit={(v) => submit(['competitor', id, '--competitor', v.competitor, '--name', v.name, '--kind', v.kind, ...(v.segment ? ['--segment', v.segment] : [])])} />}
          {form === 'observe' && <ActionForm busy={busy !== null} submit="Enregistrer" fields={[
            { name: 'competitor', label: 'Concurrent', required: true, options: competitors }, { name: 'observation', label: 'Identifiant de l’observation', required: true, placeholder: 'a-status-page', hint: 'Un identifiant existant est remplacé.' },
            { name: 'claim', label: 'Ce que le concurrent propose', required: true, multiline: true }, { name: 'source', label: 'Source', required: true, placeholder: 'Notes d’appel commercial, page publique…' },
            { name: 'date', label: 'Date de l’information', type: 'date', required: true }, { name: 'feature', label: 'Fonctionnalité (facultatif)' },
          ]} onSubmit={(v) => submit(['observe', id, '--competitor', v.competitor, '--observation', v.observation, '--claim', v.claim, '--source', v.source, '--date', v.date, ...(v.feature ? ['--feature', v.feature] : [])])} />}
          {form === 'unknown' && <ActionForm busy={busy !== null} submit="Ajouter" fields={[{ name: 'text', label: 'Ce qui reste à découvrir', required: true }]} onSubmit={(v) => submit(['unknown', id, '--text', v.text])} />}
          {form === 'watch' && <ActionForm busy={busy !== null} submit="Suivre" fields={[
            { name: 'competitor', label: 'Concurrent', required: true, options: competitors }, { name: 'url', label: 'Page publique (https)', required: true, type: 'url' },
            { name: 'kind', label: 'Nature de la page', required: true, placeholder: 'notes de version, tarifs, annonces' }, { name: 'every', label: 'Intervalle en jours', type: 'number', placeholder: '30' },
          ]} onSubmit={(v) => submit(['watch', id, '--competitor', v.competitor, '--url', v.url, '--kind', v.kind, ...(v.every ? ['--every-days', v.every] : [])])} />}
          {form === 'change' && <ActionForm busy={busy !== null} submit="Enregistrer" initial={{ verified: by }} fields={[
            { name: 'competitor', label: 'Concurrent', required: true, options: competitors }, { name: 'what', label: 'Ce qui a changé', required: true, multiline: true },
            { name: 'source', label: 'Page source', required: true, type: 'url' }, { name: 'date', label: 'Date', type: 'date', required: true },
            { name: 'verified', label: 'Vérifié par', required: true },
          ]} onSubmit={(v) => { setBy(v.verified); return submit(['change', id, '--competitor', v.competitor, '--what', v.what, '--source', v.source, '--date', v.date, '--verified-by', v.verified]); }} />}
        </Dialog>
      </div>
    )}</Q>
  );
}
