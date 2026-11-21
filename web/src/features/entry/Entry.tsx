/** Entry screen (create, load demo, resume, import) and the onboarding questionnaire (brief §5.1). */
import { useMemo, useRef, useState } from 'react';
import { dispatch, replaceState, useAppState } from '@/app/store';
import { navigate, useDirtyGuard } from '@/app/router';
import { Brand } from '@/app/Brand';
import { cmd } from '@/domain/commands';
import { ALL_QUESTIONS, answersToFacts, STEPS, suggestReferences, type Question } from '@/domain/questionnaire';
import { referenceById } from '@/domain/selectors';
import { services } from '@/adapters/services';
import { applyBackup, previewBackup, type BackupPreview } from '@/adapters/storage';
import { Building } from '@/shared/pixel/Sprite';
import { Badge, Button, Checkbox, Choices, Notice, Panel, Select, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { SimBadge } from '@/shared/ui/domain';
import type { ContextFact } from '@/domain/types';

export function Entry() {
  const s = useAppState();
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<BackupPreview | null>(null);
  const [mode, setMode] = useState<'merge' | 'replace'>('merge');
  const fileRef = useRef<HTMLInputElement>(null);
  const orgs = Object.values(s.orgs);
  const illustrated = s.prefs.mode === 'explorer';
  return (
    <main className="entry entry-home">
      <div className="entry-hero">
        {illustrated && <picture className="entry-landscape" aria-hidden="true">
          <source media="(max-width: 640px)" srcSet="./assets/world/guildhall-mobile.webp" />
          <img src="./assets/world/guildhall.webp" alt="" width={1536} height={1024} fetchPriority="high" />
        </picture>}
        <div className="entry-copy">
          <Brand size="hero" />
          <h1>Des règles aux livrables</h1>
          <p>Rassemblez les règles de vos projets, consultez les expertises et suivez les décisions jusqu'aux contrôles.</p>
          <div className="row entry-actions">
            <Button variant="primary" icon="crown" onClick={() => { dispatch(cmd.loadDemo, {}, { success: 'Atelier Nova chargé' }); navigate('/royaume'); }}>{s.orgs['org-nova'] ? 'Ouvrir Atelier Nova' : 'Charger Atelier Nova'}</Button>
            <Button onClick={() => document.getElementById('organisation-name')?.focus()}>Créer une organisation</Button>
          </div>
          <p className="small entry-disclosure">Atelier Nova est une démo. Les services externes sont simulés. Vos modifications restent dans ce navigateur.</p>
        </div>
      </div>
      <div className="entry-grid">
        <Panel className="entry-card" title={<span className="row">{illustrated && <Building place="blueprint" scale={0.5} />} Nouvelle organisation</span>}>
          <form onSubmit={(e) => {
            e.preventDefault();
            const out = dispatch(cmd.createBlankOrg, { name }, { silent: true });
            if (!out.ok) setError(out.reason); else navigate('/onboarding');
          }} className="stack tight">
            <TextField id="organisation-name" label="Nom de l'organisation" value={name} onChange={(e) => { setName(e.target.value); setError(null); }} error={error} />
            <Button type="submit" icon="plus">Commencer le questionnaire</Button>
          </form>
        </Panel>
        <Panel className="entry-card" title={<span className="row">{illustrated && <Building place="chroniques" scale={0.5} />} Organisations enregistrées</span>}>
          {orgs.length === 0 ? <p className="small muted">Aucune session enregistrée dans ce navigateur.</p> : (
            <ul className="plain stack tight">
              {orgs.map((o) => (
                <li key={o.id}><button className="card" onClick={() => { dispatch(cmd.switchOrg, { orgId: o.id }, { silent: true }); navigate(o.onboarding.status === 'done' ? '/royaume' : '/onboarding'); }}>
                  <strong>{o.name}</strong><span className="tiny muted" style={{ display: 'block' }}>{o.onboarding.status === 'done' ? 'Blueprint publié' : `Questionnaire en brouillon (étape ${o.onboarding.step + 1})`}</span>
                </button></li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel className="entry-card" title={<span className="row">{illustrated && <Building place="intendance" scale={0.5} />} Importer une sauvegarde</span>}>
          <p className="small muted">Choisissez un fichier JSON exporté depuis l'Intendance.</p>
          <input ref={fileRef} type="file" accept="application/json,.json" className="sr-only" id="backup-file" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) setPreview(previewBackup(await f.text(), s));
            e.target.value = '';
          }} />
          <Button icon="upload" onClick={() => fileRef.current?.click()}>Choisir un fichier…</Button>
        </Panel>
      </div>
      <Dialog open={!!preview} onClose={() => setPreview(null)} title="Aperçu de l'import" footer={preview?.ok ? <>
        <Button onClick={() => setPreview(null)}>Annuler</Button>
        <Button variant="primary" onClick={() => { replaceState(applyBackup(s, preview.state!, mode, mode === 'merge' ? preview.orgs.filter((o) => o.conflict).map((o) => o.id) : [])); setPreview(null); navigate('/royaume'); }}>Importer</Button>
      </> : <Button onClick={() => setPreview(null)}>Fermer</Button>}>
        {preview && !preview.ok && <Notice tone="danger" title="Import refusé, rien n’a été modifié.">{preview.errors.map((e) => <span key={e} style={{ display: 'block' }}>{e}</span>)}</Notice>}
        {preview?.ok && (
          <div className="stack">
            <p className="small muted">Sauvegarde du {preview.exportedAt ? new Date(preview.exportedAt).toLocaleString('fr-FR') : '—'}.</p>
            <table className="data"><thead><tr><th>Organisation</th><th>Projets</th><th>Quêtes</th><th>Événements</th><th>Conflit</th></tr></thead>
              <tbody>{preview.orgs.map((o) => <tr key={o.id}><td>{o.name}</td><td>{o.counts.project}</td><td>{o.counts.quest}</td><td>{o.counts.event}</td><td>{o.conflict ? <Badge tone="warning" icon="warn">Existe déjà</Badge> : <Badge tone="success">Nouvelle</Badge>}</td></tr>)}</tbody></table>
            <Select label="Mode d’import" value={mode} onChange={(e) => setMode(e.target.value as 'merge' | 'replace')} options={[{ value: 'merge', label: 'Fusionner : ajouter les organisations, remplacer celles en conflit' }, { value: 'replace', label: 'Remplacer tout l’espace de travail' }]} />
          </div>
        )}
      </Dialog>
    </main>
  );
}

/* ------------------------------------------------------------------ onboarding */

const PROV: Record<ContextFact['provenance'], { label: string; tone: 'success' | 'info' | 'ai' | 'warning' }> = {
  declared: { label: 'Déclaré', tone: 'success' }, observed: { label: 'Observé', tone: 'info' }, inferred: { label: 'Inféré', tone: 'ai' }, unknown: { label: 'Inconnu', tone: 'warning' },
};
export const ProvenanceBadge = ({ p }: { p: ContextFact['provenance'] }) => <Badge tone={PROV[p].tone} icon={p === 'unknown' ? 'question' : p === 'inferred' ? 'ai' : p === 'observed' ? 'eye' : 'check'}>{PROV[p].label}</Badge>;

export function Onboarding() {
  const s = useAppState();
  const org = s.orgs[s.session.orgId!];
  const o = org.onboarding;
  const steps = [...STEPS.map((x) => x.title), ...(o.mode === 'existing' ? ['Analyse du dépôt'] : []), 'Conclusion'];
  const [step, setStep] = useState(Math.min(o.step, steps.length - 1));
  const [local, setLocal] = useState(o.answers);
  const [touched, setTouched] = useState(false);
  const dirty = JSON.stringify(local) !== JSON.stringify(o.answers);
  useDirtyGuard('onboarding', dirty);
  const save = (nextStep = step) => dispatch(cmd.updateOnboarding, { answers: local, step: nextStep }, { silent: true });
  const go = (n: number) => { save(n); setStep(n); setTouched(false); window.scrollTo({ top: 0 }); };
  const isQuestionStep = step < STEPS.length;
  const current = isQuestionStep ? STEPS[step] : null;
  const missingRequired = (current?.questions ?? []).filter((q) => q.required && !local[q.key]?.value?.trim());

  return (
    <div className="entry">
      <div className="wizard">
        <div className="row between" style={{ marginBottom: 12 }}>
          <a href="#/entree" className="brand-link"><Brand /></a>
          <div className="row"><SimBadge label="Démonstration interactive" /><Button size="small" icon="download" onClick={() => { save(); }}>Enregistrer le brouillon</Button></div>
        </div>
        <h1 className="pixel-font">Entrée dans la guilde — {org.name}</h1>
        <div className="row" style={{ margin: '6px 0 14px' }}>
          <span className="small muted">Type de démarche :</span>
          <div className="seg" role="group" aria-label="Type de démarche">
            <button aria-pressed={o.mode === 'new'} onClick={() => dispatch(cmd.updateOnboarding, { mode: 'new' }, { silent: true })}>Nouveau produit</button>
            <button aria-pressed={o.mode === 'existing'} onClick={() => dispatch(cmd.updateOnboarding, { mode: 'existing' }, { silent: true })}>Reprise d’un produit existant</button>
          </div>
        </div>
        <nav className="wizard-steps" aria-label="Étapes du questionnaire">
          {steps.map((t, i) => <button key={t} aria-current={i === step ? 'step' : undefined} className={i < step ? 'done' : ''} onClick={() => go(i)}>{i + 1}. {t}</button>)}
        </nav>
        {current && (
          <Panel title={<span className="row"><Building place={({ Organisation: 'royaume', Équipe: 'guilde', Technique: 'forge', 'Données et exigences': 'tour', 'Qualité et exploitation': 'observatoire' } as const)[current.title as 'Équipe'] ?? 'royaume'} scale={1} />{current.title}</span>}>
            <p className="muted">{current.intro} Chaque réponse « Je ne sais pas encore » devient une inconnue à traiter : elle ne vaut ni validation, ni absence de risque.</p>
            {current.questions.map((q) => <QuestionRow key={q.key} q={q} value={local[q.key]} showError={touched} onChange={(v) => setLocal((a) => ({ ...a, [q.key]: v }))} />)}
          </Panel>
        )}
        {steps[step] === 'Analyse du dépôt' && <RepoAnalysis />}
        {steps[step] === 'Conclusion' && <Conclusion answers={local} />}
        <div className="row between" style={{ marginTop: 14 }}>
          <Button icon="chevron" disabled={step === 0} onClick={() => go(step - 1)} style={{ flexDirection: 'row-reverse' }}>Précédent</Button>
          {missingRequired.length > 0 && touched && <span className="small" style={{ color: 'var(--danger)' }}>Renseignez : {missingRequired.map((q) => q.label).join(', ')}</span>}
          {step < steps.length - 1 && <Button variant="primary" icon="chevron" onClick={() => { setTouched(true); if (!missingRequired.length) go(step + 1); }}>Suivant</Button>}
        </div>
      </div>
    </div>
  );
}

function QuestionRow({ q, value, onChange, showError }: { q: Question; value?: { value: string; unknown: boolean }; onChange: (v: { value: string; unknown: boolean }) => void; showError: boolean }) {
  const v = value ?? { value: '', unknown: false };
  const err = showError && q.required && !v.value.trim() ? 'Réponse requise.' : null;
  const field = q.type === 'text'
    ? <TextField label={q.label} hint={q.help} value={v.value} disabled={v.unknown} placeholder={q.placeholder} error={err} onChange={(e) => onChange({ value: e.target.value, unknown: false })} />
    : q.type === 'select'
      ? <Select label={q.label} hint={q.help} value={v.value} disabled={v.unknown} error={err} placeholder="Choisir…" options={q.options!.map((x) => ({ value: x, label: x }))} onChange={(e) => onChange({ value: e.target.value, unknown: false })} />
      : <Choices legend={q.label} multiple options={q.options!} disabled={v.unknown} value={v.value ? v.value.split(', ') : []} onChange={(vals) => onChange({ value: vals.join(', '), unknown: false })} />;
  return (
    <div className="question">
      <div>{field}</div>
      {q.allowUnknown && <div className="unknown-toggle"><Checkbox label="Je ne sais pas encore" checked={v.unknown} onChange={(e) => onChange({ value: e.target.checked ? '' : v.value, unknown: e.target.checked })} /></div>}
    </div>
  );
}

function RepoAnalysis() {
  const s = useAppState();
  const o = s.orgs[s.session.orgId!].onboarding;
  const [address, setAddress] = useState(o.analysis?.target ?? services.repository.scenarios[0].address);
  const [message, setMessage] = useState<string | null>(null);
  return (
    <Panel title="Analyse simulée d’un dépôt" tone="ai">
      <Notice tone="ai">L’analyse n’accède à aucun dépôt réel. Seuls les dépôts de démonstration identifiés produisent des observations ; toute autre adresse est signalée comme non analysée.</Notice>
      <form className="row" onSubmit={(e) => { e.preventDefault(); const out = dispatch(cmd.analyzeRepository, { address }, { silent: true }); if (out.ok) setMessage(out.value as string); }}>
        <div className="grow"><TextField label="Adresse du dépôt" list="demo-repos" value={address} onChange={(e) => setAddress(e.target.value)} hint={`Dépôts de démonstration : ${services.repository.scenarios.map((r) => r.address).join(', ')}`} /></div>
        <datalist id="demo-repos">{services.repository.scenarios.map((r) => <option key={r.key} value={r.address}>{r.label}</option>)}</datalist>
        <Button type="submit" variant="ai" icon="search">Analyser (simulation)</Button>
      </form>
      {message && <Notice tone={o.analysis?.scenario ? 'success' : 'warn'}>{message}</Notice>}
      {!!o.analysis?.observations.length && (
        <table className="data responsive" style={{ marginTop: 10 }}>
          <thead><tr><th>Sujet</th><th>Observation</th><th>Provenance</th><th>Correction</th><th>Conserver</th></tr></thead>
          <tbody>
            {o.analysis.observations.map((ob) => (
              <tr key={ob.id} style={{ opacity: ob.dismissed ? 0.55 : 1 }}>
                <td data-label="Sujet">{ob.topic}<div className="tiny muted">{ob.label}</div></td>
                <td data-label="Observation">{ob.value}</td>
                <td data-label="Provenance"><ProvenanceBadge p={ob.corrected ? 'declared' : ob.provenance} /></td>
                <td data-label="Correction"><div className="field"><label className="sr-only" htmlFor={`cor-${ob.id}`}>Corriger {ob.label}</label><input id={`cor-${ob.id}`} defaultValue={ob.corrected ?? ''} placeholder="Valeur corrigée" onBlur={(e) => dispatch(cmd.editObservation, { id: ob.id, corrected: e.target.value }, { silent: true })} /></div></td>
                <td data-label="Conserver"><Checkbox label={ob.dismissed ? 'Écartée' : 'Conservée'} checked={!ob.dismissed} onChange={(e) => dispatch(cmd.editObservation, { id: ob.id, dismissed: !e.target.checked }, { silent: true })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function Conclusion({ answers }: { answers: Record<string, { value: string; unknown: boolean }> }) {
  const s = useAppState();
  const o = s.orgs[s.session.orgId!].onboarding;
  const facts = useMemo(() => answersToFacts({ ...o, answers }), [o, answers]);
  const suggestions = useMemo(() => suggestReferences(facts), [facts]);
  const [accepted, setAccepted] = useState<string[]>(() => suggestions.filter((x) => x.status === 'applicable').map((x) => x.refId));
  const unknowns = facts.filter((f) => f.provenance === 'unknown');
  const inferred = facts.filter((f) => f.provenance === 'inferred');
  const missing = ['org.name', 'org.activity', 'product.name'].filter((k) => !answers[k]?.value);
  return (
    <div className="stack">
      <div className="grid-2">
        <Panel title="Profil proposé">
          <table className="data"><tbody>{facts.filter((f) => f.provenance !== 'unknown').map((f) => <tr key={f.key}><td className="small muted">{f.label}</td><td>{f.value}</td><td><ProvenanceBadge p={f.provenance} /></td></tr>)}</tbody></table>
        </Panel>
        <div className="stack">
          <Panel title={`Inconnues à traiter (${unknowns.length})`} tone={unknowns.length ? 'warn' : undefined}>
            {unknowns.length === 0 ? <p className="small muted">Aucune.</p> : <ul className="bullets">{unknowns.map((f) => <li key={f.key}>{f.label}</li>)}</ul>}
            <p className="tiny muted">Elles resteront visibles dans le Blueprint et pourront bloquer les décisions qui en dépendent.</p>
          </Panel>
          <Panel title="Validations attendues">
            <ul className="bullets small">
              <li>{inferred.length} valeur(s) inférée(s) à confirmer dans le Blueprint.</li>
              <li>Le premier Blueprint est publié par la personne propriétaire ; les versions suivantes demanderont une relecture par une autre personne.</li>
              <li>Les références cochées deviennent applicables ; les autres restent « à préciser ».</li>
            </ul>
          </Panel>
        </div>
      </div>
      <Panel title="Références suggérées" actions={<span className="small muted">{accepted.length} retenue(s)</span>}>
        <ul className="plain stack tight">
          {suggestions.map((sug) => {
            const ref = referenceById(s, sug.refId);
            return (
              <li key={sug.refId} className="row top">
                <Checkbox label={<span><strong>{ref?.name ?? sug.refId}</strong> <Badge tone={sug.status === 'applicable' ? 'success' : 'warning'}>{sug.status === 'applicable' ? 'Applicable' : 'À préciser'}</Badge>{sug.rule && <Badge tone="info" icon="plan">Crée la règle {sug.rule.code}</Badge>}<span className="small muted" style={{ display: 'block' }}>{sug.reason}</span></span>}
                  checked={accepted.includes(sug.refId)} onChange={(e) => setAccepted((a) => (e.target.checked ? [...a, sug.refId] : a.filter((x) => x !== sug.refId)))} />
              </li>
            );
          })}
        </ul>
      </Panel>
      {missing.length > 0 && <Notice tone="warn">Renseignez le nom, l’activité et le produit principal (étape 1) avant de publier.</Notice>}
      <div className="row end">
        <Button variant="primary" icon="check" disabled={missing.length > 0} onClick={() => {
          dispatch(cmd.updateOnboarding, { answers }, { silent: true });
          const out = dispatch(cmd.publishFirstBlueprint, { acceptedRefIds: accepted }, { success: 'Premier Blueprint publié (v1) : le Royaume s’enrichit' });
          if (out.ok) navigate('/royaume');
        }}>Publier le premier Blueprint</Button>
      </div>
      <p className="tiny muted">{ALL_QUESTIONS.length} questions · les réponses sont enregistrées comme brouillon à chaque changement d’étape.</p>
    </div>
  );
}
