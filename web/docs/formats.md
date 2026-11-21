# Formats d'échange

Les exports sont encodés en UTF-8. Les fichiers JSON structurés portent un identifiant de format. Dans l'interface, les imports acceptent les sauvegardes et les catalogues.

| Format | Champs principaux | Entrée ou sortie |
| --- | --- | --- |
| `ogk-blueprint/1` | `organisation`, `version`, `statut`, `publiee_le`, `auteur`, `relecture`, `justification`, `contexte`, `inconnues`, `regles`, `exclusions` | Export JSON et YAML du Blueprint choisi. La version Markdown présente le contexte, les règles et les exclusions. [Export Blueprint](../src/features/blueprint/Blueprint.tsx) |
| `ogk-catalogue/1` | `edition`, `title`, `notice`, `declared`, `references`. Chaque référence garde ses sources, sa catégorie, sa nature et son statut. | Données embarquées et import JSON. Le parseur accepte aussi le Markdown à sections et tableaux du catalogue. L'aperçu permet d'ajouter, de mettre à jour ou d'ignorer chaque ligne proposée. [Schéma du catalogue](../src/adapters/catalogue.ts) |
| `ogk-livrable/1` | `simulation`, `livrable`, `contenu`. JSON ajoute `meta` et `livrable.décrit` pour les versions de sources. | Export JSON ou YAML. Tous les types donnent aussi un Markdown. Les pages, présentations et documents Markdown donnent un HTML autonome. Les storyboards et feuilles de route donnent un SVG. [Exports des livrables](../src/adapters/export.ts) |
| `ogk-sauvegarde/1` | `exportedAt`, `schema`, `state`. `state` contient les organisations, les objets, le catalogue local, la session, les préférences et les brouillons. | Export JSON et import après validation. L'aperçu indique les conflits d'organisation et ouvre le choix entre fusion et remplacement. [Stockage et sauvegardes](../src/adapters/storage.ts) |
| `ogk-chroniques/1` | `note`, `evenements`. Chaque ligne conserve date, acteur, action, objet, version, provenance et justification disponible. | Export JSON de la sélection. YAML donne la liste des événements et Markdown un résumé. [Export des Chroniques](../src/features/chronicles/Chronicles.tsx) |

Le numéro à la fin du format identifie l'enveloppe d'échange. Le champ `schema` d'une sauvegarde identifie la structure interne du workspace. La lecture d'une sauvegarde passe par `parseWorkspace`, qui applique les migrations prévues et vérifie les relations avant l'import.
