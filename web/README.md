# Open Guild Kit — interface web

L'interface a deux modes, avec les mêmes 12 lieux et les mêmes styles RPG et Pro.

- **Projet réel** : `openguildkit ui` sert la page sur 127.0.0.1 pour le projet du dossier courant. Chaque écran lit le projet et chaque action lance une commande de la CLI ; les validations restent dans le terminal d'une personne. [Interface d'un projet réel](docs/interface-projet.md)
- **Démonstration** : servie sans la CLI (`npm run dev`, hébergement statique, ou `?demo=1`), elle montre l'expérience complète sur l'organisation fictive Atelier Nova.

## Démonstration Atelier Nova

Maquette fonctionnelle de l’expérience complète d’Open Guild Kit, en pixel art RPG : 12 lieux (Royaume, Blueprint, Guilde, Conseil, Quêtes, Bibliothèque, Forge, Tour de guet, Observatoire, Documentation, Chroniques, Intendance), règles de gestion RG-01 à RG-42 dans le domaine, services externes simulés par des adaptateurs déterministes.

L'interrupteur **RPG / Pro** de la barre du haut change le style sans toucher au travail ouvert : RPG montre les scènes illustrées, Pro garde les mêmes écrans sur des surfaces claires et sobres.

Les créations, modifications, validations, transitions, versions, imports, exports et relations sont réellement enregistrés dans le navigateur (localStorage). Tout résultat externe (analyse de dépôt, avis d’agents, contrôles, veille, intégrations) est marqué « Simulation ».

## Lancer

Utilise Node 22.12 ou Node 24, la version de la CI.

```bash
cd web
npm ci
npm run dev          # http://localhost:5199
npm run build        # typecheck + build dans dist/
npm run preview      # sert dist/ sur http://localhost:5198
npm run bundle       # copie dist/ dans le paquet Python (src/openguildkit/web_dist)
```

Pour travailler sur le mode réel : `openguildkit ui --no-browser` dans un projet, puis `OGK_API=http://127.0.0.1:7311 npm run dev`. `python scripts/sample-project.py DOSSIER` crée un projet d'exemple avec une quête dans chaque état.

## Vérifier

```bash
npm run typecheck    # TypeScript strict
npm test             # 38 tests Vitest : 28 de domaine (règles sensibles, parcours principal) et 10 du mode réel
npm run e2e          # parcours de la démonstration (Playwright, Chrome installé localement)
npm run e2e:project  # 25 parcours et 2 balayages du mode réel sur des projets d'exemple neufs servis par openguildkit ui (après npm run build)
npm run measure:project -- http://127.0.0.1:7311   # temps d'affichage, requêtes et volumes de chaque lieu du mode réel
npm run catalogue    # régénère src/fixtures/catalogue.json depuis data/SOCLE_Catalogue_395_References.md
npm run docs:roles   # régénère docs/roles.md depuis les capacités du domaine
CAPTURES=1 npm run e2e -- captures   # régénère docs/captures-apres (RPG) et docs/captures-pro
node scripts/measure.mjs http://localhost:5209 5   # mesures de performance d'une build servie par `npm run preview`
```

`npm run e2e` utilise Chrome installé (`channel: chrome`). Tu peux aussi installer Chromium avec `npx playwright install chromium`, puis définir `PW_CHANNEL=chromium` avant `npm run e2e`. Les tests déposent leurs captures dans `test-results/`. [Captures comparatives et mesures](docs/verification.md)

## Parcours de démonstration

1. Écran d’entrée › **Charger Atelier Nova** (organisation SaaS B2B fictive).
2. Ouvre **Parcours de démonstration** depuis la navigation. Le panneau suit les 20 étapes du projet d'export des données clients et coche chacune d'après les objets enregistrés dans la démo.
3. Les changements d’acteur (auteur, approbatrice distincte, lecteur, auditeur, agent IA), l’injection d’échecs, l’avancée de l’horloge et le rechargement du scénario sont dans **Intendance › Démonstration**.

**Créer une organisation** mène au questionnaire initial, jusqu'à la publication du premier Blueprint.

## Organisation du code

| Dossier | Rôle |
| --- | --- |
| `src/domain` | Types, permissions (`authorize`), machines d’états (`machines.ts`), moteur de commandes atomiques (`engine.ts`), sélecteurs dérivés (fraîcheur, clôture, impacts, notifications, traçabilité), commandes métier (`commands/`). |
| `src/adapters` | Catalogue (parseur Markdown/JSON, validation, doublons), stockage versionné, exports réels (MD, JSON, YAML, HTML autonome, SVG), simulations (`simulation/`) derrière `services.ts`. |
| `src/fixtures` | Scénario Atelier Nova, expertises, skills et contrôles, réutilisation du registre CLI (`../src/openguildkit/registry`). |
| `src/shared` | Design system (`ui/`), moteur pixel art (`pixel/` : bâtiments, portraits, carte, icônes dessinés par primitives). |
| `src/features` | Un dossier par lieu de la démonstration. |
| `src/project` | Mode réel : client de l'API locale, cache des commandes, libellés, un fichier par lieu dans `views/`. Le serveur est `../src/openguildkit/webui.py`. |
| `tests/domain`, `tests/e2e` | Tests Vitest et Playwright. |

Données d’entrée : `data/SOCLE_Catalogue_395_References.md` (395 références, 37 catégories, 12 familles, édition du 20 novembre 2026), converti en `src/fixtures/catalogue.json` avec contrôle de comptage.

[Interface d'un projet réel](docs/interface-projet.md) · [Domaine et règles de gestion](docs/domaine.md) · [Périmètre fonctionnel](docs/matrice-perimetre.md) · [Rôles](docs/roles.md) · [Adaptateurs](docs/adaptateurs.md) · [Formats d'échange](docs/formats.md) · [Charte et assets](docs/assets.md) · [Accessibilité](docs/accessibilite.md) · [Vérifications](docs/verification.md)
