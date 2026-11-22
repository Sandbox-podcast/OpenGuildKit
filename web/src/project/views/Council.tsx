/**
 * Conseil: frame a task with the questionnaire, preview and adjust the boards, consult, follow each board's
 * pass, read the reviews, deliberate, clear blockers and decide. Approval stays in the person's terminal.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { navigate } from '@/app/router';
import { Badge, Button, Empty, Notice, Panel, TextArea, TextField } from '@/shared/ui/core';
import { Dialog } from '@/shared/ui/overlay';
import { Markdown } from '@/shared/ui/markdown';
import { Icon } from '@/shared/pixel/icons';
import { listFiles, run, terminalCommand } from '../api';
import { boardTitle, useBrains, useProfile, useTasks } from '../data';
import { invalidate, showTerminal, useAction, useCli, useCliText, useQuery } from '../query';
import { BASIS, CONCERNS, CONFIDENCE, DATA, KIND, PASS, QUESTION_FR, RESEARCH, SURFACE, fmtWhen, isDecided, needsReconsult, nextLabel, nextLang, openPointLabel, verdict } from '../labels';
import { ActionForm, CommandLine, FilePick, JsonDetails, Q, Section, StepRail, TaskStatusBadge, UnreadableTask, copyText, useDebounced, useRemembered } from '../parts';
import { usePrefs } from '../prefs';
import { isMultiple, questionList, toggleChoice, unanswered } from '../answers';
import type { Answers, BlockerItem, Brain, Deliberation, PassProgress, Question, QuestionSet, Route, TaskRecord } from '../types';

const LABELS: Record<string, Record<string, string>> = { kind: KIND, surface: SURFACE, data: DATA, research: RESEARCH, concerns: CONCERNS };

export function CouncilList() {
  const tasks = useTasks();
  const { mode } = usePrefs();
  const groups = [
    { title: mode === 'explorer' ? 'Quêtes à esquisser' : 'À cadrer', statuses: ['draft', 'changes-requested', 'reconsult'] },
    { title: 'En consultation', statuses: ['consulting'] },
    { title: mode === 'explorer' ? 'À sceller' : 'À décider', statuses: ['reviewed'] },
    { title: 'Décidées', statuses: ['approved', 'done', 'done-with-reservations'] },
  ];
  return (
    <Q q={tasks} empty={<Empty title="Le Conseil est vide" action={<a className="btn primary" href="#/quetes?nouvelle=1">Ouvrir une quête</a>}>Chaque quête passe par le Conseil avant d’être réalisée.</Empty>}>
      {(list) => (
        <div className="grid-2">
          {groups.map((g) => {
            const items = list.filter((t) => g.statuses.includes(needsReconsult(t) ? 'reconsult' : t.status));
            return (
              <Panel key={g.title} title={<>{g.title} <span className="badge count">{items.length}</span></>}>
                {items.length === 0 ? <p className="muted small">Aucune quête.</p> : <ul className="plain stack tight">{items.map((t) => (
                  <li key={t.id}><a className="card" href={`#/conseil/${t.id}`}>
                    <span className="row between"><span className="mono small">{t.id}</span><TaskStatusBadge status={t.status} /></span>
                    <strong className="clamp-2">{t.brief}</strong>
                    <span className="small muted" lang={nextLang(t.next)}>{nextLabel(t.next)}</span>
                  </a></li>
                ))}</ul>}
              </Panel>
            );
          })}
        </div>
      )}
    </Q>
  );
}

export function CouncilRoom({ id }: { id: string }) {
  const item = useTasks().data?.find((t) => t.id === id);
  if (item?.status === 'unreadable') return <div className="page-grid"><p className="mono small muted">{id}</p><UnreadableTask id={id} message={item.next} /></div>;
  return <CouncilRecord id={id} reconsult={!!item && needsReconsult(item) ? item.next : null} />;
}

function CouncilRecord({ id, reconsult }: { id: string; reconsult: string | null }) {
  // The text of the consultation is read with `task brief` when the person opens it.
  const record = useCli<TaskRecord>(['task', 'show', id], { omit: ['markdown', 'review_template'] });
  return (
    <Q q={record} label="Ouverture de la salle du Conseil">
      {(t) => (
        <div className="page-grid">
          <div className="quest-head">
            <div className="grow">
              <p className="mono small muted"><a href={`#/quetes/${t.id}`}>{t.id}</a></p>
              <h2 className="h-title clamp-2">{t.brief.split('\n')[0]}</h2>
              <TaskStatusBadge status={t.status} />
            </div>
          </div>
          <StepRail status={t.status} hasResult={!!t.result} />
          {reconsult && <Notice tone="danger" title="L’approbation ne tient plus :"><span lang={nextLang(reconsult)}>{nextLabel(reconsult)}</span> Réponds au questionnaire et réunis le Conseil à nouveau : la consultation précédente et l’approbation restent dans l’historique.</Notice>}
          {(t.status === 'draft' || t.status === 'changes-requested' || !!reconsult) && <Framing task={t} />}
          {t.status === 'changes-requested' && t.decision && <Notice tone="warn" title="Renvoyée au Conseil :">{t.decision.by} — {t.decision.reason}. Une nouvelle consultation archive le tour précédent, avec son brief ; vous pouvez réviser le brief au moment de consulter à nouveau.</Notice>}
          {t.status === 'consulting' && <><Framing task={t} collapsed /><Passes task={t} /></>}
          {(t.status === 'reviewed' || isDecided(t.status)) && <Reviews task={t} />}
          {t.status === 'reviewed' && <><Deliberation id={t.id} /><Blockers id={t.id} /><Decide task={t} /></>}
          {isDecided(t.status) && t.decision && !reconsult && (
            <Notice tone="success" title="Décision scellée :">{t.decision.by}, le {fmtWhen(t.decision.at)} — {t.decision.reason}. {t.status === 'approved' && <a href={`#/forge/${t.id}`}>Passer à la Forge</a>}</Notice>
          )}
        </div>
      )}
    </Q>
  );
}

/* ------------------------------------------------------------------ framing and routing */

/** The questions of the task, then, once every question with choices is answered, its follow-ups and open points. */
function useQuestionSets(id: string, answers: Answers) {
  const base = useCli<QuestionSet>(['task', 'questions', id]);
  const json = JSON.stringify(answers);
  const complete = !!base.data && unanswered(base.data.questions, answers as Record<string, unknown>).length === 0;
  const extra = useQuery<QuestionSet | null>(complete ? `questions:${id}:${json}` : null, useCallback(async () => (await run<QuestionSet>(['task', 'questions', id, '--answers', '@upload:answers.json'], { 'answers.json': json })).json, [id, json]));
  return { base, extra };
}

function Framing({ task, collapsed }: { task: TaskRecord; collapsed?: boolean }) {
  const previous = task.answers ?? task.rounds.at(-1)?.answers ?? {};
  const [answers, setAnswers] = useState<Answers>(previous);
  const [open, setOpen] = useState(!collapsed);
  // Requests follow the answers once typing pauses, not at every keystroke.
  const settled = useDebounced(answers, 450);
  const { base, extra } = useQuestionSets(task.id, settled);
  const asked = base.data?.questions ?? [];
  const missing = unanswered(asked, settled as Record<string, unknown>);
  const complete = !!base.data && missing.length === 0;
  const prompts = Object.fromEntries([...asked, ...(extra.data?.questions ?? [])].map((q) => [q.id, q.prompt]));
  const set = (key: string, value: string | string[]) => setAnswers((a) => ({ ...a, [key]: value }));
  // A question can come back as a follow-up (concerns, once it is required): each one is drawn once.
  const shown = questionList(asked, extra.data?.questions, extra.data?.follow_ups);

  if (!open) return <Panel title="Cadrage"><p className="small">Réponses enregistrées : {KIND[answers.kind ?? ''] ?? '—'}, {[answers.surface].flat().map((s) => SURFACE[s as string] ?? s).join(', ')}, données {DATA[answers.data ?? '']?.toLowerCase() ?? '—'}{answers.concerns ? `, sujets : ${[answers.concerns].flat().map((c) => CONCERNS[c as string]?.toLowerCase() ?? c).join(', ')}` : ''}. <Button size="small" onClick={() => setOpen(true)}>Modifier et consulter à nouveau</Button></p></Panel>;
  return (
    <>
      <Section title="Cadrage : le questionnaire" icon="question">
        <p className="small muted">L’agent pose ces questions dans votre langue et confirme ce qu’il a déduit du brief. Vous pouvez aussi répondre ici.</p>
        <Q q={base} label="Lecture du questionnaire">
          {() => <div className="stack">{shown.map((q) => <QuestionField key={q.id} q={q} value={(answers as Record<string, unknown>)[q.id]} onChange={(v) => set(q.id, v)} />)}</div>}
        </Q>
        {extra.data?.open_points && extra.data.open_points.length > 0 && <Notice tone="warn" title="Points ouverts :"><ul>{extra.data.open_points.map((p) => <li key={p}>{openPointLabel(p, prompts)}</li>)}</ul>Ils ne bloquent pas la consultation : chaque cerveau dira comment ils pèsent sur son avis.</Notice>}
        {extra.error && <Notice tone="danger"><span lang={extra.error.lang}>{extra.error.message}</span></Notice>}
        {base.data && missing.length > 0 && <p className="small muted" role="status">Le routage s’affiche quand chaque question à choix a sa réponse ({missing.length} sans réponse).</p>}
      </Section>
      {complete && <Routing task={task} answers={settled} />}
    </>
  );
}

/**
 * One question of the task questionnaire. The prompt and choices are in French when the page knows the question;
 * the CLI's help and the effect of an unsure answer follow in its English. A multi-select takes several choices.
 */
function QuestionField({ q, value, onChange }: { q: Question; value: unknown; onChange: (v: string | string[]) => void }) {
  const prompt = QUESTION_FR[q.id] ? <span title={q.prompt}>{QUESTION_FR[q.id]}</span> : <span lang="en">{q.prompt}</span>;
  if (!q.choices?.length) return <TextArea label={prompt} hint={<QuestionHelp q={q} />} value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value)} rows={3} />;
  const multi = isMultiple(q);
  const selected = [value].flat().filter(Boolean) as string[];
  return (
    <fieldset className="choices" data-question={q.id}>
      <legend>{prompt} <span className="tiny muted">({multi ? 'plusieurs réponses possibles, ' : ''}obligatoire)</span></legend>
      <div className="choice-row">{q.choices.map((c) => {
        const on = selected.includes(c.id);
        const label = LABELS[q.id]?.[c.id];
        return <label key={c.id} className={`choice ${on ? 'on' : ''}`}>
          <input type={multi ? 'checkbox' : 'radio'} name={q.id} value={c.id} checked={on} onChange={() => onChange(multi ? toggleChoice(selected, c.id) : c.id)} />
          {label ? <span title={c.label}>{label}</span> : <span lang="en">{c.label}</span>}
        </label>;
      })}</div>
      {(q.help || q.unsure) && <p className="hint"><QuestionHelp q={q} /></p>}
    </fieldset>
  );
}

/** The CLI's one-line help of a question and what a "don't know" answer applies, in the CLI's English. */
function QuestionHelp({ q }: { q: Question }) {
  return <>{q.help && <span lang="en">{q.help}</span>}{q.unsure && <> Si tu ne sais pas : <span lang="en">{q.unsure}</span>.</>}</>;
}

function Routing({ task, answers }: { task: TaskRecord; answers: Answers }) {
  const brains = useBrains();
  const profile = useProfile();
  const json = JSON.stringify(answers);
  const [add, setAdd] = useState<string[]>([]);
  const [remove, setRemove] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [delegates, setDelegates] = useState<Record<string, string>>({});
  const [market, setMarket] = useState('');
  // After a request for changes, the person can revise the brief; the previous one stays in the task's history.
  const [revised, setRevised] = useState('');
  const adjust = [...add.flatMap((b) => ['--add', b]), ...remove.flatMap((b) => ['--remove', b]), ...(reason ? ['--reason', reason] : []), ...Object.entries(delegates).filter(([, n]) => n.trim()).flatMap(([b, n]) => ['--delegate', `${b}=${n.trim()}`])];
  const key = `route:${task.id}:${json}:${adjust.join('|')}`;
  const route = useQuery<Route | null>(key, useCallback(async () => (await run<Route>(['task', 'route', task.id, '--answers', '@upload:answers.json', ...adjust, '--json'], { 'answers.json': json })).json, [key]));
  const dossiers = useQuery<string[]>('market-dossiers', useCallback(async () => (await listFiles('.openguildkit/market')).filter((e) => e.name.endsWith('.json')).map((e) => e.name.replace(/\.json$/, '')), []));
  const { act, busy } = useAction();
  const enabled = profile.data?.boards?.length ? profile.data.boards : Object.keys(brains.data ?? {});
  const selected = Object.keys(route.data?.routing ?? {});
  const required = profile.data?.required_boards ?? [];
  const needsReason = (add.length > 0 || remove.length > 0) && !reason.trim();

  const brief = task.status === 'changes-requested' && revised.trim() && revised.trim() !== task.brief.trim() ? revised.trim() : null;
  const consult = () => act(['task', 'consult', task.id, '--answers', '@upload:answers.json', ...adjust, ...(market ? ['--market', market] : []), ...(brief ? ['--brief-file', '@upload:brief.md'] : [])],
    { uploads: { 'answers.json': json, ...(brief ? { 'brief.md': brief } : {}) }, success: 'Consultation préparée' });
  return (
    <Section title="Routage : les cerveaux consultés" icon="guild">
      <p className="small muted">Le routage est déterministe : mêmes réponses, mêmes cerveaux. Ajoutez ou retirez un cerveau avec un motif ; il est consigné dans la consultation.</p>
      <Q q={route} label="Calcul du routage">
        {(r) => r && <>
          <ul className="plain board-grid">{Object.entries(r.routing).map(([b, reasons]) => (
            <li key={b} className="card board-pick">
              <span className="row between"><strong><Icon name="guild" size={14} /> {boardTitle(brains.data, b)}</strong>
                {required.includes(b) ? <Badge tone="info" icon="lock">obligatoire</Badge> : <Button size="small" variant="ghost" onClick={() => setRemove((x) => [...x, b])} aria-label={`Retirer ${b}`}>Retirer</Button>}</span>
              <span className="tiny muted">{reasons.join(' · ')}</span>
            </li>
          ))}</ul>
          {Object.keys(r.excluded ?? {}).length > 0 && <Notice tone="info" title="Écartés par le brief, non consultés :"><ul>{Object.entries(r.excluded).map(([b, passages]) => <li key={b}><strong>{boardTitle(brains.data, b)}</strong> : « {passages.join(' », « ')} »</li>)}</ul>S’il s’applique quand même, ajoutez-le avec un motif.</Notice>}
          {Object.keys(r.expected_not_selected ?? {}).length > 0 && <Notice tone="warn" title="Attendus par l’équipe, non retenus :"><ul>{Object.entries(r.expected_not_selected).map(([b, why]) => <li key={b}><strong>{boardTitle(brains.data, b)}</strong> : {why}</li>)}</ul></Notice>}
          {(r.not_selected ?? []).length > 0 && <p className="tiny muted">Non retenus : {r.not_selected.map((b) => boardTitle(brains.data, b)).join(', ')}. Ajoutez-en un avec un motif si la quête le concerne.</p>}
          {r.adjustments.length > 0 && <p className="small">Ajustements : {r.adjustments.map((a) => `${a.action} ${a.board}`).join(', ')}. <Button size="small" variant="ghost" onClick={() => { setAdd([]); setRemove([]); }}>Annuler les ajustements</Button></p>}
        </>}
      </Q>
      {route.error && <Notice tone="danger"><span lang={route.error.lang}>{route.error.message}</span>{/required board/i.test(route.error.message) && ' Nommez la personne qui fera cette revue ci-dessous.'}</Notice>}
      <div className="grid-2">
        <div className="field"><label htmlFor="add-board">Ajouter un cerveau</label>
          <select id="add-board" className="input" value="" onChange={(e) => e.target.value && setAdd((x) => [...x, e.target.value])}>
            <option value="">Choisir…</option>
            {enabled.filter((b) => !selected.includes(b)).map((b) => <option key={b} value={b}>{boardTitle(brains.data, b)}</option>)}
          </select></div>
        <TextField label="Motif de l’ajustement" value={reason} onChange={(e) => setReason(e.target.value)} error={needsReason ? 'Un ajout ou un retrait a besoin d’un motif.' : null} />
      </div>
      {required.filter((b) => !enabled.includes(b)).map((b) => <TextField key={b} label={`Revue obligatoire « ${b} » : personne qui la fera`} value={delegates[b] ?? ''} onChange={(e) => setDelegates((d) => ({ ...d, [b]: e.target.value }))} hint="Ce cerveau n’est pas activé dans le profil : l’agent préparera la revue pour cette personne." />)}
      {task.status === 'changes-requested' && <TextArea label="Brief révisé (facultatif)" hint="Laissez vide pour garder le brief actuel. L’ancien brief reste dans l’historique de la quête." value={revised} onChange={(e) => setRevised(e.target.value)} rows={4} placeholder={task.brief} />}
      {(dossiers.data?.length ?? 0) > 0 && <div className="field"><label htmlFor="market">Dossier de marché à joindre</label>
        <select id="market" className="input" value={market} onChange={(e) => setMarket(e.target.value)}><option value="">Aucun</option>{dossiers.data!.map((d) => <option key={d} value={d}>{d}</option>)}</select>
        <p className="hint">Les observations datées et les lacunes du dossier accompagnent la consultation.</p></div>}
      <div className="row"><Button variant="primary" icon="council" busy={busy !== null} disabled={needsReason || !!route.error} onClick={() => void consult()}>{task.status === 'consulting' || task.status === 'approved' ? 'Consulter à nouveau' : 'Réunir le Conseil'}</Button></div>
    </Section>
  );
}

/* ------------------------------------------------------------------ board passes */

function Passes({ task }: { task: TaskRecord }) {
  const progress = useCli<PassProgress[]>(['task', 'progress', task.id, '--json']);
  const brains = useBrains();
  const { mode } = usePrefs();
  const [pass, setPass] = useState<{ board: string; start: boolean } | null>(null);
  const [summary, setSummary] = useState('');
  const [showBrief, setShowBrief] = useState(false);
  const { act, busy, error } = useAction();
  const done = (progress.data ?? []).filter((p) => p.status === 'done').length;
  const all = progress.data?.length ?? 0;
  const prompt = `Run the OpenGuildKit board passes of task ${task.id}: one independent pass per board with openguildkit task pass, then openguildkit task submit.`;

  return (
    <>
      <Section title={mode === 'explorer' ? 'Les sièges du Conseil' : 'Avis par cerveau'} icon="council" actions={<>
        <Button size="small" icon="scroll" onClick={() => setShowBrief(true)}>Brief de consultation</Button>
        <Button size="small" icon="copy" onClick={() => void run(['task', 'template', task.id], undefined, { raw: true }).then((r) => copyText(r.stdout))}>Copier le modèle d’avis</Button>
      </>}>
        <Notice tone="ai" title="Les avis viennent de votre agent.">Claude Code ou Codex lance une passe indépendante par cerveau et dépose chaque avis. Demandez-lui : <CommandLine command={prompt} label="Consigne pour l’agent" /></Notice>
        <Q q={progress} label="Lecture des passes">
          {(list) => <ul className={`plain board-seats ${mode === 'explorer' ? 'rpg' : ''}`}>{list.map((p) => {
            const s = PASS[p.status];
            return (
              <li key={p.board} className={`board-seat board-seat-${p.status}`}>
                <span className="board-seat-icon"><Icon name={p.status === 'done' ? 'check' : p.status === 'started' ? 'play' : p.status === 'failed' ? 'cross' : 'guild'} size={18} /></span>
                <strong>{boardTitle(brains.data, p.board)}</strong>
                <Badge tone={s.tone} icon={s.icon}>{s.label}</Badge>
                {p.error && <span className="tiny pre-line">{p.error}</span>}
                {p.status === 'started' && <span className="tiny muted">Passe interrompue ? Relancez-la pour ce cerveau seulement.</span>}
                <span className="row"><Button size="small" onClick={() => setPass({ board: p.board, start: p.status === 'missing' })}>{p.status === 'missing' ? 'Préparer la passe' : 'Revoir la passe'}</Button></span>
              </li>
            );
          })}</ul>}
        </Q>
        <p className="small">{done}/{all} avis déposés.</p>
        {error && <Notice tone="danger" title="Avis refusé :"><span className="pre-line">{error.message.replace(/\nFix these points in the file and send it again:.*$/s, '')}</span><span className="block small">Corrigez le fichier et déposez-le à nouveau : la passe reste ouverte, sans nouvelle tentative.</span></Notice>}
        <div className="grid-2">
          <FilePick label="Déposer l’avis d’un cerveau (JSON)" hint="L’entrée remplie renvoyée par la passe." onText={(text) => void act(['task', 'submit', task.id, '--file', '@upload:entry.json'], { uploads: { 'entry.json': text }, success: 'Avis déposé' })} />
          <FilePick label="Ou déposer la revue complète (JSON)" hint="Un fichier avec consultation_id, summary et une entrée par cerveau." onText={(text) => void act(['task', 'review', task.id, '--file', '@upload:review.json'], { uploads: { 'review.json': text }, success: 'Revue enregistrée' })} />
        </div>
        <TextArea label="Synthèse pour assembler la revue" hint="Où les cerveaux s’accordent, où ils divergent, et l’étape suivante. Disponible quand chaque cerveau a rendu son avis." value={summary} onChange={(e) => setSummary(e.target.value)} rows={3} />
        <div className="row"><Button variant="primary" busy={busy !== null} disabled={!summary.trim() || done < all || all === 0} onClick={() => void act(['task', 'review', task.id, '--summary', summary.trim()], { success: 'Revue assemblée' })}>Assembler la revue</Button></div>
      </Section>
      <PassDialog task={task.id} board={pass?.board ?? null} start={!!pass?.start} onClose={() => setPass(null)} />
      <BriefDialog id={task.id} open={showBrief} onClose={() => setShowBrief(false)} />
    </>
  );
}

/** A pass not started yet is started with task pass (it counts an attempt); an open or finished one is read again
 * with task brief --board, which changes nothing. */
function PassDialog({ task, board, start, onClose }: { task: string; board: string | null; start: boolean; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setText(null); setError(null);
    if (!board) return;
    const argv = start ? ['task', 'pass', task, board, '--mode', 'sequential'] : ['task', 'brief', task, '--board', board];
    run(argv, undefined, { raw: true }).then((r) => { setText(r.stdout); if (start) invalidate('project'); }).catch((e: Error) => setError(e.message));
  }, [task, board, start]);
  return (
    <Dialog open={!!board} onClose={onClose} wide title={`Passe du cerveau ${board ?? ''}`} footer={<><Button onClick={onClose}>Fermer</Button>{text && <Button variant="primary" icon="copy" onClick={() => void copyText(text)}>Copier pour l’agent</Button>}</>}>
      <p className="small muted">La passe ne montre à ce cerveau que la quête, son brief, les règles de ses packs qui la concernent et son modèle d’entrée, rien des autres cerveaux. Préparée, elle est marquée « commencée » jusqu’au dépôt de l’avis ; la relire ne la relance pas.</p>
      {error && <Notice tone="danger">{error}</Notice>}
      {text ? <div className="scroll-box" tabIndex={0}><Markdown text={text} /></div> : !error && <p className="muted">Préparation…</p>}
    </Dialog>
  );
}

function BriefDialog({ id, open, onClose }: { id: string; open: boolean; onClose: () => void }) {
  const brief = useCliText(open ? ['task', 'brief', id] : null);
  return (
    <Dialog open={open} onClose={onClose} wide title="Brief de consultation" footer={<><Button onClick={onClose}>Fermer</Button>{brief.data && <Button variant="primary" icon="copy" onClick={() => void copyText(brief.data!)}>Copier</Button>}</>}>
      <Q q={brief}>{(text) => <div className="scroll-box" tabIndex={0}><Markdown text={text} /></div>}</Q>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ reviews */

function Reviews({ task }: { task: TaskRecord }) {
  const brains = useBrains();
  const [challenge, setChallenge] = useState(false);
  if (!task.review) return null;
  return (
    <>
      <Section title="Avis des cerveaux" icon="eye" actions={<Button size="small" icon="scroll" onClick={() => setChallenge(true)}>Arbitrage (task challenge)</Button>}>
        <p className="pre-line">{task.review.summary}</p>
        <div className="review-grid">{task.review.boards.map((b) => <BoardCard key={b.id} entry={b} brain={brains.data?.[b.id]} />)}</div>
      </Section>
      <ChallengeDialog id={task.id} open={challenge} onClose={() => setChallenge(false)} />
    </>
  );
}

function BoardCard({ entry, brain }: { entry: NonNullable<TaskRecord['review']>['boards'][number]; brain?: Brain }) {
  const c = entry.challenge;
  const v = verdict(c?.verdict);
  const lens = (id: string) => brain?.review?.specialists.find((s) => s.id === id)?.title ?? id;
  return (
    <article className={`card review-card verdict-${c?.verdict ?? 'none'}`}>
      <header className="row between"><strong><a href={`#/guilde/${entry.id}`}>{brain?.title ?? entry.id}</a></strong><Badge tone={v.tone} icon={v.icon}>{v.label}</Badge></header>
      {entry.reviewer && <p className="tiny muted">Revue préparée pour {entry.reviewer}</p>}
      <p>{entry.recommendation}</p>
      {c && <>
        <p className="tiny muted">{CONFIDENCE[c.confidence] ?? c.confidence}</p>
        <details><summary>Lentilles ({c.specialists.length}), alternative et vérification</summary>
          <ul className="small">{c.specialists.map((s) => <li key={s.id}><strong>{lens(s.id)}</strong> <span className="tiny muted">({BASIS[s.basis] ?? s.basis}{s.evidence_refs.length ? `, preuves ${s.evidence_refs.join(', ')}` : ''})</span> : {s.finding}</li>)}</ul>
          <p className="small"><strong>Alternative :</strong> {c.alternative}</p>
          <p className="small"><strong>Mode d’échec :</strong> {c.failure_mode}</p>
          <p className="small"><strong>Vérification :</strong> {c.verification}</p>
        </details>
      </>}
      {entry.open_questions.length > 0 && <details><summary>Questions ouvertes ({entry.open_questions.length})</summary><ul className="small">{entry.open_questions.map((q) => <li key={q}>{q}</li>)}</ul></details>}
      {entry.evidence.length > 0 && <details><summary>Preuves ({entry.evidence.length})</summary><ol className="small">{entry.evidence.map((e, i) => <li key={i}><code>{e.ref}</code> <span className="tiny muted">{e.source}</span> — {e.supports}</li>)}</ol></details>}
    </article>
  );
}

function ChallengeDialog({ id, open, onClose }: { id: string; open: boolean; onClose: () => void }) {
  const text = useCliText(open ? ['task', 'challenge', id] : null);
  return (
    <Dialog open={open} onClose={onClose} wide title="Arbitrage : verdicts, désaccords et vérifications" footer={<Button onClick={onClose}>Fermer</Button>}>
      <p className="small muted">L’agent montre ce brief à la personne qui décide, avant toute réalisation.</p>
      <Q q={text}>{(t) => <div className="scroll-box" tabIndex={0}><Markdown text={t} /></div>}</Q>
    </Dialog>
  );
}

function Deliberation({ id }: { id: string }) {
  const d = useCli<Deliberation>(['task', 'deliberate', id]);
  const brains = useBrains();
  const { act } = useAction();
  if (!d.data || d.data.objections.length === 0) return null;
  return (
    <Section title={`Délibération : ${d.data.objections.length} objection(s) entre cerveaux`} icon="council">
      <ul className="plain stack tight">{d.data.objections.map((o) => (
        <li key={o.id} className="card"><strong>{boardTitle(brains.data, o.from)} → {boardTitle(brains.data, o.to)}</strong><p className="small">{o.point}</p>
          <p className="tiny muted">{o.from_position} · face à · {o.to_position}</p>{o.meets?.length ? <p className="tiny muted">Domaines communs : {o.meets.join(', ')}</p> : null}</li>
      ))}</ul>
      {d.data.rules && <details className="small"><summary>Règles des réponses</summary><ul>{Object.entries(d.data.rules.positions ?? {}).map(([k, v]) => <li key={k}><code>{k}</code> : {v}</li>)}</ul><p>{d.data.rules.resolution}</p>
        <p className="tiny muted">Une réponse peut couvrir plusieurs objections : <code>objections</code> en liste d’identifiants.</p></details>}
      <div className="grid-2">
        <div><Button size="small" icon="copy" onClick={() => void copyText(JSON.stringify(d.data!.template, null, 2))}>Copier le modèle de réponse</Button></div>
        <FilePick label="Déposer les réponses (JSON)" onText={(text) => void act(['task', 'respond', id, '--file', '@upload:deliberation.json'], { uploads: { 'deliberation.json': text }, success: 'Réponses enregistrées' })} />
      </div>
    </Section>
  );
}

function Blockers({ id }: { id: string }) {
  const blockers = useCli<BlockerItem[]>(['task', 'blockers', id, '--json']);
  const profile = useProfile();
  const [by, setBy] = useRemembered('decider');
  const [clearing, setClearing] = useState<BlockerItem | null>(null);
  const [waiving, setWaiving] = useState<BlockerItem | null>(null);
  const [signer, setSigner] = useRemembered('signer');
  const [signature, setSignature] = useState('');
  const { act, busy } = useAction();
  if (!blockers.data?.length) return null;
  const waivers = profile.data?.waivers;
  const signed = profile.data?.approval?.mode === 'signed';
  const blocking = blockers.data.filter((b) => !b.resolution && b.phase !== 'verification').length;
  return (
    <Section id="blocages" title={`Blocages (${blocking} ouvert(s) avant la validation)`} icon="ban">
      <ul className="plain stack tight">{blockers.data.map((b) => (
        <li key={b.id} className={`card blocker ${b.resolution ? 'resolved' : ''}`}>
          <span className="row between"><span className="mono small">{b.id}</span>{b.resolution ? <Badge tone="success" icon="check">{b.resolution.kind === 'waived' ? `dérogation de ${b.resolution.by}` : `levé par ${b.resolution.by}`}</Badge> : b.phase === 'verification' ? <Badge tone="warning" icon="clock">condition de la validation</Badge> : <Badge tone="danger" icon="ban">ouvert</Badge>}</span>
          {b.phase === 'verification' && !b.resolution && <span className="tiny muted">Seul le travail fini peut le lever : la validation reste possible, et la quête ne se termine pas tant qu’il est ouvert.</span>}
          <strong>{b.finding}</strong>
          {b.owner && <span className="small">Responsable : {b.owner}. Se lève quand : {b.clears_when}</span>}
          {b.resolution?.evidence && <span className="small muted">Preuve : <code>{b.resolution.evidence}</code> — {b.resolution.supports}</span>}
          {!b.resolution && <span className="row"><Button size="small" variant="primary" onClick={() => setClearing(b)}>Lever avec une preuve (au terminal)</Button>{waivers && <Button size="small" onClick={() => setWaiving(b)}>Déroger (au terminal)</Button>}</span>}
        </li>
      ))}</ul>
      {!waivers && <p className="tiny muted">Le profil n’autorise pas de dérogation : sans preuve, renvoyez la quête au Conseil.</p>}
      <Dialog open={!!clearing} onClose={() => { setClearing(null); setSignature(''); }} title={`Lever ${clearing?.id ?? ''}`}>
        {clearing && <>
          <p className="small">Lever un blocage est l’acte d’une personne : elle regarde la preuve, puis tape la commande dans son terminal et retape l’identifiant de la quête. L’interface prépare la commande, sans l’enregistrer.{signed && ' Dans un projet à approbation signée, la levée peut aussi être signée avec la clé SSH de la personne et déposée ici.'}</p>
          <ActionForm busy={busy !== null} submit="Préparer la commande" initial={{ by }} fields={[
            { name: 'evidence', label: 'Preuve', required: true, placeholder: 'tests/test_access.py, un lien, un document', hint: `Ce qui est attendu : ${clearing.clears_when ?? ''}` },
            { name: 'supports', label: 'Ce que la preuve établit', required: true },
            { name: 'by', label: 'Personne qui lève le blocage', required: true },
          ]} onSubmit={async (v) => {
            setBy(v.by);
            const argv = ['task', 'clear', id, clearing.id, '--evidence', v.evidence, '--supports', v.supports, '--by', v.by];
            if (signed && signature && signer) {
              if (await act([...argv, '--signature', '@upload:clear.sig', '--signer', signer], { uploads: { 'clear.sig': signature }, success: 'Levée signée enregistrée' })) { setClearing(null); setSignature(''); }
              return;
            }
            setClearing(null);
            showTerminal({ title: 'Levée du blocage : à faire dans votre terminal', why: 'L’interface n’enregistre jamais la levée d’un blocage sans la signature de la personne. Elle tape cette commande, puis retape l’identifiant de la quête.', command: terminalCommand(argv) });
          }} />
          {signed && <details className="small"><summary>Levée signée</summary>
            <p>1. Écrivez la levée exacte à signer :</p><CommandLine command={terminalCommand(['task', 'clear', id, clearing.id, '--evidence', 'PREUVE', '--supports', 'CE_QU_ELLE_ETABLIT', '--by', by || 'Votre nom', '--payload', 'clear.json'])} />
            <p>2. Signez-la avec votre clé SSH :</p><CommandLine command="ssh-keygen -Y sign -n openguildkit-decision -f ~/.ssh/id_ed25519 clear.json" />
            <p>3. Déposez la signature et nommez le signataire, puis « Préparer la commande » l’enregistre ; la CLI la vérifie avec le fichier des signataires autorisés.</p>
            <TextField label="Signataire (principal)" value={signer} onChange={(e) => setSigner(e.target.value)} />
            <FilePick label="Signature (clear.json.sig)" accept=".sig,text/plain" onText={(t) => setSignature(t)} />
          </details>}
        </>}
      </Dialog>
      <Dialog open={!!waiving} onClose={() => setWaiving(null)} title={`Déroger à ${waiving?.id ?? ''}`}>
        {waiving && <>
          <p className="small">Une dérogation demande la personne nommée, devant un terminal. Autorisées : {waivers?.allowed_by.join(', ')}, {waivers?.max_days} jours au plus.</p>
          <ActionForm submit="Préparer la commande" initial={{ by }} fields={[
            { name: 'by', label: 'Personne qui déroge', required: true, options: (waivers?.allowed_by ?? []).map((n) => ({ value: n, label: n })) },
            { name: 'reason', label: 'Pourquoi le risque est accepté', required: true },
            { name: 'scope', label: 'Ce que la dérogation couvre', required: true },
            { name: 'until', label: 'Dernier jour', type: 'date', required: true },
          ]} onSubmit={(v) => { setWaiving(null); showTerminal({ title: 'Dérogation : à faire dans votre terminal', why: 'L’interface n’enregistre jamais une dérogation. La personne nommée tape cette commande, puis retape l’identifiant de la quête.', command: terminalCommand(['task', 'waive', id, waiving.id, '--by', v.by, '--reason', v.reason, '--scope', v.scope, '--until', v.until]) }); }} />
        </>}
      </Dialog>
    </Section>
  );
}

/* ------------------------------------------------------------------ decision */

function Decide({ task }: { task: TaskRecord }) {
  const profile = useProfile();
  const blockers = useCli<BlockerItem[]>(['task', 'blockers', task.id, '--json']);
  const [by, setBy] = useRemembered('decider');
  const [reason, setReason] = useState('');
  const [signer, setSigner] = useState('');
  const [signature, setSignature] = useState('');
  const [brief, setBrief] = useState(false);
  const { act, busy } = useAction();
  // A blocker of phase verification is a condition of the approval: it does not hold the decision back.
  const open = (blockers.data ?? []).filter((b) => !b.resolution && b.phase !== 'verification').length;
  const conditions = (blockers.data ?? []).filter((b) => !b.resolution && b.phase === 'verification').length;
  const previous = task.rounds.at(-1)?.decision;
  const signed = profile.data?.approval?.mode === 'signed';
  const approve = useMemo(() => terminalCommand(['task', 'decide', task.id, '--approve', '--by', by || 'Votre nom', '--reason', reason || 'Motif de la décision']), [task.id, by, reason]);
  const payload = terminalCommand(['task', 'decision-payload', task.id, '--by', by || 'Votre nom', '--reason', reason || 'Motif', '--output', 'decision.json']);

  return (
    <Section id="decision" title="Décision" icon="lock">
      {previous && <Notice tone="info" title="Tour précédent :">{previous.outcome === 'approved' ? 'validé' : 'renvoyé au Conseil'} par {previous.by} : {previous.reason}</Notice>}
      {open > 0 && <Notice tone="danger" title={`${open} blocage(s) ouvert(s).`}>La validation attend qu’ils soient levés. Vous pouvez déjà renvoyer la quête au Conseil.</Notice>}
      {conditions > 0 && <Notice tone="warn" title={`${conditions} condition(s) de la validation.`}>Ces blocages ne se lèvent qu’une fois le travail fini : la validation reste possible, et la quête ne se terminera pas tant qu’ils sont ouverts.</Notice>}
      <div className="grid-2">
        <TextField label="Personne qui décide" value={by} onChange={(e) => setBy(e.target.value)} />
        <TextField label="Motif" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Périmètre en lecture seule convenu avec le support" />
      </div>
      <div className="grid-2 decision-grid">
        <div className="card">
          <h3 className="h-card"><Icon name="lock" size={14} /> Valider, dans votre terminal</h3>
          <p className="small">La CLI affiche le brief et la revue, puis vous demande de retaper <code>{task.id}</code>. Elle scelle la décision avec la révision Git et les règles en vigueur. L’interface ne valide jamais à votre place.</p>
          <CommandLine command={approve} label="Commande de validation" />
          {signed && <details className="small"><summary>Projet à approbation signée</summary>
            <p>1. Écrivez la décision exacte à signer :</p><CommandLine command={payload} />
            <p>2. Signez-la avec votre clé SSH :</p><CommandLine command="ssh-keygen -Y sign -n openguildkit-decision -f ~/.ssh/id_ed25519 decision.json" />
            <p>3. Déposez la signature ici ; la CLI la vérifie avec le fichier des signataires autorisés.</p>
            <TextField label="Signataire (principal)" value={signer} onChange={(e) => setSigner(e.target.value)} />
            <FilePick label="Signature (decision.json.sig)" accept=".sig,text/plain" onText={(t) => setSignature(t)} />
            <Button variant="primary" busy={busy !== null} disabled={!signature || !signer || !by || !reason} onClick={() => void act(['task', 'decide', task.id, '--approve', '--by', by, '--reason', reason, '--signature', '@upload:decision.sig', '--signer', signer], { uploads: { 'decision.sig': signature }, success: 'Décision signée enregistrée' })}>Enregistrer la décision signée</Button>
          </details>}
        </div>
        <div className="card">
          <h3 className="h-card"><Icon name="replace" size={14} /> Renvoyer au Conseil</h3>
          <p className="small">La prochaine consultation archive les réponses, la revue et cette décision dans l’historique de la quête.</p>
          <Button variant="danger" busy={busy !== null} disabled={!by.trim() || !reason.trim()} onClick={() => void act(['task', 'decide', task.id, '--request-changes', '--by', by.trim(), '--reason', reason.trim()], { success: 'Quête renvoyée au Conseil' }).then((r) => r && navigate(`/conseil/${task.id}`))}>Demander des changements</Button>
        </div>
      </div>
      <JsonDetails data={task.consultation?.scope} label="Périmètre soumis à la décision" />
      <div className="row"><Button size="small" icon="scroll" onClick={() => setBrief(true)}>Lire la consultation complète</Button></div>
      <BriefDialog id={task.id} open={brief} onClose={() => setBrief(false)} />
    </Section>
  );
}
