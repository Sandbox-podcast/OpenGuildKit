/**
 * Demo deliverable generator. Produces real, editable content for every deliverable type.
 * The export scenario has dedicated content (including a first code proposal with a tenant
 * isolation defect, fixed by the "correctif" variant); other quests get generic content
 * built from their objective and criteria.
 */
import type { Content, DeliverableType } from '@/domain/types';

export interface GenerationContext {
  projectName: string;
  productName: string;
  questTitle: string;
  objective: string;
  criteria: string[];
  retentionDays?: string;
  variant: 'initial' | 'correctif';
  scenario: 'export' | 'vuln' | 'generic';
}

const bullet = (items: string[]) => items.map((i) => `- ${i}`).join('\n');

export function generateContent(type: DeliverableType, c: GenerationContext): { title: string; content: Content } {
  const exp = c.scenario === 'export';
  const retention = c.retentionDays ?? 'à fixer (inconnue du Blueprint)';
  switch (type) {
    case 'spec':
      return {
        title: `Spécification — ${c.questTitle}`,
        content: { kind: 'markdown', body: `# Spécification — ${c.questTitle}

## Objectif
${c.objective}

## Contexte
Produit : ${c.productName}. Projet : ${c.projectName}.${exp ? ` Plateforme multi-clients : chaque client ne voit que ses propres données.` : ''}

## Parcours
${exp ? `1. L'administrateur ouvre **Organisation › Données** et choisit **Exporter les données clients**.
2. La demande est enregistrée ; un traitement prépare le fichier CSV chiffré.
3. Une notification signale que le fichier est prêt.
4. Le lien de téléchargement reste valable **${retention} jours**, puis le fichier est purgé.` : bullet(['Définir le parcours principal', 'Préciser les cas limites'])}

## Critères d'acceptation
${bullet(c.criteria)}

## Règles du Blueprint appliquées
${exp ? bullet(['SEC-ISO-01 — Isolation stricte des données entre clients (non dérogeable)', 'PRIV-RET-02 — Durée de disponibilité des exports', 'SEC-PERM-03 — Permission dédiée pour les opérations sensibles', 'OPS-LOG-01 — Journalisation des opérations sur données personnelles']) : '- À compléter lors de la revue'}

## Questions ouvertes
${exp ? bullet(['Faut-il permettre de choisir les champs exportés ? (seconde itération)']) : '- Aucune'}
` },
      };
    case 'adr':
      return {
        title: `ADR — ${c.questTitle}`,
        content: { kind: 'markdown', body: `# ADR-014 — ${exp ? 'Export asynchrone par file de tâches' : c.questTitle}

- **Statut** : proposé
- **Contexte** : ${c.objective}
- **Décision** : ${exp ? 'Les exports passent par la file de tâches existante. Le fichier est écrit sous un préfixe propre au client et servi par une URL signée à durée limitée.' : 'À préciser.'}
- **Conséquences** : ${exp ? 'Un worker supplémentaire ; politique de purge du stockage ; endpoint versionné `/v1/exports`.' : 'À préciser.'}
- **Alternatives écartées** : ${exp ? 'Export synchrone plafonné (limite de 30 s de l’API).' : '—'}
` },
      };
    case 'code':
      return { title: `Proposition de code — ${c.questTitle}`, content: { kind: 'files', files: exp ? exportCode(c.variant) : c.scenario === 'vuln' ? vulnCode(c.variant) : genericCode(c) } };
    case 'tests':
      return {
        title: `Tests — ${c.questTitle}`,
        content: { kind: 'files', files: [{ path: exp ? 'tests/export/isolation.test.ts' : 'tests/feature.test.ts', language: 'typescript', body: exp ? EXPORT_TEST : `import { describe, it, expect } from 'vitest';\n\ndescribe('${c.questTitle}', () => {\n${c.criteria.map((k) => `  it(${JSON.stringify(k)}, () => {\n    expect(true).toBe(true); // à remplacer par la vérification réelle\n  });`).join('\n')}\n});\n` }] },
      };
    case 'component':
      return {
        title: exp ? 'Composant — Bouton d’export' : `Composant — ${c.questTitle}`,
        content: {
          kind: 'component', name: exp ? 'ExportButton' : 'LongActionButton',
          description: 'Bouton déclenchant une action longue. L’état courant est annoncé par une région aria-live ; chaque état associe un texte et un symbole, jamais la couleur seule.',
          variants: [
            { name: 'Repos', props: { state: 'idle', label: exp ? 'Exporter les données clients' : 'Lancer' } },
            { name: 'Préparation', props: { state: 'pending', label: 'Préparation du fichier…' } },
            { name: 'Prêt', props: { state: 'ready', label: 'Télécharger le fichier' } },
            { name: 'Expiré', props: { state: 'expired', label: 'Lien expiré — relancer' } },
            { name: 'Erreur', props: { state: 'error', label: 'Échec — réessayer' } },
            { name: 'Désactivé', props: { state: 'disabled', label: 'Permission « export » requise', disabled: true } },
          ],
          checks: ['Contraste du texte ≥ 4,5:1', 'Focus visible', 'Annonce aria-live des changements d’état', 'Raison affichée quand le bouton est désactivé'],
        },
      };
    case 'gallery':
      return { title: 'Galerie de composants', content: { kind: 'gallery', componentIds: [], intro: 'Galerie inspirée d’un Storybook : chaque composant est rendu dans tous ses états.' } };
    case 'api':
      return { title: exp ? 'Référence d’API — Exports' : `Référence d’API — ${c.questTitle}`, content: { kind: 'api', spec: exp ? exportOpenApi(retention) : genericOpenApi(c) } };
    case 'doc':
      return {
        title: exp ? 'Guide administrateur — Exporter les données clients' : `Guide — ${c.questTitle}`,
        content: { kind: 'markdown', body: exp ? `# Exporter les données de vos clients

Ce guide s'adresse aux administrateurs d'une organisation cliente d'${c.productName}.

## Avant de commencer
- Vous devez disposer de la permission **Export**.
- L'export contient uniquement les données de votre organisation.

## Lancer un export
1. Ouvrez **Organisation › Données**.
2. Sélectionnez **Exporter les données clients**.
3. Une notification vous prévient lorsque le fichier est prêt.

## Durée de disponibilité
Le fichier reste téléchargeable **${retention} jours**. Passé ce délai, il est supprimé et le lien affiche « Lien expiré ».

## Traçabilité
Chaque demande et chaque téléchargement sont enregistrés dans le journal d'audit de votre organisation.
` : `# ${c.questTitle}\n\n${c.objective}\n\n## Étapes\n${bullet(c.criteria)}\n` },
      };
    case 'changelog':
      return { title: `Changelog — ${c.productName}`, content: { kind: 'markdown', body: `# Changelog\n\nFormat inspiré de Keep a Changelog ; versions SemVer.\n\n## [Non publié]\n### Ajouté\n- ${c.questTitle}\n\n## [4.12.0] — 2026-10-28\n### Corrigé\n- Pagination des activités sur les comptes volumineux.\n` } };
    case 'roadmap':
      return { title: `Roadmap — ${c.productName}`, content: { kind: 'roadmap', items: [
        { horizon: 'T4 2026', title: c.questTitle, status: 'En cours', note: 'Issue d’une décision du Conseil.' },
        { horizon: 'T1 2027', title: 'Choix des champs exportés', status: 'À l’étude', note: 'Question ouverte du Conseil.' },
        { horizon: 'T2 2027', title: 'Export planifié récurrent', status: 'Hypothèse', note: 'À réévaluer selon les signaux de veille.' },
      ] } };
    case 'landing':
      return { title: 'Landing page — Vos données, vos règles', content: { kind: 'landing', hero: 'Vos données clients, sous votre contrôle', subtitle: `${c.productName} exporte les données de chaque client de façon isolée, tracée et limitée dans le temps.`, features: [
        { title: 'Isolé par client', text: 'Chaque export ne contient que les données de votre organisation.' },
        { title: 'Tracé', text: 'Demandes et téléchargements apparaissent dans votre journal d’audit.' },
        { title: 'Limité dans le temps', text: `Le fichier est supprimé après ${retention} jours.` },
      ], cta: 'Demander une démonstration', note: 'Support de démonstration : contenu fictif, aucune revendication de certification.' } };
    case 'presentation':
      return { title: 'Présentation — Export maîtrisé', content: { kind: 'slides', slides: [
        { title: 'Le besoin', bullets: ['Les administrateurs veulent récupérer leurs données', 'Sans exposer celles des autres clients'], note: 'Contexte issu du Conseil.' },
        { title: 'Notre réponse', bullets: ['Export asynchrone isolé par client', 'Lien à durée limitée', 'Journal d’audit'], note: 'Ne pas promettre de date contractuelle.' },
        { title: 'Ce que nous ne promettons pas', bullets: ['Aucune certification n’est délivrée par la fonctionnalité', 'La conformité reste l’affaire de chaque client'], note: 'Message validé par la vie privée.' },
        { title: 'Prochaines étapes', bullets: ['Démonstration', 'Choix des champs (2027)'], note: '' },
      ] } };
    case 'video':
      return { title: 'Storyboard — Export en 45 secondes', content: { kind: 'storyboard', scenes: [
        { title: 'Ouverture', seconds: 5, visual: 'Logo produit sur fond sombre', voice: 'Vos données vous appartiennent.' },
        { title: 'Le geste', seconds: 12, visual: 'Clic sur « Exporter les données clients »', voice: 'Un administrateur lance l’export en un clic.' },
        { title: 'La préparation', seconds: 10, visual: 'Bouton en état « Préparation »', voice: 'Le fichier est préparé sans ralentir votre équipe.' },
        { title: 'Le contrôle', seconds: 10, visual: 'Journal d’audit et date d’expiration', voice: 'Chaque export est tracé et expire automatiquement.' },
        { title: 'Appel à l’action', seconds: 8, visual: 'Bouton « Demander une démonstration »', voice: 'Découvrez-le avec nous.' },
      ] } };
  }
}

function exportCode(variant: GenerationContext['variant']) {
  const fixed = variant === 'correctif';
  return [
    { path: 'src/export/exportJob.ts', language: 'typescript', body: `import { db } from '../db';
import { storage } from '../storage';
import { toCsv } from './csv';

export interface ExportRequest { id: string; tenantId: string; requestedBy: string; since: Date }

/** Builds the CSV file for one tenant and stores it under the tenant prefix. */
export async function buildExport(request: ExportRequest): Promise<string> {
  const contacts = await db.query(
${fixed ? `    'SELECT id, name, email, phone FROM contacts WHERE tenant_id = $1 AND created_at >= $2',
    [request.tenantId, request.since],` : `    'SELECT id, name, email, phone FROM contacts WHERE created_at >= $1',
    [request.since],`}
  );
  const key = \`exports/\${request.tenantId}/\${request.id}.csv\`;
  await storage.put(key, toCsv(contacts.rows), { encrypt: true });
  return key;
}
` },
    { path: 'src/export/exportController.ts', language: 'typescript', body: `import { requirePermission } from '../auth';
import { audit } from '../audit';
import { queue } from '../queue';

export async function requestExport(ctx) {
  requirePermission(ctx.user, 'export');
  const job = await queue.enqueue('export', { tenantId: ctx.user.tenantId, requestedBy: ctx.user.id, since: ctx.body.since });
  await audit(ctx.user, 'export.requested', { jobId: job.id });
  return { status: 202, body: { exportId: job.id, state: 'pending' } };
}
` },
  ];
}

function vulnCode(variant: GenerationContext['variant']) {
  const fixed = variant === 'correctif';
  return [
    { path: 'package.json', language: 'json', body: `{
  "name": "nova-billing-exports",
  "dependencies": {
    "csv-forge": "${fixed ? '2.4.0' : '2.3.1'}"
  }
}
` },
    { path: 'src/csv.ts', language: 'typescript', body: fixed
      ? `import { stringify } from 'csv-forge';

/** Neutralise les cellules interprétées comme des formules par les tableurs. */
export const escapeFormula = (v: string) => (/^[=+\-@]/.test(v) ? \`'\${v}\` : v);

export const toCsv = (rows: string[][]) => stringify(rows.map((r) => r.map(escapeFormula)));
`
      : `import { stringify } from 'csv-forge';

export const toCsv = (rows: string[][]) => stringify(rows);
` },
  ];
}

function genericCode(c: GenerationContext) {
  return [{ path: 'src/feature/index.ts', language: 'typescript', body: `/** ${c.questTitle} — proposition générée pour la démonstration. */\nexport function feature() {\n  // ${c.objective}\n  return true;\n}\n` }];
}

const EXPORT_TEST = `import { describe, it, expect } from 'vitest';
import { buildExport } from '../../src/export/exportJob';
import { seedTwoTenants, readCsv } from '../helpers';

describe('export des données clients', () => {
  it("n’exporte que les données du client demandeur", async () => {
    const { tenantA, tenantB } = await seedTwoTenants();
    const key = await buildExport({ id: 'e1', tenantId: tenantA.id, requestedBy: 'admin-a', since: new Date(0) });
    const rows = await readCsv(key);
    expect(rows.every((r) => tenantA.contactIds.includes(r.id))).toBe(true);
    expect(rows.some((r) => tenantB.contactIds.includes(r.id))).toBe(false);
  });

  it('range le fichier sous le préfixe du client', async () => {
    const { tenantA } = await seedTwoTenants();
    const key = await buildExport({ id: 'e2', tenantId: tenantA.id, requestedBy: 'admin-a', since: new Date(0) });
    expect(key.startsWith(\`exports/\${tenantA.id}/\`)).toBe(true);
  });
});
`;

function exportOpenApi(retention: string) {
  return `openapi: 3.1.0
info:
  title: Atlas CRM — Exports
  version: 1.0.0
  description: Demande et suivi des exports de données clients. Disponibilité du fichier — ${retention} jours.
paths:
  /v1/exports:
    post:
      summary: Demander un export des données de l'organisation
      security: [{ oauth2: [export] }]
      responses:
        '202': { description: Demande acceptée, content: { application/json: { schema: { $ref: '#/components/schemas/Export' } } } }
        '403': { description: Permission « export » manquante }
  /v1/exports/{id}:
    get:
      summary: Consulter l'état d'un export
      parameters: [{ name: id, in: path, required: true, schema: { type: string } }]
      responses:
        '200': { description: État de l'export, content: { application/json: { schema: { $ref: '#/components/schemas/Export' } } } }
        '404': { description: Export inconnu ou appartenant à une autre organisation }
components:
  schemas:
    Export:
      type: object
      required: [exportId, state]
      properties:
        exportId: { type: string }
        state: { type: string, enum: [pending, ready, expired, failed] }
        downloadUrl: { type: string, format: uri, description: URL signée, valable ${retention} jours }
`;
}

function genericOpenApi(c: GenerationContext) {
  return `openapi: 3.1.0\ninfo:\n  title: ${c.productName}\n  version: 0.1.0\n  description: ${c.questTitle}\npaths: {}\n`;
}
