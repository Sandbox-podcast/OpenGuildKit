/** The task questionnaire as the page fills it: which questions need an answer, and how several choices combine. */
import type { Question } from './types';

/** "none" and "unsure" stand alone: choosing one clears the others, and choosing another clears them. */
const ALONE = new Set(['none', 'unsure']);

/** The choices of a multi-select question once the person clicks one. */
export function toggleChoice(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((x) => x !== id);
  if (ALONE.has(id)) return [id];
  return [...selected.filter((x) => !ALONE.has(x)), id];
}

/** A question with choices takes several answers when the CLI says so (type multi-select), one otherwise. */
export const isMultiple = (q: Question) => q.type === 'multi-select';

/** The questions with choices that still have no answer: the routing needs every one of them. */
export function unanswered(questions: Question[], answers: Record<string, unknown>): string[] {
  return questions.filter((q) => q.choices?.length).filter((q) => {
    const value = answers[q.id];
    return Array.isArray(value) ? value.length === 0 : !value;
  }).map((q) => q.id);
}
