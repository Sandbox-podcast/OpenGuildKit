# Interface d'un projet réel

`openguildkit ui` ouvre l'interface web sur le projet du dossier courant. La page est la même que la démonstration, avec ses deux styles RPG et Pro, mais chaque écran lit le projet et chaque action lance une commande de la CLI. Rien n'y est simulé.

## Lancer

OpenGuildKit n'est pas sur PyPI : installe la roue d'une release GitHub, qui embarque l'interface construite ([installation](../../docs/install.md)).

```bash
pipx install ./openguildkit-X.Y.Z-py3-none-any.whl
cd mon-projet
openguildkit ui                   # http://127.0.0.1:7311, ouvre le navigateur
openguildkit ui --port 0 --no-browser
```

Le serveur écoute seulement sur 127.0.0.1. Si le port 7311 est pris, il en choisit un libre et l'affiche. Ctrl+C l'arrête.

Dans un projet sans `.openguildkit/project.json`, la page ouvre l'installation : le questionnaire de `init`, le plan des packs de règles qui s'appliqueront, puis l'écriture du profil.

## Ce que fait chaque lieu

| Lieu | Ce qu'on y fait | Commandes |
| --- | --- | --- |
| Royaume | Les actions qui attendent une personne ou l'agent, les quêtes par état, la carte avec les compteurs | `task list`, `check`, `alerts list`, `docs share list`, `market due --all`, `update`, `host check` |
| Blueprint | Installer le projet, modifier le profil, adopter ou refuser une norme ou un pattern, lire les packs en vigueur et leur origine, la pile détectée et les patterns | `init --questions`, `init --answers`, `preview`, `detect`, `recommend`, `sync`, `profile adopt`, `profile decline` |
| Guilde | Les cerveaux, leurs lentilles, leurs questions, leurs critères de décision et leurs connaissances | `brains --json`, `brains --id` |
| Conseil | Cadrer une quête, prévisualiser et ajuster le routage (avec les cerveaux écartés par le brief et ceux que l'équipe attendait), consulter, réviser le brief après une demande de changements, suivre les passes par cerveau et relire une passe, lire les avis, délibérer, préparer la levée des blocages, décider | `task questions`, `task route`, `task consult` (`--brief-file`), `task progress`, `task pass`, `task brief --board`, `task submit`, `task review`, `task challenge`, `task deliberate`, `task respond`, `task blockers`, `task clear --signature`, `task decide --request-changes` |
| Quêtes | Toutes les quêtes par état, une nouvelle quête, la fiche d'une quête avec sa prochaine étape | `task list`, `task new`, `task show`, `task export` |
| Bibliothèque | Les références, les patterns, les packs avec chaque règle et sa vérification, les secteurs | `references`, `patterns`, `catalog`, `preview` |
| Forge | La passation, les conditions de la validation, les vérifications, les résultats, la clôture et ses réserves ; les livrables métier ; les outils et serveurs MCP, avec leurs simulations ; le design system extrait d'une application | `task handoff`, `task blockers`, `task checks`, `task verify`, `task result`, `task complete`, `task authorize --deny`, `task runs`, `deliverable`, `tools`, `storybook` |
| Tour de guet | La cohérence des instructions, ce que l'hôte applique, la garde, le registre des alertes de dépendances, les blocages ouverts | `check`, `host check`, `host apply`, `guard`, `alerts import`, `alerts set`, `alerts link` |
| Observatoire | Les dossiers de marché, leurs lacunes, la veille des concurrents | `market new`, `competitor`, `observe`, `unknown`, `watch`, `checked`, `change`, `pause`, `resume`, `check`, `due` |
| Documentation | L'export des quêtes terminées pour Documentalist, le registre des partages, les relevés de décision | `docs export`, `docs share add`, `revoke`, `check`, `.openguildkit/decisions/` |
| Chroniques | L'historique reconstruit à partir des enregistrements des quêtes | `task show` |
| Intendance | Les réglages de l'hôte, les fichiers de l'agent, l'adoption du catalogue installé, le fonctionnement de l'interface | `host apply`, `integrations`, `update --apply`, `sync` |

Les textes renvoyés par la CLI en anglais (prochaine étape, questions du cadrage, points ouverts) sont affichés en français quand leur forme est connue. Les avis des cerveaux restent dans la langue où l'agent les a écrits.

## Ce que l'interface ne fait jamais

La CLI demande une personne devant un terminal pour valider une quête, lever ou déroger à un blocage, autoriser une action externe, accepter une alerte confirmée, écarter une alerte critique ou fixer la sévérité d'une alerte, déclarer qu'une commande de vérification ne peut pas tourner ici (`task verify --cannot-run`, `--withdraw`), clore une quête par-dessus des points sensibles (`task complete --by`), et pour un changement du profil qui affaiblit une protection : baisser la garde, ouvrir la recherche publique, retirer ou refuser une réglementation. L'interface n'enregistre aucune de ces décisions. Elle affiche la commande exacte, à copier dans son propre terminal :

```text
openguildkit --project 'C:\…\mon-projet' task decide request-export --approve --by 'Camille Martin' --reason '…'
```

Dans un projet à approbation signée, la page guide la signature : `task decision-payload` (ou `task clear --payload` pour lever un blocage), `ssh-keygen -Y sign`, puis le dépôt de la signature, que la CLI vérifie.

Une commande qui échoue peut avoir enregistré quelque chose : `task verify` sort en 1 quand une commande obligatoire échoue mais garde le résultat de chaque contrôle, `task submit` garde la passe en échec avec la liste de ses problèmes. La page affiche ce que la commande a dit et se recharge. `tools apply --mock` sort en 0 quand chaque outil est connecté, en 2 quand une partie l'est, en 1 quand aucun ne l'est ; la page le dit.

Elle n'appelle aucune IA et n'ouvre aucune connexion vers l'extérieur. Les avis des cerveaux viennent de l'agent du projet (Claude Code, Codex) : la page lui donne la consigne et le brief de chaque passe, puis reçoit les avis qu'il dépose.

## Sécurité du serveur local

- Écoute sur 127.0.0.1 uniquement. L'en-tête `Host` doit être `127.0.0.1`, `localhost` ou `[::1]` avec le bon port, ce qui bloque le rebinding DNS.
- Chaque appel de l'API est un `POST` JSON qui porte l'origine de la page et un jeton de session tiré au lancement. Une page d'un autre site ne peut ni lire le jeton ni appeler l'API.
- Les commandes passent par l'analyseur de la CLI, puis par une liste de refus : `ci-check`, `ui`, `guard --hook`, `tools mock`, `integrations --user`, et les décisions réservées au terminal ci-dessus. Les abréviations d'options (`--appr`) sont résolues avant le contrôle.
- Pendant chaque commande, l'entrée standard n'est jamais un terminal, même si le serveur tourne dans un terminal : une invite interactive échoue au lieu d'attendre.
- Les fichiers lus ou écrits restent dans le projet, hors `.git`. Les fichiers envoyés par la page (avis, rapport de scanner, résultats) passent par un dossier temporaire supprimé après la commande. La lecture refuse `.env` et les noms qui évoquent un secret.
- La page écrit directement deux fichiers seulement : `.openguildkit/project.json`, suivi de `sync` (le profil précédent est remis si la CLI le refuse ; un changement qui affaiblit une protection est refusé avant d'écrire, avec la commande `profile` à taper), et `.openguildkit/storybook/proposals.json`.
- Les commandes s'exécutent une à la fois, dans le processus du serveur, sous un verrou. Une page envoie un fichier absent du projet comme une réponse vide, pas comme une erreur.

Un autre programme du poste peut appeler l'API comme il peut lancer la CLI : le serveur ne donne aucun droit de plus que le terminal.

## Développer l'interface

```bash
python web/scripts/sample-project.py /tmp/portail     # projet d'exemple : une quête dans chaque état
openguildkit --project /tmp/portail ui --no-browser --port 7311
cd web
OGK_API=http://127.0.0.1:7311 npm run dev             # rechargement à chaud sur le projet réel
```

Sans `OGK_API`, `npm run dev` ouvre la démonstration. `?demo=1` force la démonstration sur une page servie par `openguildkit ui`.

Le code du mode réel est dans `src/project/` : le client de l'API (`api.ts`), le cache des commandes (`query.ts`), les données communes (`data.ts`), les libellés (`labels.ts`) et un fichier par lieu dans `views/`. Chaque lieu est chargé à la demande. Le serveur est `src/openguildkit/webui.py`.

## Empaqueter

```bash
cd web && npm ci --ignore-scripts && npm run build && npm run bundle   # copie dist/ dans src/openguildkit/web_dist
python -m build --wheel
```

La release (`.github/workflows/release.yml`) et le job CI `package` font ces étapes, et refusent une roue sans `openguildkit/web_dist/index.html`. Le job `package` installe ensuite la roue sur Linux, macOS et Windows (avec `pipx` sous Windows) et vérifie que `openguildkit ui` répond 200 sur `/` avec chaque script de la page (`.github/scripts/check-installed-cli.py`). Dans un dépôt source, le serveur prend la plus récente des deux : `web/dist` ou la copie de `web_dist`.

## Performances

Le serveur garde entre deux commandes ce que chaque commande de la CLI reconstruit : l'analyseur d'arguments, le catalogue validé et le verrou du catalogue. Il les reprend tant que leurs fichiers n'ont pas changé, et chaque commande en reçoit sa propre copie. Une commande lancée par la page prend 2 à 25 ms, contre 70 à 130 ms pour la même commande lancée seule.

- Une réponse JSON ne porte pas le texte imprimé en double. Un écran peut demander d'omettre les champs qu'il n'affiche pas : la fiche d'une quête laisse le texte de la consultation sur le serveur, l'historique ne garde que les dates et les décisions.
- Les réponses de plus de 2 Ko sont compressées quand le navigateur l'accepte, ce qui compte à travers un tunnel SSH ou un port redirigé.
- La vue d'ensemble (quêtes, contrôle des instructions, alertes, partages, veille, catalogue, hôte) part en une seule requête. Elle seule se recharge après une action ; ce qui ne dépend que du catalogue (cerveaux, références, packs, outils, modèles) ne se recharge qu'après `sync`, `update`, `init` ou une modification du profil.
- Le lieu de l'adresse ouverte est chargé avant le premier rendu ; les autres se chargent en arrière-plan ensuite. Changer de lieu ne passe donc jamais par l'écran d'attente que React 19 retient environ 300 ms.

Mesures du 21 novembre 2026 sur le projet d'exemple, avec `node scripts/measure-project.mjs http://127.0.0.1:7311` (Chrome, navigateur neuf à chaque exécution, médiane de 3) :

| Écran | Temps d'affichage | Requêtes d'API | Données reçues (décompressées) |
| --- | ---: | ---: | ---: |
| Premier écran (Royaume) | 341 ms | 4 | 508 Ko, dont 219 Ko de React |
| Quêtes, Guilde, Tour de guet, Intendance, Blueprint | 3 à 15 ms | 0 | 2 à 43 Ko |
| Conseil d'une quête | 17 ms | 3 | 31 Ko |
| Forge d'une quête | 28 ms | 3 | 11 Ko |
| Bibliothèque (464 références) | 51 ms | 1 | 308 Ko |
| Chroniques | 50 ms | 1 | 49 Ko |

Avant ces optimisations, chaque changement de lieu prenait environ 320 ms, le premier écran environ 900 ms, et les Chroniques recevaient 1,3 Mo.

## Vérifier

```bash
python -m unittest tests.test_webui                    # 26 tests du serveur : hôtes, origine, jeton, refus, chemins, envois, concurrence, cache, compression, profil
cd web && npm test                                     # dont 10 tests unitaires du mode réel : libellés, citations, signaux, cache
npm run build && npm run e2e:project                   # 27 parcours et 2 balayages sur des projets d'exemple neufs
```

`npm run e2e:project` construit un projet d'exemple dans un dossier temporaire et le sert sur le port 7322 (`PW_PROJECT_PORT`), plus un dossier vide sur le port 7323 pour l'installation. Les parcours passent par chaque action de l'interface : nouvelle quête, refus de valider à la place d'une personne, dérogation, levée d'un blocage et autorisation renvoyées au terminal, arbitrage, renvoi au Conseil, cadrage et consultation, passes et avis de chaque cerveau, synthèse, refus d'une action externe, passation, vérifications, résultats et clôture, livrable métier, outil connecté et sa simulation, design system extrait puis généré, import d'un rapport de scanner, revue d'alerte et alerte critique renvoyée au terminal, contrôles, dossier de marché et veille, export Documentalist, partage puis retrait, historique, profil (y compris un profil refusé puis remis, et une protection affaiblie renvoyée au terminal), fichiers de l'agent, bibliothèque, recherche, raccourcis clavier, style Pro, installation d'un dossier vide. Les deux balayages ouvrent 34 routes en RPG sur bureau et en Pro sur mobile : aucune erreur, un seul titre principal, chaque champ et chaque bouton nommés, aucun identifiant en double, pas de défilement horizontal.
