import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { PLACES } from '@/shared/places';
import { GLOSSARY_TERMS, WORDS } from '@/project/words';
import { TASK_STATUS } from '@/project/labels';

const glossary = readFileSync(new URL('../../../docs/glossary.md', import.meta.url), 'utf-8');
const plain = (text: string) => text.replace(/[’']/g, '\'').trim().toLowerCase();
/** The French gloss of each entry: "### `task` · tâche". */
const gloss = Object.fromEntries([...glossary.matchAll(/^### `([^`]+)` · (.+)$/gm)].map((m) => [m[1], plain(m[2])]));
/** The rows of a table of the glossary's web interface section, by their first column. */
function rows(header: string) {
  const start = glossary.indexOf(header);
  expect(start).toBeGreaterThan(-1);
  const lines = glossary.slice(start).split('\n').slice(2);
  return lines.filter((line) => line.startsWith('| ')).map((line) => line.split('|').slice(1, -1).map((cell) => cell.trim()));
}

describe('words of the Pro style', () => {
  it('are the glossary terms', () => {
    for (const [term, word] of Object.entries(GLOSSARY_TERMS)) expect([term, gloss[term]]).toEqual([term, plain(word)]);
    expect(WORDS.focus.task).toBe(GLOSSARY_TERMS.task);
    expect(WORDS.focus.lens).toBe(GLOSSARY_TERMS.lens);
    expect(TASK_STATUS.approved.label.toLowerCase()).toBe('approuvée');
  });

  it('match the glossary table of RPG words and places', () => {
    const words = rows('| RPG | CLI | Pro |');
    expect(words).toContainEqual([WORDS.explorer.task, '`task`', WORDS.focus.task]);
    expect(words).toContainEqual([WORDS.explorer.lens, '`lens`', WORDS.focus.lens]);
    const places = rows('| Lieu RPG | Pro | CLI |').slice(0, PLACES.length);
    expect(places.map(([rpg, pro]) => [rpg, pro])).toEqual(PLACES.map((p) => [p.name, p.proName]));
  });
});
