# Reprise du chantier

Mis à jour le 21 novembre 2026 en fin d'après-midi par Claude (Opus 5.5), après une passe d'optimisation et de tests. Remplace la version de midi.

## Où en est le projet

L'interface web a maintenant deux modes, avec les mêmes 12 lieux et les mêmes styles RPG et Pro.

- **Projet réel**, nouveau : `openguildkit ui` sert la page sur 127.0.0.1 pour le projet du dossier courant. Chaque écran lit le projet, chaque action lance une commande de la CLI. Il couvre ce que la CLI de `main` (0.16.1, commit 9fa0cc4) sait faire : installation, profil, routage et consultation, passes par cerveau, avis, délibération, blocages, décision, passation, vérifications, résultats, clôture, alertes de dépendances, dossiers de marché et veille, livrables, outils et MCP avec simulations, Storybook, export Documentalist et partages, mise à jour du catalogue, réglages de l'hôte. [Interface d'un projet réel](docs/interface-projet.md)
- **Démonstration** Atelier Nova, inchangée sur le fond : servie sans la CLI, ou avec `?demo=1`.

Tout est sur la branche locale `feat/guild-web-app`, rebasée sur `origin/main` 9fa0cc4. **Rien n'est commité ni poussé**, à la demande de Lou.

`git status` :

- modifiés : `.github/workflows/ci.yml`, `.gitignore`, `README.md`, `README.fr.md`, `pyproject.toml`, `src/openguildkit/cli.py` ;
- nouveaux : `src/openguildkit/webui.py`, `tests/test_webui.py`, `web/`.
- retouché : `tests/test_alerts.py` (deux assertions forcent l'absence de terminal ; note de coordination du soir).

## Fichiers touchés hors de web/

Le côté Python appartient à Codex (`.openguildkit-coordination.md`, note du 21 novembre 11h). J'y ai ajouté :

- `src/openguildkit/webui.py` : le serveur et l'API ;
- dans `src/openguildkit/cli.py` : le sous-parseur `ui`, deux lignes dans `_run`, et un correctif de `_print_rule_plan` (sa sortie ne suivait pas une redirection de `sys.stdout`, donc `preview` renvoyait une réponse vide au serveur) ;
- dans `pyproject.toml` : `web_dist/**/*` dans le package-data ;
- `tests/test_webui.py`.

La CI (`package`) construit le front, le copie dans le paquet (`npm run bundle`) et vérifie que la wheel installée trouve l'interface. `src/openguildkit/web_dist/` est ignoré par Git.

## Vérifié le 21 novembre 2026

| Contrôle | Résultat |
| --- | --- |
| `npm run typecheck` | OK |
| `npm test` | 38/38 (28 de domaine, 10 du mode réel) |
| `npm run build` | OK, aucun bloc au-dessus de 500 Ko (le plus gros : 316 Ko), sans relever la limite |
| `npm run e2e` (démonstration) | 11 réussis, 1 ignoré (captures, `CAPTURES=1`) |
| `npm run e2e:project` (mode réel) | 27/27 : 25 parcours, une fois par action de l'interface, et 2 balayages de 34 routes (bureau RPG, mobile Pro). Trois exécutions de suite sans échec |
| `python -m unittest tests.test_webui` | 20/20 |
| `npm run measure:project` | premier écran 341 ms, changement de lieu 3 à 51 ms (voir `docs/interface-projet.md#performances`) |
| Suite Python complète | 303 tests, 8 ignorés, tous réussis, sans redirection de l'entrée standard (`test_alerts` force maintenant l'absence de terminal, comme `test_core`) |
| Wheel | 3,9 Mo, avec l'interface (128 fichiers, 3,7 Mo avant compression). Le logo PNG en double et les polices non latines ne sont plus embarqués |

Revue visuelle dans le navigateur intégré : les 12 lieux en RPG et en Pro, sur bureau (1440 px) et mobile (375 px), sans défilement horizontal. Le balayage automatique contrôle en plus, sur chaque route : un seul titre principal, chaque champ et bouton nommés, aucun identifiant en double, aucune erreur.

## Corrigé pendant ce chantier

- Serveur : l'analyse des arguments redirigeait la sortie standard hors du verrou ; deux requêtes simultanées pouvaient avaler la sortie d'une commande. Tout passe sous le même verrou (test de concurrence ajouté).
- Serveur : sous Windows, la file d'attente des connexions (5) débordait au chargement d'une page ; elle passe à 64 et le front réessaie une fois.
- Front : une invalidation du cache pendant un chargement en cours était perdue ; l'entrée reste périmée et se recharge.
- Front : une page restée ouverte après une reconstruction n'est plus un écran vide ; elle propose de recharger.
- Démonstration : ma règle mobile `.grid-2` écrasait le `minmax(0, 1fr)` de la démo et créait un défilement horizontal ; elle est limitée au mode réel.
- Formats mal supposés, trouvés en vérifiant chaque action contre le code de la CLI : propositions Storybook (`components`, `variants`, `tokens` avec `status`), état d'un partage expiré (`"expired: remove the access in Documentalist"`, jamais compté avant), revue d'une alerte (`by`, `reason`, `accepted`), actions de `task authorize` et champ `decision`. Le script d'exemple n'inventoriait rien (chemin relatif au mauvais dossier).
- Performances : React 19 retient environ 300 ms l'affichage d'un lieu chargé à la demande ; les lieux sont maintenant préchargés et le premier est chargé avant le rendu. Le serveur garde l'analyseur, le catalogue et le verrou entre deux commandes (`Speedups`). Les réponses ne portent plus le texte en double, omettent ce que l'écran n'affiche pas et sont compressées.
- Un fichier absent (propositions Storybook, profil d'un projet pas installé) n'est plus une erreur 404 dans la console.

## À faire

1. **Décisions de Lou avant tout commit** : celles du matin restent ouvertes (catalogue SOCLE dans le dépôt public, conditions d'usage des images ImageGen, `docs/art` de 22 Mo). S'y ajoute : la wheel passe de quelques centaines de Ko à 3,9 Mo, surtout à cause des décors et personnages de la démo (environ 1,4 Mo).
2. Faire relire `webui.py`, la ligne `ui` de `cli.py` et le package-data par Codex (voir la note de coordination).
3. Commit sur `feat/guild-web-app`, puis PR vers `main` (check `contribution-checks`, squash). La CI n'a pas encore tourné avec les nouvelles étapes du job `package` ni le job `web`.
4. Le job CI `web-e2e` (parcours de la démo et de l'interface projet, avec le Chrome du runner Ubuntu) n'a encore jamais tourné. Il n'est pas requis par `contribution-checks` : l'y ajouter après un premier passage vert sur main.
5. Pas de test avec lecteur d'écran ni de mesure de chaque cible tactile.

## Pièges connus

- Les décisions réservées au terminal (valider, déroger, autoriser, accepter ou écarter une alerte critique) ne passent jamais par l'interface. Ne pas « simplifier » `check_request` dans `webui.py`.
- Après `npm run build`, une page ouverte doit être rechargée : les noms des fichiers changent.
- `npm run e2e:project` refuse de démarrer si le port 7322 ou 7323 est occupé, par exemple par un serveur d'une exécution précédente.
- `Speedups` (dans `webui.py`) remplace `cli._parser`, `cli.load_catalog` et `cli.read_lock` pendant les commandes du serveur seulement ; si l'une de ces fonctions change de nom, le serveur s'en passe. Un nouveau fichier lu par ces fonctions doit entrer dans leur signature de cache.
- Pour mesurer, le panneau navigateur de l'application ne convient pas : en arrière-plan, Chrome y ralentit les minuteries. Utilisez `npm run measure:project`.
- **Ne lancez pas `npm ci` quand un serveur `vite` tourne sur ce dossier** : Windows verrouille `@rolldown/.../*.node`. Arrêtez les serveurs d'abord, ou réparez avec `npm install`.
- Testez la démonstration sur un autre port que 5199 (serveur de dev de Lou) : le localStorage est par origine. `playwright.config.ts` utilise 5201 par défaut (`PW_PORT`).
- Chaînes d'interface en français avec apostrophe typographique `’` : les tests comparent des messages.
- Démonstration : les règles métier vivent dans `src/domain` ; les composants appellent `dispatch(cmd.x, …)`. Mode réel : les règles sont celles de la CLI ; le front ne duplique aucune garde, il affiche le refus de la CLI.
- `.claude/launch.json` (exclu via `.git/info/exclude`) déclare `ogk-web` (5199), `ogk-web-test` (5200) et `ogk-ui-sample` (7321, sur un projet d'exemple du dossier temporaire de la session).
