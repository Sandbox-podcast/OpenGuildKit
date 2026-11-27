// @vitest-environment happy-dom
import { act } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import type { CliResult } from '@/project/api';
import { CheckNotice, ErrorNotice, StepRail, TerminalDialog } from '@/project/parts';
import { ApiError } from '@/project/api';
import { showTerminal } from '@/project/query';
import type { TaskListItem } from '@/project/types';
import { cleanup, mount } from './harness';

afterEach(cleanup);

const result = (code: number, stdout: string, stderr = ''): CliResult => ({ code, stdout, stderr, json: null });
const task = (id: string, status: string, severity?: string) => ({ id, status, severity, next: '', brief: '' }) as unknown as TaskListItem;

describe('what a place says about the checks', () => {
  it('says the instructions match the profile, in the success case', async () => {
    const { container } = await mount(<CheckNotice result={result(0, '')} tasks={[]} />);
    expect(container.textContent).toContain('Les instructions correspondent au profil du projet.');
  });

  it('names the tasks that only a person can repair when the instructions are in line', async () => {
    const failing = result(1, '', 'OpenGuildKit: the instructions match the project profile; 2 tasks fail.');
    const { container } = await mount(
      <CheckNotice result={failing} tasks={[task('a', 'unreadable'), task('b', 'approved', 'error'), task('c', 'draft')]} />,
    );
    expect(container.textContent).toContain('des tâches sont à reprendre par une personne');
    expect([...container.querySelectorAll('li a')].map((a) => a.getAttribute('href'))).toEqual(['#/quetes/a', '#/conseil/b']);
    expect(container.textContent).toContain('fichier illisible, à réparer');
    expect(container.textContent).toContain('Synchroniser ne change rien à ces tâches.');
  });

  it('says openguildkit is off the PATH, which neither sync nor the host settings fix', async () => {
    const off = result(1, '', "OpenGuildKit: openguildkit is not on this workstation's PATH, so the hooks cannot run it.");
    const { container } = await mount(<CheckNotice result={off} tasks={[]} />);
    expect(container.textContent).toContain('openguildkit n’est pas sur le PATH de ce poste');
    expect(container.textContent).toContain('pipx install');
  });
});

describe('steps of a task', () => {
  it('marks the steps done, the current one and the ones to come', async () => {
    const { container } = await mount(<StepRail status="reviewed" hasResult={false} />);
    const items = [...container.querySelectorAll('li')];
    expect(items).toHaveLength(6);
    const states = items.map((li) => (li.className.match(/\b(done|current|todo)\b/) ?? [])[1]);
    expect(states).toEqual(['done', 'done', 'done', 'current', 'todo', 'todo']);
    expect(items.filter((li) => li.getAttribute('aria-current') === 'step')).toHaveLength(1);
  });
});

describe('refusals', () => {
  it('shows the failure of a command, with the words of the server behind it', async () => {
    const { container } = await mount(
      <ErrorNotice error={new ApiError('A task needs a brief.', 200, { lang: 'en' })} title="Ouverture refusée" />,
    );
    expect(container.textContent).toContain('Ouverture refusée');
    expect(container.querySelector('[lang="en"]')!.textContent).toContain('A task needs a brief.');
  });

  it('hands a decision reserved to a person to the terminal, with the command to type', async () => {
    const { container } = await mount(<TerminalDialog />);
    expect(container.querySelector('dialog')!.textContent).toBe('');
    await act(async () => {
      showTerminal({
        title: 'À faire dans ton terminal',
        why: 'Seule une personne approuve.',
        command: 'openguildkit task decide x --approve',
      });
    });
    const dialog = container.querySelector('dialog')!;
    expect(dialog.textContent).toContain('À faire dans ton terminal');
    expect(dialog.querySelector('[aria-label="Commande"]')!.textContent).toBe('openguildkit task decide x --approve');
    await act(async () => {
      showTerminal(null);
    });
    expect(dialog.textContent).toBe('');
  });
});
