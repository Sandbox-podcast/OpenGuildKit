import { describe, expect, it } from 'vitest';
import { MACHINES, type TransitionDef } from '@/domain/machines';
import { terminalCommand } from '@/domain/terminal';
import { nova } from './helpers';

describe('decisions recorded at a terminal', () => {
  const s = nova();

  it('marks every approval and refusal of a person as a terminal decision', () => {
    const decisions = Object.entries(MACHINES).flatMap(([kind, m]) => (m.transitions as readonly TransitionDef[])
      .filter((t) => ['approve', 'refuse', 'requestChanges', 'requestRevision'].includes(t.action))
      .map((t) => `${kind}.${t.action}:${t.terminal === true}`));
    expect(decisions.length).toBeGreaterThan(6);
    expect(decisions.filter((d) => d.endsWith(':false'))).toEqual([]);
  });

  it('approves the task of a quest closure with task decide, in the name of the person', () => {
    expect(terminalCommand(s, { kind: 'approval', id: 'apr-close-portal' }, 'approve', 'Inès Morel'))
      .toEqual({ command: "openguildkit task decide qst-portal --approve --by 'Inès Morel' --reason '…'", note: undefined });
  });

  it('sends a decision back with --request-changes, on the task of its council', () => {
    const out = terminalCommand(s, { kind: 'decision', id: 'dec-audit' }, 'refuse', "Jeanne d'Arc");
    expect(out.command).toBe("openguildkit task decide cns-audit --request-changes --by 'Jeanne d'\\''Arc' --reason '…'");
  });

  it('says that approving a deliverable version is the demo’s own', () => {
    const out = terminalCommand(s, { kind: 'approval', id: 'apr-p-roadmap' }, 'approve', 'Yanis Belkacem');
    expect(out.command).toMatch(/^openguildkit task decide \S+ --approve/);
    expect(out.note).toMatch(/propre à la démo/);
  });

  it('waives a rule with task waive, and refuses a waiver without any command', () => {
    expect(terminalCommand(s, { kind: 'exception', id: 'exc-billing-draft' }, 'approve', 'Inès Morel').command)
      .toMatch(/^openguildkit task waive prj-billing \S+ --by 'Inès Morel' --reason/);
    const refused = terminalCommand(s, { kind: 'exception', id: 'exc-billing-draft' }, 'refuse', 'Inès Morel');
    expect(refused.command).toBeUndefined();
    expect(refused.note).toMatch(/aucune commande/);
  });

  it('keeps the instructions of a brain as a demo approval, without a command', () => {
    const out = terminalCommand(s, { kind: 'approval', id: 'apr-instr' }, 'approve', 'Inès Morel');
    expect(out.command).toBeUndefined();
    expect(out.note).toMatch(/pull request/);
  });
});
