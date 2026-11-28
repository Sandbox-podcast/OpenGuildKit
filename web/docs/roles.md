# Rôles et capacités

> Démonstration Atelier Nova : cette page décrit la maquette, pas le produit. [Ce qui les distingue](interface-projet.md#ce-qui-distingue-la-démonstration)

Matrice générée depuis [permissions.ts](../src/demo/domain/permissions.ts) avec `npm run docs:roles`. Une case vide indique que le rôle ne donne pas cette capacité.

| Capacité | Propriétaire | Admin | Mainteneur | Contributeur | Lecteur | Auditeur | Agent IA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Consulter | Oui | Oui | Oui | Oui | Oui | Oui | Oui |
| Proposer | Oui | Oui | Oui | Oui |  |  | Oui |
| Modifier | Oui | Oui | Oui | Oui |  |  |  |
| Publier | Oui | Oui | Oui |  |  |  |  |
| Approuver | Oui | Oui | Oui |  |  |  |  |
| Gérer les membres | Oui | Oui |  |  |  |  |  |
| Configurer les agents | Oui | Oui |  |  |  |  |  |
| Lancer les contrôles | Oui | Oui | Oui | Oui |  |  |  |
| Demander une exception | Oui | Oui | Oui | Oui |  |  |  |
| Approuver une exception | Oui | Oui |  |  |  |  |  |
| Exporter | Oui | Oui | Oui | Oui |  | Oui |  |
| Partager | Oui | Oui | Oui |  |  |  |  |
| Archiver et restaurer | Oui | Oui | Oui |  |  |  |  |
| Paramétrer l'organisation | Oui | Oui |  |  |  |  |  |

Les rôles sont attribués à l'organisation ou à un projet. Pour une action portant sur un projet, les capacités issues de ces deux périmètres se cumulent. Un projet archivé reste consultable, exportable et restaurable par les rôles habilités.

La commande tient aussi compte des règles métier. Elle peut exiger un approbateur distinct de l'auteur, une version précise ou une justification. Ces vérifications s'exécutent dans le navigateur et simulent les autorisations du domaine.
