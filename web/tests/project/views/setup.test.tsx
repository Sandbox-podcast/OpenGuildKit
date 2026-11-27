// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Setup } from '@/project/views/Blueprint';
import { button, cleanup, click, fakeApi, field, mount, type, wait } from './harness';

afterEach(cleanup);

const questions = [
  { id: 'name', prompt: 'Project name', type: 'text', required: true },
  {
    id: 'stack',
    prompt: 'Stack',
    type: 'multi-select',
    choices: [
      { id: 'react', label: 'React' },
      { id: 'node', label: 'Node.js' },
    ],
  },
];
const plan = {
  packs: [{ id: 'core', title: 'Core rules', version: '1.2.0', provenance: ['OpenGuildKit'], scope: {}, rules: ['a', 'b', 'c'] }],
  excluded: [],
  conflicts: [],
  conventions: ['Small commits'],
  checks: ['npm test'],
};
const uploaded: string[] = [];
const commands = {
  'init --questions': questions,
  recommend: { matched: [] },
  preview: (_argv: string[], uploads: Record<string, string>) => {
    uploaded.push(uploads['profile.json']);
    return plan;
  },
  'init --answers': { initialized: true },
};

describe('installation of the guild in a project without a profile', () => {
  it('asks for the name first, and shows no plan before it', async () => {
    const api = await fakeApi(commands);
    const { container } = await mount(<Setup />);
    await wait();
    expect(container.textContent).toContain('Installer la guilde dans Portail support');
    expect(container.textContent).toContain('Donne un nom au projet pour voir le plan.');
    expect(button(container, 'Installer la guilde').disabled).toBe(true);
    expect(container.textContent).toContain('Question obligatoire sans réponse');
    expect(api.sent('preview')).toEqual([]);
  });

  it('previews the rules once typing pauses, then installs with the answers', async () => {
    vi.useFakeTimers();
    const api = await fakeApi(commands);
    const { container } = await mount(<Setup />);
    await wait();
    uploaded.length = 0;
    for (const text of ['P', 'Po', 'Por', 'Port', 'Portail']) {
      await type(field(container, /Nom du projet/), text);
      await wait(50);
    }
    // Nothing is asked for a name still being typed; the install waits for the plan of the answers as they stand.
    const names = () => uploaded.map((upload) => JSON.parse(upload).name).filter(Boolean);
    expect(names()).toEqual([]);
    expect(button(container, 'Installer la guilde').disabled).toBe(true);
    await wait(500);
    expect(names()).toEqual(['Portail']);
    expect(container.textContent).toContain('Core rules');
    expect(container.textContent).toContain('3 règle(s)');
    expect(button(container, 'Installer la guilde').disabled).toBe(false);

    await click(button(container, 'Installer la guilde'));
    expect(api.sent('init --answers')).toEqual(['init --answers @upload:profile.json']);
  });

  it('keeps the install button off while the answers have changed since the plan', async () => {
    vi.useFakeTimers();
    await fakeApi(commands);
    const { container } = await mount(<Setup />);
    await wait();
    await type(field(container, /Nom du projet/), 'Portail');
    await wait(500);
    expect(button(container, 'Installer la guilde').disabled).toBe(false);
    await type(field(container, /Nom du projet/), 'Portail support');
    expect(button(container, 'Installer la guilde').disabled).toBe(true);
    await wait(500);
    expect(button(container, 'Installer la guilde').disabled).toBe(false);
  });
});
