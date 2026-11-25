# Open Guild Kit — interface web

L'interface a deux modes, avec les mêmes 12 lieux et les mêmes styles RPG et Pro.

- **Projet réel** : `openguildkit ui` sert la page sur 127.0.0.1 pour le projet du dossier courant. Chaque écran lit le projet et chaque action lance une commande de la CLI ; les validations restent dans le terminal d'une personne. C'est le seul mode que le paquet Python embarque. [Interface d'un projet réel](docs/interface-projet.md)
- **Démonstration** : lancée depuis ce dossier (`npm run dev`), sans la CLI, elle montre l'expérience sur l'organisation fictive Atelier Nova. Elle n'est pas dans le paquet : sur une page servie par `openguildkit ui`, `?demo=1` dit comment la lancer.

## Démonstration Atelier Nova

Maquette de l'expérience d'Open Guild Kit en pixel art RPG, sur une organisation fictive : 12 lieux (Royaume, Blueprint, Guilde, Conseil, Quêtes, Bibliothèque, Forge, Tour de guet, Observatoire, Documentation, Chroniques, Intendance), règles de gestion RG-01 à RG-42 dans le domaine, services externes simulés par des adaptateurs déterministes.

Elle diffère du produit sur trois points, détaillés dans [Interface d'un projet réel](docs/interface-projet.md#ce-qui-distingue-la-démonstration) :

- « Approuver » et « Refuser » affichent la commande que la personne tape dans son terminal, comme dans le produit, où la page n'enregistre jamais une décision. La démo n'a pas de terminal : « Simuler la commande » joue cette saisie.
- Les rôles (propriétaire, mainteneur, contributeur, lecteur, auditeur, agent IA) n'existent que dans la démo ; la CLI demande le nom de la personne qui décide.
- La démo valide chaque version d'un livrable et du Blueprint ; la CLI approuve une tâche et vérifie ses livrables.

L'interrupteur **RPG / Pro** de la barre du haut change le style sans toucher au travail ouvert : RPG montre les scènes illustrées, Pro garde les mêmes écrans sur des surfaces claires et sobres.

Les créations, modifications, transitions, versions, imports, exports et relations sont réellement enregistrés dans le navigateur (localStorage). Tout résultat externe (analyse de dépôt, avis d’agents, contrôles, veille, intégrations) est marqué « Simulation ».

## Lancer

Utilise Node 22.12 ou Node 24, la version de la CI.

```bash
cd web
npm ci --ignore-scripts
npm run dev          # http://localhost:5199 : la démonstration, ou le projet avec OGK_API
npm run build        # typecheck + build de l'interface d'un projet dans dist/, sans la démo
npm run bundle       # copie dist/ dans le paquet Python (src/openguildkit/web_dist) et vérifie son budget
npm run build:demo   # build de la démonstration seule dans dist-demo/, servie par npm run preview:demo
```

`npm run bundle` refuse une construction qui contient la démo ou qui dépasse 1 298 Ko (`BUDGET_KB` dans `scripts/bundle.mjs` : la taille mesurée le 22 novembre 2026, plus 10 %). Relève ce budget seulement avec la mesure qui le justifie.

Pour travailler sur le mode réel : `openguildkit ui --no-browser` dans un projet, puis `OGK_API=http://ogk-….localhost:7311 npm run dev` avec l'origine de l'adresse imprimée, et ouvre une fois `http://localhost:5199/api/session?key=…` avec la clé de cette adresse avant `http://localhost:5199/`. `python scripts/sample-project.py DOSSIER` crée un projet d'exemple avec une quête dans chaque état.

## Vérifier

```bash
npm run typecheck    # TypeScript strict
npm test             # tests Vitest : domaine de la démo (règles sensibles, parcours principal, commandes du terminal), mode réel, script d'empaquetage
npm run e2e          # parcours de la démonstration (Playwright, Chrome installé localement)
npm run e2e:project  # parcours et balayages du mode réel sur des projets d'exemple neufs servis par openguildkit ui (après npm run build)
npm run measure:project -- 'http://ogk-….localhost:7311/?key=…'   # l'adresse imprimée par openguildkit ui ; temps d'affichage, requêtes et volumes de chaque lieu du mode réel
npm run catalogue    # régénère src/fixtures/catalogue.json depuis data/SOCLE_Catalogue_395_References.md
npm run docs:roles   # régénère docs/roles.md depuis les capacités du domaine
CAPTURES=1 npm run e2e -- captures   # régénère docs/captures-apres (RPG) et docs/captures-pro
node scripts/measure.mjs http://localhost:5209 5   # mesures de performance de la démo servie par `npm run preview:demo`
```

Régénère les captures de `docs/captures-apres` (RPG) et `docs/captures-pro` après chaque changement visible de la démonstration (un lieu, un libellé, le style), avec `CAPTURES=1 npm run e2e -- captures`, et commite-les avec ce changement.

`npm run e2e` utilise Chrome installé (`channel: chrome`). Tu peux aussi installer Chromium avec `npx playwright install chromium`, puis définir `PW_CHANNEL=chromium` avant `npm run e2e`. Les tests déposent leurs captures dans `test-results/`. [Captures comparatives et mesures](docs/verification.md)

## Pièges connus

- Les décisions réservées au terminal (valider, retirer une validation, déroger, lever un blocage sans signature, autoriser une action externe, accepter ou écarter une alerte critique) ne passent jamais par l'interface. Ne « simplifie » pas `check_request` dans `src/openguildkit/webui.py`.
- Après `npm run build`, une page ouverte doit être rechargée : les noms des fichiers changent.
- `npm run e2e:project` refuse de démarrer si le port 7322 (`PW_PROJECT_PORT`) ou l’un des deux suivants est occupé, par exemple par le serveur d'une exécution précédente.
- Le serveur garde le catalogue entre deux commandes (le cache de `catalog.py`, invalidé quand un fichier change) : un nouveau fichier que lit le chargement du catalogue doit entrer dans sa signature.
- Pour mesurer, n'utilise pas un onglet en arrière-plan : Chrome y ralentit les minuteries. Utilise `npm run measure:project`.
- Ne lance pas `npm ci` quand un serveur `vite` tourne sur ce dossier : Windows verrouille `@rolldown/.../*.node`. Arrête les serveurs d'abord, ou répare avec `npm install`.
- Teste la démonstration sur un autre port que celui de ton serveur de développement (5199) : le localStorage est propre à chaque origine. `playwright.config.ts` utilise 5201 par défaut (`PW_PORT`).
- Les chaînes de l'interface sont en français avec l'apostrophe typographique `’` : les tests comparent des messages.
- Démonstration : les règles métier vivent dans `src/domain` ; les composants appellent `dispatch(cmd.x, …)`. Mode réel : les règles sont celles de la CLI ; le front ne duplique aucune garde, il affiche le refus de la CLI.

## Parcours de démonstration

1. Écran d’entrée › **Charger Atelier Nova** (organisation SaaS B2B fictive).
2. Ouvre **Parcours de démonstration** depuis la navigation. Le panneau suit les 20 étapes du projet d'export des données clients et coche chacune d'après les objets enregistrés dans la démo.
3. Les changements d’acteur (auteur, approbatrice distincte, lecteur, auditeur, agent IA), l’injection d’échecs, l’avancée de l’horloge et le rechargement du scénario sont dans **Intendance › Démonstration**.

**Créer une organisation** mène au questionnaire initial, jusqu'à la publication du premier Blueprint.

## Organisation du code

| Dossier | Rôle |
| --- | --- |
| `src/domain` | Types, permissions (`authorize`), machines d’états (`machines.ts`), moteur de commandes atomiques (`engine.ts`), sélecteurs dérivés (fraîcheur, clôture, impacts, notifications, traçabilité), commandes métier (`commands/`), commande du terminal de chaque décision d'une personne (`terminal.ts`). |
| `src/adapters` | Catalogue (parseur Markdown/JSON, validation, doublons), stockage versionné, exports réels (MD, JSON, YAML, HTML autonome, SVG), simulations (`simulation/`) derrière `services.ts`. |
| `src/fixtures` | Scénario Atelier Nova, expertises, skills et contrôles, réutilisation du registre CLI (`../src/openguildkit/registry`). |
| `src/shared` | Design system (`ui/`), moteur pixel art (`pixel/` : bâtiments, portraits, carte, icônes dessinés par primitives). |
| `src/features` | Un dossier par lieu de la démonstration. |
| `src/project` | Mode réel : client de l'API locale, cache des commandes, libellés, un fichier par lieu dans `views/`. Le serveur est `../src/openguildkit/webui.py`. |
| `tests/domain`, `tests/project`, `tests/scripts`, `tests/e2e` | Tests Vitest et Playwright. |

Données d’entrée : `data/SOCLE_Catalogue_395_References.md` (395 références, 37 catégories, 12 familles, édition du 20 novembre 2026), converti en `src/fixtures/catalogue.json` avec contrôle de comptage.

## Documentation

### Interface d'un projet

- [Interface d'un projet réel](docs/interface-projet.md), avec ce qui distingue la démonstration
- [Accessibilité](docs/accessibilite.md), des deux modes
- [Charte et assets](docs/assets.md)
- [Vérifications](docs/verification.md)

### Démonstration

Ces pages décrivent la maquette Atelier Nova, pas le produit.

- [Domaine et règles de gestion](docs/domaine.md)
- [Périmètre fonctionnel](docs/matrice-perimetre.md)
- [Rôles](docs/roles.md)
- [Adaptateurs de simulation](docs/adaptateurs.md)
- [Formats d'échange](docs/formats.md)
