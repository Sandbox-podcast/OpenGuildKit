/**
 * Onboarding questionnaire (brief §5.1) and reference suggestions.
 * Answers become Blueprint context facts: declared, or unknown when the person answers
 * "Je ne sais pas encore" — an unknown is never treated as a validation or an absence of risk.
 */
import type { ContextFact, OnboardingState, RepoObservation } from './types';

export interface Question {
  key: string;
  label: string;
  help?: string;
  type: 'text' | 'select' | 'multi';
  options?: string[];
  allowUnknown?: boolean;
  required?: boolean;
  placeholder?: string;
}
export interface Step {
  id: string;
  title: string;
  place: string;
  intro: string;
  questions: Question[];
}

export const STEPS: Step[] = [
  {
    id: 'org',
    title: 'Organisation',
    place: 'Royaume',
    intro: 'Qui êtes-vous et pour qui construisez-vous ?',
    questions: [
      { key: 'org.name', label: 'Nom de l’organisation', type: 'text', required: true, placeholder: 'Ex. Atelier Orion' },
      {
        key: 'org.activity',
        label: 'Activité',
        type: 'select',
        options: ['Éditeur SaaS B2B', 'Éditeur SaaS B2C', 'Agence ou ESN', 'Équipe produit interne', 'Projet open source'],
        required: true,
      },
      { key: 'product.name', label: 'Produit principal', type: 'text', required: true, placeholder: 'Ex. Orion Desk' },
      { key: 'users', label: 'Utilisateurs du produit', type: 'text', allowUnknown: true, placeholder: 'Ex. équipes support de PME' },
      {
        key: 'countries',
        label: 'Pays où le produit est utilisé',
        type: 'multi',
        options: ['France', 'Union européenne', 'Royaume-Uni', 'États-Unis', 'Canada', 'Autres'],
        allowUnknown: true,
      },
      {
        key: 'sectors',
        label: 'Secteurs des clients',
        type: 'multi',
        options: ['Généraliste', 'Santé', 'Finance et assurance', 'Secteur public', 'Industrie', 'Éducation'],
        allowUnknown: true,
      },
    ],
  },
  {
    id: 'team',
    title: 'Équipe',
    place: 'Guilde',
    intro: 'Qui décide, qui construit, qui valide ?',
    questions: [
      {
        key: 'team',
        label: 'Taille de l’équipe',
        type: 'select',
        options: ['1 à 5 personnes', '6 à 20 personnes', '21 à 100 personnes', 'Plus de 100 personnes'],
        allowUnknown: true,
      },
      {
        key: 'responsibilities',
        label: 'Responsabilités clés déjà attribuées',
        type: 'multi',
        options: ['Produit', 'Sécurité', 'Vie privée', 'Qualité', 'Exploitation', 'Design'],
        allowUnknown: true,
        help: 'Une responsabilité non attribuée deviendra une inconnue à traiter.',
      },
      {
        key: 'experts',
        label: 'Expertises à mobiliser',
        type: 'multi',
        options: [
          'Produit',
          'Engineering',
          'Architecture',
          'Design et accessibilité',
          'Sécurité et cyber',
          'Vie privée et exigences',
          'Qualité et tests',
          'Performance',
          'Données',
          'Plateforme et exploitation',
          'Marché et concurrence',
          'Marketing',
          'Commerce',
          'Documentation',
        ],
      },
    ],
  },
  {
    id: 'tech',
    title: 'Technique',
    place: 'Forge',
    intro: 'Comment le produit est-il construit et hébergé ?',
    questions: [
      {
        key: 'stack',
        label: 'Langages et frameworks',
        type: 'multi',
        options: ['TypeScript', 'React', 'Node.js', 'Python', 'Java', 'Go', '.NET', 'PHP', 'Kotlin', 'Swift'],
        allowUnknown: true,
      },
      {
        key: 'architecture',
        label: 'Architecture',
        type: 'select',
        options: ['Monolithe', 'Monolithe modulaire', 'Microservices', 'Serverless', 'Application mobile + API'],
        allowUnknown: true,
      },
      {
        key: 'databases',
        label: 'Bases de données',
        type: 'multi',
        options: ['PostgreSQL', 'MySQL', 'MongoDB', 'Redis', 'SQLite', 'Autre'],
        allowUnknown: true,
      },
      {
        key: 'storage',
        label: 'Stockage de fichiers',
        type: 'select',
        options: ['Stockage objet', 'Système de fichiers', 'Aucun'],
        allowUnknown: true,
      },
      {
        key: 'hosting',
        label: 'Hébergement',
        type: 'select',
        options: ['Cloud public', 'Cloud souverain', 'Sur site', 'Hybride'],
        allowUnknown: true,
      },
      {
        key: 'environments',
        label: 'Environnements',
        type: 'multi',
        options: ['Développement', 'Recette', 'Préproduction', 'Production'],
        allowUnknown: true,
      },
    ],
  },
  {
    id: 'data',
    title: 'Données et exigences',
    place: 'Tour de guet',
    intro: 'Quelles données traitez-vous et quelles exigences s’appliquent ?',
    questions: [
      {
        key: 'data.personal',
        label: 'Données personnelles',
        type: 'select',
        options: ['Oui', 'Non'],
        allowUnknown: true,
        help: 'Détermine notamment la séparation auteur-approbateur.',
      },
      {
        key: 'data.sensitive',
        label: 'Données sensibles ou réglementées',
        type: 'multi',
        options: ['Aucune', 'Santé', 'Paiement', 'Données d’enfants', 'Données judiciaires'],
        allowUnknown: true,
      },
      {
        key: 'tenancy',
        label: 'Plusieurs clients partagent-ils la même instance ?',
        type: 'select',
        options: ['Oui, multi-clients', 'Non, une instance par client'],
        allowUnknown: true,
      },
      {
        key: 'customer.requirements',
        label: 'Exigences exprimées par les clients',
        type: 'text',
        allowUnknown: true,
        placeholder: 'Ex. questionnaire sécurité, clauses contractuelles',
      },
      { key: 'risks', label: 'Risques principaux identifiés', type: 'text', allowUnknown: true },
    ],
  },
  {
    id: 'quality',
    title: 'Qualité et exploitation',
    place: 'Observatoire',
    intro: 'Quelles attentes de qualité et d’exploitation ?',
    questions: [
      {
        key: 'a11y',
        label: 'Objectif d’accessibilité',
        type: 'select',
        options: ['WCAG 2.2 niveau AA', 'RGAA', 'Pas d’objectif formalisé'],
        allowUnknown: true,
      },
      { key: 'performance', label: 'Objectif de performance', type: 'text', allowUnknown: true, placeholder: 'Ex. p95 < 500 ms sur l’API' },
      {
        key: 'operations',
        label: 'Organisation de l’exploitation',
        type: 'select',
        options: ['Astreinte interne', 'Prestataire', 'Pas encore organisée'],
        allowUnknown: true,
      },
    ],
  },
];

export const ALL_QUESTIONS = STEPS.flatMap((s) => s.questions.map((q) => ({ ...q, section: s.title })));

export function answersToFacts(o: OnboardingState): ContextFact[] {
  const facts: ContextFact[] = ALL_QUESTIONS.filter((q) => q.key !== 'experts').map((q) => {
    const a = o.answers[q.key];
    const unknown = !a || a.unknown || !a.value.trim();
    return {
      key: q.key,
      section: q.section,
      label: q.label,
      value: unknown ? '' : a.value,
      provenance: unknown ? 'unknown' : 'declared',
      source: unknown ? 'Questionnaire : « Je ne sais pas encore »' : 'Questionnaire',
    } satisfies ContextFact;
  });
  for (const ob of o.analysis?.observations ?? []) {
    if (ob.dismissed) continue;
    facts.push(observationToFact(ob));
  }
  return facts;
}

export function observationToFact(ob: RepoObservation): ContextFact {
  return {
    key: `repo.${ob.id}`,
    section: 'Analyse du dépôt',
    label: ob.label,
    value: ob.corrected ?? ob.value,
    provenance: ob.corrected ? 'declared' : ob.provenance,
    source: ob.corrected ? `Corrigé (détection : ${ob.value})` : 'Analyse simulée du dépôt',
  };
}

export interface Suggestion {
  refId: string;
  reason: string;
  status: 'applicable' | 'to_clarify';
  rule?: { code: string; title: string; statement: string; blocking: boolean; criticality: 'basse' | 'moyenne' | 'haute' | 'critique' };
}

/** Reference suggestions computed from the context. They stay proposals until validated (RG-08). */
export function suggestReferences(facts: ContextFact[]): Suggestion[] {
  const v = (k: string) => facts.find((f) => f.key === k);
  const has = (k: string, word: string) => (v(k)?.value ?? '').toLowerCase().includes(word.toLowerCase());
  const unknown = (k: string) => v(k)?.provenance === 'unknown';
  const out: Suggestion[] = [
    {
      refId: 'conventional-commits',
      reason: 'Historique lisible pour les personnes et les agents.',
      status: 'applicable',
      rule: {
        code: 'CODE-COM-01',
        title: 'Messages de commit structurés',
        statement: 'Chaque commit suit le format Conventional Commits (type, portée facultative, description).',
        blocking: false,
        criticality: 'basse',
      },
    },
    { refId: 'semantic-versioning', reason: 'Le produit publie des versions.', status: 'applicable' },
    {
      refId: 'code-review',
      reason: 'Tout changement est relu par une autre personne.',
      status: 'applicable',
      rule: {
        code: 'CODE-REV-01',
        title: 'Relecture indépendante',
        statement: 'Toute modification du code est approuvée par une personne distincte de son auteur.',
        blocking: true,
        criticality: 'haute',
      },
    },
  ];
  if (has('data.personal', 'oui'))
    out.push(
      {
        refId: 'reglement-general-sur-la-protection-des-donnees-ue-2016-679',
        reason: 'Le produit traite des données personnelles ; applicabilité à confirmer selon les pays.',
        status: has('countries', 'France') || has('countries', 'Union') ? 'applicable' : 'to_clarify',
      },
      {
        refId: 'protection-des-donnees-des-la-conception-et-par-defaut',
        reason: 'Données personnelles déclarées.',
        status: 'applicable',
        rule: {
          code: 'PRIV-MIN-01',
          title: 'Minimisation des données',
          statement: 'Chaque nouvelle collecte ou exposition de données personnelles est justifiée par une finalité documentée.',
          blocking: true,
          criticality: 'haute',
        },
      },
    );
  if (unknown('data.personal'))
    out.push({
      refId: 'reglement-general-sur-la-protection-des-donnees-ue-2016-679',
      reason: 'Présence de données personnelles inconnue : applicabilité à préciser.',
      status: 'to_clarify',
    });
  if (has('tenancy', 'multi'))
    out.push({
      refId: 'owasp-application-security-verification-standard-5-0-0',
      reason: 'Instance partagée entre clients : contrôle d’accès et isolation à vérifier.',
      status: 'applicable',
      rule: {
        code: 'SEC-ISO-01',
        title: 'Isolation stricte des données entre clients',
        statement:
          'Toute lecture ou écriture de données métier est filtrée par l’identifiant du client courant et couverte par un test à deux clients.',
        blocking: true,
        criticality: 'critique',
      },
    });
  if (has('stack', 'TypeScript'))
    out.push(
      { refId: 'eslint', reason: 'TypeScript déclaré.', status: 'applicable' },
      { refId: 'vitest', reason: 'Tests unitaires pour TypeScript.', status: 'applicable' },
    );
  if (has('stack', 'React')) out.push({ refId: 'storybook', reason: 'Interface React : galerie de composants.', status: 'applicable' });
  if (has('stack', 'Python'))
    out.push(
      { refId: 'pep-8-style-guide-for-python-code', reason: 'Python déclaré.', status: 'applicable' },
      { refId: 'pytest', reason: 'Tests Python.', status: 'applicable' },
    );
  if (has('a11y', 'WCAG'))
    out.push({
      refId: 'wcag-2-2',
      reason: 'Objectif WCAG 2.2 AA déclaré.',
      status: 'applicable',
      rule: {
        code: 'A11Y-01',
        title: 'Accessibilité des composants',
        statement: 'Chaque composant interactif respecte les critères WCAG 2.2 niveau AA applicables.',
        blocking: false,
        criticality: 'moyenne',
      },
    });
  if (has('a11y', 'RGAA')) out.push({ refId: 'rgaa', reason: 'Objectif RGAA déclaré.', status: 'applicable' });
  if (has('data.sensitive', 'Santé'))
    out.push({
      refId: 'referentiel-de-certification-hebergeur-de-donnees-de-sante-hds',
      reason: 'Données de santé : applicabilité à qualifier selon l’hébergement et le pays.',
      status: 'to_clarify',
    });
  if (has('data.sensitive', 'Paiement'))
    out.push({
      refId: 'payment-card-industry-data-security-standard-pci-dss-v4-0-1',
      reason: 'Données de paiement : périmètre à qualifier.',
      status: 'to_clarify',
    });
  if (has('architecture', 'Microservices'))
    out.push({ refId: 'opentelemetry', reason: 'Traces distribuées entre services.', status: 'applicable' });
  if (unknown('operations') || has('operations', 'Pas encore'))
    out.push({ refId: 'organisation-de-reponse-aux-incidents', reason: 'Exploitation non organisée : à préciser.', status: 'to_clarify' });
  const seen = new Set<string>();
  return out.filter((sug) => (seen.has(sug.refId) ? false : (seen.add(sug.refId), true)));
}

export const EXPERT_LABEL_TO_KEY: Record<string, string> = {
  Produit: 'product',
  Engineering: 'engineering',
  Architecture: 'architecture',
  'Design et accessibilité': 'design',
  'Sécurité et cyber': 'security',
  'Vie privée et exigences': 'privacy',
  'Qualité et tests': 'quality',
  Performance: 'performance',
  Données: 'data',
  'Plateforme et exploitation': 'platform',
  'Marché et concurrence': 'market',
  Marketing: 'marketing',
  Commerce: 'commerce',
  Documentation: 'documentation',
};
