/** Blueprint: assistant, structured view by level, versions and comparison, impacts, export (brief §5.3). */
import { useMemo, useState } from 'react';
import { dispatch, useAppState } from '@/app/store';
import { navigate, setQuery, useRoute } from '@/app/router';
import { ProvenanceBadge } from '@/features/entry/Entry';
import { cmd } from '@/domain/commands';
import type { RuleInput } from '@/domain/commands/blueprint';
import { list } from '@/domain/engine';
import { CAPABILITIES } from '@/domain/permissions';
import {
  LEVELS, POLICIES, allReferences, blueprintImpacts, blueprintOf, bpVersion, fmtDate, latestPublished, objectLabel, openDraft, referenceById, resolveRules, unconfirmedInferred, unknownFacts,
} from '@/domain/selectors';
import type { BlueprintVersion, ContextFact, ID, Rule, RuleScope, RuleVersion } from '@/domain/types';
import { download, toYaml } from '@/adapters/export';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Checkbox, Empty, KV, Notice, Panel, Select, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { CmdButton, Lifecycle, ObjectLink, Person, StatusBadge, Version } from '@/shared/ui/domain';
import { DiffView } from '@/shared/ui/content';

const TABS = [
  { id: 'assistant', label: 'Assistant', icon: 'spark' as const },
  { id: 'structure', label: 'Vue structurée', icon: 'plan' as const },
  { id: 'versions', label: 'Versions', icon: 'history' as const },
  { id: 'impacts', label: 'Impacts', icon: 'warn' as const },
  { id: 'export', label: 'Export', icon: 'download' as const },
];

export function BlueprintSpace({ tab = 'assistant' }: { tab?: string }) {
  const s = useAppState();
  const bp = blueprintOf(s, s.session.orgId);
  const draft = openDraft(s, s.session.orgId);
  const pub = latestPublished(s, s.session.orgId);
  const reviews = list(s, 'review', s.session.orgId).filter((r) => r.status === 'open');
  if (!bp) return <Empty title="Aucun Blueprint">Terminez le questionnaire initial.</Empty>;
  return (
    <div className="stack">
      <Tabs label="Blueprint" value={tab} onChange={(t) => navigate(`/blueprint/${t}`)} tabs={TABS.map((t) => ({ ...t, count: t.id === 'impacts' ? reviews.length : t.id === 'assistant' ? unknownFacts(draft ?? pub).length : undefined }))} />
      <div className="row small">
        <span className="muted">Dernière version publiée :</span><Version n={pub?.number} />
        {draft && <><span className="muted">· en préparation :</span><Version n={draft.number} /><StatusBadge kind="blueprint" state={draft.status} /></>}
      </div>
      {tab === 'assistant' && <Assistant />}
      {tab === 'structure' && <Structure />}
      {tab === 'versions' && <Versions />}
      {tab === 'impacts' && <Impacts />}
      {tab === 'export' && <ExportProfile />}
    </div>
  );
}

/* ------------------------------------------------------------------ assistant */
function Assistant() {
  const s = useAppState();
  const draft = openDraft(s, s.session.orgId);
  const pub = latestPublished(s, s.session.orgId)!;
  const [why, setWhy] = useState('');
  const target = draft ?? pub;
  const unknowns = unknownFacts(target);
  const inferred = unconfirmedInferred(target);
  const conflicts = resolveRules(s, target).conflicts;
  const steps = [
    { label: 'Préparer une nouvelle version', done: !!draft },
    { label: 'Résoudre les inconnues ou les justifier', done: !!draft && unknowns.length === 0 },
    { label: 'Confirmer les valeurs inférées', done: !!draft && inferred.length === 0 },
    { label: 'Arbitrer les conflits de règles', done: !!draft && conflicts.length === 0 },
    { label: 'Soumettre en revue', done: draft?.status === 'review' },
    { label: 'Publication par une autre personne', done: false },
  ];
  return (
    <div className="grid-2">
      <Panel title="Faire évoluer le profil">
        <p className="muted small">Une version publiée est immuable : toute évolution passe par une nouvelle version, sa revue et sa publication. Les projets continuent de suivre leur version jusqu’à adoption explicite.</p>
        <ol className="plain closure">
          {steps.map((st, i) => <li key={st.label}><span className={st.done ? 'ok' : 'info'}><Icon name={st.done ? 'check' : 'dot'} size={14} /></span><span>{i + 1}. {st.label}</span></li>)}
        </ol>
        {!draft ? (
          <div className="stack" style={{ marginTop: 10 }}>
            <TextArea label="Pourquoi cette évolution ?" value={why} onChange={(e) => setWhy(e.target.value)} hint="Conservé avec la version." />
            <CmdButton def={cmd.startBlueprintDraft} payload={{ justification: why }} variant="primary" icon="plus" success={(n) => `Version ${n} en préparation`}>Préparer la version {(blueprintOf(s, s.session.orgId)?.versions.length ?? 0) + 1}</CmdButton>
          </div>
        ) : (
          <div className="stack" style={{ marginTop: 10 }}>
            <p className="small">Version {draft.number} préparée par <Person id={draft.authorId} /> — « {draft.justification} »</p>
            <Lifecycle kind="blueprint" id={blueprintOf(s, s.session.orgId)!.id} state={draft.status} version={draft.number} />
          </div>
        )}
      </Panel>
      <div className="stack">
        <Panel title={`Inconnues (${unknowns.length})`} tone={unknowns.length ? 'warn' : undefined}>
          {unknowns.length === 0 ? <p className="small muted">Aucune inconnue dans la version {target.number}.</p> : unknowns.map((f) => <FactRow key={f.key} f={f} version={target} />)}
        </Panel>
        <Panel title={`Valeurs inférées à confirmer (${inferred.length})`}>
          {inferred.length === 0 ? <p className="small muted">Toutes les valeurs inférées sont confirmées.</p> : inferred.map((f) => <FactRow key={f.key} f={f} version={target} />)}
        </Panel>
        {conflicts.length > 0 && <Panel title="Conflits à arbitrer" tone="danger">{conflicts.map((c) => <ConflictRow key={c.message} c={c} version={target} />)}</Panel>}
      </div>
    </div>
  );
}

function FactRow({ f, version }: { f: ContextFact; version: BlueprintVersion }) {
  const [value, setValue] = useState(f.value);
  const editable = version.status === 'draft';
  return (
    <div className="card" style={{ margin: 3 }}>
      <div className="row between"><strong>{f.label}</strong><ProvenanceBadge p={f.provenance} /></div>
      <p className="tiny muted" style={{ margin: '2px 0 6px' }}>{f.section} · {f.source}{f.confirmedBy ? ' · confirmée' : ''}</p>
      {editable ? (
        <div className="row">
          <div className="grow"><TextField label={<span className="sr-only">Valeur de {f.label}</span>} value={value} onChange={(e) => setValue(e.target.value)} placeholder={f.provenance === 'unknown' ? 'Renseigner la valeur…' : undefined} /></div>
          <CmdButton def={cmd.setFact} payload={{ version: version.number, key: f.key, value }} size="small" variant="primary" success={f.provenance === 'unknown' ? 'Inconnue résolue dans le brouillon' : 'Valeur enregistrée'}>{f.provenance === 'unknown' ? 'Résoudre' : 'Déclarer'}</CmdButton>
          {f.provenance === 'inferred' && !f.confirmedBy && <CmdButton def={cmd.confirmInferred} payload={{ version: version.number, key: f.key }} size="small" success="Valeur confirmée">Confirmer</CmdButton>}
        </div>
      ) : (
        <p style={{ margin: 0 }}>{f.provenance === 'unknown' ? <em className="muted">Inconnue — préparez une nouvelle version pour la résoudre.</em> : f.value}</p>
      )}
    </div>
  );
}

function ConflictRow({ c, version }: { c: ReturnType<typeof resolveRules>['conflicts'][number]; version: BlueprintVersion }) {
  const s = useAppState();
  const [keep, setKeep] = useState(c.rules[0].ruleId);
  const [reason, setReason] = useState('');
  return (
    <div className="card" style={{ margin: 3 }}>
      <p style={{ margin: '0 0 6px' }}><Icon name="warn" size={14} /> {c.message}</p>
      {c.kind === 'competing' && version.status === 'draft' && (
        <div className="stack tight">
          <Select label="Règle retenue" value={keep} onChange={(e) => setKeep(e.target.value)} options={c.rules.map((r) => ({ value: r.ruleId, label: objectLabel(s, { kind: 'rule', id: r.ruleId }) }))} />
          <TextField label="Motif de l’arbitrage" value={reason} onChange={(e) => setReason(e.target.value)} />
          <CmdButton def={cmd.arbitrateConflict} payload={{ version: version.number, keepRuleId: keep, dropRuleIds: c.rules.map((r) => r.ruleId).filter((x) => x !== keep), reason }} size="small" variant="primary" success="Arbitrage enregistré">Arbitrer</CmdButton>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ structure */
function Structure() {
  const s = useAppState();
  const route = useRoute();
  const draft = openDraft(s, s.session.orgId);
  const pub = latestPublished(s, s.session.orgId)!;
  const vn = Number(route.query.get('version') ?? (draft?.number ?? pub.number));
  const v = bpVersion(s, s.session.orgId, vn) ?? pub;
  const selectedRule = route.query.get('regle');
  const { rules, conflicts } = resolveRules(s, v);
  const products = list(s, 'product', s.session.orgId);
  const [form, setForm] = useState<{ rule?: Rule; adapts?: Rule } | null>(null);
  const editable = v.status === 'draft';
  const byScope = (pred: (sc: RuleScope) => boolean) => rules.filter((e) => pred(e.version.scope));
  const sections = [
    { title: 'Organisation', items: byScope((sc) => sc.level === 'org') },
    ...products.map((p) => ({ title: `Produit ${p.name}`, items: byScope((sc) => sc.level === 'product' && sc.productId === p.id) })),
    ...products.flatMap((p) => p.repos.map((r) => ({ title: `Dépôt ${r.name}`, items: byScope((sc) => (sc.level === 'repo' || sc.level === 'module') && sc.repoId === r.id) }))),
  ].filter((x) => x.items.length || x.title === 'Organisation');
  const sel = selectedRule ? rules.find((e) => e.rule.id === selectedRule) : undefined;
  return (
    <div className="stack">
      <div className="row">
        <Select label="Version affichée" value={String(v.number)} onChange={(e) => setQuery({ version: e.target.value })} options={blueprintOf(s, s.session.orgId)!.versions.map((x) => ({ value: String(x.number), label: `v${x.number} — ${x.status === 'published' ? 'publiée' : x.status === 'draft' ? 'brouillon' : x.status === 'review' ? 'en revue' : 'archivée'}` }))} />
        <StatusBadge kind="blueprint" state={v.status} />
        {!editable && <span className="small muted">Version {v.status === 'published' ? 'publiée : immuable' : 'non modifiable'}. {draft ? <a href={`#/blueprint/structure?version=${draft.number}`}>Modifier la v{draft.number} en préparation</a> : <a href="#/blueprint/assistant">Préparer une nouvelle version</a>}</span>}
        {editable && <CmdButton def={cmd.addRule} payload={{ version: v.number, rule: { code: 'NOUVELLE-01', title: 'Nouvelle règle', statement: 'Formulation vérifiable de la règle à préciser.', referenceIds: [], scope: { level: 'org' }, ownerId: 'x', criticality: 'moyenne', blocking: false, derogable: true, policy: 'additive', expectedControlIds: [], justification: '' } as RuleInput }} size="small" icon="plus" variant="primary" showReason onRun={() => setForm({})}>Ajouter une règle</CmdButton>}
      </div>
      {conflicts.map((c) => <Notice key={c.message} tone="warn">{c.message}</Notice>)}
      <div className="grid-2">
        <div className="stack">
          {sections.map((sec) => (
            <Panel key={sec.title} title={<span className="row"><Icon name="plan" size={14} />{sec.title}</span>}>
              {sec.items.length === 0 ? <p className="small muted">Aucune règle à ce niveau.</p> : (
                <ul className="plain stack tight">
                  {sec.items.map((e) => (
                    <li key={e.rule.id}>
                      <button className={`card ${selectedRule === e.rule.id ? 'selected' : ''}`} onClick={() => setQuery({ regle: e.rule.id })}>
                        <div className="row between"><strong>{e.rule.code}</strong><span className="row"><Version n={e.ref.version} />{e.version.status === 'draft' && <Badge tone="neutral" icon="draft">brouillon</Badge>}</span></div>
                        <span className="small">{e.version.title}</span>
                        <div className="row tiny" style={{ marginTop: 4 }}><Badge tone={e.version.policy === 'imposed' ? 'danger' : e.version.policy === 'adjustable' ? 'info' : 'success'}>{POLICIES[e.version.policy].label}</Badge><span>{e.version.criticality}</span>{e.version.blocking && <Badge tone="danger" icon="lock">bloquante</Badge>}{!e.version.derogable && <Badge tone="warning" icon="shield">non dérogeable</Badge>}{e.version.adapts && <Badge tone="info" icon="link">adapte {s.db.rule[e.version.adapts]?.code}</Badge>}{e.overriddenBy && <Badge tone="muted">adaptée plus bas</Badge>}</div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          ))}
        </div>
        <div className="stack">
          {sel ? <RuleDetail entry={sel} version={v} onEdit={() => setForm({ rule: sel.rule })} onAdapt={() => setForm({ adapts: sel.rule })} /> : <Panel title="Règle"><p className="muted">Sélectionnez une règle pour voir sa provenance, son propriétaire, sa version, son exigence, son périmètre et sa politique d’héritage.</p></Panel>}
          <ContextPanel v={v} />
          <ExclusionsPanel v={v} />
        </div>
      </div>
      {form && <RuleForm open version={v} rule={form.rule} adapts={form.adapts} onClose={() => setForm(null)} />}
    </div>
  );
}

function RuleDetail({ entry, version, onEdit, onAdapt }: { entry: ReturnType<typeof resolveRules>['rules'][number]; version: BlueprintVersion; onEdit: () => void; onAdapt: () => void }) {
  const s = useAppState();
  const v = entry.version;
  const sc = v.scope;
  const target = sc.level === 'org' ? s.orgs[s.session.orgId!]?.name : sc.level === 'product' ? s.db.product[sc.productId!]?.name : `${list(s, 'product', s.session.orgId).flatMap((p) => p.repos).find((r) => r.id === sc.repoId)?.name ?? ''}${sc.moduleId ? ` / ${list(s, 'product', s.session.orgId).flatMap((p) => p.repos.flatMap((r) => r.modules)).find((m) => m.id === sc.moduleId)?.name}` : ''}`;
  const controls = list(s, 'control', s.session.orgId).filter((c) => c.ruleIds.includes(entry.rule.id));
  const editable = version.status === 'draft';
  const [reason, setReason] = useState('');
  return (
    <Panel title={`${entry.rule.code} — ${v.title}`} actions={editable && <>
      <CmdButton def={cmd.editRule} payload={{ version: version.number, ruleId: entry.rule.id, patch: {} }} size="small" icon="edit" showReason onRun={onEdit}>Modifier</CmdButton>
      <Button size="small" icon="link" onClick={onAdapt}>Proposer une adaptation</Button>
    </>}>
      <p>{v.statement}</p>
      <KV items={[
        ['Provenance', v.referenceIds.length ? v.referenceIds.map((id) => <span key={id} style={{ display: 'block' }}><ObjectLink to={{ kind: 'reference', id }} /></span>) : 'Règle interne'],
        ['Propriétaire', <Person id={v.ownerId} />], ['Version', <><Version n={entry.ref.version} /> ({v.status === 'published' ? 'publiée' : 'brouillon'}, {fmtDate(v.createdAt)})</>],
        ['Exigence', `${v.criticality}${v.blocking ? ', bloquante' : ', informative'}${v.derogable ? ', dérogeable' : ', non dérogeable'}`],
        ['Périmètre', `${LEVELS[sc.level].label} — ${target}`], ['Héritage', `${POLICIES[v.policy].label} : ${POLICIES[v.policy].hint}`],
        ['Paramètre', v.parameter ? `${v.parameter.name} = ${v.parameter.value} ${v.parameter.unit} (bornes ${v.parameter.min}–${v.parameter.max})` : '—'],
        ['Contrôles attendus', controls.length ? controls.map((c) => <span key={c.id} style={{ display: 'block' }}>{c.code} — {c.name}</span>) : 'Aucun contrôle défini : une référence ne crée pas de contrôle automatiquement.'],
        ['Justification', v.justification],
      ]} />
      <p className="tiny muted" style={{ marginTop: 8 }}>Activer une règle n’ajoute ni preuve, ni validation, ni résultat réussi.</p>
      {editable && (
        <div className="row" style={{ marginTop: 8 }}>
          <div className="grow"><TextField label="Motif du retrait" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
          <CmdButton def={cmd.removeRuleFromDraft} payload={{ version: version.number, ruleId: entry.rule.id, reason }} size="small" variant="danger" icon="trash" success="Règle retirée du brouillon">Retirer de la version</CmdButton>
        </div>
      )}
      <h3 style={{ marginTop: 12 }}>Historique de la règle</h3>
      <ul className="plain stack tight">{entry.rule.versions.map((rv) => <li key={rv.number} className="small"><Version n={rv.number} /> {rv.status === 'published' ? 'publiée' : 'brouillon'} — {rv.title} · <Person id={rv.authorId} /> · {fmtDate(rv.createdAt)}</li>)}</ul>
    </Panel>
  );
}

function RuleForm({ open, version, rule, adapts, onClose }: { open: boolean; version: BlueprintVersion; rule?: Rule; adapts?: Rule; onClose: () => void }) {
  const s = useAppState();
  const cur: RuleVersion | undefined = rule?.versions.find((x) => x.number === version.rules.find((r) => r.ruleId === rule.id)?.version);
  const parent = adapts?.versions.find((x) => x.number === version.rules.find((r) => r.ruleId === adapts.id)?.version);
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : '';
  const products = list(s, 'product', s.session.orgId);
  const repos = products.flatMap((p) => p.repos);
  const [v, setV] = useState<RuleInput>(() => cur ? { code: rule!.code, title: cur.title, statement: cur.statement, referenceIds: cur.referenceIds, scope: cur.scope, ownerId: cur.ownerId, criticality: cur.criticality, blocking: cur.blocking, derogable: cur.derogable, policy: cur.policy, parameter: cur.parameter, expectedControlIds: cur.expectedControlIds, justification: '', conflictGroup: cur.conflictGroup }
    : { code: adapts ? `${adapts.code}-A` : '', title: parent ? `${parent.title} (adaptation)` : '', statement: parent?.statement ?? '', referenceIds: parent?.referenceIds ?? [], scope: adapts ? { level: 'product', productId: products[0]?.id } : { level: 'org' }, ownerId: me, criticality: parent?.criticality ?? 'moyenne', blocking: parent?.blocking ?? false, derogable: parent?.derogable ?? true, policy: parent?.policy === 'adjustable' ? 'adjustable' : 'additive', parameter: parent?.parameter ? { ...parent.parameter } : undefined, expectedControlIds: parent?.expectedControlIds ?? [], justification: '' });
  const [refQuery, setRefQuery] = useState('');
  const refs = useMemo(() => allReferences(s).filter((r) => refQuery.length > 1 && r.name.toLowerCase().includes(refQuery.toLowerCase())).slice(0, 8), [s, refQuery]);
  const members = [...new Set(list(s, 'member', s.session.orgId).map((m) => m.userId))];
  const submit = () => {
    const out = rule ? dispatch(cmd.editRule, { version: version.number, ruleId: rule.id, patch: v }, { success: 'Règle mise à jour dans le brouillon' }) : dispatch(cmd.addRule, { version: version.number, rule: v, adapts: adapts?.id }, { success: adapts ? 'Adaptation ajoutée' : 'Règle ajoutée' });
    if (out.ok) onClose();
  };
  const set = (patch: Partial<RuleInput>) => setV((x) => ({ ...x, ...patch }));
  return (
    <Dialog open={open} onClose={onClose} wide title={rule ? `Modifier ${rule.code} (nouvelle version de règle)` : adapts ? `Adapter ${adapts.code}` : 'Nouvelle règle'} footer={<><Button onClick={onClose}>Annuler</Button><Button variant="primary" onClick={submit}>Enregistrer dans la v{version.number}</Button></>}>
      {adapts && parent && <Notice tone={parent.policy === 'imposed' ? 'danger' : 'info'} title={`Politique de ${adapts.code} : ${POLICIES[parent.policy].label}.`}>{POLICIES[parent.policy].hint}{parent.parameter ? ` Bornes : ${parent.parameter.min}–${parent.parameter.max} ${parent.parameter.unit}.` : ''} Une adaptation interdite sera refusée avec son motif.</Notice>}
      <div className="form-grid">
        <TextField label="Code" value={v.code} disabled={!!rule} onChange={(e) => set({ code: e.target.value.toUpperCase() })} hint="Ex. SEC-ISO-02" />
        <TextField label="Titre" value={v.title} onChange={(e) => set({ title: e.target.value })} />
        <TextArea className="full" label="Formulation vérifiable" value={v.statement} onChange={(e) => set({ statement: e.target.value })} />
        <Select label="Niveau" value={v.scope.level} onChange={(e) => { const level = e.target.value as RuleScope['level']; set({ scope: level === 'org' ? { level } : level === 'product' ? { level, productId: products[0]?.id } : { level, repoId: repos[0]?.id, moduleId: level === 'module' ? repos[0]?.modules[0]?.id : undefined } }); }} options={Object.entries(LEVELS).map(([k, l]) => ({ value: k, label: l.label }))} />
        {v.scope.level === 'product' && <Select label="Produit" value={v.scope.productId} onChange={(e) => set({ scope: { level: 'product', productId: e.target.value } })} options={products.map((p) => ({ value: p.id, label: p.name }))} />}
        {(v.scope.level === 'repo' || v.scope.level === 'module') && <Select label="Dépôt" value={v.scope.repoId} onChange={(e) => set({ scope: { ...v.scope, repoId: e.target.value, moduleId: v.scope.level === 'module' ? repos.find((r) => r.id === e.target.value)?.modules[0]?.id : undefined } })} options={repos.map((r) => ({ value: r.id, label: r.name }))} />}
        {v.scope.level === 'module' && <Select label="Module" value={v.scope.moduleId} onChange={(e) => set({ scope: { ...v.scope, moduleId: e.target.value } })} options={(repos.find((r) => r.id === v.scope.repoId)?.modules ?? []).map((m) => ({ value: m.id, label: m.name }))} />}
        <Select label="Propriétaire" value={v.ownerId} onChange={(e) => set({ ownerId: e.target.value })} options={members.map((id) => ({ value: id, label: s.users[id]?.name ?? id }))} />
        <Select label="Criticité" value={v.criticality} onChange={(e) => set({ criticality: e.target.value as RuleInput['criticality'] })} options={['basse', 'moyenne', 'haute', 'critique'].map((x) => ({ value: x, label: x }))} />
        <Select label="Politique d’héritage" value={v.policy} onChange={(e) => set({ policy: e.target.value as RuleInput['policy'], parameter: e.target.value === 'adjustable' ? v.parameter ?? { name: 'valeur', unit: '', value: 1, min: 0, max: 10 } : undefined })} options={Object.entries(POLICIES).map(([k, p]) => ({ value: k, label: `${p.label} — ${p.hint}` }))} />
        <div className="row"><Checkbox label="Bloquante" checked={v.blocking} onChange={(e) => set({ blocking: e.target.checked })} /><Checkbox label="Dérogeable" checked={v.derogable} onChange={(e) => set({ derogable: e.target.checked })} /></div>
        {v.parameter && <>
          <TextField label="Paramètre" value={v.parameter.name} onChange={(e) => set({ parameter: { ...v.parameter!, name: e.target.value } })} />
          <TextField label="Unité" value={v.parameter.unit} onChange={(e) => set({ parameter: { ...v.parameter!, unit: e.target.value } })} />
          <TextField label="Valeur" type="number" value={v.parameter.value} onChange={(e) => set({ parameter: { ...v.parameter!, value: Number(e.target.value) } })} />
          <div className="row"><TextField label="Min" type="number" value={v.parameter.min} onChange={(e) => set({ parameter: { ...v.parameter!, min: Number(e.target.value) } })} /><TextField label="Max" type="number" value={v.parameter.max} onChange={(e) => set({ parameter: { ...v.parameter!, max: Number(e.target.value) } })} /></div>
        </>}
        <div className="full stack tight">
          <TextField label="Sources (références du catalogue)" value={refQuery} onChange={(e) => setRefQuery(e.target.value)} placeholder="Rechercher une référence à citer…" />
          {refs.length > 0 && <div className="row">{refs.map((r) => <Button key={r.id} size="small" icon="plus" onClick={() => { set({ referenceIds: [...new Set([...v.referenceIds, r.id])] }); setRefQuery(''); }}>{r.name}</Button>)}</div>}
          <div className="row">{v.referenceIds.map((id) => <span key={id} className="chip">{referenceById(s, id)?.name ?? id}<button className="linklike" aria-label={`Retirer ${id}`} onClick={() => set({ referenceIds: v.referenceIds.filter((x) => x !== id) })}><Icon name="close" size={10} /></button></span>)}</div>
        </div>
        <TextArea className="full" label="Justification" value={v.justification} onChange={(e) => set({ justification: e.target.value })} />
      </div>
    </Dialog>
  );
}

function ContextPanel({ v }: { v: BlueprintVersion }) {
  const groups = [...new Set(v.context.map((f) => f.section))];
  return (
    <Panel title="Contexte déclaré, observé, inféré et inconnu">
      {groups.map((g) => (
        <details key={g} open={g === 'Données et exigences'}>
          <summary className="small" style={{ cursor: 'pointer', fontWeight: 600, padding: '4px 0' }}>{g}</summary>
          {v.context.filter((f) => f.section === g).map((f) => <FactRow key={f.key} f={f} version={v} />)}
        </details>
      ))}
    </Panel>
  );
}

function ExclusionsPanel({ v }: { v: BlueprintVersion }) {
  const s = useAppState();
  const [refId, setRefId] = useState('');
  const [reason, setReason] = useState('');
  return (
    <Panel title="Exclusions justifiées">
      {v.exclusions.length === 0 ? <p className="small muted">Aucune.</p> : <ul className="plain stack tight">{v.exclusions.map((e) => <li key={e.refId} className="small"><ObjectLink to={{ kind: 'reference', id: e.refId }} /> — {e.reason} <span className="muted">(<Person id={e.authorId} />, {fmtDate(e.at)})</span></li>)}</ul>}
      {v.status === 'draft' && (
        <div className="stack tight" style={{ marginTop: 8 }}>
          <Select label="Référence exclue" value={refId} onChange={(e) => setRefId(e.target.value)} placeholder="Choisir…" options={allReferences(s).filter((r) => r.natureGroup === 'reglementation' || r.natureGroup === 'norme').map((r) => ({ value: r.id, label: r.name }))} />
          <TextArea label="Justification" value={reason} onChange={(e) => setReason(e.target.value)} />
          <CmdButton def={cmd.excludeReference} payload={{ version: v.number, refId, reason }} size="small" success="Exclusion enregistrée">Justifier l’exclusion</CmdButton>
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ versions */
function factsText(v?: BlueprintVersion) { return (v?.context ?? []).map((f) => `${f.label} : ${f.provenance === 'unknown' ? '(inconnue)' : f.value} [${f.provenance}]`).join('\n'); }
function rulesText(s: ReturnType<typeof useAppState>, v?: BlueprintVersion) { return (v?.rules ?? []).map((r) => { const rv = s.db.rule[r.ruleId]?.versions.find((x) => x.number === r.version); return `${s.db.rule[r.ruleId]?.code} v${r.version} — ${rv?.title} : ${rv?.statement}`; }).sort().join('\n'); }

function Versions() {
  const s = useAppState();
  const bp = blueprintOf(s, s.session.orgId)!;
  const [a, setA] = useState(String(Math.max(1, bp.versions.length - 1)));
  const [b, setB] = useState(String(bp.versions.length));
  const va = bpVersion(s, s.session.orgId, Number(a));
  const vb = bpVersion(s, s.session.orgId, Number(b));
  return (
    <div className="stack">
      <Panel title="Versions du Blueprint">
        <table className="data responsive">
          <thead><tr><th>Version</th><th>État</th><th>Auteur</th><th>Relecture</th><th>Justification</th><th>Projets</th><th>Actions</th></tr></thead>
          <tbody>
            {[...bp.versions].reverse().map((v) => (
              <tr key={v.number}>
                <td data-label="Version"><Version n={v.number} /> <span className="tiny muted">{fmtDate(v.publishedAt ?? v.createdAt)}</span></td>
                <td data-label="État"><StatusBadge kind="blueprint" state={v.status} /></td>
                <td data-label="Auteur"><Person id={v.authorId} /></td>
                <td data-label="Relecture">{v.reviewerId ? <Person id={v.reviewerId} /> : '—'}</td>
                <td data-label="Justification" className="small">{v.justification}</td>
                <td data-label="Projets" className="small">{list(s, 'project', s.session.orgId).filter((p) => p.blueprintVersion === v.number).map((p) => p.name).join(', ') || '—'}</td>
                <td data-label="Actions"><Lifecycle kind="blueprint" id={bp.id} state={v.status} version={v.number} compact /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="Comparer deux versions">
        <div className="row">
          <Select label="De" value={a} onChange={(e) => setA(e.target.value)} options={bp.versions.map((v) => ({ value: String(v.number), label: `v${v.number}` }))} />
          <Select label="À" value={b} onChange={(e) => setB(e.target.value)} options={bp.versions.map((v) => ({ value: String(v.number), label: `v${v.number}` }))} />
        </div>
        <h3>Contexte</h3>
        <DiffView before={factsText(va)} after={factsText(vb)} labels={[`v${a}`, `v${b}`]} />
        <h3 style={{ marginTop: 12 }}>Règles</h3>
        <DiffView before={rulesText(s, va)} after={rulesText(s, vb)} labels={[`v${a}`, `v${b}`]} />
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ impacts */
function Impacts() {
  const s = useAppState();
  const bp = blueprintOf(s, s.session.orgId)!;
  const projects = list(s, 'project', s.session.orgId).filter((p) => p.status === 'active');
  const route = useRoute();
  const requestedProjectId = route.query.get('projet');
  const project = requestedProjectId
    ? projects.find((p) => p.id === requestedProjectId)
    : projects.find((p) => p.id === s.session.projectId) ?? projects[0];
  const candidates = bp.versions.filter((v) => v.number !== project?.blueprintVersion && v.status !== 'archived');
  const [target, setTarget] = useState(String(openDraft(s, s.session.orgId)?.number ?? candidates.at(-1)?.number ?? ''));
  const to = bpVersion(s, s.session.orgId, Number(target));
  const impacts = project ? blueprintImpacts(s, bpVersion(s, s.session.orgId, project.blueprintVersion), to, project.id) : undefined;
  const reviews = list(s, 'review', s.session.orgId).sort((a, b) => b.createdAt - a.createdAt);
  return (
    <div className="stack">
      <Panel title="Impacts d’une version sur un projet">
        <div className="row">
          <Select label="Projet" value={project?.id ?? ''} placeholder="Choisir un projet" onChange={(e) => setQuery({ projet: e.target.value })} options={projects.map((p) => ({ value: p.id, label: `${p.name} (suit v${p.blueprintVersion})` }))} />
          <Select label="Version envisagée" value={target} onChange={(e) => setTarget(e.target.value)} options={candidates.map((v) => ({ value: String(v.number), label: `v${v.number} (${v.status === 'published' ? 'publiée' : v.status === 'draft' ? 'brouillon' : 'en revue'})` }))} />
        </div>
        {requestedProjectId && !project && <p className="small muted">Projet indisponible dans cette organisation.</p>}
        {impacts && to && (
          <div className="stack" style={{ marginTop: 10 }}>
            {impacts.conflicts.map((c) => <Notice key={c.message} tone="warn">{c.message}</Notice>)}
            <div className="grid-3">
              <Panel title={`Règles concernées (${impacts.changedRules.length})`}><ul className="plain small stack tight">{impacts.changedRules.map((c) => <li key={c.rule.id}><Badge tone={c.change === 'retirée' ? 'danger' : c.change === 'ajoutée' ? 'success' : 'info'}>{c.change}</Badge> {c.rule.code} {c.from ? `v${c.from}` : ''}{c.to ? ` → v${c.to}` : ''}</li>)}</ul></Panel>
              <Panel title={`Contexte modifié (${impacts.changedFacts.length})`}><ul className="plain small stack tight">{impacts.changedFacts.map((f) => <li key={f.label}>{f.resolved && <Badge tone="success" icon="check">inconnue résolue</Badge>} {f.label} : <span className="muted">{f.from}</span> → {f.to}</li>)}</ul></Panel>
              <Panel title={`Contrôles à réexécuter (${impacts.controls.length})`}><ul className="plain small">{impacts.controls.map((c) => <li key={c.id}>{c.code} — {c.name}</li>)}</ul><p className="tiny muted">{impacts.staleResults.length} résultat(s) deviendront « à réévaluer ».</p></Panel>
              <Panel title={`Missions impactées (${impacts.quests.length})`}><ul className="plain small">{impacts.quests.map((q) => <li key={q.id}><ObjectLink to={{ kind: 'quest', id: q.id }} /></li>)}</ul></Panel>
              <Panel title={`Décisions à réexaminer (${impacts.decisions.length})`}><ul className="plain small">{impacts.decisions.map((d) => <li key={d.id}><ObjectLink to={{ kind: 'decision', id: d.id }} /></li>)}</ul><p className="tiny muted">Les décisions historiques ne sont pas modifiées.</p></Panel>
              <Panel title={`Documents à actualiser (${impacts.docs.length})`}><ul className="plain small">{impacts.docs.map((d) => <li key={d.id}><ObjectLink to={{ kind: 'deliverable', id: d.id }} /></li>)}</ul></Panel>
            </div>
            {to.status === 'published' ? (
              <CmdButton def={cmd.adoptBlueprint} payload={{ projectId: project!.id, version: to.number, reason: '' }} variant="primary" icon="check" success={`« ${project!.name} » suit désormais la v${to.number}`}
                confirm={{ title: `Adopter la v${to.number} pour « ${project!.name} »`, message: <p>Les éléments listés seront marqués à réexaminer. Les décisions et résultats historiques restent consultables sans modification.</p>, needsReason: true, label: 'Adopter la version' }}>Adopter la v{to.number} pour ce projet</CmdButton>
            ) : <Notice>La version {to.number} n’est pas publiée : ses impacts sont présentés avant publication ; elle ne peut pas encore être adoptée.</Notice>}
          </div>
        )}
      </Panel>
      <Panel title={`Éléments à réexaminer (${reviews.filter((r) => r.status === 'open').length})`}>
        {reviews.length === 0 ? <p className="small muted">Aucun réexamen demandé.</p> : <ul className="plain stack tight">{reviews.map((r) => <ReviewRow key={r.id} id={r.id} />)}</ul>}
      </Panel>
    </div>
  );
}

function ReviewRow({ id }: { id: ID }) {
  const s = useAppState();
  const r = s.db.review[id];
  const [note, setNote] = useState('');
  return (
    <li className="card" style={{ margin: 3 }}>
      <div className="row between"><span className="row"><StatusBadge kind="review" state={r.status} /><ObjectLink to={r.subject} /></span><span className="tiny muted">{fmtDate(r.createdAt, true)}</span></div>
      <p className="small" style={{ margin: '4px 0' }}>{r.reason} — cause : <ObjectLink to={r.cause} /></p>
      {r.status === 'open' ? <div className="row"><div className="grow"><TextField label="Conclusion" value={note} onChange={(e) => setNote(e.target.value)} /></div><CmdButton def={cmd.resolveReview} payload={{ id, note }} size="small" success="Réexamen conclu">Marquer réexaminé</CmdButton></div> : <p className="tiny muted">Réexaminé par {s.users[r.doneBy ?? '']?.name}</p>}
    </li>
  );
}

/* ------------------------------------------------------------------ export */
export function blueprintExport(s: ReturnType<typeof useAppState>, v: BlueprintVersion) {
  const org = s.orgs[s.session.orgId!];
  return {
    format: 'ogk-blueprint/1',
    note: 'Export de démonstration Open Guild Kit. Aucune certification ni attestation n’est déduite de ce profil.',
    organisation: org.name,
    version: v.number,
    statut: v.status,
    publiee_le: v.publishedAt ? new Date(v.publishedAt).toISOString() : null,
    auteur: s.users[v.authorId]?.name ?? v.authorId,
    relecture: v.reviewerId ? s.users[v.reviewerId]?.name : null,
    justification: v.justification,
    contexte: v.context.map((f) => ({ cle: f.key, section: f.section, libelle: f.label, valeur: f.provenance === 'unknown' ? null : f.value, provenance: f.provenance, confirme: f.provenance === 'inferred' ? !!f.confirmedBy : undefined })),
    inconnues: unknownFacts(v).map((f) => f.label),
    regles: v.rules.map((r) => {
      const rule = s.db.rule[r.ruleId];
      const rv = rule?.versions.find((x) => x.number === r.version);
      return { code: rule?.code, version: r.version, titre: rv?.title, formulation: rv?.statement, niveau: rv?.scope.level, politique: rv?.policy, criticite: rv?.criticality, bloquante: rv?.blocking, derogeable: rv?.derogable, parametre: rv?.parameter ?? null, references: rv?.referenceIds, adapte: rv?.adapts ? s.db.rule[rv.adapts]?.code : null, proprietaire: s.users[rv?.ownerId ?? '']?.name };
    }),
    exclusions: v.exclusions.map((e) => ({ reference: referenceById(s, e.refId)?.name ?? e.refId, motif: e.reason })),
  };
}

function ExportProfile() {
  const s = useAppState();
  const bp = blueprintOf(s, s.session.orgId)!;
  const [vn, setVn] = useState(String(latestPublished(s, s.session.orgId)?.number ?? 1));
  const v = bpVersion(s, s.session.orgId, Number(vn))!;
  const data = blueprintExport(s, v);
  const md = `# Blueprint ${data.organisation} — v${data.version}\n\n> ${data.note}\n\n## Contexte\n${data.contexte.map((f) => `- **${f.libelle}** : ${f.valeur ?? '_inconnue_'} (${f.provenance})`).join('\n')}\n\n## Règles\n${data.regles.map((r) => `### ${r.code} v${r.version} — ${r.titre}\n${r.formulation}\n\n- Niveau : ${r.niveau} · Politique : ${r.politique} · Criticité : ${r.criticite}${r.bloquante ? ' · bloquante' : ''}${r.derogeable ? '' : ' · non dérogeable'}\n- Références : ${(r.references ?? []).join(', ') || '—'}`).join('\n\n')}\n\n## Exclusions\n${data.exclusions.map((e) => `- ${e.reference} : ${e.motif}`).join('\n') || '—'}\n`;
  const exportAs = (format: 'json' | 'yaml' | 'md') => {
    const out = dispatch(cmd.recordExport, { what: `Blueprint v${v.number}`, format: format.toUpperCase(), count: data.regles.length, object: { kind: 'blueprint', id: bp.id, version: v.number } }, {});
    if (!out.ok) return;
    const text = format === 'json' ? JSON.stringify(data, null, 2) : format === 'yaml' ? `# ${data.note}\n${toYaml(data)}\n` : md;
    download(`blueprint-v${v.number}.${format === 'md' ? 'md' : format}`, format === 'json' ? 'application/json' : format === 'yaml' ? 'application/yaml' : 'text/markdown', text);
  };
  return (
    <Panel title="Exporter le profil et ses règles">
      <div className="row">
        <Select label="Version" value={vn} onChange={(e) => setVn(e.target.value)} options={bp.versions.map((x) => ({ value: String(x.number), label: `v${x.number}` }))} />
        <CmdButton def={cmd.recordExport} payload={{ what: 'Blueprint', format: 'JSON', count: 0 }} icon="download" onRun={() => exportAs('json')}>JSON</CmdButton>
        <CmdButton def={cmd.recordExport} payload={{ what: 'Blueprint', format: 'YAML', count: 0 }} icon="download" onRun={() => exportAs('yaml')}>YAML</CmdButton>
        <CmdButton def={cmd.recordExport} payload={{ what: 'Blueprint', format: 'MD', count: 0 }} icon="download" onRun={() => exportAs('md')}>Markdown</CmdButton>
      </div>
      <p className="small muted">Format <code>ogk-blueprint/1</code>, documenté dans <code>web/docs/formats.md</code> : contexte avec provenance, inconnues, règles versionnées avec niveau, politique, criticité et références, exclusions justifiées. Capacité requise : {CAPABILITIES.export.toLowerCase()}.</p>
      <pre className="code" style={{ maxHeight: 360 }}><code>{JSON.stringify(data, null, 2)}</code></pre>
    </Panel>
  );
}
