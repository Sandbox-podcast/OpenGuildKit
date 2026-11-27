// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Routing } from '@/project/views/Council';
import type { TaskRecord } from '@/project/types';
import { button, cleanup, click, fakeApi, field, mount, type, wait } from './harness';

afterEach(cleanup);

const task = (id: string) => ({ id, status: 'draft', brief: 'Send a survey when a request closes.', rounds: [] }) as unknown as TaskRecord;
const answers = { kind: 'feature', surface: ['web'], data: 'none' };
const route = { routing: { security: ['handles personal data'], qa: ['a feature'] }, excluded: {}, expected_not_selected: {}, not_selected: ['privacy'], adjustments: [] };
const commands = {
  'brains --json': { security: { id: 'security', title: 'Security', description: '' }, qa: { id: 'qa', title: 'Quality', description: '' }, privacy: { id: 'privacy', title: 'Privacy', description: '' } },
  'task route': route,
  'task consult': { consultation_id: 'c1' },
};
const files = { '.openguildkit/project.json': JSON.stringify({ name: 'Portail support', boards: ['security', 'qa', 'privacy'], required_boards: [] }) };
const REASON = 'La sécurité doit relire ce flux de mails';

describe('Routing', () => {
  /** Issue #467: one `task route` per character typed in the reason, and the grid of brains blinked. */
  it('asks for one routing while a reason is typed, and keeps the brains on screen', async () => {
    vi.useFakeTimers();
    const api = await fakeApi(commands, files);
    const { container } = await mount(<Routing task={task('typed')} answers={answers} />);
    await wait(10);
    expect(container.querySelectorAll('.board-grid li')).toHaveLength(2);
    const asked = api.sent('task route').length;

    const grids: number[] = [];
    new MutationObserver(() => grids.push(container.querySelectorAll('.board-grid').length)).observe(container, { childList: true, subtree: true });
    expect(REASON).toHaveLength(40);
    for (let i = 1; i <= REASON.length; i++) {
      await type(field(container, 'Motif de l’ajustement'), REASON.slice(0, i));
      await wait(40);
    }
    expect(api.sent('task route').length - asked).toBe(0);
    await wait(600);

    expect(api.sent('task route').length - asked).toBe(1);
    expect(api.sent('task route').at(-1)).toContain(`--reason ${REASON}`);
    expect(grids).not.toContain(0);
    expect(container.querySelectorAll('.board-grid li')).toHaveLength(2);
  });

  it('sends the reason as typed when the person consults at once, without waiting for the pause', async () => {
    vi.useFakeTimers();
    const api = await fakeApi(commands, files);
    const { container } = await mount(<Routing task={task('consult')} answers={answers} />);
    await wait(10);
    await type(field(container, 'Motif de l’ajustement'), 'Needs a second look');
    await click(button(container, 'Réunir le Conseil'));
    expect(api.sent('task consult').at(-1)).toContain('--reason Needs a second look');
  });

  it('asks again at once when a brain is removed, and says a reason is needed', async () => {
    vi.useFakeTimers();
    const api = await fakeApi(commands, files);
    const { container } = await mount(<Routing task={task('removed')} answers={answers} />);
    await wait(10);
    const asked = api.sent('task route').length;
    await click(button(container, 'Retirer'));
    await wait(10);
    expect(api.sent('task route').length - asked).toBe(1);
    expect(api.sent('task route').at(-1)).toMatch(/--remove (security|qa)/);
    expect(container.textContent).toContain('Un ajout ou un retrait a besoin d’un motif.');
    expect(button(container, 'Réunir le Conseil').disabled).toBe(true);
  });
});
