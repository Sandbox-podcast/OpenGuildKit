// @vitest-environment happy-dom
import { act } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectSearch } from '@/project/ProjectSearch';
import { cleanup, fakeApi, field, mount, type, wait } from './harness';

afterEach(cleanup);

const commands = {
  // The overview the shell reads in one batch.
  'task list': [{ id: 'closing-survey', status: 'draft', brief: 'Send a survey when a request closes', next: '' }],
  check: 'ok',
  'alerts list': { summary: { total: 0, by_status: {}, by_severity: {}, imports: [] }, alerts: [] },
  'docs share list': [],
  'market due': { due: [] },
  update: { changes: [], conflicts: [], applied: false, stale_tasks: [] },
  'host check': [],
  'brains --json': {
    security: { id: 'security', title: 'Security', description: 'Threats, secrets and access' },
    qa: { id: 'qa', title: 'Quality', description: 'Tests and acceptance' },
  },
  'references --json': [
    {
      id: 'owasp-top-10',
      title: 'OWASP Top 10',
      summary: 'Web application risks',
      aliases: [],
      category: 'security',
      kind: 'list',
      status: 'current',
      family: 'owasp',
      family_title: 'OWASP',
      applies_when: '',
      sources: [],
    },
  ],
  'patterns --json': [],
};
const hits = (container: HTMLElement) => [...container.querySelectorAll('.palette-hit')].map((a) => a.textContent ?? '');
const press = (element: HTMLElement, key: string) =>
  act(async () => {
    element.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });

describe('search of the project', () => {
  /** Issue #469: `brains --json` (146 KB) loaded on every screen for a search that was closed. */
  it('reads no catalog while it is closed, nor before two letters are typed', async () => {
    const api = await fakeApi(commands);
    const closed = await mount(<ProjectSearch open={false} onClose={() => {}} />);
    await wait();
    expect(api.sent('brains')).toEqual([]);
    await closed.unmount();

    const { container } = await mount(<ProjectSearch open onClose={() => {}} />);
    await wait();
    await type(field(container, 'Rechercher'), 's');
    await wait();
    expect([api.sent('brains'), api.sent('references'), api.sent('patterns')]).toEqual([[], [], []]);
    await type(field(container, 'Rechercher'), 'se');
    await wait();
    expect([api.sent('brains').length, api.sent('references').length, api.sent('patterns').length]).toEqual([1, 1, 1]);
    expect(api.sent('brains')[0]).toBe('brains --json');
  });

  it('finds a place, a task, a brain and a reference, and says how many it found', async () => {
    await fakeApi(commands);
    const { container } = await mount(<ProjectSearch open onClose={() => {}} />);
    await wait();
    expect(hits(container).filter((text) => text.endsWith('Lieu'))).toHaveLength(13);
    await type(field(container, 'Rechercher'), 'security');
    await wait();
    const found = hits(container);
    expect(found.some((text) => text.endsWith('Cerveau'))).toBe(true);
    expect(container.querySelector('[role="status"]')!.textContent).toBe(`${found.length} résultat${found.length > 1 ? 's' : ''}`);
    await type(field(container, 'Rechercher'), 'owasp');
    await wait();
    expect(hits(container)).toEqual([expect.stringMatching(/OWASP Top 10.*Référence$/)]);
    await type(field(container, 'Rechercher'), 'closing-survey');
    await wait();
    expect(hits(container)).toEqual([expect.stringMatching(/closing-survey.*Tâche$/)]);
    await type(field(container, 'Rechercher'), 'nothing like this');
    await wait();
    expect(container.textContent).toContain('Aucun résultat.');
  });

  it('opens the first result on Enter, and closes', async () => {
    await fakeApi(commands);
    const onClose = vi.fn();
    const { container } = await mount(<ProjectSearch open onClose={onClose} />);
    await wait();
    await type(field(container, 'Rechercher'), 'closing-survey');
    await wait();
    await press(field(container, 'Rechercher'), 'Enter');
    expect(window.location.hash).toBe('#/quetes/closing-survey');
    expect(onClose).toHaveBeenCalledOnce();
  });
});
