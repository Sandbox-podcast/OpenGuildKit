/**
 * Domain-aware components. Command buttons ask the domain (same `check` as the command) whether
 * the action is allowed, and show the reason when it is not (RG-12).
 */
import { useState, type ReactNode } from 'react';
import { can, dispatch, newOpId, useAppState } from '@/demo/app/store';
import { routeOf } from '@/demo/app/routes';
import { cmd } from '@/demo/domain/commands';
import type { CommandDef } from '@/demo/domain/engine';
import { stateDef, transitionsFrom, type MachineKind } from '@/demo/domain/machines';
import { ROLES, rolesOf } from '@/demo/domain/permissions';
import { KIND_LABELS, approvalValidity, effectiveApprovalStatus, fmtDate, objectLabel, resultFreshness } from '@/demo/domain/selectors';
import { terminalCommand, type TerminalCommand } from '@/demo/domain/terminal';
import type { Actor, ID, Ref, RefKind, Result } from '@/demo/domain/types';
import { Icon } from '@/shared/pixel/icons';
import { portraitUrl } from '@/shared/pixel/portraits';
import { Badge, Button, Select } from '@/shared/ui/core';
import { ConfirmDialog } from '@/shared/ui/overlay';
import type { TransitionKind } from '@/demo/domain/commands/transitions';

export function StatusBadge({ kind, state, title }: { kind: MachineKind; state: string; title?: string }) {
  const d = stateDef(kind, state);
  return <Badge tone={d.tone} icon={d.icon} title={title ?? d.hint}>{d.label}</Badge>;
}

export function SimBadge({ label = 'Simulation' }: { label?: string }) {
  return <span className="badge sim" title="Résultat produit par un adaptateur de démonstration, pas par un service réel"><Icon name="dice" size={12} />{label}</span>;
}

export function Portrait({ k, size = 32, alt = '' }: { k: string; size?: number; alt?: string }) {
  return <img className="pixel" src={portraitUrl(k, size)} width={size} height={size} alt={alt} decoding="async" style={{ background: 'var(--surface-3)' }} />;
}

export function Person({ id, showRole }: { id?: string | null; showRole?: boolean }) {
  const s = useAppState();
  if (!id) return <span className="muted">Non assigné</span>;
  if (id.startsWith('agent:')) return <ExpertChip id={`exp-${s.session.orgId}-${id.slice(6)}`} fallback={id.slice(6)} />;
  if (s.db.expert[id]) return <ExpertChip id={id} />;
  const u = s.users[id];
  if (!u) return <span className="muted">{id}</span>;
  const roles = s.session.orgId ? rolesOf(s, id, s.session.orgId) : [];
  return (
    <span className="person">
      <Portrait k={u.portrait} size={24} />
      <span>{u.name}{showRole && roles.length > 0 && <span className="role"> · {roles.map((r) => ROLES[r].short).join(', ')}</span>}</span>
    </span>
  );
}

/** AI expertise: portrait always paired with the "IA" mark (brief §5.4). */
export function ExpertChip({ id, fallback }: { id: ID; fallback?: string }) {
  const s = useAppState();
  const e = s.db.expert[id];
  if (!e) return <span className="muted">{fallback ?? id}</span>;
  return (
    <a className="person" href={`#/guilde/${e.id}`} style={{ color: 'inherit', textDecoration: 'none' }}>
      <Portrait k={e.key} size={24} />
      <span>{e.name}</span><span className="ai-mark" title="Expertise IA (agent)"><Icon name="ai" size={10} />IA</span>
    </a>
  );
}

export function ActorLabel({ actor }: { actor: Actor }) {
  if (actor.type === 'human') return <Person id={actor.userId} />;
  if (actor.type === 'agent') return <ExpertChip id={actor.expertId} />;
  return <span className="person"><Icon name="settings" size={16} /> Système de démonstration</span>;
}

export const Version = ({ n, label = 'v' }: { n?: number | string; label?: string }) => (n === undefined ? null : <span className="version">{label}{n}</span>);

export function ObjectLink({ to, children, bare }: { to: Ref; children?: ReactNode; bare?: boolean }) {
  const s = useAppState();
  return (
    <a className="objlink" href={`#${routeOf(to)}`}>
      {!bare && <span className="kind">{KIND_LABELS[to.kind]}</span>}
      <span>{children ?? objectLabel(s, to)}</span>
    </a>
  );
}

export function Freshness({ result }: { result: Result }) {
  const s = useAppState();
  const f = resultFreshness(s, result);
  return <StatusBadge kind="freshness" state={f.state} title={f.reasons.join(' ') || 'Les entrées utilisées sont toujours celles en vigueur.'} />;
}

/* ------------------------------------------------------------------ command buttons */

interface CmdButtonProps<P> {
  def: CommandDef<P, unknown>; payload: P; children: ReactNode; variant?: 'primary' | 'danger' | 'ai' | 'ghost'; size?: 'small';
  icon?: Parameters<typeof Button>[0]['icon']; success?: string | ((v: unknown) => string); onDone?: (value: unknown) => void;
  confirm?: { title: string; message?: ReactNode; needsReason?: boolean; reasonKey?: keyof P; danger?: boolean; label?: string; extra?: (set: (patch: Partial<P>) => void, payload: P) => ReactNode };
  hideWhenDenied?: boolean; showReason?: boolean;
  /** opens a form instead of running the command; the button is still gated by the same check */
  onRun?: () => void;
}

/** Button bound to a domain command: enabled, disabled with its reason, or absent. */
export function CmdButton<P>({ def, payload, children, variant, size, icon, success, onDone, confirm, hideWhenDenied, showReason = true, onRun }: CmdButtonProps<P>) {
  useAppState();
  const [open, setOpen] = useState(false);
  const [extra, setExtra] = useState<Partial<P>>({});
  // A reason typed later in the dialog is simulated so that the other guards are evaluated now.
  const probe = confirm?.needsReason ? { ...payload, [confirm.reasonKey ?? 'reason']: 'motif renseigné dans la boîte de dialogue' } : payload;
  const verdict = can(def, probe as P);
  const blocked = !verdict.ok;
  if (blocked && hideWhenDenied) return null;
  const reason = blocked ? (verdict as { reason: string }).reason : undefined;
  const opId = newOpId();
  const run = (p: P) => {
    const out = dispatch(def, p, { success, opId });
    if (out.ok) onDone?.(out.value);
  };
  return (
    <span className="btn-wrap">
      <Button variant={variant} size={size} icon={icon} aria-disabled={blocked || undefined} disabled={blocked}
        title={reason} onClick={() => (onRun ? onRun() : confirm ? setOpen(true) : run(payload))}>
        {children}
      </Button>
      {blocked && showReason && <span className="why"><Icon name="lock" size={11} />{reason}</span>}
      {confirm && (
        <ConfirmDialog open={open} title={confirm.title} message={confirm.message} danger={confirm.danger} needsReason={confirm.needsReason}
          confirmLabel={confirm.label ?? (typeof children === 'string' ? children : 'Confirmer')}
          extra={confirm.extra?.((patch) => setExtra((x) => ({ ...x, ...patch })), { ...payload, ...extra })}
          onClose={() => setOpen(false)}
          onConfirm={(r) => { setOpen(false); run({ ...payload, ...extra, ...(confirm.needsReason ? { [confirm.reasonKey ?? 'reason']: r } : {}) } as P); }} />
      )}
    </span>
  );
}

/** Approver picker shown when submitting something for review. */
export function ApproverPicker({ value, onChange, exclude }: { value?: string; onChange: (id: string | undefined) => void; exclude?: string }) {
  const s = useAppState();
  const people = Object.values(s.db.member).filter((m) => m.orgId === s.session.orgId && ['owner', 'admin', 'maintainer'].includes(m.role) && m.userId !== exclude);
  return <Select label="Approbateur·rice" hint="Une personne distincte de l’auteur lorsque le profil l’exige." value={value ?? ''} onChange={(e) => onChange(e.target.value || undefined)} placeholder="Toute personne habilitée" options={[...new Set(people.map((m) => m.userId))].map((id) => ({ value: id, label: `${s.users[id]?.name} (${people.filter((m) => m.userId === id).map((m) => ROLES[m.role].short).join(', ')})` }))} />;
}

/** A person's decision as OpenGuildKit records it, in their own terminal; the demo then simulates its entry. */
export function TerminalDecision({ command, note }: TerminalCommand) {
  return (
    <div className="stack tight">
      <p>Dans OpenGuildKit, une personne enregistre cette décision dans son propre terminal : la page ne l’enregistre jamais.</p>
      {command && <div className="command-line"><code aria-label="Commande à taper dans le terminal">{command}</code></div>}
      {note && <p className="small muted">{note}</p>}
      <p className="small muted">La démo n’a pas de terminal : « Simuler la commande » joue la personne qui la tape.</p>
    </div>
  );
}

/** Current state + every transition available from it, each guarded by the domain. */
export function Lifecycle({ kind, id, state, version, compact, exclude = [] }: { kind: TransitionKind; id: ID; state: string; version?: number; compact?: boolean; exclude?: string[] }) {
  const s = useAppState();
  const me = s.session.actor.type === 'human' ? s.session.actor.userId : undefined;
  const transitions = transitionsFrom(kind as MachineKind, state).filter((t) => !exclude.includes(t.action));
  const withApprover = ['submit', 'request'].map((a) => `${kind}.${a}`);
  const person = (me && s.users[me]?.name) || 'NOM';
  return (
    <div className="row" style={{ alignItems: 'flex-start' }}>
      {!compact && <StatusBadge kind={kind as MachineKind} state={state} />}
      {transitions.map((t) => (
        <CmdButton key={t.action} def={cmd.transition} payload={{ kind, id, action: t.action, version }} size="small" variant={t.danger ? 'danger' : t.action === 'approve' || t.action === 'publish' || t.action === 'close' ? 'primary' : undefined}
          success={`${t.label} : fait`}
          confirm={t.terminal ? {
            title: `${t.label} : dans le terminal`, needsReason: t.needsReason, danger: t.danger, label: 'Simuler la commande',
            message: <TerminalDecision {...terminalCommand(s, { kind: kind as RefKind, id }, t.action, person)} />,
          } : t.needsReason || withApprover.includes(`${kind}.${t.action}`) || t.danger ? {
            title: t.label, needsReason: t.needsReason, danger: t.danger, label: t.label,
            message: <p>{t.needsReason ? 'Cette action modifie le suivi : indiquez son motif.' : 'Confirmez cette action.'}</p>,
            extra: withApprover.includes(`${kind}.${t.action}`) ? (set, p) => <ApproverPicker value={(p as { approverId?: string }).approverId} exclude={me} onChange={(v) => set({ approverId: v } as never)} /> : undefined,
          } : undefined}>
          {t.label}
        </CmdButton>
      ))}
    </div>
  );
}

export function ApprovalList({ subject }: { subject: Ref }) {
  const s = useAppState();
  const list = Object.values(s.db.approval).filter((a) => a.orgId === s.session.orgId && a.subject.kind === subject.kind && a.subject.id === subject.id).sort((a, b) => b.createdAt - a.createdAt);
  if (!list.length) return <p className="small muted">Aucune demande de validation.</p>;
  return (
    <ul className="plain stack tight">
      {list.map((a) => {
        const st = effectiveApprovalStatus(s, a);
        const validity = approvalValidity(s, a);
        return (
          <li key={a.id} className="card" style={{ margin: 3 }}>
            <div className="row between">
              <div className="row"><StatusBadge kind="approval" state={st} /><span className="small">{a.purpose} · <Version n={a.subject.version} label="rév. " /></span></div>
              <span className="tiny muted">{fmtDate(a.createdAt, true)}</span>
            </div>
            <div className="row small" style={{ marginTop: 6 }}>
              <span className="muted">Demandée par</span><Person id={a.authorId} />
              <span className="muted">· approbateur</span>{a.approverId ? <Person id={a.approverId} /> : <span>toute personne habilitée</span>}
              {a.requireDistinct && <Badge tone="info" icon="shield">Deux identités requises</Badge>}
            </div>
            {a.decidedBy && <p className="small" style={{ margin: '6px 0 0' }}>Décidée par <Person id={a.decidedBy} /> le {fmtDate(a.decidedAt, true)}{a.reason ? ` — ${a.reason}` : ''}</p>}
            {st === 'approved' && !validity.valid && <p className="small" style={{ color: 'var(--warning)', margin: '6px 0 0' }}><Icon name="warn" size={12} /> {validity.reason}</p>}
            {st === 'expected' && <div style={{ marginTop: 6 }}><Lifecycle kind="approval" id={a.id} state={st} compact /></div>}
          </li>
        );
      })}
    </ul>
  );
}

