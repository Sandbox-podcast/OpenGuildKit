/**
 * Demo watch feed. Every company and signal is fictional and labelled as such.
 * "Lancer une collecte" returns the next prepared signals; the feed never invents others.
 */
import type { Signal } from '@/demo/domain/types';

export type SignalTemplate = Omit<
  Signal,
  'id' | 'orgId' | 'sourceId' | 'competitorId' | 'publishedAt' | 'consultedAt' | 'notes' | 'favorite' | 'fictional' | 'projectIds'
> & {
  competitor?: string;
  source: string;
  daysAgo: number;
  projects: string[];
};

export const WATCH_FEED: SignalTemplate[] = [
  {
    competitor: 'Helio CRM',
    source: 'Blog produit Helio (fictif)',
    daysAgo: 1,
    type: 'fonctionnalité',
    title: 'Helio CRM (fictif) ajoute des rapports planifiés',
    context: 'Billet de blog fictif décrivant des rapports envoyés chaque semaine par courriel.',
    facts: ['Le billet annonce des rapports planifiés hebdomadaires.'],
    interpretations: ['Le concurrent fictif investit dans l’automatisation des exports.'],
    hypotheses: ['Une demande d’export récurrent pourrait émerger chez nos clients.'],
    recommendations: ['Réévaluer la ligne « Export planifié récurrent » de la roadmap.'],
    relevance: { level: 'moyenne', reasons: ['Touche le même besoin que l’export', 'Aucun client du scénario ne l’a demandé'] },
    projects: ['prj-export'],
  },
  {
    source: 'Veille réglementaire (fictive)',
    daysAgo: 2,
    type: 'écosystème',
    title: 'Nouvelle version d’une bibliothèque CSV (fictive) annoncée',
    context: 'Note de version fictive de csv-forge 2.4.0, qui corrige l’injection de formules.',
    facts: ['csv-forge 2.4.0 échappe les cellules commençant par =, +, -, @.'],
    interpretations: ['La dépendance de l’export peut être mise à jour.'],
    hypotheses: [],
    recommendations: ['Rattacher ce signal à la quête de correction de la vulnérabilité simulée.'],
    relevance: { level: 'forte', reasons: ['Dépendance utilisée par l’export'] },
    projects: ['prj-export'],
  },
];
