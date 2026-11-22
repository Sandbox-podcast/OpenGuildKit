/** The setup answers the page sends to `init`: the norms a person accepts or declines, and what is still missing. */
import type { Question } from './types';

/** One norm as the page keeps it while the person answers: yes, or no with who and why. */
export interface NormDraft { answer: 'yes' | 'no'; by?: string; reason?: string }
export type NormAnswer = 'yes' | { answer: 'no'; by: string; reason: string };

const complete = (draft: NormDraft) => draft.answer === 'yes' || (!!draft.by?.trim() && !!draft.reason?.trim());

/** The norms answers `init` takes: "yes", or a no with who and why. A no without both is not sent yet. */
export function normAnswers(drafts: Record<string, NormDraft>): Record<string, NormAnswer> {
  const out: Record<string, NormAnswer> = {};
  for (const [id, draft] of Object.entries(drafts)) {
    if (!complete(draft)) continue;
    out[id] = draft.answer === 'yes' ? 'yes' : { answer: 'no', by: draft.by!.trim(), reason: draft.reason!.trim() };
  }
  return out;
}

/** The proposed norms without a complete answer: `init` refuses to write the profile while one is left. */
export const pendingNorms = (proposed: string[], drafts: Record<string, NormDraft>) => proposed.filter((id) => !drafts[id] || !complete(drafts[id]));

/** Required questions (the CLI marks them `required`) the person has not answered. */
export const missingRequired = (questions: (Question & { required?: boolean })[], answers: Record<string, unknown>) =>
  questions.filter((q) => q.required && (answers[q.id] === undefined || answers[q.id] === '')).map((q) => q.id);

/** The answers sent to `init` and `preview`: the questions answered, and the norms once one is answered. */
export function setupAnswers(answers: Record<string, unknown>, drafts: Record<string, NormDraft>) {
  const norms = normAnswers(drafts);
  return Object.keys(norms).length ? { ...answers, norms } : { ...answers };
}
