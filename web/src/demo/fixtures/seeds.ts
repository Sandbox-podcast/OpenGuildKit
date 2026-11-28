/**
 * Skills and control definitions shared by every organisation (demo catalogue).
 * Versions are fictional; licences describe the demo content of this repository.
 */
import type { ControlDef, DeliverableType, Skill, SkillVersion } from '@/demo/domain/types';

const v = (version: string, permissions: string[], changelog: string, days: number, dependencies: string[] = []): Omit<SkillVersion, 'publishedAt'> & { days: number } => ({ version, permissions, changelog, dependencies, days });

export interface SkillSeed { key: string; name: string; summary: string; produces?: DeliverableType; capabilities: string[]; scope: string; params: Record<string, string>; versions: ReturnType<typeof v>[]; installed: string | null; active: boolean; experts: string[] }

const READ = 'Lecture du contexte de la quête';
const WRITE = 'Écriture de brouillons dans le studio';

export const SKILL_SEEDS: SkillSeed[] = [
  { key: 'spec', name: 'Rédaction de spécification', summary: 'Rédige une spécification fonctionnelle à partir de la quête et des règles.', produces: 'spec', capabilities: ['Critères d’acceptation', 'Règles appliquées'], scope: 'Projet', params: { langue: 'fr', niveau: 'détaillé' }, versions: [v('1.0.0', [READ, WRITE], 'Première version', 200), v('1.1.0', [READ, WRITE], 'Ajout des questions ouvertes', 60)], installed: '1.1.0', active: true, experts: ['product'] },
  { key: 'adr', name: 'Décision d’architecture', summary: 'Consigne une décision au format ADR.', produces: 'adr', capabilities: ['Contexte, décision, conséquences'], scope: 'Projet', params: { numérotation: 'ADR-NNN' }, versions: [v('0.9.0', [READ, WRITE], 'Version initiale', 120)], installed: '0.9.0', active: true, experts: ['architecture'] },
  { key: 'code', name: 'Proposition de code', summary: 'Propose des fichiers et un diff, sans jamais les pousser vers un dépôt.', produces: 'code', capabilities: ['Fichiers', 'Diff'], scope: 'Dépôt', params: { style: 'Règles du Blueprint' }, versions: [v('1.3.0', [READ, WRITE, 'Lecture du dépôt (simulée)'], 'Diff par fichier', 90), v('1.4.0', [READ, WRITE, 'Lecture du dépôt (simulée)', 'Écriture dans le dépôt distant'], 'Ajoute la création automatique de branches sur le dépôt distant', 3, ['git-remote-adapter 2.x'])], installed: '1.3.0', active: true, experts: ['engineering'] },
  { key: 'tests', name: 'Générateur de tests', summary: 'Écrit des tests reliés aux critères d’acceptation.', produces: 'tests', capabilities: ['Tests unitaires', 'Tests à deux clients'], scope: 'Dépôt', params: { framework: 'vitest' }, versions: [v('2.0.0', [READ, WRITE], 'Tests multi-clients', 45)], installed: '2.0.0', active: true, experts: ['quality', 'engineering'] },
  { key: 'ui', name: 'Composants d’interface', summary: 'Décrit un composant et tous ses états accessibles.', produces: 'component', capabilities: ['États', 'Annonces aria-live'], scope: 'Design system', params: { tokens: 'Nova DS v2' }, versions: [v('1.2.0', [READ, WRITE], 'États désactivés expliqués', 30)], installed: '1.2.0', active: true, experts: ['design'] },
  { key: 'gallery', name: 'Galerie de composants', summary: 'Assemble une galerie inspirée de Storybook.', produces: 'gallery', capabilities: ['Rendu des états'], scope: 'Design system', params: {}, versions: [v('0.5.0', [READ, WRITE], 'Première galerie', 40)], installed: '0.5.0', active: true, experts: ['design', 'documentation'] },
  { key: 'api', name: 'Référence OpenAPI', summary: 'Décrit les endpoints au format OpenAPI 3.1.', produces: 'api', capabilities: ['OpenAPI 3.1'], scope: 'Dépôt', params: { format: 'YAML' }, versions: [v('1.0.0', [READ, WRITE], 'Version initiale', 100)], installed: '1.0.0', active: true, experts: ['engineering', 'architecture'] },
  { key: 'doc', name: 'Rédaction documentaire', summary: 'Rédige guides et explications en indiquant les versions décrites.', produces: 'doc', capabilities: ['Diátaxis', 'Versions décrites'], scope: 'Organisation', params: { ton: 'clair' }, versions: [v('1.1.0', [READ, WRITE], 'Mention des versions décrites', 50)], installed: '1.1.0', active: true, experts: ['documentation'] },
  { key: 'changelog', name: 'Changelog', summary: 'Prépare les notes de version.', produces: 'changelog', capabilities: ['Keep a Changelog'], scope: 'Produit', params: {}, versions: [v('1.0.0', [READ, WRITE], 'Initiale', 150)], installed: '1.0.0', active: true, experts: ['documentation'] },
  { key: 'roadmap', name: 'Roadmap', summary: 'Prépare une roadmap à partir des quêtes et décisions.', produces: 'roadmap', capabilities: ['Horizons'], scope: 'Produit', params: {}, versions: [v('0.8.0', [READ, WRITE], 'Initiale', 80)], installed: '0.8.0', active: true, experts: ['product'] },
  { key: 'landing', name: 'Landing page', summary: 'Construit une landing page autonome.', produces: 'landing', capabilities: ['HTML autonome'], scope: 'Marketing', params: { ton: 'factuel' }, versions: [v('1.0.0', [READ, WRITE], 'Initiale', 70)], installed: '1.0.0', active: false, experts: ['marketing'] },
  { key: 'slides', name: 'Présentation', summary: 'Prépare une présentation navigable.', produces: 'presentation', capabilities: ['Diapositives', 'Notes'], scope: 'Commerce', params: {}, versions: [v('1.0.0', [READ, WRITE], 'Initiale', 70)], installed: '1.0.0', active: true, experts: ['marketing', 'commerce'] },
  { key: 'video', name: 'Storyboard vidéo', summary: 'Découpe une vidéo courte en scènes chronométrées.', produces: 'video', capabilities: ['Scènes', 'Chronologie'], scope: 'Marketing', params: { durée: '45 s' }, versions: [v('0.3.0', [READ, WRITE], 'Initiale', 20)], installed: null, active: false, experts: ['marketing'] },
];

export function skillFromSeed(seed: SkillSeed, orgId: string, now: number): Skill {
  return {
    id: `skl-${seed.key}-${orgId}`, orgId, name: seed.name, summary: seed.summary, origin: 'Catalogue de démonstration Open Guild Kit', license: 'MIT (contenu de démonstration)',
    capabilities: seed.capabilities, scope: seed.scope, params: { ...seed.params }, produces: seed.produces, installed: seed.installed, active: seed.active,
    versions: seed.versions.map(({ days, ...rest }) => ({ ...rest, publishedAt: now - days * 86_400_000 })),
  };
}

export interface ControlSeed { key: string; code: string; name: string; category: ControlDef['category']; description: string; ruleCodes: string[]; blocking: boolean; strategy: string; appliesTo: DeliverableType[] }

export const CONTROL_SEEDS: ControlSeed[] = [
  { key: 'ctl-isolation', code: 'CTL-ISO', name: 'Isolation entre clients', category: 'sécurité', description: 'Vérifie que chaque requête sur les données métier filtre par client.', ruleCodes: ['SEC-ISO-01'], blocking: true, strategy: 'tenant-isolation', appliesTo: ['code'] },
  { key: 'ctl-perm', code: 'CTL-PERM', name: 'Permission dédiée', category: 'accès', description: 'Vérifie que l’opération sensible exige sa permission dédiée.', ruleCodes: ['SEC-PERM-03'], blocking: true, strategy: 'permission-check', appliesTo: ['code'] },
  { key: 'ctl-tests', code: 'CTL-TST', name: 'Tests automatisés', category: 'tests', description: 'Exécute les tests reliés aux critères d’acceptation.', ruleCodes: ['QA-TST-01'], blocking: true, strategy: 'tests-present', appliesTo: ['tests'] },
  { key: 'ctl-deps', code: 'CTL-DEP', name: 'Dépendances vulnérables', category: 'dépendances', description: 'Compare les dépendances à la base de vulnérabilités de démonstration.', ruleCodes: ['DEP-VUL-01'], blocking: true, strategy: 'deps-scan', appliesTo: ['code'] },
  { key: 'ctl-a11y', code: 'CTL-A11Y', name: 'États accessibles', category: 'qualité', description: 'Vérifie les états et annonces d’un composant.', ruleCodes: ['A11Y-01'], blocking: true, strategy: 'a11y-check', appliesTo: ['component'] },
  { key: 'ctl-doc', code: 'CTL-DOC', name: 'Revue documentaire', category: 'qualité', description: 'Vérifie la structure d’un guide.', ruleCodes: ['DOC-01'], blocking: false, strategy: 'doc-review', appliesTo: ['doc'] },
];

export function controlFromSeed(seed: ControlSeed, id: string, orgId: string, ruleIdByCode: Record<string, string>): ControlDef {
  return { id, orgId, code: seed.code, name: seed.name, category: seed.category, description: seed.description, ruleIds: seed.ruleCodes.map((c) => ruleIdByCode[c]).filter(Boolean), blocking: seed.blocking, version: 1, strategy: seed.strategy, appliesTo: seed.appliesTo };
}
