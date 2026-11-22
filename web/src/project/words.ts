/**
 * The words of the two styles. Pro speaks the glossary (docs/glossary.md): tâche, angle de spécialiste, point
 * bloquant, garde-fou, approbation, brief d'implémentation, modèle de projet. RPG keeps its game words for a task
 * and a lens (quête, lentille), and the places keep their names; the glossary explains each one.
 */
import { usePrefs } from './prefs';

export const GLOSSARY_TERMS = {
  task: 'tâche', lens: 'angle de spécialiste', blocker: 'point bloquant', guard: 'garde-fou', approval: 'approbation',
  handoff: 'brief d’implémentation', pattern: 'modèle de projet', brain: 'cerveau métier', board: 'comité métier',
} as const;

export const WORDS = {
  focus: { task: 'tâche', tasks: 'tâches', Task: 'Tâche', Tasks: 'Tâches', lenses: 'angles de spécialiste', Lenses: 'Angles de spécialiste', lens: 'angle de spécialiste' },
  explorer: { task: 'quête', tasks: 'quêtes', Task: 'Quête', Tasks: 'Quêtes', lenses: 'lentilles', Lenses: 'Lentilles', lens: 'lentille' },
} as const;

/** The words of the style the person chose. */
export const useWords = () => WORDS[usePrefs().mode];
