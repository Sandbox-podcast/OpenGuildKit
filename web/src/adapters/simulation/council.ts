/**
 * Demo adapter for the agentic council. Contributions are prepared scenarios, selected
 * explicitly when the session is created. A session outside every scenario receives
 * limited contributions that say so instead of inventing an analysis (brief §2).
 */
import type { CouncilOption, ExpertKey, QuestPlan, Stance } from '@/domain/types';

export interface ContributionTemplate {
  facts: string[]; hypotheses: string[]; questions: string[]; risks: string[];
  recommendation: string; reservation?: string; deliverable?: string;
  sources: string[]; stances: Record<string, Stance>;
}
export interface CouncilScenario {
  key: string;
  label: string;
  summary: string;
  defaultExperts: ExpertKey[];
  requiredFacts: string[];
  options: CouncilOption[];
  contributions: Partial<Record<ExpertKey, ContributionTemplate>>;
  clarifications: Partial<Record<ExpertKey, string>>;
  problem: string;
  compromise: string;
  quests: Record<string, QuestPlan[]>;
}

const opt = (id: string, title: string, summary: string, pros: string[], cons: string[], impacts: Record<string, string>, blocking: string[] = []): CouncilOption =>
  ({ id, title, summary, pros, cons, impacts, blocking });

export const COUNCIL_SCENARIOS: Record<string, CouncilScenario> = {
  'export-donnees': {
    key: 'export-donnees',
    label: 'Export des données clients (Atlas CRM)',
    summary: "Permettre à un administrateur d’exporter les données de ses clients.",
    defaultExperts: ['product', 'design', 'engineering', 'security', 'privacy', 'performance'],
    requiredFacts: ['export.retention'],
    problem: "Les administrateurs des clients d’Atlas CRM veulent récupérer les fiches contacts, comptes et activités de leur organisation. La plateforme est multi-clients : un export ne doit jamais contenir de données d’un autre client, doit être réservé aux personnes autorisées, tracé, et sa durée de disponibilité doit être fixée.",
    compromise: "Un export asynchrone couvre les grands volumes sans dégrader l’API ; il demande un stockage temporaire isolé par client, des liens à durée limitée et une notification. L’export immédiat est plus rapide à livrer mais plafonné en volume.",
    options: [
      opt('opt-a', 'Export immédiat limité', 'Téléchargement CSV synchrone, plafonné à 10 000 lignes, réservé au rôle administrateur du client.',
        ['Livrable en un sprint', 'Aucun stockage intermédiaire', 'Parcours simple pour l’utilisateur'],
        ['Délai d’attente au-delà de ~20 000 lignes', 'Clients volumineux exclus', 'Charge ponctuelle sur la base principale'],
        { simplicité: 'Élevée', délai: '1 sprint', isolation: 'Filtre client dans la requête', permissions: 'Rôle administrateur', conservation: 'Aucun fichier conservé', traçabilité: 'Événement par export' }),
      opt('opt-b', 'Traitement asynchrone', 'Tâche en file d’attente produisant un fichier chiffré dans un espace isolé par client, lien de téléchargement à durée limitée et notification.',
        ['Grands volumes pris en charge', 'Pas d’impact sur la latence de l’API', 'Reprise possible en cas d’échec'],
        ['Deux à trois sprints', 'Stockage temporaire à protéger et purger', 'Durée de disponibilité à fixer'],
        { simplicité: 'Moyenne', délai: '2 à 3 sprints', isolation: 'Filtre client + espace de stockage par client', permissions: 'Permission « export » dédiée', conservation: 'Fichier purgé après la durée fixée', traçabilité: 'Événements de demande, génération et téléchargement' },
        ['Durée de disponibilité du fichier à fixer (inconnue du Blueprint)']),
    ],
    contributions: {
      product: {
        facts: ['Dans le scénario, 41 tickets support du trimestre portent sur la récupération de données par les administrateurs clients.', 'Trois clients du segment « grands comptes » dépassent 200 000 contacts.'],
        hypotheses: ['La plupart des exports concernent moins de 10 000 lignes.'],
        questions: ['Les grands comptes acceptent-ils un délai de génération de quelques minutes ?'],
        risks: ['Livrer tard un export complet laisse les clients extraire leurs données par l’API, sans traçabilité.'],
        recommendation: 'Livrer vite une première valeur. Je privilégie l’export immédiat limité, puis l’asynchrone si la demande des grands comptes se confirme.',
        reservation: 'Si les grands comptes sont prioritaires ce trimestre, l’option B devient préférable.',
        deliverable: 'Spécification fonctionnelle avec critères d’acceptation.',
        sources: ['jobs-to-be-done', 'rice', 'definition-of-done'],
        stances: { 'opt-a': 'pour', 'opt-b': 'réservé' },
      },
      design: {
        facts: ['Le design system ne possède pas encore de bouton d’action longue avec état de progression.'],
        hypotheses: ['Un administrateur lance l’export depuis la page « Organisation ».'],
        questions: ['Faut-il permettre de choisir les champs exportés ?'],
        risks: ['Un téléchargement sans retour visuel au-delà de 10 secondes passe pour une panne.', 'Les états d’attente doivent être annoncés aux technologies d’assistance.'],
        recommendation: 'Les deux options sont praticables. L’option B demande un composant d’état (préparation, prêt, expiré) et une notification ; je fournis ces états.',
        deliverable: 'Proposition d’interface et composant « Bouton d’export » avec ses états.',
        sources: ['wcag-2-2', 'wai-aria-1-2', 'atomic-design'],
        stances: { 'opt-a': 'pour', 'opt-b': 'pour' },
      },
      engineering: {
        facts: ['L’API actuelle applique une limite de 30 secondes par requête.', 'Les tables contacts et activités sont partitionnées par tenant_id.'],
        hypotheses: ['Une génération de 200 000 lignes prend environ 3 minutes sur un worker.'],
        questions: ['Le stockage objet actuel permet-il un préfixe par client avec politique de purge ?'],
        risks: ['L’option A atteint la limite de 30 s au-delà d’environ 20 000 lignes et sature une connexion de base.'],
        recommendation: 'Je recommande le traitement asynchrone : file de tâches existante, fichier par client, URL signée.',
        reservation: 'Je m’oppose à l’option A si elle doit couvrir les grands comptes.',
        deliverable: 'Proposition de code, référence d’API et tests.',
        sources: ['the-twelve-factor-app', 'openapi-specification', 'hexagonal-architecture'],
        stances: { 'opt-a': 'contre', 'opt-b': 'pour' },
      },
      security: {
        facts: ['Atlas CRM est multi-clients : chaque requête doit être filtrée par l’identifiant du client (règle SEC-ISO-01).'],
        hypotheses: [],
        questions: ['Qui peut déclencher un export : tout administrateur du client ou une permission dédiée ?'],
        risks: ['Une requête d’export sans filtre client exposerait les données d’autres clients : contrôle bloquant d’isolation obligatoire.', 'Un lien de téléchargement non expirant serait partageable sans contrôle.'],
        recommendation: 'Les deux options sont acceptables si : permission dédiée, filtre client vérifié par un test d’isolation, journalisation de chaque export et lien à durée limitée pour l’option B.',
        reservation: 'Le contrôle d’isolation entre clients doit réussir sur la version livrée. Il n’est pas dérogeable.',
        deliverable: 'Critères de sécurité et contrôle d’isolation.',
        sources: ['owasp-application-security-verification-standard-5-0-0', 'owasp-api-security-top-10-2023', 'principe-du-moindre-privilege'],
        stances: { 'opt-a': 'réservé', 'opt-b': 'réservé' },
      },
      privacy: {
        facts: ['Les fiches contacts contiennent des données personnelles (nom, courriel, téléphone).', 'Le Blueprint ne fixe pas la durée de disponibilité d’un fichier exporté : c’est une inconnue.'],
        hypotheses: ['Le client est responsable de traitement, Atelier Nova sous-traitant.'],
        questions: ['Quelle durée de disponibilité retenir pour le fichier : 24 h, 7 jours ?'],
        risks: ['Sans durée fixée, un fichier exporté resterait accessible indéfiniment.', 'Exporter des champs non nécessaires contredit la minimisation.'],
        recommendation: 'Je ne peux pas soutenir l’option B tant que la durée de disponibilité n’est pas fixée dans le Blueprint. Une fois fixée, l’option B est compatible.',
        reservation: 'Décision bloquée tant que l’inconnue « durée de disponibilité de l’export » n’est pas résolue.',
        deliverable: 'Mention dans la documentation administrateur et registre des traitements.',
        sources: ['reglement-general-sur-la-protection-des-donnees-ue-2016-679', 'protection-des-donnees-des-la-conception-et-par-defaut', 'cnil-guide-de-la-securite-des-donnees-personnelles'],
        stances: { 'opt-a': 'pour', 'opt-b': 'réservé' },
      },
      performance: {
        facts: ['Mesure du scénario : export synchrone de 50 000 lignes, p95 = 34 s sur l’environnement de recette.'],
        hypotheses: ['Le worker asynchrone peut traiter 1 000 lignes par seconde.'],
        questions: ['Quel volume maximal par export faut-il garantir ?'],
        risks: ['L’option A dégrade les temps de réponse des autres requêtes pendant l’export.'],
        recommendation: 'Option B au-delà de 10 000 lignes. Un plafond strict rend l’option A acceptable.',
        deliverable: 'Budget de performance et test de charge.',
        sources: ['load-testing', 'service-level-objective-slo', 'methode-red'],
        stances: { 'opt-a': 'réservé', 'opt-b': 'pour' },
      },
      architecture: {
        facts: ['Le portail client appelle l’API d’Atlas CRM : un nouvel endpoint d’export l’impacte.'],
        hypotheses: [],
        questions: ['L’export doit-il être exposé dans l’API publique ou réservé à l’interface ?'],
        risks: ['Un endpoint public sans versionnement casserait les intégrations du portail.'],
        recommendation: 'Option B, avec un endpoint versionné et une décision d’architecture (ADR) consignée.',
        deliverable: "Décision d’architecture (ADR).",
        sources: ['architecture-decision-records', 'c4-model', 'semantic-versioning'],
        stances: { 'opt-a': 'réservé', 'opt-b': 'pour' },
      },
      quality: {
        facts: ['Aucun test d’isolation multi-clients n’existe sur le module export.'],
        hypotheses: [],
        questions: ['Quelles données de test multi-clients sont disponibles ?'],
        risks: ['Sans test d’intégration à deux clients, une régression d’isolation passerait inaperçue.'],
        recommendation: 'Ajouter un test d’intégration à deux clients et un test de contrat de l’API.',
        deliverable: 'Plan de test et tests automatisés.',
        sources: ['integration-testing', 'contract-testing', 'testcontainers'],
        stances: { 'opt-a': 'pour', 'opt-b': 'pour' },
      },
      documentation: {
        facts: ['La documentation administrateur ne décrit aucun export.'],
        hypotheses: [],
        questions: ['Le guide doit-il couvrir les deux modes ?'],
        risks: ['Une durée de disponibilité non documentée génère des tickets support.'],
        recommendation: 'Un guide administrateur et une référence d’API, versionnés avec le livrable.',
        deliverable: 'Guide administrateur.',
        sources: ['diataxis', 'docs-as-code'],
        stances: { 'opt-a': 'pour', 'opt-b': 'pour' },
      },
    },
    clarifications: {
      privacy: 'Une durée courte (7 jours au plus) limite l’exposition. Le scénario retient 7 jours si le Blueprint le confirme.',
      engineering: 'Le stockage objet de recette accepte un préfixe par client et une règle de purge automatique.',
      security: 'Une permission « export » distincte du rôle administrateur permet de la retirer sans toucher au reste des droits.',
      product: 'Les trois grands comptes ont déclaré pouvoir attendre 5 minutes.',
      performance: 'Garantir 250 000 lignes couvre tous les clients actuels du scénario.',
      design: 'Le choix des champs peut attendre une seconde itération ; l’export complet suffit pour la première.',
    },
    quests: {
      'opt-a': [{
        title: 'Export immédiat des données clients', objective: 'Permettre à un administrateur de télécharger jusqu’à 10 000 lignes de ses données clients.', type: 'fonctionnalité',
        criteria: ['Seules les données du client de l’administrateur sont exportées', 'Le téléchargement est réservé à la permission « export »', 'Chaque export produit un événement d’audit', 'Au-delà de 10 000 lignes, un message explique la limite'],
        deliverables: ['spec', 'component', 'api', 'tests', 'code', 'doc'], controlIds: ['ctl-isolation', 'ctl-tests', 'ctl-perm'],
        tasks: ['Rédiger la spécification', 'Implémenter l’endpoint d’export', 'Ajouter le bouton dans l’interface', 'Écrire le test d’isolation', 'Documenter pour les administrateurs'],
      }],
      'opt-b': [{
        title: 'Export asynchrone des données clients', objective: 'Permettre à un administrateur d’obtenir l’export complet de ses données clients, quel que soit le volume.', type: 'fonctionnalité',
        criteria: ['Seules les données du client de l’administrateur sont exportées', 'Le lancement est réservé à la permission « export »', 'Le fichier n’est disponible que pendant la durée fixée par le Blueprint', 'Chaque demande, génération et téléchargement produit un événement d’audit', 'L’administrateur est notifié quand le fichier est prêt'],
        deliverables: ['spec', 'component', 'api', 'tests', 'code', 'doc'], controlIds: ['ctl-isolation', 'ctl-tests', 'ctl-perm'],
        tasks: ['Rédiger la spécification', 'Créer la tâche de génération', 'Exposer l’API de demande et de statut', 'Ajouter le composant d’export', 'Écrire le test d’isolation à deux clients', 'Documenter pour les administrateurs'],
      }],
    },
  },
  positionnement: {
    key: 'positionnement',
    label: 'Réponse au signal concurrentiel Helio CRM (fictif)',
    summary: 'Décider du positionnement face à l’annonce d’un export « illimité » par un concurrent fictif.',
    defaultExperts: ['market', 'marketing', 'commerce', 'product'],
    requiredFacts: [],
    problem: 'Le concurrent fictif Helio CRM annonce un export « illimité et instantané ». Faut-il riposter sur la fonctionnalité ou se positionner sur la maîtrise et la traçabilité des données ?',
    compromise: 'Mettre en avant la traçabilité et l’isolation, appuyées par la feuille de route de l’export asynchrone, sans promettre une capacité non livrée.',
    options: [
      opt('opt-a', 'Riposte fonctionnelle', 'Annoncer un export équivalent dans le trimestre.', ['Message simple'], ['Promesse non encore livrée', 'Course aux fonctionnalités'], { délai: 'Immédiat', risque: 'Promesse non tenue', cohérence: 'Faible' }),
      opt('opt-b', 'Positionnement sur la maîtrise des données', 'Valoriser l’export tracé, isolé et limité dans le temps.', ['Différenciant pour les clients régulés', 'Aligné sur la décision d’export'], ['Message plus long à expliquer'], { délai: '2 semaines', risque: 'Faible', cohérence: 'Élevée' }),
    ],
    contributions: {
      market: { facts: ['Signal fictif : page produit Helio CRM mise à jour le 12 novembre.', 'Aucune mention de la durée de conservation des fichiers chez ce concurrent fictif.'], hypotheses: ['L’annonce vise les PME plutôt que les grands comptes.'], questions: ['Combien d’opportunités en cours citent Helio CRM ?'], risks: ['Réagir à une annonce non vérifiée.'], recommendation: 'Positionnement sur la maîtrise des données, en surveillant la disponibilité réelle de la fonctionnalité concurrente.', deliverable: 'Fiche de comparaison', sources: ['jobs-to-be-done', 'value-proposition-canvas'], stances: { 'opt-a': 'contre', 'opt-b': 'pour' } },
      marketing: { facts: ['Nos pages actuelles ne parlent ni d’export ni de traçabilité.'], hypotheses: [], questions: ['Pouvons-nous citer la conformité au RGPD sans revendiquer une certification ?'], risks: ['Toute mention de conformité doit rester factuelle : aucune certification n’est délivrée par l’outil.'], recommendation: 'Une landing page « Vos données, vos règles » et une présentation commerciale.', deliverable: 'Landing page et présentation', sources: ['schema-org', 'parametres-utm'], stances: { 'opt-a': 'réservé', 'opt-b': 'pour' } },
      commerce: { facts: ['Deux opportunités du scénario mentionnent l’export comme critère.'], hypotheses: [], questions: [], risks: ['Perdre ces opportunités sans réponse claire.'], recommendation: 'Fournir un argumentaire et une date indicative tirée de la roadmap, sans engagement contractuel.', deliverable: 'Argumentaire commercial', sources: ['meddpicc', 'spiced'], stances: { 'opt-a': 'pour', 'opt-b': 'pour' } },
      product: { facts: ['La quête d’export asynchrone est planifiée.'], hypotheses: [], questions: [], risks: ['Une riposte fonctionnelle détournerait l’équipe de la quête en cours.'], recommendation: 'Option B, en citant la roadmap publique.', sources: ['north-star-framework'], stances: { 'opt-a': 'contre', 'opt-b': 'pour' } },
    },
    clarifications: { market: 'La page fictive ne précise ni volume ni délai réels : l’information reste une annonce.' },
    quests: {
      'opt-b': [{ title: 'Supports « maîtrise des données »', objective: 'Produire une landing page et une présentation commerciale sur l’export tracé.', type: 'campagne', criteria: ['Aucune revendication de certification', 'Le message cite la roadmap sans date contractuelle'], deliverables: ['landing', 'presentation'], controlIds: [], tasks: ['Rédiger le message', 'Construire la landing page', 'Préparer la présentation'] }],
      'opt-a': [{ title: 'Annonce de l’export étendu', objective: 'Annoncer l’export complet dans le trimestre.', type: 'campagne', criteria: ['Date validée par l’équipe produit'], deliverables: ['landing'], controlIds: [], tasks: ['Rédiger l’annonce'] }],
    },
  },
  vulnerabilite: {
    key: 'vulnerabilite',
    label: 'Vulnérabilité simulée dans une dépendance',
    summary: 'Traiter une vulnérabilité simulée (identifiant fictif SIM-2026-0042) dans la bibliothèque de génération CSV.',
    defaultExperts: ['security', 'engineering', 'quality', 'platform'],
    requiredFacts: [],
    problem: 'Le contrôle de dépendances signale une vulnérabilité simulée SIM-2026-0042 (injection de formule dans les CSV) dans csv-forge 2.3.1, utilisée par l’export.',
    compromise: 'Neutraliser les formules immédiatement dans notre code, puis monter de version dès la publication du correctif.',
    options: [
      opt('opt-a', 'Mise à jour immédiate', 'Passer à csv-forge 2.4.0.', ['Corrige à la source'], ['Changement de comportement à tester'], { délai: '2 jours', risque: 'Régression possible' }),
      opt('opt-b', 'Atténuation puis mise à jour', 'Échapper les cellules commençant par =, +, -, @ puis mettre à jour.', ['Protection immédiate'], ['Deux changements successifs'], { délai: '1 jour puis 1 semaine', risque: 'Faible' }),
    ],
    contributions: {
      security: { facts: ['Vulnérabilité simulée de gravité haute ; les fichiers CSV sont ouverts dans des tableurs.'], hypotheses: [], questions: [], risks: ['Exécution de formules à l’ouverture du fichier.'], recommendation: 'Atténuer immédiatement, puis mettre à jour.', sources: ['common-vulnerabilities-and-exposures-cve', 'common-vulnerability-scoring-system-cvss', 'software-composition-analysis-sca'], stances: { 'opt-a': 'pour', 'opt-b': 'pour' } },
      engineering: { facts: ['La version 2.4.0 change le séparateur par défaut.'], hypotheses: [], questions: [], risks: ['Casser les imports clients existants.'], recommendation: 'Option B.', sources: ['semantic-versioning'], stances: { 'opt-a': 'réservé', 'opt-b': 'pour' } },
      quality: { facts: [], hypotheses: [], questions: ['Avons-nous un test pour les cellules commençant par « = » ?'], risks: [], recommendation: 'Ajouter un test de non-régression.', sources: ['regression-testing'], stances: { 'opt-a': 'pour', 'opt-b': 'pour' } },
      platform: { facts: ['Le déploiement canari est disponible.'], hypotheses: [], questions: [], risks: [], recommendation: 'Déployer la mise à jour en canari.', sources: ['deploiement-canary'], stances: { 'opt-a': 'pour', 'opt-b': 'pour' } },
    },
    clarifications: {},
    quests: { 'opt-b': [{ title: 'Neutraliser l’injection de formules CSV', objective: 'Supprimer le risque SIM-2026-0042 sur l’export.', type: 'sécurité', criteria: ['Les cellules dangereuses sont échappées', 'La dépendance est à jour'], deliverables: ['code', 'tests'], controlIds: ['ctl-deps', 'ctl-tests'], tasks: ['Échapper les cellules', 'Monter de version', 'Test de non-régression'] }], 'opt-a': [{ title: 'Mettre à jour csv-forge', objective: 'Passer en 2.4.0.', type: 'sécurité', criteria: ['Dépendance à jour'], deliverables: ['code'], controlIds: ['ctl-deps'], tasks: ['Monter de version'] }] },
  },
  'design-system': {
    key: 'design-system',
    label: 'Évolution du design system : bouton d’action longue',
    summary: 'Ajouter au design system un bouton d’action longue avec états, et proposer son adoption.',
    defaultExperts: ['design', 'engineering', 'quality', 'documentation'],
    requiredFacts: [],
    problem: 'Plusieurs produits ont besoin d’un bouton déclenchant une action longue (export, génération). Faut-il un composant partagé ou des variantes locales ?',
    compromise: 'Un composant partagé avec états documentés, adopté progressivement par les produits concernés.',
    options: [
      opt('opt-a', 'Composant partagé', 'Ajouter « Bouton d’action longue » au design system.', ['Cohérence', 'Accessibilité vérifiée une fois'], ['Coordination entre produits'], { délai: '1 sprint' }),
      opt('opt-b', 'Variante locale', 'Chaque produit développe sa variante.', ['Autonomie'], ['Divergences', 'Accessibilité à revérifier partout'], { délai: 'Variable' }),
    ],
    contributions: {
      design: { facts: ['Trois écrans du scénario utilisent un bouton d’attente différent.'], hypotheses: [], questions: [], risks: ['Annonces aux lecteurs d’écran incohérentes.'], recommendation: 'Composant partagé.', sources: ['atomic-design', 'dtcg-design-tokens', 'storybook'], stances: { 'opt-a': 'pour', 'opt-b': 'contre' } },
      engineering: { facts: [], hypotheses: [], questions: ['Le composant doit-il gérer l’annulation ?'], risks: [], recommendation: 'Composant partagé avec propriété d’annulation.', sources: ['semantic-versioning'], stances: { 'opt-a': 'pour', 'opt-b': 'réservé' } },
      quality: { facts: [], hypotheses: [], questions: [], risks: ['Les états d’erreur ne sont pas testés aujourd’hui.'], recommendation: 'Tests visuels et d’accessibilité pour chaque état.', sources: ['wcag-2-2'], stances: { 'opt-a': 'pour', 'opt-b': 'contre' } },
      documentation: { facts: [], hypotheses: [], questions: [], risks: [], recommendation: 'Une page de galerie et une note d’adoption.', sources: ['diataxis'], stances: { 'opt-a': 'pour', 'opt-b': 'réservé' } },
    },
    clarifications: {},
    quests: { 'opt-a': [{ title: 'Composant « Bouton d’action longue »', objective: 'Publier le composant partagé, ses états et sa documentation.', type: 'design', criteria: ['États repos, attente, succès, erreur, désactivé', 'Contraste vérifié', 'Note d’adoption pour les projets concernés'], deliverables: ['component', 'gallery', 'doc'], controlIds: ['ctl-a11y'], tasks: ['Dessiner les états', 'Implémenter', 'Documenter', 'Proposer l’adoption'] }], 'opt-b': [] },
  },
};

export const SCENARIO_LIST = Object.values(COUNCIL_SCENARIOS).map((s) => ({ key: s.key, label: s.label, summary: s.summary }));

/** Contribution of an expert. Outside the prepared scenarios it says what it cannot do. */
export function contributionFor(scenarioKey: string | null, expert: ExpertKey, expertName: string): ContributionTemplate & { limited: boolean } {
  const scenario = scenarioKey ? COUNCIL_SCENARIOS[scenarioKey] : undefined;
  const t = scenario?.contributions[expert];
  if (t) return { ...t, limited: false };
  return {
    limited: true,
    facts: [],
    hypotheses: [],
    questions: [scenario ? `Ce scénario ne prépare pas d’avis pour l’expertise ${expertName}. Quelle question précise doit-elle examiner ?` : 'Quel est le contexte précis, et quelles sources puis-je consulter ?'],
    risks: [],
    recommendation: scenario
      ? `Aucun avis préparé pour cette expertise dans le scénario « ${scenario.label} ». Je ne formule pas de recommandation.`
      : 'Ce sujet sort des scénarios de démonstration : aucune analyse n’a été effectuée. Je liste seulement les informations nécessaires pour examiner la demande.',
    reservation: 'Contribution limitée : simulation hors scénario.',
    sources: [],
    stances: {},
  };
}

export function clarificationFor(scenarioKey: string | null, expert: ExpertKey, question: string): string {
  const answer = scenarioKey ? COUNCIL_SCENARIOS[scenarioKey]?.clarifications[expert] : undefined;
  return answer ?? `Le scénario ne contient pas de réponse préparée à « ${question.slice(0, 80)} ». La question reste ouverte et figure dans la synthèse.`;
}

export const genericOptions = (): CouncilOption[] => [];
