/**
 * Demo repository analysis. Only the identified demo repositories return observations;
 * any other address returns an explicit "no analysis performed" result (brief §2).
 */
import type { RepoObservation } from '@/domain/types';

export interface RepoScenario { key: string; label: string; address: string; description: string; observations: Omit<RepoObservation, 'id'>[] }

export const REPO_SCENARIOS: RepoScenario[] = [
  {
    key: 'crm-api', label: 'API d’un CRM multi-clients (TypeScript)', address: 'demo://depots/crm-api',
    description: 'Service Node.js avec PostgreSQL, partitionné par client.',
    observations: [
      { topic: 'langages', label: 'Langage principal', value: 'TypeScript (82 %), SQL (11 %)', provenance: 'observed' },
      { topic: 'dépendances', label: 'Framework HTTP', value: 'fastify 5', provenance: 'observed' },
      { topic: 'dépendances', label: 'Base de données', value: 'PostgreSQL (client pg)', provenance: 'observed' },
      { topic: 'tests', label: 'Tests', value: 'Vitest, 214 cas ; aucun test multi-clients', provenance: 'observed' },
      { topic: 'documentation', label: 'Documentation', value: 'README et OpenAPI partielle', provenance: 'observed' },
      { topic: 'structure', label: 'Architecture', value: 'Monolithe modulaire (modules contacts, comptes, activités)', provenance: 'inferred' },
      { topic: 'configuration', label: 'Multi-clients', value: 'Colonne tenant_id sur les tables métier', provenance: 'inferred' },
      { topic: 'configuration', label: 'Données personnelles', value: 'Probables (champs email, phone)', provenance: 'inferred' },
    ],
  },
  {
    key: 'billing', label: 'Service de facturation (Python)', address: 'demo://depots/billing',
    description: 'API FastAPI et tâches planifiées.',
    observations: [
      { topic: 'langages', label: 'Langage principal', value: 'Python 3.12', provenance: 'observed' },
      { topic: 'dépendances', label: 'Framework', value: 'FastAPI, SQLAlchemy', provenance: 'observed' },
      { topic: 'tests', label: 'Tests', value: 'pytest, couverture non mesurée', provenance: 'observed' },
      { topic: 'documentation', label: 'Documentation', value: 'Aucun guide utilisateur', provenance: 'observed' },
      { topic: 'structure', label: 'Architecture', value: 'Service unique avec workers', provenance: 'inferred' },
      { topic: 'configuration', label: 'Données de paiement', value: 'Référencées par un prestataire externe (probable)', provenance: 'inferred' },
    ],
  },
  {
    key: 'portal', label: 'Portail client (React)', address: 'demo://depots/portal',
    description: 'Application web consommant une API.',
    observations: [
      { topic: 'langages', label: 'Langage principal', value: 'TypeScript, React 19', provenance: 'observed' },
      { topic: 'dépendances', label: 'Build', value: 'Vite', provenance: 'observed' },
      { topic: 'tests', label: 'Tests', value: 'Playwright, 18 parcours', provenance: 'observed' },
      { topic: 'documentation', label: 'Documentation', value: 'Storybook partiel', provenance: 'observed' },
      { topic: 'structure', label: 'Architecture', value: 'Application monopage', provenance: 'inferred' },
      { topic: 'configuration', label: 'Accessibilité', value: 'Aucun contrôle automatisé détecté', provenance: 'inferred' },
    ],
  },
];

export function analyzeRepository(address: string): { scenario: string | null; observations: Omit<RepoObservation, 'id'>[]; message: string } {
  const s = REPO_SCENARIOS.find((r) => r.address === address.trim() || r.key === address.trim());
  if (!s) {
    return {
      scenario: null,
      observations: [],
      message: `Aucun dépôt de démonstration ne correspond à « ${address.trim() || '(vide)'} ». Aucune analyse n’a été effectuée : choisissez un dépôt de démonstration ou renseignez les informations à la main.`,
    };
  }
  return { scenario: s.key, observations: s.observations, message: `Analyse simulée du dépôt de démonstration « ${s.label} ». Les observations sont modifiables.` };
}
