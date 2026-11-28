/**
 * The command a person types in their own terminal to record a decision in OpenGuildKit. The product never
 * records an approval from a page: the demo shows this command, then simulates its entry, so that it teaches
 * the product's path. Objects the CLI does not have (deliverable versions, Blueprint versions, roles) keep
 * their demo approval, with a note saying so.
 */
import type { AppState, ID, Ref } from './types';

export interface TerminalCommand {
  /** What to type, or nothing when no command records this decision (refusing a waiver is not waiving). */
  command?: string;
  /** How this demo decision differs from the product. */
  note?: string;
}

/** The actions that only a person records, at a terminal (machines.ts marks them `terminal`). */
const APPROVE = new Set(['approve']);

const quote = (text: string) => `'${text.replace(/'/g, `'\\''`)}'`;

const DELIVERABLE_NOTE = 'OpenGuildKit approuve la tâche, pas chaque version de livrable : cette validation est propre à la démo.';
const BLUEPRINT_NOTE =
  'Le Blueprint de la démo tient lieu du profil du projet, qui se change avec openguildkit profile (--by, --reason) : sa validation par version est propre à la démo.';
const EXPERT_NOTE =
  'Les consignes d’un cerveau sont un fichier du catalogue du projet, relu dans une pull request : cette validation est propre à la démo.';

/** The task the CLI decides on for a demo object, and what the demo adds to the product. */
function taskOf(s: AppState, ref: Ref): { task?: ID; note?: string } {
  switch (ref.kind) {
    case 'approval': {
      const approval = s.db.approval[ref.id];
      return approval ? taskOf(s, approval.subject) : {};
    }
    case 'decision':
      return { task: s.db.decision[ref.id]?.councilId ?? ref.id };
    case 'quest':
      return { task: ref.id };
    case 'deliverable':
      return { task: s.db.deliverable[ref.id]?.questId ?? ref.id, note: DELIVERABLE_NOTE };
    case 'blueprint':
      return { note: BLUEPRINT_NOTE };
    case 'expert':
      return { note: EXPERT_NOTE };
    default:
      return {};
  }
}

/** The terminal command of a person's decision on a demo object: approve, or send back with --request-changes. */
export function terminalCommand(s: AppState, ref: Ref, action: string, by: string): TerminalCommand {
  const person = quote(by);
  if (ref.kind === 'exception') {
    const exception = s.db.exception[ref.id];
    const task = (exception?.subject && s.db.deliverable[exception.subject.deliverableId]?.questId) ?? exception?.projectId ?? ref.id;
    const rule = (exception && s.db.rule[exception.ruleId]?.code) ?? 'REGLE';
    if (!APPROVE.has(action))
      return { note: 'Refuser une dérogation ne demande aucune commande : sans task waive, le point reste bloquant.' };
    return { command: `openguildkit task waive ${task} ${rule} --by ${person} --reason '…' --scope '…' --until AAAA-MM-JJ` };
  }
  const { task, note } = taskOf(s, ref);
  if (!task) return { note };
  const outcome = APPROVE.has(action) ? '--approve' : '--request-changes';
  return { command: `openguildkit task decide ${task} ${outcome} --by ${person} --reason '…'`, note };
}
