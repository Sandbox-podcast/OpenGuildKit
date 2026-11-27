// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest';
import { Decide } from '@/project/views/Council';
import type { TaskRecord } from '@/project/types';
import { button, cleanup, click, fakeApi, field, mount, type, wait } from './harness';

afterEach(cleanup);

const task = (id: string) => ({ id, status: 'reviewed', brief: 'Dark theme', rounds: [] }) as unknown as TaskRecord;
const profile = (approval?: unknown) => ({
  '.openguildkit/project.json': JSON.stringify({ name: 'Portail support', boards: [], approval }),
});
const blocker = { id: 'b1', board: 'security', point: 'Keep emails out of the logs', phase: 'before-approval', resolution: null };
const commands = { 'task blockers': [], 'task decide': { decided: true } };
const approvalCommand = (container: HTMLElement) => container.querySelector('[aria-label="Commande d’approbation"]')!.textContent!;

describe('decision of a reviewed task', () => {
  it('shows the command a person types to approve, and fills it with what they enter', async () => {
    await fakeApi(commands, profile());
    const { container } = await mount(<Decide task={task('dark-theme')} />);
    await wait();
    expect(approvalCommand(container)).toContain("task decide dark-theme --approve --by TES_INITIALES --reason 'Motif de la décision'");
    await type(field(container, 'Personne qui décide'), 'CM');
    await type(field(container, 'Motif'), 'No customer email before the release note');
    expect(approvalCommand(container)).toContain("--by CM --reason 'No customer email before the release note'");
  });

  it('never approves from the page: it only sends the task back to the Council, with who and why', async () => {
    const api = await fakeApi(commands, profile());
    const { container } = await mount(<Decide task={task('dark-theme')} />);
    await wait();
    const send = button(container, 'Demander des changements');
    expect(send.disabled).toBe(true);
    await type(field(container, 'Personne qui décide'), 'Camille Martin');
    expect(send.disabled).toBe(true);
    await type(field(container, 'Motif'), 'Agree on the CSV columns with support first');
    expect(send.disabled).toBe(false);
    await click(send);
    expect(api.sent('task decide')).toEqual([
      'task decide dark-theme --request-changes --by Camille Martin --reason Agree on the CSV columns with support first',
    ]);
    expect(api.commands.some((line) => line.includes('--approve'))).toBe(false);
  });

  it('counts the open blockers, which hold the approval back, and shows the signature steps of a signed project', async () => {
    await fakeApi(
      { ...commands, 'task blockers': [blocker, { ...blocker, id: 'b2', resolution: { by: 'CM' } }] },
      profile({ mode: 'signed' }),
    );
    const { container } = await mount(<Decide task={task('blocked')} />);
    await wait();
    expect(container.textContent).toContain('1 point(s) bloquant(s) ouvert(s).');
    expect(container.textContent).toContain('Projet à approbation signée');
    expect(container.textContent).toContain('ssh-keygen -Y sign');
  });
});
