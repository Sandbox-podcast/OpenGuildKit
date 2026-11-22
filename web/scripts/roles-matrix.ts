import { writeFileSync } from 'node:fs';
import { AGENT_CAPABILITIES, CAPABILITIES, ROLE_CAPABILITIES, ROLES, type Capability, type RoleId } from '../src/domain/permissions';

const roles = Object.keys(ROLES) as RoleId[];
const permissions = Object.entries(CAPABILITIES) as [Capability, string][];
const columns = ['Capacité', ...roles.map((role) => ROLES[role].short), 'Agent IA'];
const humanColumns = (capability: Capability) => roles.map((role) => ROLE_CAPABILITIES[role].includes(capability) ? 'Oui' : '');
const row = (cells: string[]) => `| ${cells.join(' | ')} |`;
const matrix = [
  row(columns),
  row(columns.map(() => '---')),
  ...permissions.map(([capability, label]) => row([label.replaceAll('’', "'"), ...humanColumns(capability), AGENT_CAPABILITIES.includes(capability) ? 'Oui' : ''])),
].join('\n');

writeFileSync(new URL('../docs/roles.md', import.meta.url), `# Rôles et capacités

> Démonstration Atelier Nova : cette page décrit la maquette, pas le produit. [Ce qui les distingue](interface-projet.md#ce-qui-distingue-la-démonstration)

Matrice générée depuis [permissions.ts](../src/domain/permissions.ts) avec \`npm run docs:roles\`. Une case vide indique que le rôle ne donne pas cette capacité.

${matrix}

Les rôles sont attribués à l'organisation ou à un projet. Pour une action portant sur un projet, les capacités issues de ces deux périmètres se cumulent. Un projet archivé reste consultable, exportable et restaurable par les rôles habilités.

La commande tient aussi compte des règles métier. Elle peut exiger un approbateur distinct de l'auteur, une version précise ou une justification. Ces vérifications s'exécutent dans le navigateur et simulent les autorisations du domaine.
`);
