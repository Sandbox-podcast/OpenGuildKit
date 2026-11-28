/**
 * Forge: implement approved tasks (handoff, checks, verification, results, completion), start business
 * deliverables, connect the tools of the stack with their MCP servers or mocks, and extract a design system.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { setQuery, useRoute } from '@/shared/router';
import { Badge, Button, Empty, Notice, Panel, Tabs, TextArea, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Markdown } from '@/shared/ui/markdown';
import { norm } from '@/shared/text';
import { toast } from '@/shared/ui/toast';
import { batchJson, cliMessage, projectPath, readJson, readText, run, terminalCommand, writeFile, type CliResult } from '../api';
import { useProfile, useTasks } from '../data';
import { invalidate, showTerminal, useAction, useCli, useCliResult, useCliText, useQuery } from '../query';
import {
  CLOSING_GROUP,
  checkLabel,
  checkOutcome,
  deliveryOf,
  isRequiredCheck,
  mustSupplyLabel,
  fmtWhen,
  hasFailedCheck,
  isDecided,
  isDone,
  needsReconsult,
  nextLabel,
  nextLang,
  parseTemplates,
} from '../labels';
import {
  ActionForm,
  CommandLine,
  ErrorNotice,
  ExternalLink,
  FilePick,
  JsonDetails,
  Pre,
  Q,
  Section,
  StepRail,
  TableBox,
  TaskStatusBadge,
  UnreadableTask,
  copyText,
  useRemembered,
} from '../parts';
import { errorText, notRecorded } from '../refusals';
import type { BlockerItem, ExpectedCheck, MockListing, ProposalItem, ProposalStatus, StorybookProposals, TaskRecord, Tool } from '../types';

export function Forge({ tab = 'quetes' }: { tab?: string }) {
  return (
    <div className="page-grid">
      <Tabs
        label="Forge"
        value={tab}
        onChange={(t) => {
          window.location.hash = t === 'quetes' ? '#/forge' : `#/forge/${t}`;
        }}
        tabs={[
          { id: 'quetes', label: 'À réaliser', icon: 'anvil' },
          { id: 'livrables', label: 'Livrables', icon: 'scroll' },
          { id: 'outils', label: 'Outils et MCP', icon: 'key' },
          { id: 'storybook', label: 'Storybook', icon: 'grid' },
        ]}
      />
      {tab === 'livrables' ? <Deliverables /> : tab === 'outils' ? <Tools /> : tab === 'storybook' ? <Storybook /> : <ToBuild />}
    </div>
  );
}

function ToBuild() {
  const tasks = useTasks();
  return (
    <Q q={tasks}>
      {(list) => {
        const approved = list.filter((t) => t.status === 'approved' && !needsReconsult(t));
        const reconsult = list.filter(needsReconsult);
        const done = list.filter((t) => isDone(t.status));
        return (
          <div className="grid-2">
            {reconsult.length > 0 && (
              <Panel
                title={
                  <>
                    Approbation à reprendre <span className="badge count">{reconsult.length}</span>
                  </>
                }
                tone="danger"
              >
                <p className="small">
                  Les règles ont changé depuis l’approbation, ou son enregistrement ne correspond plus : rien n’est à réaliser tant qu’une
                  personne n’a pas consulté la tâche à nouveau.
                </p>
                <ul className="plain stack tight">
                  {reconsult.map((t) => (
                    <li key={t.id}>
                      <a className="card" href={`#/conseil/${t.id}`}>
                        <span className="row between">
                          <span className="mono small">{t.id}</span>
                          <Badge tone="danger" icon="replace">
                            à consulter à nouveau, par une personne
                          </Badge>
                        </span>
                        <strong data-own>{t.brief}</strong>
                        <span className="small muted" lang={nextLang(t.next)}>
                          {nextLabel(t.next)}
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
            <Panel
              title={
                <>
                  Approuvées, à réaliser <span className="badge count">{approved.length}</span>
                </>
              }
            >
              {approved.length === 0 ? (
                <Empty title="Rien à forger">Une tâche arrive ici quand une personne l’a approuvée dans son terminal.</Empty>
              ) : (
                <ul className="plain stack tight">
                  {approved.map((t) => (
                    <li key={t.id}>
                      <a className="card" href={`#/forge/${t.id}`}>
                        <span className="row between">
                          <span className="mono small">{t.id}</span>
                          {hasFailedCheck(t.next) && (
                            <Badge tone="danger" icon="cross">
                              contrôle en échec
                            </Badge>
                          )}
                        </span>
                        <strong data-own>{t.brief}</strong>
                        <span className="small muted">{nextLabel(t.next)}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel
              title={
                <>
                  Terminées <span className="badge count">{done.length}</span>
                </>
              }
            >
              {done.length === 0 ? (
                <p className="muted">Aucune tâche terminée.</p>
              ) : (
                <ul className="plain stack tight">
                  {done.map((t) => (
                    <li key={t.id}>
                      <a className="card" href={`#/forge/${t.id}`}>
                        <span className="mono small">{t.id}</span>
                        <strong data-own>{t.brief}</strong>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        );
      }}
    </Q>
  );
}

/* ------------------------------------------------------------------ one task */

export function ForgeTask({ id }: { id: string }) {
  const item = useTasks().data?.find((t) => t.id === id);
  if (item?.status === 'unreadable')
    return (
      <div className="page-grid">
        <p className="mono small muted">{id}</p>
        <UnreadableTask id={id} message={item.next} />
      </div>
    );
  return <ForgeRecord id={id} reconsult={!!item && needsReconsult(item) ? item.next : null} />;
}

function ForgeRecord({ id, reconsult }: { id: string; reconsult: string | null }) {
  const record = useCli<TaskRecord>(['task', 'show', id], { omit: ['markdown', 'review_template', 'scope', 'review', 'consultation'] });
  const [handoff, setHandoff] = useState(false);
  return (
    <Q q={record}>
      {(t) => (
        <div className="page-grid">
          <div className="quest-head">
            <div className="grow">
              <p className="mono small muted">
                <a href={`#/quetes/${t.id}`}>{t.id}</a>
              </p>
              <h2 className="h-title clamp-2" data-own>
                {t.brief.split('\n')[0]}
              </h2>
              <TaskStatusBadge status={t.status} />
            </div>
            <div className="row">
              <Button icon="scroll" variant="primary" onClick={() => setHandoff(true)}>
                {t.answers?.kind === 'decision' ? 'Relevé de décision' : 'Brief d’implémentation'}
              </Button>
            </div>
          </div>
          <StepRail status={t.status} hasResult={!!t.result} />
          {reconsult ? (
            <Notice tone="danger" title="L’approbation ne tient plus :">
              <span lang={nextLang(reconsult)}>{nextLabel(reconsult)}</span> Rien n’est à réaliser avant une nouvelle consultation.{' '}
              <a href={`#/conseil/${t.id}`}>Ouvrir le Conseil</a>
            </Notice>
          ) : !isDecided(t.status) ? (
            <Notice tone="warn">
              Cette tâche n’est pas approuvée : la Forge n’a pas de brief d’implémentation.{' '}
              <a href={`#/conseil/${t.id}`}>Ouvrir le Conseil</a>
            </Notice>
          ) : (
            <>
              {t.answers?.kind === 'decision' && (
                <Notice tone="info" title="Tâche de décision :">
                  le brief d’implémentation est un relevé de décision. Rapporte la décision sans modifier le projet ; ouvre une nouvelle
                  tâche pour la mettre en œuvre.
                </Notice>
              )}
              {t.status === 'approved' && <Conditions id={t.id} />}
              <Checks task={t} />
              {t.result?.closing && <Closing task={t} />}
              {t.status === 'approved' && <Results task={t} />}
              <Authorizations task={t} />
              <Runs id={t.id} />
            </>
          )}
          <HandoffDialog id={t.id} open={handoff} onClose={() => setHandoff(false)} />
        </div>
      )}
    </Q>
  );
}

function HandoffDialog({ id, open, onClose }: { id: string; open: boolean; onClose: () => void }) {
  const text = useCliText(open ? ['task', 'handoff', id] : null);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      wide
      title="Brief d’implémentation"
      footer={
        <>
          <Button onClick={onClose}>Fermer</Button>
          {text.data && (
            <Button variant="primary" icon="copy" onClick={() => void copyText(text.data!)}>
              Copier pour l’agent
            </Button>
          )}
        </>
      }
    >
      <p className="small muted">
        La décision (qui et pourquoi), le périmètre approuvé avec les règles en vigueur et la revue. Elle échoue si le profil ou le
        catalogue ont changé depuis la validation.
      </p>
      <Q q={text}>
        {(t) => (
          <div className="scroll-box" tabIndex={0}>
            <Markdown text={t} />
          </div>
        )}
      </Q>
    </Dialog>
  );
}

/** Why a named evidence must be supplied: in French when the page knows the reason. */
function MustSupply({ reason }: { reason: string }) {
  const fr = mustSupplyLabel(reason);
  return fr ? <span title={reason}>{fr}</span> : <span lang="en">{reason}</span>;
}

const KIND_LABEL: Record<string, string> = {
  command: 'commande',
  rule: 'règle',
  machine: 'contrôle automatique',
  evidence: 'preuve nommée',
  scenario: 'scénario',
};

function Checks({ task }: { task: TaskRecord }) {
  const checks = useCli<ExpectedCheck[]>(['task', 'checks', task.id, '--json']);
  const { act, busy } = useAction();
  const [running, setRunning] = useState(false);
  const [verified, setVerified] = useState<CliResult | null>(null);
  const [chaos, setChaos] = useState<string | null>(null);
  const [toolVersion, setToolVersion] = useState('');
  // task verify records the checks it ran even when one fails (exit code 1): show what it says, then reload.
  const verify = async () => {
    setRunning(true);
    try {
      const result = await run(['task', 'verify', task.id], undefined, { allowFailure: true, raw: true });
      setVerified(result);
      toast({
        tone: result.code === 0 ? 'success' : 'warning',
        title: result.code === 0 ? 'Vérifications enregistrées' : 'Vérifications enregistrées, avec des points à reprendre',
      });
    } catch (e) {
      const shown = errorText(e as Error);
      toast({ tone: 'danger', title: 'Commande refusée', text: shown.text.slice(0, 240), lang: shown.lang });
    } finally {
      setRunning(false);
      invalidate('project');
    }
  };
  const commands = (checks.data ?? []).filter((c) => c.kind === 'command');
  return (
    <Section
      title="Vérifications attendues"
      icon="shield"
      actions={
        task.status === 'approved' ? (
          <Button size="small" variant="primary" icon="play" busy={running || busy !== null} onClick={() => void verify()}>
            Lancer les commandes du projet
          </Button>
        ) : undefined
      }
    >
      <p className="small muted">
        <code>task verify</code> lance seulement les commandes du profil, à la racine du projet, et garde le journal de chacune comme
        preuve. Une commande obligatoire en échec laisse la tâche ouverte : corrige, puis relance.
      </p>
      {verified && (
        <Notice
          tone={verified.code === 0 ? 'success' : 'warn'}
          title={verified.code === 0 ? 'task verify :' : 'task verify a trouvé des points à reprendre :'}
        >
          <Pre text={(verified.stdout || cliMessage(verified)).trim()} />
        </Notice>
      )}
      <Q q={checks}>
        {(list) => (
          <TableBox label="Tableau des vérifications">
            <table className="data compact">
              <thead>
                <tr>
                  <th>Contrôle</th>
                  <th>Type</th>
                  <th>Obligatoire</th>
                  <th>Résultat</th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => {
                  const l = checkOutcome(c);
                  return (
                    <tr key={c.id} className={c.concerned === false ? 'muted' : undefined}>
                      <td>
                        <span className="mono small">{c.id}</span>
                        {c.command ? (
                          <code className="small block">{c.command}</code>
                        ) : (
                          <span className="small block" lang="en">
                            {c.title ?? c.instruction ?? c.rule}
                          </span>
                        )}
                        {c.verification && (
                          <span className="tiny muted block" lang="en">
                            {c.verification}
                          </span>
                        )}
                        {c.owner_role && (
                          <span className="tiny muted block">
                            Fournie par <span lang="en">{c.owner_role}</span>
                            {c.must_supply && (
                              <>
                                {' '}
                                (obligatoire : <MustSupply reason={c.must_supply} />)
                              </>
                            )}
                          </span>
                        )}
                        {c.concerned === false && (
                          <span className="tiny muted block">
                            Non demandé à cette tâche
                            {c.reason && (
                              <>
                                {' '}
                                : <span lang="en">{c.reason}</span>
                              </>
                            )}
                          </span>
                        )}
                      </td>
                      <td className="small">{KIND_LABEL[c.kind] ?? c.kind}</td>
                      <td>
                        {isRequiredCheck(c) ? (
                          <Badge tone="warning" icon="lock">
                            oui
                          </Badge>
                        ) : (
                          <span className="tiny muted">non</span>
                        )}
                      </td>
                      <td>
                        <Badge tone={l.tone} icon={l.icon}>
                          {l.label}
                        </Badge>
                        {c.result?.cannot_run && (
                          <span className="block">
                            <Badge tone="warning" icon="user">
                              ne peut pas tourner ici
                            </Badge>
                          </span>
                        )}
                        {c.result?.message && (
                          <span className="tiny block" lang="en">
                            {c.result.message}
                          </span>
                        )}
                        {c.result?.evidence && <span className="tiny muted block mono">{c.result.evidence}</span>}
                        {c.kind === 'evidence' && c.result?.owner && !c.result.reason && (
                          <span className="tiny muted block">
                            fournie par <span data-own>{c.result.owner}</span>
                          </span>
                        )}
                        {c.result?.reason && (
                          <span className="tiny muted block" data-own>
                            {c.result.reason}
                            {c.result.owner ? ` (${c.result.owner})` : ''}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableBox>
        )}
      </Q>
      {task.status === 'approved' && commands.length > 0 && (
        <details className="small">
          <summary>Une commande ne peut pas tourner ici</summary>
          <p>
            Une personne le déclare dans son terminal, avec ses initiales et la raison : la CLI relance d’abord la commande, puis lui
            demande de retaper l’identifiant de la tâche. La tâche se termine alors avec cette réserve. L’interface n’enregistre jamais
            cette déclaration.
          </p>
          {commands.map((c) => (
            <div key={c.id}>
              <p className="tiny">
                <span className="mono">{c.id}</span> : <code>{c.command}</code>
              </p>
              <CommandLine
                command={terminalCommand([
                  'task',
                  'verify',
                  task.id,
                  '--cannot-run',
                  c.id,
                  '--by',
                  'TES_INITIALES',
                  '--reason',
                  'Pourquoi elle ne peut pas tourner ici',
                ])}
              />
            </div>
          ))}
        </details>
      )}
      {task.status === 'approved' && (
        <details className="small">
          <summary>Enregistrer un rejeu ChaosFolk</summary>
          <FilePick label="summary.json du rejeu" onText={(t) => setChaos(t)} />
          <TextField label="Version ou commit de ChaosFolk" value={toolVersion} onChange={(e) => setToolVersion(e.target.value)} />
          <Button
            disabled={!chaos}
            busy={busy !== null}
            onClick={() =>
              void act(
                ['task', 'verify', task.id, '--chaosfolk', '@upload:summary.json', ...(toolVersion ? ['--tool-version', toolVersion] : [])],
                { uploads: { 'summary.json': chaos! }, success: 'Scénarios ChaosFolk enregistrés' },
              )
            }
          >
            Enregistrer les scénarios
          </Button>
        </details>
      )}
    </Section>
  );
}

/** Blockers the person approved with, that only the finished work can clear: a person clears each in their terminal. */
function Conditions({ id }: { id: string }) {
  const blockers = useCli<BlockerItem[]>(['task', 'blockers', id, '--json']);
  const pending = (blockers.data ?? []).filter((b) => b.phase === 'verification');
  if (!pending.length) return null;
  return (
    <Section title={`Conditions de l’approbation (${pending.filter((b) => !b.resolution).length} à lever)`} icon="ban">
      <p className="small muted">
        La personne a approuvé avec ces points bloquants ouverts : seul le travail fini peut les lever. Construis la preuve que chacun nomme
        et montre-la ; la personne le lève dans son terminal. <code>task complete</code> refuse la tâche tant qu’un point bloquant reste
        ouvert.
      </p>
      <ul className="plain stack tight">
        {pending.map((b) => (
          <li key={b.id} className={`card blocker ${b.resolution ? 'resolved' : ''}`}>
            <span className="row between">
              <span className="mono small">{b.id}</span>
              {b.resolution ? (
                <Badge tone="success" icon="check">
                  levé par {b.resolution.by}
                </Badge>
              ) : (
                <Badge tone="warning" icon="clock">
                  à lever
                </Badge>
              )}
            </span>
            <strong data-own>{b.finding}</strong>
            {b.owner && (
              <span className="small">
                Responsable : {b.owner}. Se lève quand : <span data-own>{b.clears_when}</span>
              </span>
            )}
            {!b.resolution && (
              <CommandLine
                command={terminalCommand([
                  'task',
                  'clear',
                  id,
                  b.id,
                  '--evidence',
                  'CHEMIN_OU_LIEN',
                  '--supports',
                  'Ce que la preuve établit',
                  '--by',
                  'TES_INITIALES',
                ])}
              />
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

/** What the completion left open, most serious first, and what the task was not asked. */
function Closing({ task }: { task: TaskRecord }) {
  const closing = task.result!.closing!;
  return (
    <Section title={task.status === 'done-with-reservations' ? 'Terminée avec réserves' : 'Clôture'} icon="flag">
      {closing.by && <p className="small">Clôture confirmée par {closing.by}.</p>}
      {closing.verification && (
        <Notice tone="warn">
          <span lang="en">{closing.verification}</span>
        </Notice>
      )}
      {closing.open_points.length === 0 ? (
        <p className="small muted">Aucun point laissé ouvert.</p>
      ) : (
        closing.open_points.map((g) => (
          <div key={g.group}>
            <h3 className="h-card" lang={CLOSING_GROUP[g.group] ? undefined : 'en'}>
              {CLOSING_GROUP[g.group] ?? g.group}
            </h3>
            <ul className="small" lang="en">
              {g.points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>
        ))
      )}
      {closing.not_concerned.length > 0 && (
        <details className="small">
          <summary>Non demandé à cette tâche ({closing.not_concerned.length})</summary>
          <ul>
            {closing.not_concerned.map((n) => (
              <li key={n.pack ?? n.check}>
                <span className="mono">{n.pack ?? n.check}</span> ({n.checks}) : <span lang="en">{n.reason}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="tiny muted">Pour reprendre un point, ouvre une tâche de suite depuis la fiche de la tâche.</p>
    </Section>
  );
}

/** owner: who answers for a rule set aside; supplier: who provided a named evidence (its owner, never the agent). */
type Outcome = { status: string; evidence: string; reason: string; owner: string; supplier: string };

function Results({ task }: { task: TaskRecord }) {
  const checks = useCli<ExpectedCheck[]>(['task', 'checks', task.id, '--json']);
  const [owner, setOwner] = useRemembered('decider');
  const [delivery, setDelivery] = useState(deliveryOf(task.result));
  const [ref, setRef] = useState(task.result?.pull_request ?? task.result?.revision ?? '');
  const [criteria, setCriteria] = useState(task.result?.criteria ?? []);
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const [held, setHeld] = useState<{ text: string; lang?: 'en' }[]>([]);
  const { act, busy, error } = useAction();
  // The page reports the rules and named evidence the task is asked; commands and automatic checks are run by task verify.
  const rules = (checks.data ?? []).filter((c) => (c.kind === 'rule' || c.kind === 'evidence') && c.concerned !== false);
  const kinds = Object.fromEntries(rules.map((c) => [c.id, c.kind]));
  const outcome = (id: string): Outcome => outcomes[id] ?? { status: '', evidence: '', reason: '', owner, supplier: '' };
  const setOutcome = (id: string, patch: Partial<Outcome>) => setOutcomes((o) => ({ ...o, [id]: { ...outcome(id), ...patch } }));
  const result = {
    ...(ref ? { [delivery]: ref.trim() } : {}),
    criteria: criteria.filter((c) => c.criterion.trim()),
    checks: Object.entries(outcomes)
      .filter(([, o]) => o.status)
      .map(([check, o]) =>
        o.status === 'passed' || o.status === 'failed'
          ? // A named evidence passes with the person who provided it: the CLI refuses it without them.
            {
              check,
              status: o.status,
              evidence: o.evidence,
              ...(kinds[check] === 'evidence' && o.status === 'passed' ? { owner: o.supplier } : {}),
            }
          : { check, status: o.status, reason: o.reason, owner: o.owner || owner },
      ),
  };
  const incomplete = result.checks
    .filter(
      (c) =>
        ('reason' in c && (!c.reason?.trim() || !c.owner?.trim())) ||
        ('evidence' in c && (!c.evidence?.trim() || ('owner' in c && !c.owner?.trim()))),
    )
    .map((c) => c.check);
  const save = () =>
    act(['task', 'result', task.id, '--file', '@upload:result.json'], {
      uploads: { 'result.json': JSON.stringify(result, null, 2) },
      success: 'Résultats enregistrés',
      onDone: (r) => setHeld(notRecorded(r.stderr)),
    });
  // The rules the page may set aside in one click: never one the task's answers select (GDPR for personal data),
  // a mandatory one, or a named evidence; each of those keeps its own answer, with its own reason.
  const sweepable = rules.filter((c) => c.kind === 'rule' && !c.selected && !isRequiredCheck(c));
  const kept = rules.filter((c) => !c.result && !sweepable.includes(c)).length;
  return (
    <Section title="Rapporter les résultats" icon="flag">
      <p className="small muted">
        Les rapports suivants mettent à jour les précédents, contrôle par contrôle. <code>task complete</code> termine la tâche quand chaque
        contrôle obligatoire a réussi, ou ne peut pas tourner ici sur la déclaration d’une personne, et que chaque critère est atteint ; ce
        qui reste ouvert (règle ignorée, réserve, désaccord) la termine « avec réserves ».
      </p>
      {!!task.result?.waiting_for?.length && (
        <Notice tone="warn" title="En attente de preuves :">
          <ul>
            {task.result.waiting_for.map((w) => (
              <li key={w.check}>
                <span className="mono">{w.check}</span> : <span lang="en">{w.title}</span>, fournie par <span lang="en">{w.owner}</span> (
                <span lang="en">{w.why}</span>). Demande-la ; ne la rédige pas à sa place.
              </li>
            ))}
          </ul>
        </Notice>
      )}
      {!!task.result?.warnings?.length && (
        <Notice tone="warn" title="Avertissements :">
          <ul lang="en">
            {task.result.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Notice>
      )}
      <TextField
        label="Tes initiales"
        hint="Responsable des règles ignorées ou non applicables que tu rapportes, par exemple CM."
        value={owner}
        onChange={(e) => setOwner(e.target.value)}
      />
      <div className="grid-2">
        <div className="field">
          <label htmlFor="delivery">Livraison</label>
          <select id="delivery" className="input" value={delivery} onChange={(e) => setDelivery(e.target.value as typeof delivery)}>
            <option value="pull_request">Pull request</option>
            <option value="revision">Révision Git</option>
          </select>
        </div>
        <TextField
          label={delivery === 'pull_request' ? 'Adresse de la pull request' : 'Révision'}
          value={ref}
          onChange={(e) => setRef(e.target.value)}
          placeholder={delivery === 'pull_request' ? 'https://github.com/…/pull/7' : 'abc1234'}
        />
      </div>
      <fieldset className="list-editor">
        <legend>Critères d’acceptation</legend>
        {criteria.map((c, i) => (
          <div className="row criteria-row" key={i}>
            <input
              className="input grow"
              aria-label="Critère"
              value={c.criterion}
              onChange={(e) => setCriteria((x) => x.map((y, j) => (j === i ? { ...y, criterion: e.target.value } : y)))}
            />
            <select
              className="input"
              aria-label="Statut"
              value={c.status}
              onChange={(e) => setCriteria((x) => x.map((y, j) => (j === i ? { ...y, status: e.target.value as 'met' } : y)))}
            >
              <option value="met">atteint</option>
              <option value="not-met">non atteint</option>
            </select>
            <input
              className="input"
              aria-label="Preuve"
              placeholder="Preuve"
              value={c.evidence}
              onChange={(e) => setCriteria((x) => x.map((y, j) => (j === i ? { ...y, evidence: e.target.value } : y)))}
            />
            <Button
              size="small"
              variant="ghost"
              icon="trash"
              aria-label="Retirer le critère"
              onClick={() => setCriteria((x) => x.filter((_, j) => j !== i))}
            />
          </div>
        ))}
        <Button size="small" icon="plus" onClick={() => setCriteria((x) => [...x, { criterion: '', status: 'met', evidence: '' }])}>
          Ajouter un critère
        </Button>
      </fieldset>
      {rules.length > 0 && (
        <div>
          <TableBox label="Règles à rapporter">
            <table className="data compact">
              <thead>
                <tr>
                  <th>Règle</th>
                  <th>Issue</th>
                  <th>Preuve, ou motif et responsable</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((c) => {
                  const o = outcome(c.id);
                  return (
                    <tr key={c.id}>
                      <td>
                        <span className="mono small">{c.id}</span>
                        <span className="tiny muted block" lang="en">
                          {c.title ?? c.instruction ?? c.verification}
                        </span>
                        {c.must_supply && (
                          <span className="tiny block">
                            Fournie par <span lang="en">{c.owner_role}</span> : ne peut pas être déclarée non applicable (
                            <MustSupply reason={c.must_supply} />
                            ).
                          </span>
                        )}
                        {c.selected && c.kind === 'rule' && (
                          <span className="tiny muted block">
                            Demandée par les réponses de la tâche : un motif propre si elle ne s’applique pas.
                          </span>
                        )}
                      </td>
                      <td>
                        <select
                          className="input"
                          aria-label={`Issue de ${c.id}`}
                          value={o.status || (c.result?.status ?? '')}
                          onChange={(e) => setOutcome(c.id, { status: e.target.value })}
                        >
                          <option value="">{c.result ? checkLabel(c.result.status).label : 'À rapporter'}</option>
                          <option value="passed">réussie</option>
                          {c.kind === 'evidence' ? (
                            !c.must_supply && <option value="not-applicable">non applicable</option>
                          ) : (
                            <>
                              <option value="failed">en échec</option>
                              <option value="skipped">ignorée</option>
                              <option value="not-applicable">non applicable</option>
                            </>
                          )}
                        </select>
                      </td>
                      <td>
                        {o.status === 'passed' || o.status === 'failed' ? (
                          <span className="row">
                            <input
                              className="input"
                              aria-label={`Preuve de ${c.id}`}
                              placeholder={c.kind === 'evidence' ? 'Chemin du projet ou lien https' : 'Preuve'}
                              value={o.evidence}
                              onChange={(e) => setOutcome(c.id, { evidence: e.target.value })}
                            />
                            {c.kind === 'evidence' && o.status === 'passed' && (
                              <input
                                className="input"
                                aria-label={`Fournie par, pour ${c.id}`}
                                placeholder="Fournie par"
                                title="La personne qui a fourni ou confirmé le document"
                                value={o.supplier}
                                onChange={(e) => setOutcome(c.id, { supplier: e.target.value })}
                              />
                            )}
                          </span>
                        ) : o.status ? (
                          <span className="row">
                            <input
                              className="input"
                              aria-label="Motif"
                              placeholder="Motif"
                              value={o.reason}
                              onChange={(e) => setOutcome(c.id, { reason: e.target.value })}
                            />
                            <input
                              className="input"
                              aria-label="Responsable"
                              placeholder="Responsable"
                              value={o.owner}
                              onChange={(e) => {
                                setOwner(e.target.value);
                                setOutcome(c.id, { owner: e.target.value });
                              }}
                            />
                          </span>
                        ) : (
                          <span className="tiny muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableBox>
          <Button
            size="small"
            variant="ghost"
            className="wrap"
            disabled={!owner.trim()}
            title={owner.trim() ? undefined : 'Indique d’abord tes initiales ou l’identifiant de ton équipe'}
            onClick={() =>
              sweepable.forEach(
                (c) => !c.result && setOutcome(c.id, { status: 'not-applicable', reason: 'Aucun changement dans ce domaine.', owner }),
              )
            }
          >
            Marquer « non applicables » les règles non rapportées que la tâche ne demande pas
          </Button>
          {kept > 0 && (
            <p className="tiny muted">
              {kept} règle(s) ou preuve(s) restent à rapporter une par une : les réponses de la tâche les demandent, ou elles sont
              obligatoires. Une règle de protection des données, de sécurité ou d’IA écartée se confirme ensuite au terminal, par la
              personne qui clôt la tâche.
            </p>
          )}
        </div>
      )}
      {held.length > 0 && (
        <Notice tone="warn" title="Non enregistré :">
          <ul>
            {held.map((h) => (
              <li key={h.text} lang={h.lang}>
                {h.text}
              </li>
            ))}
          </ul>
        </Notice>
      )}
      {incomplete.length > 0 && (
        <Notice tone="warn">Il manque une preuve, ou un motif et un responsable, pour : {incomplete.join(', ')}.</Notice>
      )}
      {error && <ErrorNotice error={error} title="La CLI a refusé :" />}
      <div className="row">
        <Button
          variant="primary"
          busy={busy !== null}
          disabled={(!result.criteria.length && !result.checks.length && !ref) || incomplete.length > 0}
          onClick={() => void save()}
        >
          Enregistrer les résultats
        </Button>
        <Button icon="star" busy={busy !== null} onClick={() => void act(['task', 'complete', task.id], { success: 'Tâche terminée' })}>
          Terminer la tâche
        </Button>
      </div>
      <JsonDetails data={result} label="Aperçu du fichier de résultats" />
    </Section>
  );
}

/** The actions of task authorize --action (tasks.ACTIONS). */
const ACTIONS: [string, string][] = [
  ['public-research', 'Recherche publique'],
  ['external-api', 'Appel d’une API externe'],
  ['send-message', 'Envoi de messages'],
  ['publish', 'Publication'],
  ['install-dependency', 'Installation d’une dépendance'],
  ['other', 'Autre'],
];

function Authorizations({ task }: { task: TaskRecord }) {
  const [by] = useRemembered('decider');
  const { act, busy } = useAction();
  return (
    <Section title="Actions externes hors périmètre" icon="external">
      <p className="small muted">
        Envoyer un message, publier, acheter… hors du périmètre approuvé demande la décision d’une personne. Refuser se fait ici ; autoriser
        se fait au terminal.
      </p>
      {task.authorizations?.length ? (
        <ul className="small">
          {task.authorizations.map((a, i) => (
            <li key={i}>
              <strong>{ACTIONS.find(([id]) => id === a.action)?.[1] ?? a.action}</strong> sur {a.target} :{' '}
              {a.decision === 'allow' ? 'autorisée' : 'refusée'} par {a.by} ({a.reason}), {fmtWhen(a.at)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="tiny muted">Aucune décision enregistrée.</p>
      )}
      <ActionForm
        busy={busy !== null}
        submit="Préparer"
        initial={{ by, decision: 'deny' }}
        fields={[
          { name: 'action', label: 'Action', required: true, options: ACTIONS.map(([value, label]) => ({ value, label })) },
          {
            name: 'target',
            label: 'Hôte ou outil',
            required: true,
            placeholder: 'Brevo, api.example.org',
            hint: 'Un nom d’hôte ou d’outil, sans requête, adresse ni détail privé.',
          },
          {
            name: 'decision',
            label: 'Décision',
            required: true,
            options: [
              { value: 'deny', label: 'Refuser (enregistré ici)' },
              { value: 'allow', label: 'Autoriser (commande au terminal)' },
            ],
          },
          { name: 'by', label: 'Personne qui décide', required: true },
          { name: 'reason', label: 'Motif', required: true },
        ]}
        onSubmit={(v) => {
          const argv = [
            'task',
            'authorize',
            task.id,
            '--action',
            v.action,
            '--target',
            v.target,
            v.decision === 'allow' ? '--allow' : '--deny',
            '--by',
            v.by,
            '--reason',
            v.reason,
          ];
          if (v.decision === 'allow')
            showTerminal({
              title: 'Autorisation : à faire dans ton terminal',
              why: 'Autoriser une action externe demande une personne devant un terminal.',
              command: terminalCommand(argv),
            });
          else void act(argv, { success: 'Refus enregistré' });
        }}
      />
    </Section>
  );
}

function Runs({ id }: { id: string }) {
  const runs = useCliResult(['task', 'runs', id, '--json']);
  if (!runs.data || runs.data.code !== 0) return null;
  return (
    <Section title="Rejeux ChaosFolk" icon="history">
      <JsonDetails data={runs.data.json} label="Comparaison des deux derniers rejeux" />
    </Section>
  );
}

/* ------------------------------------------------------------------ deliverables */

function Deliverables() {
  const list = useCliText(['deliverable', 'list']);
  const tasks = useTasks();
  const profile = useProfile();
  const route = useRoute();
  const [show, setShow] = useState<string | null>(null);
  const asked = route.query.get('brouillon');
  const [draft, setDraft] = useState<string | null>(asked && projectPath(asked));
  const { act, busy } = useAction();
  const templates = useMemo(() => parseTemplates(list.data ?? ''), [list.data]);
  const records = useQuery<TaskRecord[]>(
    tasks.data ? `deliverable-records:${(tasks.data ?? []).map((t) => `${t.id}=${t.status}`).join(',')}` : null,
    useCallback(async () => {
      const ids = (tasks.data ?? []).filter((x) => isDecided(x.status)).map((x) => x.id);
      const records = await batchJson<TaskRecord>(Object.fromEntries(ids.map((id) => [id, ['task', 'show', id]])), {
        omit: ['consultation', 'review', 'rounds', 'answers'],
      });
      return ids.map((id) => records[id]).filter((r): r is TaskRecord => !!r);
    }, [tasks.data]),
  );
  const drafts = (records.data ?? []).flatMap((t) => (t.deliverables ?? []).map((d) => ({ ...d, task: t.id })));
  return (
    <div className="page-grid">
      <Panel title="Modèles de livrables">
        <p className="small muted">
          Un livrable métier (brief de campagne, annonce, article d’aide) part d’une tâche approuvée. Le modèle liste les entrées, les
          données qu’elles touchent, les actions qui demandent ton accord et les contrôles du relecteur.
        </p>
        <Q q={list}>
          {() => (
            <ul className="plain board-grid">
              {templates.map((t) => (
                <li key={t.id} className="card">
                  <strong lang="en">{t.title}</strong>
                  <span className="mono tiny">{t.id}</span>
                  {t.method && <span className="tiny muted">méthode {t.method}</span>}
                  <span className="row">
                    {t.brains.map((b) => (
                      <Badge key={b}>{b}</Badge>
                    ))}
                  </span>
                  <Button size="small" onClick={() => setShow(t.id)}>
                    Voir le modèle
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Q>
      </Panel>
      <Panel title="Nouveau brouillon">
        <p className="small muted">
          L’outil est facultatif, sauf pour un modèle qui l’exige : chaque action dans un outil se décide à part (task authorize). Le
          brouillon s’écrit dans le projet, hors de <code>.openguildkit/</code>.
        </p>
        <ActionForm
          busy={busy !== null}
          submit="Écrire le brouillon"
          fields={[
            { name: 'template', label: 'Modèle', required: true, options: templates.map((t) => ({ value: t.id, label: t.title })) },
            {
              name: 'task',
              label: 'Tâche approuvée',
              required: true,
              options: (tasks.data ?? []).filter((t) => isDecided(t.status)).map((t) => ({ value: t.id, label: t.id })),
            },
            {
              name: 'tool',
              label: 'Outil de l’équipe (facultatif)',
              options: (profile.data?.tools ?? []).map((t) => ({ value: t, label: t })),
            },
            {
              name: 'output',
              label: 'Fichier Markdown à écrire',
              required: true,
              placeholder: 'marketing/brief-printemps.md',
              hint: 'Chemin relatif à la racine du projet.',
            },
          ]}
          onSubmit={(v) =>
            act(['deliverable', 'new', v.template, '--task', v.task, ...(v.tool ? ['--tool', v.tool] : []), '--output', v.output], {
              success: 'Brouillon écrit',
            })
          }
        />
      </Panel>
      <Panel
        title={
          <>
            Brouillons des tâches <span className="badge count">{drafts.length}</span>
          </>
        }
      >
        {drafts.length === 0 ? (
          <p className="muted">Aucun brouillon.</p>
        ) : (
          <TableBox label="Brouillons des tâches">
            <table className="data compact">
              <thead>
                <tr>
                  <th>Brouillon</th>
                  <th>Tâche</th>
                  <th>Outil</th>
                  <th>
                    <span className="sr-only">Ouvrir</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {drafts.map((d) => (
                  <tr key={d.path}>
                    <td>
                      <span className="mono small">{projectPath(d.path)}</span>
                      <span className="tiny muted block mono">{d.deliverable}</span>
                    </td>
                    <td>
                      <a href={`#/quetes/${d.task}`}>{d.task}</a>
                    </td>
                    <td>{d.tool ?? '—'}</td>
                    <td>
                      <Button size="small" onClick={() => setDraft(projectPath(d.path))}>
                        Ouvrir
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableBox>
        )}
      </Panel>
      <TemplateDialog id={show} onClose={() => setShow(null)} />
      <DraftDialog
        path={draft}
        onClose={() => {
          setDraft(null);
          setQuery({ brouillon: null });
        }}
      />
    </div>
  );
}

function TemplateDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const text = useCliText(id ? ['deliverable', 'show', id] : null);
  return (
    <Dialog open={!!id} onClose={onClose} wide title={`Modèle ${id ?? ''}`} footer={<Button onClick={onClose}>Fermer</Button>}>
      <Q q={text}>{(t) => <Pre text={t} />}</Q>
    </Dialog>
  );
}

function DraftDialog({ path, onClose }: { path: string | null; onClose: () => void }) {
  const text = useQuery<string>(
    path ? `file:${path}` : null,
    useCallback(() => readText(path!), [path]),
  );
  const check = useCliResult(path ? ['deliverable', 'check', path] : null);
  return (
    <Dialog open={!!path} onClose={onClose} wide title={path ?? ''} footer={<Button onClick={onClose}>Fermer</Button>}>
      {check.data &&
        (check.data.code === 0 ? (
          <Notice tone="success">Prêt pour la relecture.</Notice>
        ) : (
          <Notice tone="warn" title="Ce qui empêche la relecture :">
            <Pre text={check.data.stdout || check.data.stderr} />
          </Notice>
        ))}
      <Q q={text}>
        {(t) => (
          <div className="scroll-box" tabIndex={0}>
            <Markdown text={t.replace(/^---[\s\S]*?---\n/, '')} />
          </div>
        )}
      </Q>
      <p className="tiny muted">Modifie le fichier dans ton éditeur ; rouvre ce brouillon pour revoir les contrôles.</p>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ tools */

const HOSTS = ['claude-code', 'codex'];

function Tools() {
  const tools = useCli<Tool[]>(['tools', 'list', '--json']);
  const recommended = useCli<{
    tools: { id: string; title: string; named: boolean; signals: string[]; servers: string[]; mock: boolean }[];
    unknown: string[];
  }>(['tools', 'recommend', '--json']);
  const status = useCli<unknown[]>(['tools', 'status', '--json']);
  const profile = useProfile();
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [onlyMocks, setOnlyMocks] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [host, setHost] = useState(profile.data?.host ?? '');
  const [mock, setMock] = useState(true);
  const [plan, setPlan] = useState<{ text: string; lang: 'en' | 'fr' } | null>(null);
  const [call, setCall] = useState<string | null>(null);
  const { act, busy } = useAction();
  const categories = [...new Set((tools.data ?? []).map((t) => t.category))].sort();
  const shown = (tools.data ?? []).filter(
    (t) =>
      (!category || t.category === category) &&
      (!onlyMocks || t.mock) &&
      (!q || norm(`${t.id} ${t.title} ${t.vendor} ${t.summary} ${t.brains.join(' ')}`).includes(norm(q))),
  );
  const hostArgs = host ? ['--host', host] : [];
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const [applying, setApplying] = useState(false);
  // tools apply exits 0 when every tool is connected, 2 when some are and others are not, 1 when none could be.
  const apply = async () => {
    const argv = ['tools', 'apply', ...picked, ...hostArgs, ...(mock ? ['--mock'] : [])];
    if (!mock) {
      showTerminal({
        title: 'Serveurs réels : à faire dans ton terminal',
        why: 'Un serveur MCP réel accède aux données de l’entreprise : la personne relit le plan et répond oui dans son terminal. L’interface n’écrit que des simulations.',
        command: terminalCommand(argv),
      });
      return;
    }
    setApplying(true);
    try {
      const result = await run(argv, undefined, { allowFailure: true, raw: true });
      const last = (result.stdout.trim().split('\n').at(-1) ?? '').slice(0, 200);
      if (result.code === 0) toast({ tone: 'success', title: 'Configuration de l’hôte écrite', text: last || undefined, lang: 'en' });
      else if (result.code === 2)
        toast({ tone: 'warning', title: 'Configuration écrite en partie', text: last || cliMessage(result).slice(0, 200), lang: 'en' });
      else toast({ tone: 'danger', title: 'Rien n’a été connecté', text: (last || cliMessage(result)).slice(0, 240), lang: 'en' });
      setPlan({ text: result.stdout || cliMessage(result), lang: 'en' });
    } catch (e) {
      const shown = errorText(e as Error);
      toast({ tone: 'danger', title: 'Commande refusée', text: shown.text.slice(0, 240), lang: shown.lang });
    } finally {
      setApplying(false);
      invalidate('project');
    }
  };
  const doPlan = async () => {
    try {
      setPlan({
        text: (await run(['tools', 'plan', ...picked, ...hostArgs, ...(mock ? ['--mock'] : [])], undefined, { raw: true })).stdout,
        lang: 'en',
      });
    } catch (e) {
      const shown = errorText(e as Error);
      setPlan({ text: shown.text, lang: shown.lang ?? 'fr' });
    }
  };

  return (
    <div className="page-grid">
      <div className="grid-2">
        <Panel title="Recommandés pour ce projet">
          <Q q={recommended}>
            {(r) =>
              r.tools.length === 0 ? (
                <p className="muted">Aucun outil reconnu dans le profil ou le dépôt.</p>
              ) : (
                <ul className="plain stack tight">
                  {r.tools.map((t) => (
                    <li key={t.id} className="row between">
                      <span>
                        <strong>{t.title}</strong>{' '}
                        <span className="tiny muted">{t.named ? 'nommé dans le profil' : t.signals.join(', ')}</span>
                      </span>
                      <span className="row">
                        {t.mock && <Badge tone="ai">simulable</Badge>}
                        <Button size="small" onClick={() => toggle(t.id)}>
                          {picked.includes(t.id) ? 'Retirer' : 'Choisir'}
                        </Button>
                      </span>
                    </li>
                  ))}
                </ul>
              )
            }
          </Q>
          {recommended.data?.unknown.length ? (
            <p className="tiny muted">Inconnus du registre : {recommended.data.unknown.join(', ')}</p>
          ) : null}
        </Panel>
        <Panel title="Connexions enregistrées">
          <Q q={status}>
            {(s) =>
              s.length === 0 ? (
                <p className="muted">Aucune connexion. Choisis des outils, vérifie le plan, puis écris la configuration de l’hôte.</p>
              ) : (
                <JsonDetails data={s} label={`${s.length} connexion(s)`} />
              )
            }
          </Q>
        </Panel>
      </div>
      <Panel title={`Registre : ${tools.data?.length ?? '…'} outils`}>
        <div className="toolbar">
          <input
            className="input"
            type="search"
            placeholder="Outil, éditeur, cerveau…"
            aria-label="Rechercher un outil"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select className="input" aria-label="Catégorie" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Toutes les catégories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <label className="row small">
            <input type="checkbox" checked={onlyMocks} onChange={(e) => setOnlyMocks(e.target.checked)} /> Avec une simulation
          </label>
        </div>
        <TableBox label="Registre des outils" tall>
          <table className="data compact">
            <thead>
              <tr>
                <th>
                  <span className="sr-only">Choisir</span>
                </th>
                <th>Outil</th>
                <th>Catégorie</th>
                <th>Serveurs MCP</th>
                <th>Cerveaux</th>
                <th>
                  <span className="sr-only">Essayer et site</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Choisir ${t.title}`}
                      checked={picked.includes(t.id)}
                      onChange={() => toggle(t.id)}
                    />
                  </td>
                  <td lang="en">
                    <strong>{t.title}</strong> <span className="tiny muted">{t.vendor}</span>
                    <span className="tiny muted block clamp-1">{t.summary}</span>
                  </td>
                  <td className="small" lang="en">
                    {t.category}
                  </td>
                  <td className="small">
                    {t.servers.length || '—'}
                    {t.mock && (
                      <>
                        {' '}
                        · <Badge tone="ai">simulation</Badge>
                      </>
                    )}
                  </td>
                  <td className="tiny">{t.brains.join(', ')}</td>
                  <td>
                    {t.mock && (
                      <Button size="small" variant="ghost" onClick={() => setCall(t.id)}>
                        Essayer
                      </Button>
                    )}
                    {t.homepage && (
                      <ExternalLink href={t.homepage} className="target-link">
                        site
                      </ExternalLink>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableBox>
      </Panel>
      <Panel title={`Connecter ${picked.length} outil(s)`} tone={picked.length ? 'ai' : undefined}>
        <p className="small">{picked.join(', ') || 'Coche des outils dans le registre.'}</p>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="host">Hôte de l’agent</label>
            <select id="host" className="input" value={host} onChange={(e) => setHost(e.target.value)}>
              <option value="">Celui du profil</option>
              {HOSTS.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </select>
          </div>
          <label className="row small">
            <input type="checkbox" checked={mock} onChange={(e) => setMock(e.target.checked)} /> Simulations locales (données synthétiques,
            sans réseau ni compte)
          </label>
        </div>
        <div className="row">
          <Button disabled={!picked.length} onClick={() => void doPlan()}>
            Voir le plan
          </Button>
          <Button variant="primary" disabled={!picked.length} busy={busy !== null || applying} onClick={() => void apply()}>
            Écrire la configuration
          </Button>
          <Button
            variant="danger"
            disabled={!picked.length}
            busy={busy !== null}
            onClick={() => void act(['tools', 'remove', ...picked, ...hostArgs], { success: 'Connexions retirées' })}
          >
            Retirer
          </Button>
        </div>
        {plan && <Pre text={plan.text} lang={plan.lang} />}
      </Panel>
      <MockConsole id={call} onClose={() => setCall(null)} />
    </div>
  );
}

/** The console of a mock: its tools come from `tools call ID --json`, each with its arguments and a working example. */
function MockConsole({ id, onClose }: { id: string | null; onClose: () => void }) {
  const listing = useCli<MockListing>(id ? ['tools', 'call', id, '--json'] : null);
  const [name, setName] = useState('');
  const [args, setArgs] = useState('{}');
  const [answer, setAnswer] = useState<{ text: string; failed: boolean } | null>(null);
  useEffect(() => {
    setName('');
    setArgs('{}');
    setAnswer(null);
  }, [id]);
  const pick = (tool: string) => {
    setName(tool);
    const example = listing.data?.tools.find((t) => t.name === tool)?.example;
    if (example) setArgs(JSON.stringify(example));
  };
  return (
    <Dialog open={!!id} onClose={onClose} wide title={`Simulation ${id ?? ''}`} footer={<Button onClick={onClose}>Fermer</Button>}>
      <p className="small muted">
        La simulation répond avec des données synthétiques : un portail de support fictif, ses tickets, ses alertes. Aucun réseau, aucun
        compte.
      </p>
      <Q q={listing}>
        {(l) => (
          <>
            <p className="small" lang="en">
              {l.instructions}
            </p>
            {l.generic && (
              <p className="tiny muted">
                Données d’exemple génériques, pas celles de ton projet : <code>openguildkit tools scenario</code> écrit les tiennes.
              </p>
            )}
            <ul className="small">
              {l.tools.map((t) => (
                <li key={t.name}>
                  <code>{t.name}</code> ({t.read_only ? 'lecture' : 'écriture simulée'}) : <span lang="en">{t.description}</span>{' '}
                  <span className="tiny muted block mono">{t.arguments}</span>
                </li>
              ))}
            </ul>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="mock-name">Outil de la simulation</label>
                <select id="mock-name" className="input" value={name} onChange={(e) => pick(e.target.value)}>
                  <option value="">Choisir…</option>
                  {l.tools.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
              <TextArea label="Arguments (JSON)" value={args} onChange={(e) => setArgs(e.target.value)} rows={2} />
            </div>
          </>
        )}
      </Q>
      <Button
        variant="primary"
        disabled={!name}
        onClick={() =>
          void run(['tools', 'call', id!, name, '--args', args], undefined, { raw: true, allowFailure: true })
            .then((r) => setAnswer({ text: r.code === 0 ? r.stdout : cliMessage(r), failed: r.code !== 0 }))
            .catch((e: Error) => setAnswer({ text: e.message, failed: true }))
        }
      >
        Appeler
      </Button>
      {answer && <Pre text={answer.text} />}
    </Dialog>
  );
}

/* ------------------------------------------------------------------ storybook */

type Status = ProposalStatus;
type Item = ProposalItem;
type Proposals = StorybookProposals;
const SECTIONS = [
  ['components', 'Composants'],
  ['variants', 'Variantes'],
  ['tokens', 'Jetons'],
] as const;
type Section = (typeof SECTIONS)[number][0];
const STATUS_LABEL: Record<Status, string> = { proposed: 'à décider', validated: 'validé', rejected: 'rejeté' };

function itemOrigin(it: Item, section: Section, draft: Proposals) {
  if (section === 'variants') {
    const component = draft.components.find((c) => c.key === it.component)?.name ?? it.component;
    return `${component} · ${Object.entries(it.props ?? {})
      .map(([k, v]) => `${k}=${String(v)}`)
      .join(', ')}`;
  }
  if (section === 'tokens') return `${it.kind} ${it.value}`;
  return `${it.file}:${it.line}`;
}

function Storybook() {
  const proposals = useQuery<Proposals | null>(
    'file:proposals',
    useCallback(async () => {
      try {
        return await readJson<Proposals>('.openguildkit/storybook/proposals.json');
      } catch {
        return null;
      }
    }, []),
  );
  const inventory = useQuery<{ scanned?: { components: number; styles: number }; notes?: string[]; sources?: string[] } | null>(
    'file:inventory',
    useCallback(async () => {
      try {
        return await readJson('.openguildkit/storybook/inventory.json');
      } catch {
        return null;
      }
    }, []),
  );
  const [draft, setDraft] = useState<Proposals | null>(null);
  const [src, setSrc] = useState('src');
  const [section, setSection] = useState<Section>('components');
  const [saving, setSaving] = useState(false);
  const { act, busy } = useAction();
  useEffect(() => {
    setDraft(proposals.data ?? null);
  }, [proposals.data]);
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(proposals.data);
  const update = (key: string, patch: Partial<Item>) =>
    setDraft((d) => d && { ...d, [section]: d[section].map((it) => (it.key === key ? { ...it, ...patch } : it)) });
  const bulk = (status: Status, only: (it: Item) => boolean) =>
    setDraft((d) => d && { ...d, [section]: d[section].map((it) => (only(it) ? { ...it, status } : it)) });
  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await writeFile('.openguildkit/storybook/proposals.json', JSON.stringify(draft, null, 2));
      toast({ tone: 'success', title: 'Décisions enregistrées' });
      invalidate();
    } catch (e) {
      const shown = errorText(e as Error);
      toast({ tone: 'danger', title: 'Enregistrement impossible', text: shown.text, lang: shown.lang });
    } finally {
      setSaving(false);
    }
  };
  const items = draft?.[section] ?? [];
  const validated = draft ? SECTIONS.reduce((n, [k]) => n + draft[k].filter((it) => it.status === 'validated').length, 0) : 0;

  return (
    <div className="page-grid">
      <Panel title="Extraire le design system d’une application React">
        <p className="small muted">
          La CLI inventorie les composants fonctionnels, leurs props et variantes, et les jetons CSS, sans réseau. Elle lit le code par
          motifs, pas avec un analyseur complet : vérifie l’inventaire avant de valider.
        </p>
        <div className="row">
          <TextField
            label="Dossiers ou fichiers à lire, relatifs au projet (séparés par des virgules)"
            value={src}
            onChange={(e) => setSrc(e.target.value)}
          />
          <Button
            variant="primary"
            busy={busy !== null}
            disabled={!src.trim()}
            onClick={() =>
              void act(
                [
                  'storybook',
                  'extract',
                  ...src
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean)
                    .flatMap((s) => ['--src', s]),
                ],
                { success: 'Inventaire écrit' },
              )
            }
          >
            Inventorier
          </Button>
          <Button
            busy={busy !== null}
            disabled={!inventory.data}
            onClick={() => void act(['storybook', 'propose'], { success: 'Propositions mises à jour' })}
          >
            Proposer
          </Button>
          <Button
            busy={busy !== null}
            disabled={!validated || dirty}
            title={dirty ? 'Enregistre d’abord tes décisions' : undefined}
            onClick={() => void act(['storybook', 'generate'], { success: 'Jetons, stories et index générés' })}
          >
            Générer ({validated} validé(s))
          </Button>
        </div>
        {inventory.data?.scanned && (
          <p className="small">
            Inventaire de {inventory.data.sources?.join(', ')} : {inventory.data.scanned.components} composant(s) et{' '}
            {inventory.data.scanned.styles} feuille(s) de style lus.
          </p>
        )}
        {inventory.data?.notes?.map((n) => (
          <Notice key={n} tone="warn">
            <span lang="en">{n}</span>
          </Notice>
        ))}
      </Panel>
      <Panel
        title="Propositions"
        actions={
          draft ? (
            <>
              <Button size="small" onClick={() => bulk('validated', (it) => it.confidence === 'observed' && it.status === 'proposed')}>
                Valider ce qui est observé
              </Button>
              <Button size="small" variant="ghost" onClick={() => bulk('rejected', (it) => it.status === 'proposed')}>
                Rejeter le reste
              </Button>
            </>
          ) : undefined
        }
      >
        {!draft ? (
          <p className="muted">Aucune proposition. Inventorie puis propose.</p>
        ) : (
          <>
            <Tabs
              label="Type de proposition"
              value={section}
              onChange={(s) => setSection(s as Section)}
              tabs={SECTIONS.map(([id, title]) => ({ id, label: title, count: draft[id].length }))}
            />
            <TableBox label="Tableau des propositions" tall>
              <table className="data compact">
                <thead>
                  <tr>
                    <th>Nom</th>
                    <th>Origine</th>
                    <th>Confiance</th>
                    <th>Décision</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.key} className={it.observed === false ? 'muted' : undefined}>
                      <td>
                        <input
                          className="input"
                          aria-label={`Nom de ${it.key}`}
                          value={it.name}
                          onChange={(e) => update(it.key, { name: e.target.value })}
                        />
                        <span className="mono tiny block">{it.key}</span>
                      </td>
                      <td className="small">
                        {section === 'tokens' && it.kind === 'color' && (
                          <span className="swatch" style={{ background: it.value }} aria-hidden="true" />
                        )}
                        {itemOrigin(it, section, draft)}
                        {it.kind === 'screen' && (
                          <>
                            {' '}
                            <Badge tone="muted">écran</Badge>
                          </>
                        )}
                        {it.observed === false && (
                          <>
                            {' '}
                            <Badge tone="warning">plus observé</Badge>
                          </>
                        )}
                        {it.origins?.length ? (
                          <span className="tiny muted block">
                            {it.origins.slice(0, 3).join(' · ')}
                            {it.origins.length > 3 ? ` · +${it.origins.length - 3}` : ''}
                          </span>
                        ) : null}
                      </td>
                      <td>
                        <Badge tone={it.confidence === 'observed' ? 'success' : 'warning'}>
                          {it.confidence === 'observed' ? 'observé' : 'hypothèse'}
                        </Badge>
                        {it.basis && <span className="tiny muted block">{it.basis}</span>}
                      </td>
                      <td>
                        <select
                          className="input"
                          aria-label={`Décision pour ${it.key}`}
                          value={it.status}
                          onChange={(e) => update(it.key, { status: e.target.value as Status })}
                        >
                          {(Object.keys(STATUS_LABEL) as Status[]).map((s) => (
                            <option key={s} value={s}>
                              {STATUS_LABEL[s]}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableBox>
            <div className="row">
              <Button variant="primary" busy={saving} disabled={!dirty} onClick={() => void save()}>
                Enregistrer les décisions
              </Button>
              <Button disabled={!dirty} onClick={() => setDraft(proposals.data ?? null)}>
                Annuler
              </Button>
              {dirty && <span className="small muted">Décisions non enregistrées</span>}
            </div>
            <p className="tiny muted">
              Les décisions sont écrites dans <code>.openguildkit/storybook/proposals.json</code> ; un nouveau <code>propose</code> les
              garde. <code>generate</code> écrit dans <code>src/design-system/</code> et ne remplace jamais un fichier modifié à la main.
            </p>
          </>
        )}
      </Panel>
      <Panel title="Design system de l’entreprise">
        <ActionForm
          busy={busy !== null}
          submit="Ajouter la référence"
          fields={[
            { name: 'ref', label: 'Identifiant de la référence', required: true, placeholder: 'company' },
            { name: 'url', label: 'Adresse du Storybook publié', required: true, placeholder: 'https://design.example.com' },
            { name: 'title', label: 'Titre dans la barre latérale', placeholder: 'Design system Acme' },
          ]}
          onSubmit={(v) =>
            act(['storybook', 'compose', v.ref, '--url', v.url, ...(v.title ? ['--title', v.title] : [])], { success: 'Référence ajoutée' })
          }
        />
        <p className="tiny muted">
          Une story se cite ensuite comme <code>storybook:REF_STORY_ID</code> dans un avis du cerveau Design.
        </p>
        <Notice tone="info">
          Pour comparer les index Storybook du projet et de l’entreprise :{' '}
          <CommandLine command={terminalCommand(['storybook', 'import', '--company-index', 'company/index.json'])} />
        </Notice>
      </Panel>
    </div>
  );
}
