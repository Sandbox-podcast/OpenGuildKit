/**
 * Library: the reference catalogue, sheets, applicability, activation into rules, collections, packs, imports and update
 * proposals (brief §5.5).
 */
import { useMemo, useRef, useState } from 'react';
import { NotFound } from '@/demo/app/App';
import { dispatch, useAppState } from '@/demo/app/store';
import { navigate, setQuery, useRoute } from '@/shared/router';
import { aliasesOf, norm } from '@/demo/app/search';
import { cmd } from '@/demo/domain/commands';
import { list } from '@/demo/domain/engine';
import { stateDef } from '@/demo/domain/machines';
import {
  allReferences,
  approvalValidity,
  baseCatalogueInfo,
  fmtDate,
  latestResults,
  openDraft,
  projectRules,
  referenceById,
  resultFreshness,
} from '@/demo/domain/selectors';
import type { ApplicabilityStatus, ID } from '@/demo/domain/types';
import {
  catalogueStats,
  NATURE_GROUPS,
  PUBLICATION_STATUS,
  previewCatalogueImport,
  type ImportPreview,
  type Reference,
} from '@/demo/adapters/catalogue';
import { CLI_PACKS } from '@/demo/fixtures/registry';
import { download } from '@/demo/adapters/export';
import { Icon } from '@/shared/pixel/icons';
import { Badge, Button, Checkbox, Empty, KV, Notice, Panel, Segmented, Select, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { CmdButton, ObjectLink, Person } from '@/demo/ui/domain';
import { DiffView } from '@/demo/ui/content';

const APPLICABILITY: Record<ApplicabilityStatus, { label: string; tone: 'success' | 'muted' | 'warning' }> = {
  applicable: { label: 'Applicable', tone: 'success' },
  not_applicable: { label: 'Non applicable', tone: 'muted' },
  to_clarify: { label: 'À préciser', tone: 'warning' },
};

export function LibrarySpace({ tab = 'catalogue' }: { tab?: string }) {
  const s = useAppState();
  const refs = allReferences(s);
  const proposals = s.catalogue.proposals.filter((p) => p.status === 'proposed');
  return (
    <div className="stack">
      <Tabs
        label="Bibliothèque"
        value={tab}
        onChange={(t) => navigate(`/bibliotheque/${t === 'catalogue' ? '' : t}`)}
        tabs={[
          { id: 'catalogue', label: `Catalogue (${refs.length})`, icon: 'book' },
          { id: 'applicabilite', label: 'Applicabilité par projet', icon: 'check' },
          { id: 'collections', label: 'Collections et favoris', icon: 'star' },
          { id: 'packs', label: 'Packs', icon: 'archive' },
          { id: 'propositions', label: 'Mises à jour proposées', icon: 'spark', count: proposals.length },
          { id: 'import', label: 'Import', icon: 'upload' },
        ]}
      />
      {tab === 'catalogue' && <Catalogue />}
      {tab === 'applicabilite' && <ApplicabilityView />}
      {tab === 'collections' && <Collections />}
      {tab === 'packs' && <Packs />}
      {tab === 'propositions' && <Proposals />}
      {tab === 'import' && <ImportView />}
    </div>
  );
}

/* ------------------------------------------------------------------ catalogue */
function Catalogue() {
  const s = useAppState();
  const route = useRoute();
  const refs = allReferences(s);
  const stats = catalogueStats(refs);
  const q = route.query.get('q') ?? '';
  const fam = route.query.get('famille') ?? '';
  const cat = route.query.get('categorie') ?? '';
  const nat = route.query.get('nature') ?? '';
  const st = route.query.get('statut') ?? '';
  const proj = route.query.get('projet') ?? '';
  const view = route.query.get('vue') ?? 'grille';
  const favs = s.catalogue.favorites[s.session.orgId!] ?? [];
  const apps = list(s, 'applicability', s.session.orgId);
  const [facetsOpen, setFacetsOpen] = useState(false);
  const filtered = useMemo(() => {
    const tokens = norm(q).split(/\s+/).filter(Boolean);
    return refs.filter((r) => {
      if (fam && r.familyId !== fam) return false;
      if (cat && r.categoryId !== cat) return false;
      if (nat && r.natureGroup !== nat) return false;
      if (st === 'favoris' && !favs.includes(r.id)) return false;
      if (st === 'suggestion' && !apps.some((a) => a.refId === r.id && !a.validated && (!proj || a.projectId === proj))) return false;
      if (st && st in PUBLICATION_STATUS && r.publicationStatus !== st) return false;
      if (proj && st !== 'suggestion' && !apps.some((a) => a.refId === r.id && a.projectId === proj)) return false;
      if (!tokens.length) return true;
      const text = norm(`${r.name} ${aliasesOf(r).join(' ')} ${r.description} ${r.whenToUse} ${r.nature}`);
      return tokens.every((t) => text.includes(t));
    });
  }, [refs, q, fam, cat, nat, st, proj, favs, apps]);
  const families = [...new Map(refs.map((r) => [r.familyId, r.family])).entries()];
  const categories = [...new Map(refs.filter((r) => !fam || r.familyId === fam).map((r) => [r.categoryId, r.category])).entries()];
  const count = (pred: (r: Reference) => boolean) => refs.filter(pred).length;
  return (
    <div className="library-layout">
      <aside className={`facets panel ${facetsOpen ? 'open' : ''}`} aria-label="Filtres du catalogue">
        <p className="small" style={{ margin: '0 0 8px' }}>
          <strong>{stats.references}</strong> références chargées · {stats.categories} catégories · {stats.families} familles
          <br />
          <span className="tiny muted">
            Édition {baseCatalogueInfo.edition}. {baseCatalogueInfo.notice}
          </span>
        </p>
        <h3 className="small">Famille</h3>
        <div className="facet">
          {families.map(([id, label]) => (
            <button key={id} aria-pressed={fam === id} onClick={() => setQuery({ famille: fam === id ? null : id, categorie: null })}>
              <span>{label}</span>
              <span>{count((r) => r.familyId === id)}</span>
            </button>
          ))}
        </div>
        {fam && (
          <>
            <h3 className="small" style={{ marginTop: 10 }}>
              Catégorie
            </h3>
            <div className="facet">
              {categories.map(([id, label]) => (
                <button key={id} aria-pressed={cat === id} onClick={() => setQuery({ categorie: cat === id ? null : id })}>
                  <span>{label}</span>
                  <span>{count((r) => r.categoryId === id)}</span>
                </button>
              ))}
            </div>
          </>
        )}
        <h3 className="small" style={{ marginTop: 10 }}>
          Nature
        </h3>
        <div className="facet">
          {Object.entries(NATURE_GROUPS).map(([id, label]) => (
            <button key={id} aria-pressed={nat === id} onClick={() => setQuery({ nature: nat === id ? null : id })}>
              <span>{label}</span>
              <span>{count((r) => r.natureGroup === id)}</span>
            </button>
          ))}
        </div>
        <h3 className="small" style={{ marginTop: 10 }}>
          Statut
        </h3>
        <div className="facet">
          {Object.entries(PUBLICATION_STATUS).map(([id, label]) => (
            <button key={id} aria-pressed={st === id} onClick={() => setQuery({ statut: st === id ? null : id })}>
              <span>{label}</span>
              <span>{count((r) => r.publicationStatus === id)}</span>
            </button>
          ))}
          <button aria-pressed={st === 'favoris'} onClick={() => setQuery({ statut: st === 'favoris' ? null : 'favoris' })}>
            <span>Mes favoris</span>
            <span>{favs.length}</span>
          </button>
          <button aria-pressed={st === 'suggestion'} onClick={() => setQuery({ statut: st === 'suggestion' ? null : 'suggestion' })}>
            <span>Suggestions à valider</span>
            <span>{apps.filter((a) => !a.validated).length}</span>
          </button>
        </div>
        <h3 className="small" style={{ marginTop: 10 }}>
          Projet
        </h3>
        <Select
          label={<span className="sr-only">Projet</span>}
          value={proj}
          placeholder="Tous"
          onChange={(e) => setQuery({ projet: e.target.value })}
          options={list(s, 'project', s.session.orgId).map((p) => ({ value: p.id, label: p.name }))}
        />
      </aside>
      <section className="panel" aria-label="Références">
        <div className="collection-bar">
          <div className="field search-field">
            <label className="sr-only" htmlFor="lib-q">
              Rechercher une référence
            </label>
            <input
              id="lib-q"
              type="search"
              value={q}
              placeholder="Nom ou sigle (RGPD, SemVer, ASVS)"
              onChange={(e) => setQuery({ q: e.target.value })}
            />
          </div>
          <Button size="small" className="facet-toggle" icon="filter" onClick={() => setFacetsOpen((o) => !o)} aria-expanded={facetsOpen}>
            Filtres
          </Button>
          <span className="small muted" aria-live="polite">
            {filtered.length} / {refs.length}
          </span>
          {(fam || cat || nat || st || proj || q) && (
            <button
              className="linklike small"
              onClick={() => setQuery({ famille: null, categorie: null, nature: null, statut: null, projet: null, q: null })}
            >
              Réinitialiser la recherche
            </button>
          )}
          <div style={{ marginLeft: 'auto' }}>
            <Segmented
              label="Vue"
              value={view}
              onChange={(v) => setQuery({ vue: v })}
              options={[
                { value: 'grille', label: 'Grille', icon: 'grid' },
                { value: 'liste', label: 'Liste', icon: 'list' },
              ]}
            />
          </div>
        </div>
        {filtered.length === 0 ? (
          <Empty title="Aucune référence trouvée">Modifiez la recherche ou retirez un filtre.</Empty>
        ) : view === 'liste' ? (
          <table className="data responsive">
            <thead>
              <tr>
                <th>Référence</th>
                <th>Nature</th>
                <th>Catégorie</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 200).map((r) => (
                <tr key={r.id}>
                  <td data-label="Référence">
                    <a href={`#/bibliotheque/ref/${r.id}`}>{r.name}</a>
                    {favs.includes(r.id) && <Icon name="star" size={10} className="fav-on" />}
                  </td>
                  <td data-label="Nature">{r.nature}</td>
                  <td data-label="Catégorie" className="small">
                    {r.category}
                  </td>
                  <td data-label="Statut">
                    {r.publicationStatus !== 'published' ? (
                      <Badge tone="warning">{PUBLICATION_STATUS[r.publicationStatus]}</Badge>
                    ) : (
                      <span className="tiny muted">publiée</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="ref-grid">
            {filtered.slice(0, 200).map((r) => (
              <a key={r.id} className="card ref-card" href={`#/bibliotheque/ref/${r.id}`}>
                <div className="row between">
                  <h3>{r.name}</h3>
                  {favs.includes(r.id) && <Icon name="star" size={12} className="fav-on" label="favori" />}
                </div>
                <div className="row tiny" style={{ marginBottom: 4 }}>
                  <Badge tone="info">{r.nature}</Badge>
                  {r.publicationStatus !== 'published' && <Badge tone="warning">{PUBLICATION_STATUS[r.publicationStatus]}</Badge>}
                </div>
                <p className="desc">{r.description}</p>
                <span className="tiny muted">{r.category}</span>
              </a>
            ))}
          </div>
        )}
        {filtered.length > 200 && <p className="small muted">Seuls les 200 premiers résultats sont affichés. Affinez la recherche.</p>}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ reference sheet */
export function ReferenceSheet({ id }: { id?: string }) {
  const s = useAppState();
  const r = id ? referenceById(s, id) : undefined;
  const [edit, setEdit] = useState(false);
  if (!r) return <NotFound what="Référence" />;
  const favs = s.catalogue.favorites[s.session.orgId!] ?? [];
  const rules = list(s, 'rule', s.session.orgId).filter((x) => x.versions.some((v) => v.referenceIds.includes(r.id)));
  const controls = list(s, 'control', s.session.orgId).filter((c) => c.ruleIds.some((rid) => rules.some((x) => x.id === rid)));
  const experts = list(s, 'expert', s.session.orgId).filter((e) => e.sources.includes(r.id));
  const apps = list(s, 'applicability', s.session.orgId).filter((a) => a.refId === r.id);
  const history = s.catalogue.history[r.id] ?? [];
  const collections = list(s, 'collection', s.session.orgId);
  return (
    <div className="stack">
      <Panel
        title={r.name}
        actions={
          <>
            <Button
              size="small"
              icon="star"
              aria-pressed={favs.includes(r.id)}
              onClick={() => dispatch(cmd.toggleFavoriteReference, { refId: r.id }, { silent: true })}
            >
              {favs.includes(r.id) ? 'Favori' : 'Ajouter aux favoris'}
            </Button>
            <CmdButton
              def={cmd.editReference}
              payload={{ refId: r.id, patch: {}, note: 'xxx' }}
              size="small"
              icon="edit"
              showReason={false}
              onRun={() => setEdit((e) => !e)}
            >
              Modifier la fiche
            </CmdButton>
          </>
        }
      >
        <div className="row" style={{ marginBottom: 8 }}>
          <Badge tone="info">{r.nature}</Badge>
          <Badge tone="neutral">{NATURE_GROUPS[r.natureGroup]}</Badge>
          <Badge tone={r.publicationStatus === 'published' ? 'success' : 'warning'}>{PUBLICATION_STATUS[r.publicationStatus]}</Badge>
          {aliasesOf(r).map((a) => (
            <span key={a} className="chip">
              {a}
            </span>
          ))}
        </div>
        <p>{r.description}</p>
        <KV
          items={[
            ['Quand l’utiliser', r.whenToUse],
            ['Famille · catégorie', `${r.family} · ${r.category}`],
            ['Édition du catalogue', r.edition],
            ['Précision de statut', r.statusNote ?? 'Publiée par sa source ; version et conditions à vérifier lors de l’intégration.'],
            [
              'Sources',
              <ul className="plain">
                {r.sources.map((src) => (
                  <li key={src.url}>
                    <a href={src.url} target="_blank" rel="noopener noreferrer">
                      {src.label} <Icon name="external" size={10} />
                    </a>
                  </li>
                ))}
              </ul>,
            ],
          ]}
        />
      </Panel>
      {edit && <EditReference r={r} onClose={() => setEdit(false)} />}
      <div className="grid-2">
        <ProjectStatus r={r} />
        <Activation r={r} />
      </div>
      <div className="grid-2">
        <Panel title="Relations">
          <KV
            items={[
              [
                'Règles',
                rules.length
                  ? rules.map((x) => (
                      <span key={x.id} style={{ display: 'block' }}>
                        <ObjectLink to={{ kind: 'rule', id: x.id }} />
                      </span>
                    ))
                  : 'Aucune règle ne cite cette référence.',
              ],
              [
                'Contrôles',
                controls.length
                  ? controls.map((c) => (
                      <span key={c.id} style={{ display: 'block' }}>
                        {c.code} — {c.name}
                      </span>
                    ))
                  : 'Aucun contrôle relié.',
              ],
              [
                'Projets',
                apps.length
                  ? apps.map((a) => (
                      <span key={a.id} style={{ display: 'block' }}>
                        <ObjectLink to={{ kind: 'project', id: a.projectId }} /> — {APPLICABILITY[a.status].label}
                      </span>
                    ))
                  : '—',
              ],
              [
                'Expertises',
                experts.length ? (
                  <div className="row">
                    {experts.map((e) => (
                      <a key={e.id} href={`#/guilde/${e.id}`}>
                        {e.name}
                      </a>
                    ))}
                  </div>
                ) : (
                  '—'
                ),
              ],
              [
                'Documents',
                list(s, 'deliverable', s.session.orgId)
                  .filter((d) => d.versions.some((v) => JSON.stringify(v.content).includes(r.name)))
                  .map((d) => (
                    <span key={d.id} style={{ display: 'block' }}>
                      <ObjectLink to={{ kind: 'deliverable', id: d.id }} />
                    </span>
                  )),
              ],
            ]}
          />
        </Panel>
        <Panel title="Collections">
          {collections.map((c) => (
            <Checkbox
              key={c.id}
              label={c.name}
              checked={c.refIds.includes(r.id)}
              onChange={() => dispatch(cmd.toggleInCollection, { collectionId: c.id, refId: r.id }, { silent: true })}
            />
          ))}
          <a href="#/bibliotheque/collections" className="small">
            Gérer les collections
          </a>
        </Panel>
      </div>
      {history.length > 0 && (
        <Panel title={`Versions de la fiche (${history.length})`}>
          {history.map((h, i) => (
            <details key={i}>
              <summary className="small">
                {fmtDate(h.at, true)} — {h.note} (<Person id={h.authorId} />)
              </summary>
              <DiffView
                before={`${h.data.description}\n${h.data.whenToUse}\n${h.data.nature}`}
                after={`${r.description}\n${r.whenToUse}\n${r.nature}`}
                labels={['version enregistrée', 'version actuelle']}
              />
              <CmdButton
                def={cmd.restoreReference}
                payload={{ refId: r.id, index: i }}
                size="small"
                icon="replace"
                success="Fiche restaurée par une nouvelle version"
              >
                Restaurer cette version
              </CmdButton>
            </details>
          ))}
        </Panel>
      )}
    </div>
  );
}

function EditReference({ r, onClose }: { r: Reference; onClose: () => void }) {
  const [v, setV] = useState({ description: r.description, whenToUse: r.whenToUse, nature: r.nature, note: '' });
  return (
    <Panel title="Modifier la fiche (la version précédente reste restaurable)">
      <div className="form-grid">
        <TextArea
          className="full"
          label="Description"
          value={v.description}
          onChange={(e) => setV({ ...v, description: e.target.value })}
        />
        <TextArea
          className="full"
          label="Quand l’utiliser"
          value={v.whenToUse}
          onChange={(e) => setV({ ...v, whenToUse: e.target.value })}
        />
        <TextField label="Nature" value={v.nature} onChange={(e) => setV({ ...v, nature: e.target.value })} />
        <TextField label="Note de modification" value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />
      </div>
      <div className="row end">
        <Button onClick={onClose}>Annuler</Button>
        <CmdButton
          def={cmd.editReference}
          payload={{ refId: r.id, patch: { description: v.description, whenToUse: v.whenToUse, nature: v.nature }, note: v.note }}
          variant="primary"
          success="Fiche modifiée"
          onDone={onClose}
        >
          Enregistrer
        </CmdButton>
      </div>
    </Panel>
  );
}

/** Applicability ≠ activation ≠ control available ≠ result ≠ evidence ≠ approval (brief §5.5). */
function ProjectStatus({ r }: { r: Reference }) {
  const s = useAppState();
  const projects = list(s, 'project', s.session.orgId).filter((p) => p.status === 'active');
  const [selectedProjectId, setSelectedProjectId] = useState<string>();
  const [status, setStatus] = useState<ApplicabilityStatus>('applicable');
  const [reason, setReason] = useState('');
  const project = projects.find((p) => p.id === (selectedProjectId ?? s.session.projectId)) ?? projects[0];
  if (!project)
    return (
      <Panel title="Applicabilité par projet">
        <Empty title="Aucun projet actif" />
      </Panel>
    );
  const pid = project.id;
  const app = list(s, 'applicability', s.session.orgId).find((a) => a.refId === r.id && a.projectId === pid);
  const active = projectRules(s, project).rules.filter(({ version }) => version.referenceIds.includes(r.id));
  const controls = list(s, 'control', s.session.orgId).filter((c) => c.ruleIds.some((id) => active.some(({ rule }) => rule.id === id)));
  const results = latestResults(s, pid).filter((x) => controls.some((c) => c.id === x.controlId));
  const statuses = results.map((result) => ({ result, stale: resultFreshness(s, result).state === 'stale' }));
  const complete = controls.length > 0 && controls.every((c) => results.some((r) => r.controlId === c.id));
  const successful = complete && statuses.every(({ result, stale }) => result.outcome === 'passed' && !stale);
  const outcomeLabels = statuses.map(
    ({ result, stale }) =>
      `${s.db.control[result.controlId]?.code} (${stateDef('result', result.outcome).label.toLowerCase()}${stale ? ', à réévaluer' : ''})`,
  );
  const evidence = list(s, 'evidence', s.session.orgId).filter((e) => results.some((x) => x.id === e.resultId));
  const approvals = list(s, 'approval', s.session.orgId).filter(
    (a) =>
      a.projectId === pid &&
      a.subject.kind === 'deliverable' &&
      approvalValidity(s, a).valid &&
      results.some(({ inputs }) => inputs.subject?.deliverableId === a.subject.id && inputs.subject.version === a.subject.version),
  );
  const row = (label: string, ok: boolean, detail: string) => (
    <li>
      <span className={ok ? 'ok' : 'info'}>
        <Icon name={ok ? 'check' : 'dot'} size={14} />
      </span>
      <span>
        <strong className="small">{label}</strong>
        <span className="small muted" style={{ display: 'block' }}>
          {detail}
        </span>
      </span>
    </li>
  );
  return (
    <Panel title="Applicabilité par projet">
      <Select
        label="Projet"
        value={pid}
        onChange={(e) => setSelectedProjectId(e.target.value)}
        options={projects.map((p) => ({ value: p.id, label: p.name }))}
      />
      <ul className="plain closure" style={{ marginTop: 8 }}>
        {row(
          'Applicabilité',
          app?.status === 'applicable' && app.validated,
          app
            ? `${APPLICABILITY[app.status].label}${app.validated ? '' : ' (suggestion)'}${app.reason ? `. ${app.reason}` : ''}`
            : 'À qualifier.',
        )}
        {row(
          'Règles actives',
          active.length > 0,
          active.length
            ? `Blueprint v${project.blueprintVersion} (${active.map(({ rule }) => rule.code).join(', ')})`
            : 'Aucune règle active ne cite cette référence.',
        )}
        {row('Contrôles', controls.length > 0, controls.length ? controls.map((c) => c.code).join(', ') : 'Aucun contrôle associé.')}
        {row('Résultats simulés', successful, outcomeLabels.join(', ') || 'Aucun contrôle exécuté.')}
        {row('Preuves simulées', evidence.length > 0, evidence.length === 1 ? '1 preuve liée.' : `${evidence.length} preuves liées.`)}
        {row(
          'Approbations',
          approvals.length > 0,
          approvals.length === 1
            ? '1 approbation humaine valide sur la version évaluée.'
            : `${approvals.length} approbations humaines valides sur les versions évaluées.`,
        )}
      </ul>
      <h3 style={{ marginTop: 10 }}>Qualifier la référence</h3>
      {app && !app.validated && (
        <div className="row" style={{ marginBottom: 6 }}>
          <Badge tone="ai" icon="ai">
            Suggestion de {app.suggestedBy ?? 'calcul'}
          </Badge>
          <CmdButton def={cmd.validateApplicability} payload={{ id: app.id }} size="small" variant="primary" success="Suggestion validée">
            Valider la suggestion
          </CmdButton>
        </div>
      )}
      <div className="row">
        <Select
          label="Statut"
          value={status}
          onChange={(e) => setStatus(e.target.value as ApplicabilityStatus)}
          options={Object.entries(APPLICABILITY).map(([k, v]) => ({ value: k, label: v.label }))}
        />
        <div className="grow">
          <TextField label="Motif" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </div>
      <CmdButton
        def={cmd.setApplicability}
        payload={{ projectId: pid, refId: r.id, status, reason }}
        size="small"
        success="Applicabilité enregistrée"
      >
        Enregistrer le statut
      </CmdButton>
    </Panel>
  );
}

function Activation({ r }: { r: Reference }) {
  const s = useAppState();
  const draft = openDraft(s, s.session.orgId);
  const draftRules = draft ? draft.rules.map((ref) => s.db.rule[ref.ruleId]).filter(Boolean) : [];
  const [ruleId, setRuleId] = useState('');
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : '';
  const [v, setV] = useState({ code: '', title: r.name, statement: '', criticality: 'moyenne' as const, blocking: false });
  return (
    <Panel title="Citer dans le Blueprint">
      {!draft || draft.status !== 'draft' ? (
        <Notice tone="warn">
          Aucune version du Blueprint en préparation. <a href="#/blueprint/assistant">Préparer une nouvelle version</a> pour activer cette
          référence.
        </Notice>
      ) : (
        <div className="stack">
          <p className="small">
            Version en préparation : <strong>v{draft.number}</strong>
          </p>
          <div className="row">
            <Select
              label="Citer dans une règle existante"
              value={ruleId}
              placeholder="Choisir une règle…"
              onChange={(e) => setRuleId(e.target.value)}
              options={draftRules.map((x) => ({ value: x.id, label: `${x.code} ${x.versions.at(-1)?.title}` }))}
            />
            <CmdButton def={cmd.linkReferenceToRule} payload={{ refId: r.id, ruleId }} size="small" success="Référence citée par la règle">
              Citer
            </CmdButton>
          </div>
          <h3>Ou créer une règle locale</h3>
          <div className="form-grid">
            <TextField
              label="Code"
              value={v.code}
              onChange={(e) => setV({ ...v, code: e.target.value.toUpperCase() })}
              hint="Ex. API-DOC-01"
            />
            <TextField label="Titre" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
            <TextArea
              className="full"
              label="Formulation vérifiable"
              value={v.statement}
              onChange={(e) => setV({ ...v, statement: e.target.value })}
            />
            <Checkbox label="Bloquante" checked={v.blocking} onChange={(e) => setV({ ...v, blocking: e.target.checked })} />
          </div>
          <CmdButton
            def={cmd.addRule}
            payload={{
              version: draft.number,
              rule: {
                code: v.code,
                title: v.title,
                statement: v.statement,
                referenceIds: [r.id],
                scope: { level: 'org' },
                ownerId: me,
                criticality: v.criticality,
                blocking: v.blocking,
                derogable: true,
                policy: 'additive',
                expectedControlIds: [],
                justification: `Activation de ${r.name}`,
              },
            }}
            variant="primary"
            icon="plus"
            success="Règle créée dans le brouillon"
          >
            Créer la règle
          </CmdButton>
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ applicability */
function ApplicabilityView() {
  const s = useAppState();
  const apps = list(s, 'applicability', s.session.orgId).sort((a, b) => Number(a.validated) - Number(b.validated));
  const groups = new Map<ID, typeof apps>();
  apps.forEach((a) => groups.set(a.projectId, [...(groups.get(a.projectId) ?? []), a]));
  return (
    <div className="stack">
      <Notice tone="ai">
        Une suggestion calculée ou proposée par un agent reste une proposition tant qu’un humain ne l’a pas validée.
      </Notice>
      {[...groups.entries()].map(([pid, items]) => (
        <Panel key={pid} title={s.db.project[pid]?.name ?? pid}>
          <table className="data responsive">
            <thead>
              <tr>
                <th>Référence</th>
                <th>Statut</th>
                <th>Motif</th>
                <th>Auteur</th>
                <th>Validation</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td data-label="Référence">
                    <a href={`#/bibliotheque/ref/${a.refId}`}>{referenceById(s, a.refId)?.name ?? a.refId}</a>
                  </td>
                  <td data-label="Statut">
                    <Badge tone={APPLICABILITY[a.status].tone}>{APPLICABILITY[a.status].label}</Badge>
                  </td>
                  <td data-label="Motif" className="small">
                    {a.reason}
                  </td>
                  <td data-label="Auteur">
                    <Person id={a.authorId} />
                  </td>
                  <td data-label="Validation">
                    {a.validated ? (
                      <Badge tone="success" icon="check">
                        validée
                      </Badge>
                    ) : (
                      <CmdButton def={cmd.validateApplicability} payload={{ id: a.id }} size="small" success="Suggestion validée">
                        Valider
                      </CmdButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      ))}
      {groups.size === 0 && <Empty title="Aucune qualification">Qualifiez l’applicabilité depuis la fiche d’une référence.</Empty>}
    </div>
  );
}

/* ------------------------------------------------------------------ collections and packs */
function Collections() {
  const s = useAppState();
  const cols = list(s, 'collection', s.session.orgId);
  const favs = s.catalogue.favorites[s.session.orgId!] ?? [];
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  return (
    <div className="stack">
      <Panel title={`Mes favoris (${favs.length})`}>
        {favs.length ? (
          <div className="row">
            {favs.map((id) => (
              <a key={id} className="chip" href={`#/bibliotheque/ref/${id}`}>
                <Icon name="star" size={10} className="fav-on" />
                {referenceById(s, id)?.name}
              </a>
            ))}
          </div>
        ) : (
          <p className="small muted">Ajoutez des favoris depuis les fiches.</p>
        )}
      </Panel>
      <div className="grid-2">
        {cols.map((c) => (
          <Panel
            key={c.id}
            title={c.name}
            actions={
              <Button
                size="small"
                icon="download"
                onClick={() => {
                  const out = dispatch(cmd.recordExport, { what: `Collection ${c.name}`, format: 'JSON', count: c.refIds.length }, {});
                  if (out.ok)
                    download(
                      `collection-${c.id}.json`,
                      'application/json',
                      JSON.stringify(
                        { format: 'ogk-collection/1', nom: c.name, references: c.refIds.map((id) => referenceById(s, id)) },
                        null,
                        2,
                      ),
                    );
                }}
              >
                Exporter
              </Button>
            }
          >
            <p className="small muted">{c.description}</p>
            <ul className="plain">
              {c.refIds.map((id) => (
                <li key={id} className="row between small">
                  <a href={`#/bibliotheque/ref/${id}`}>{referenceById(s, id)?.name ?? id}</a>
                  <button
                    className="linklike tiny"
                    onClick={() => dispatch(cmd.toggleInCollection, { collectionId: c.id, refId: id }, { silent: true })}
                  >
                    retirer
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        ))}
        <Panel title="Nouvelle collection">
          <TextField label="Nom" value={name} onChange={(e) => setName(e.target.value)} />
          <TextArea label="Description" value={desc} onChange={(e) => setDesc(e.target.value)} />
          <CmdButton
            def={cmd.saveCollection}
            payload={{ name, description: desc, refIds: favs }}
            variant="primary"
            success="Collection créée"
            onDone={() => {
              setName('');
              setDesc('');
            }}
          >
            Créer (avec mes favoris)
          </CmdButton>
        </Panel>
      </div>
    </div>
  );
}

function Packs() {
  const s = useAppState();
  const packs = list(s, 'pack', s.session.orgId).sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name));
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Panel
      title={`Packs configurables (${packs.length}, dont ${packs.filter((p) => p.origin === 'cli').length} issus du registre CLI OpenGuildKit)`}
    >
      <p className="small muted">
        Les packs du registre CLI (dossier <code>src/openguildkit/registry/packs</code>) sont réutilisés tels quels ; leurs sources sont
        rapprochées des références du catalogue par adresse.
      </p>
      <div className="grid-auto">
        {packs.map((p) => {
          const cli = CLI_PACKS.find((x) => x.id === p.cliId);
          return (
            <div key={p.id} className="card">
              <div className="row between">
                <strong>{p.name}</strong>
                {p.enabled ? (
                  <Badge tone="success" icon="check">
                    activé
                  </Badge>
                ) : (
                  <Badge tone="muted">désactivé</Badge>
                )}
              </div>
              <p className="tiny muted" style={{ margin: '4px 0' }}>
                {p.description}
              </p>
              <p className="tiny">
                {p.refIds.length} référence(s) du catalogue · {p.origin === 'cli' ? 'registre CLI' : 'pack local'}
              </p>
              <div className="row">
                <CmdButton
                  def={cmd.savePack}
                  payload={{ id: p.id, name: p.name, description: p.description, refIds: p.refIds, enabled: !p.enabled }}
                  size="small"
                  success={p.enabled ? 'Pack désactivé' : 'Pack activé'}
                  showReason={false}
                >
                  {p.enabled ? 'Désactiver' : 'Activer'}
                </CmdButton>
                {cli && (
                  <Button size="small" variant="ghost" onClick={() => setOpen(open === p.id ? null : p.id)}>
                    {open === p.id ? 'Masquer' : 'Règles du pack'}
                  </Button>
                )}
              </div>
              {open === p.id && cli && (
                <ul className="bullets tiny">
                  {cli.rules.map((r) => (
                    <li key={r.id}>
                      <strong>{r.id}</strong> — {r.instruction}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------ proposals and import */
function Proposals() {
  const s = useAppState();
  const props = [...s.catalogue.proposals].reverse();
  const [refId, setRefId] = useState('wcag-2-2');
  return (
    <div className="stack">
      {props.length === 0 && <Empty title="Aucune proposition" />}
      {props.map((p) => {
        const cur = referenceById(s, p.refId);
        return (
          <Panel
            key={p.id}
            title={`${p.incoming.name} — ${p.origin}`}
            actions={
              <Badge tone={p.status === 'proposed' ? 'info' : p.status === 'adopted' ? 'success' : 'muted'}>
                {{ proposed: 'proposée', adopted: 'adoptée', dismissed: 'écartée' }[p.status]}
              </Badge>
            }
          >
            <p className="small muted">
              Champs modifiés : {p.changes.join(', ')} · {fmtDate(p.at, true)} · impacts :{' '}
              {list(s, 'rule', s.session.orgId)
                .filter((r) => r.versions.some((v) => v.referenceIds.includes(p.refId)))
                .map((r) => r.code)
                .join(', ') || 'aucune règle ne cite cette référence'}
            </p>
            {cur && (
              <DiffView
                before={`${cur.description}\nÉdition : ${cur.edition}`}
                after={`${p.incoming.description}\nÉdition : ${p.incoming.edition}`}
                labels={['actuelle', 'proposée']}
              />
            )}
            {p.status === 'proposed' && (
              <div className="row" style={{ marginTop: 8 }}>
                <CmdButton
                  def={cmd.decideReferenceProposal}
                  payload={{ id: p.id, adopt: true }}
                  variant="primary"
                  size="small"
                  success="Mise à jour adoptée (version précédente restaurable)"
                >
                  Adopter
                </CmdButton>
                <CmdButton
                  def={cmd.decideReferenceProposal}
                  payload={{ id: p.id, adopt: false }}
                  size="small"
                  success="Mise à jour écartée"
                >
                  Écarter
                </CmdButton>
              </div>
            )}
          </Panel>
        );
      })}
      <Panel title="Veille des références (simulation)">
        <p className="small muted">
          Simule la détection d’une nouvelle édition : une proposition est créée, jamais une mise à jour silencieuse.
        </p>
        <div className="row">
          <Select
            label="Référence"
            value={refId}
            onChange={(e) => setRefId(e.target.value)}
            options={allReferences(s)
              .slice(0, 120)
              .map((r) => ({ value: r.id, label: r.name }))}
          />
          <CmdButton
            def={cmd.proposeReferenceUpdate}
            payload={{
              refId,
              changes: {
                edition: `${baseCatalogueInfo.edition} (proposition simulée)`,
                description: `${referenceById(s, refId)?.description ?? ''} Une nouvelle édition est signalée par la veille simulée.`,
              },
              origin: 'Veille des références (simulation)',
            }}
            size="small"
            success="Proposition créée"
          >
            Simuler une nouvelle édition
          </CmdButton>
        </div>
      </Panel>
    </div>
  );
}

function ImportView() {
  const s = useAppState();
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [name, setName] = useState('');
  const [decisions, setDecisions] = useState<Record<number, 'add' | 'update' | 'skip'>>({});
  const refs = allReferences(s);
  const load = (text: string, source: string) => {
    const p = previewCatalogueImport(text, refs);
    setPreview(p);
    setName(source);
    setDecisions(Object.fromEntries(p.rows.map((r, i) => [i, r.decision])));
  };
  const rows = preview?.rows.map((r, i) => ({ ...r, decision: decisions[i] ?? r.decision })) ?? [];
  return (
    <div className="stack">
      <Panel title="Importer un catalogue (Markdown ou JSON)">
        <p className="small muted">
          Format Markdown du catalogue fourni (familles, catégories, tableaux) ou JSON <code>ogk-catalogue/1</code>. Le fichier est validé
          et prévisualisé : rien n’est appliqué avant votre choix. Les URL non http(s) sont refusées ; aucun contenu n’est exécuté.
        </p>
        <input
          ref={fileRef}
          type="file"
          className="sr-only"
          id="cat-file"
          accept=".md,.json,text/markdown,application/json"
          onChange={async (e) => {
            const f = e.target.files?.[0];
            if (f) load(await f.text(), f.name);
            e.target.value = '';
          }}
        />
        <div className="row">
          <Button icon="upload" onClick={() => fileRef.current?.click()}>
            Choisir un fichier…
          </Button>
          <Button
            onClick={() =>
              load(
                `# Exemple\n\n## 1. Code et collaboration — 2 références\n\n### Git, versions et collaboration (2)\n\n| Référence | Nature | Description | Quand l’utiliser | Sources |\n| --- | --- | --- | --- | --- |\n| **Semantic Versioning** | convention | Numérotation majeure.mineure.corrective annonçant la nature des changements. | Pour une interface publique versionnée. | [Source 1: SemVer](https://semver.org/) |\n| **Release Please** | outil | Prépare les notes et numéros de version à partir de l’historique. | Pour automatiser les publications. | [Source 1: Release Please](https://github.com/googleapis/release-please) |\n| **Lien piégé** | outil | Exemple refusé. | Jamais. | [Source 1: Piège](javascript:alert(1)) |\n`,
                'exemple-import.md',
              )
            }
          >
            Charger un exemple d’import
          </Button>
        </div>
      </Panel>
      {preview && (
        <Panel title={`Aperçu : ${name} (${preview.format})`}>
          {preview.errors.length > 0 && (
            <Notice tone="danger" title={`${preview.errors.length} problème(s) :`}>
              {preview.errors.slice(0, 8).map((e, i) => (
                <span key={i} style={{ display: 'block' }}>
                  {e.line ? `ligne ${e.line} : ` : ''}
                  {e.message}
                </span>
              ))}
            </Notice>
          )}
          <table className="data responsive">
            <thead>
              <tr>
                <th>Référence</th>
                <th>Rapprochement</th>
                <th>Changements</th>
                <th>Choix</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td data-label="Référence">
                    {r.incoming.name}
                    <span className="tiny muted" style={{ display: 'block' }}>
                      {r.incoming.sources.length} source(s)
                    </span>
                  </td>
                  <td data-label="Rapprochement">
                    {r.existing ? <Badge tone="warning">doublon de « {r.existing.name} »</Badge> : <Badge tone="success">nouvelle</Badge>}
                  </td>
                  <td data-label="Changements" className="small">
                    {r.changes.join(', ') || '—'}
                  </td>
                  <td data-label="Choix">
                    <select
                      aria-label={`Choix pour ${r.incoming.name}`}
                      value={r.decision}
                      onChange={(e) => setDecisions({ ...decisions, [i]: e.target.value as 'add' })}
                      style={{ background: 'var(--bg-deep)', color: 'var(--text)', border: 0, padding: 4 }}
                    >
                      {r.existing ? (
                        <>
                          <option value="update">Mettre à jour</option>
                          <option value="skip">Ignorer</option>
                          <option value="add">Ajouter comme nouvelle</option>
                        </>
                      ) : (
                        <>
                          <option value="add">Ajouter</option>
                          <option value="skip">Ignorer</option>
                        </>
                      )}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row end" style={{ marginTop: 8 }}>
            <Button onClick={() => setPreview(null)}>Annuler</Button>
            <CmdButton
              def={cmd.applyCatalogueImport}
              payload={{ rows, source: name }}
              variant="primary"
              success={(v) => {
                const c = v as { added: number; updated: number; skipped: number };
                return `Import appliqué : ${c.added} ajout(s), ${c.updated} mise(s) à jour, ${c.skipped} ignorée(s)`;
              }}
              onDone={() => setPreview(null)}
            >
              Appliquer l’import
            </CmdButton>
          </div>
        </Panel>
      )}
    </div>
  );
}
