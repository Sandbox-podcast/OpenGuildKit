# Interface d'un projet réel

`openguildkit ui` ouvre l'interface web sur le projet du dossier courant. Elle reprend les lieux et les deux styles RPG et Pro de la démonstration Atelier Nova, mais chaque écran lit le projet et chaque action lance une commande de la CLI. Rien n'y est simulé.

## Ce qui distingue la démonstration

La démonstration Atelier Nova ([web/README.md](../README.md#démonstration-atelier-nova)) montre l'expérience sur une organisation fictive, sans la CLI. Elle diffère du produit sur trois points :

- **L'approbation.** Dans le produit, une personne approuve, refuse ou déroge dans son propre terminal, et la page n'enregistre jamais ces décisions. Dans la démo, « Approuver » et « Refuser » affichent la même commande du terminal ; la démo, qui n'a pas de terminal, peut ensuite simuler sa saisie.
- **Les rôles.** Propriétaire, mainteneur, contributeur, lecteur, auditeur et agent IA n'existent que dans la démo ([rôles](roles.md)). La CLI n'a pas de rôles : elle demande le nom de la personne qui décide (`--by`).
- **Les versions de livrables et du Blueprint.** La démo valide chaque version d'un livrable et du Blueprint. La CLI approuve une tâche, vérifie ses livrables (`deliverable check`) et change le profil avec `openguildkit profile`.

La démo n'est pas dans le paquet : `openguildkit ui` ne la charge jamais, et `?demo=1` sur sa page dit comment la lancer depuis un clone du dépôt (`cd web && npm run dev`).

## Lancer

OpenGuildKit n'est pas sur PyPI : installe la roue d'une release GitHub, qui embarque l'interface construite ([installation](../../docs/install.md)).

```bash
pipx install ./openguildkit-X.Y.Z-py3-none-any.whl
cd mon-projet
openguildkit ui                   # imprime http://ogk-….localhost:7311/?key=… et l'ouvre
openguildkit ui --port 0 --no-browser
```

Le serveur écoute seulement sur 127.0.0.1, sous un nom d'hôte propre à chaque lancement (`ogk-….localhost`), que les navigateurs envoient à la boucle locale. Si le port 7311 est pris, il en choisit un libre et l'affiche. Ctrl+C l'arrête.

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
| Arsenal | Activer ou désactiver une fonctionnalité : un outil de l'équipe ou l'une de ses trois alternatives les plus connues, avec la personne qui décide et pourquoi, inscrits dans l'historique du profil ; après une désactivation, la connexion MCP qui donne encore l'outil à l'agent, avec la commande qui la retire | `features list`, `features enable`, `features disable`, `tools status` |

Les textes renvoyés par la CLI en anglais (prochaine étape, questions du cadrage, points ouverts) sont affichés en français quand leur forme est connue. Les avis des cerveaux restent dans la langue où l'agent les a écrits.

Dans l'onglet Réalisation, une pièce justificative marquée « réussie » demande son chemin (ou un lien https) et la personne qui l'a fournie (« Fournie par »). Le bouton qui marque « non applicables » les règles non rapportées laisse de côté les règles que les réponses de la tâche sélectionnent (les règles RGPD pour des données personnelles), les règles obligatoires et les pièces justificatives : chacune garde sa propre réponse et son motif. Une règle de protection des données, de sécurité ou d'IA sélectionnée et déclarée non applicable se confirme au terminal, par la personne qui clôt la tâche (`task complete --by`).

## Ce que l'interface ne fait jamais

La CLI demande une personne devant un terminal pour valider une quête, lever ou déroger à un blocage, autoriser une action externe, accepter une alerte confirmée, écarter une alerte critique ou fixer la sévérité d'une alerte, déclarer qu'une commande de vérification ne peut pas tourner ici (`task verify --cannot-run`, `--withdraw`), clore une quête par-dessus des points sensibles ou des règles sensibles déclarées non applicables (`task complete --by`), et pour un changement du profil qui affaiblit une protection : baisser la garde, ouvrir la recherche publique, retirer ou refuser une réglementation, changer l'approbation signée, ouvrir ou élargir les dérogations, retirer une règle, un cerveau ou une commande de vérification obligatoire. L'interface n'enregistre aucune de ces décisions. Elle affiche la commande exacte, à copier dans son propre terminal :

```text
openguildkit --project 'C:\…\mon-projet' task decide request-export --approve --by CM --reason '…'
```

Dans un projet à approbation signée, la page guide la signature : `task decision-payload` (ou `task clear --payload` pour lever un blocage), `ssh-keygen -Y sign`, puis le dépôt de la signature, que la CLI vérifie.

Une commande qui échoue peut avoir enregistré quelque chose : `task verify` sort en 1 quand une commande obligatoire échoue mais garde le résultat de chaque contrôle, `task submit` garde la passe en échec avec la liste de ses problèmes. La page affiche ce que la commande a dit et se recharge. `tools apply --mock` sort en 0 quand chaque outil est connecté, en 2 quand une partie l'est, en 1 quand aucun ne l'est ; la page le dit.

Elle n'appelle aucune IA et n'ouvre aucune connexion vers l'extérieur. Les avis des cerveaux viennent de l'agent du projet (Claude Code, Codex) : la page lui donne la consigne et le brief de chaque passe, puis reçoit les avis qu'il dépose.

## Sécurité du serveur local

Tout programme du poste peut ouvrir une connexion vers 127.0.0.1 : ceux d'un autre compte sur un poste partagé, une machine de build ou une VM de développement, un processus sandboxé qui a le droit d'ouvrir des sockets locales, et une page d'un autre site chargée dans le navigateur. Le serveur ne fait donc confiance qu'à la clé de l'adresse qu'il imprime.

- Écoute sur 127.0.0.1 uniquement. L'en-tête `Host` doit être le nom d'hôte du lancement avec le bon port, ce qui bloque le rebinding DNS. Sur `127.0.0.1`, `localhost` ou `[::1]`, la page affiche seulement l'invitation à ouvrir l'adresse imprimée, même avec la clé.
- `openguildkit ui` imprime une adresse qui porte une clé tirée au lancement, `http://ogk-….localhost:7311/?key=…`, et l'ouvre dans le navigateur. Seul le terminal qui a lancé la commande la voit. Le nom d'hôte `ogk-….localhost` est tiré de la clé. En ouvrant cette adresse, le navigateur reçoit la clé dans un cookie `HttpOnly` et `SameSite=Strict` de ce seul nom d'hôte (`ogk-7311`), et la clé quitte la barre d'adresse. Un navigateur envoie un cookie à tous les ports de l'hôte qui l'a posé : posé sur `127.0.0.1`, il partirait vers tout autre serveur du poste, comme le serveur de développement du projet. Sous le nom du lancement, aucun autre serveur ne le reçoit. Sans ce cookie, `/api/session` répond 403 (`open-printed-link`) et la page affiche, à la place de l'interface, l'invitation à ouvrir l'adresse imprimée. La clé change à chaque lancement : après un redémarrage, ouvre la nouvelle adresse.
- La clé protège la session : le jeton que `/api/session` remet à la page et que chaque appel de l'API porte. Un programme qui ne connaît pas la clé ne lit ni le jeton, ni le profil, ni les fichiers, et ne lance aucune commande. Elle ne protège pas d'un programme qui tourne sous ton propre compte : celui-là peut déjà lire les fichiers du projet et lancer la CLI.
- Chaque appel de l'API est un `POST` JSON qui porte l'origine de la page et le jeton. Une page d'un autre site ne peut ni lire le jeton ni appeler l'API.
- Sous Windows, le serveur réserve son port en exclusivité : un autre programme ne peut pas s'y lier pour recevoir les requêtes de la page.
- Un script qui lance le serveur pour son propre navigateur, comme les tests de bout en bout, peut fixer la clé avec `OPENGUILDKIT_UI_KEY` (32 à 128 lettres, chiffres, `-` ou `_`) ; elle reste aussi secrète que le script la garde. En développement avec `OGK_API` (l'origine de l'adresse imprimée), Vite sert la page : ouvre une fois `http://localhost:5199/api/session?key=…` avec la clé imprimée, puis `http://localhost:5199/`. Le cookie est alors posé sur `localhost` et part vers ses autres ports : réserve ce mode à un projet d'exemple.
- Les commandes passent par l'analyseur de la CLI, puis par une liste de refus : `ci-check`, `mcp`, `ui`, `guard --hook`, `tools mock`, `integrations --user`, et les décisions réservées au terminal ci-dessus. Les abréviations d'options (`--appr`) sont résolues avant le contrôle.
- Pendant chaque commande, l'entrée standard n'est jamais un terminal, même si le serveur tourne dans un terminal : une invite interactive échoue au lieu d'attendre.
- Les fichiers lus ou écrits restent dans le projet, hors de `.git` quelle que soit sa casse : sur un disque qui ignore la casse, `.GIT/x` s'écrirait dans `.git`. Les fichiers envoyés par la page (avis, rapport de scanner, résultats) passent par un dossier temporaire supprimé après la commande. La page ne liste ni ne lit `.env`, les noms qui évoquent un secret, ni les fichiers où les outils gardent leurs jetons : `token*.json`, `auth.json`, `*service-account*.json`, `local.settings.json`, ni ceux où les gestionnaires de paquets, Docker et les frameworks gardent un jeton ou un mot de passe en clair : `.yarnrc.yml`, `.npmrc`, `.pypirc`, `.netrc`, `.git-credentials`, `appsettings*.json`, `database.yml`, `.docker/config.json` (les enregistrements de l'outil sous `.openguildkit/` restent listés et lisibles, même quand une quête s'appelle `token-rotation` ou `password-reset`, ou un dossier de marché `password-manager`). Une commande n'ouvre pas non plus ces fichiers par ses options : `task new --file credentials.md` est refusé (`secret-file`), alors qu'un fichier envoyé par la page est pris tel quel.
- La page enregistre le profil par le chemin des commandes `profile` : sous le verrou du projet, validé comme `init`, inscrit dans l'historique `changes` avec le nom et la raison que la page envoie (`by`, `reason`, sinon `web interface`), puis `AGENTS.md` et le verrou du catalogue sont réécrits. Un changement qui affaiblit une protection est refusé avant d'écrire (`weakens-protection`), avec la commande `profile` à taper ; un profil invalide, ou dont l'historique diffère de celui enregistré (la page l'a modifié, ou une autre commande a changé le profil depuis sa lecture), est refusé (`invalid-profile`) ; dans les deux cas rien n'est écrit. Le seul autre fichier que la page écrit est `.openguildkit/storybook/proposals.json`, sous le même verrou (`project-busy` quand une autre commande le tient trop longtemps).
- Les commandes s'exécutent une à la fois, dans le processus du serveur, sous un verrou. Une page envoie un fichier absent du projet comme une réponse vide, pas comme une erreur.

## Codes de refus

Chaque refus du serveur porte un code stable dans le champ `reason`, à côté du message anglais (`error`) et, quand une personne peut taper la commande dans son terminal, de cette commande (`command`) : `{"error", "command", "reason"}`. Le résultat d'une commande que la CLI refuse faute de terminal, seul ou dans un lot (`batch`), porte les mêmes champs `command` et `reason`. La page traduit le code ; le message anglais reste le détail. La liste vit dans `REFUSALS`, dans `src/openguildkit/webui.py`, et un test vérifie que chaque code y figure ici.

La commande rendue est celle que la CLI nomme dans son refus quand elle en nomme une (par exemple `task complete ID --by NAME` pour clore par-dessus des points sensibles), et sinon celle que la page a envoyée.

| Code | Sens |
|---|---|
| `approve-at-terminal` | Valider une quête : une personne au terminal, ou une signature dans un projet à approbation signée. |
| `withdraw-at-terminal` | Retirer une approbation : la personne au terminal. |
| `cannot-run-at-terminal` | Déclarer qu'une commande de vérification ne peut pas tourner ici, ou retirer cette déclaration. |
| `clear-at-terminal` | Lever un blocage sans signature. |
| `complete-at-terminal` | Clore une quête par-dessus des points sensibles (`task complete ID --by NAME`). |
| `live-plan-at-terminal` | Appliquer un plan MCP réel, hors simulation. |
| `waiver-at-terminal` | Déroger à un blocage : la personne nommée, au terminal. |
| `external-action-at-terminal` | Autoriser une action externe. |
| `alert-accept-at-terminal` | Accepter une alerte confirmée. |
| `alert-severity-at-terminal` | Fixer la sévérité d'une alerte. |
| `alert-status-at-terminal` | Écarter une alerte critique, ou revenir sur une alerte critique confirmée (`alerts set` ou `task alerts --set`). |
| `weakens-protection` | Un changement du profil qui affaiblit une protection : la commande `profile` à taper, avec `--by` et `--reason`. |
| `person-at-terminal` | Une autre décision que la CLI réserve à une personne au terminal. |
| `send-setup-answers` | `init` sans réponses : la page envoie le questionnaire rempli. |
| `send-task-answers` | `task consult` sans réponses : la page envoie le cadrage rempli. |
| `invalid-profile` | Le profil envoyé n'est pas du JSON, n'est pas un profil valide, ou modifie l'historique des changements. Rien n'est écrit. |
| `not-initialized` | Le projet n'est pas encore installé. |
| `outside-project` | Un chemin sort du projet. |
| `secret-file` | Le nom du fichier évoque un secret, ou le fichier est dans `.git` : la page ne le liste ni ne le lit. Un fichier dont le texte contient un secret (clé de compte de service, jeton, mot de passe) n'est pas lu non plus. |
| `not-readable` | La page ne lit que le Markdown, le JSON, le YAML et le texte. |
| `too-large` | La requête ou le fichier est trop gros (8 Mo par requête, 2 Mo par fichier lu). |
| `not-in-page` | Une commande ou un fichier qui n'a pas sa place dans une page (`ui`, `ci-check`, `mcp`, `guard --hook`, `tools mock`, `integrations --user`, l'écriture d'un autre fichier que les propositions Storybook). |
| `project-busy` | Une autre commande d'OpenGuildKit écrit le projet : réessayer. |
| `stale-token` | Jeton de session absent ou périmé : le serveur a redémarré. Recharger la page. |
| `foreign-page` | La requête ne vient pas de la page du serveur (en-tête `Host` ou `Origin` inconnu). |
| `bad-request` | Une requête mal formée : corps, commande ou options, un chemin avec un octet nul, un texte qu'aucun fichier ne peut contenir (un substitut isolé). |
| `not-found` | Point d'accès ou fichier inconnu. |
| `open-printed-link` | Le navigateur n'a pas ouvert l'adresse imprimée par `openguildkit ui` pour ce lancement : l'ouvrir. |
| `server-error` | Le serveur a échoué en traitant la requête : le type, le message et la trace sont écrits dans le terminal de `openguildkit ui`. |

## Développer l'interface

```bash
python web/scripts/sample-project.py /tmp/portail     # projet d'exemple : une quête dans chaque état
openguildkit --project /tmp/portail ui --no-browser --port 7311
cd web
OGK_API=http://ogk-….localhost:7311 npm run dev       # l'origine de l'adresse imprimée ; rechargement à chaud
```

Sans `OGK_API`, `npm run dev` ouvre la démonstration ; `?demo=1` l'ouvre aussi quand `OGK_API` est posé. La construction du paquet (`npm run build`) laisse la démo de côté : sur une page servie par `openguildkit ui`, `?demo=1` affiche qu'elle n'est pas incluse et comment la lancer. `npm run build:demo` construit la démo seule, dans `dist-demo/`, pour `npm run preview:demo`.

Le code du mode réel est dans `src/project/` : le client de l'API (`api.ts`), le cache des commandes (`query.ts`), les données communes (`data.ts`), les libellés (`labels.ts`) et un fichier par lieu dans `views/`. Chaque lieu est chargé à la demande. Le serveur est `src/openguildkit/webui.py`.

## Empaqueter

```bash
cd web && npm ci --ignore-scripts && npm run build && npm run bundle   # copie dist/, sans la démo, dans src/openguildkit/web_dist
python -m build --wheel
```

`npm run bundle` refuse une construction qui contient les images de la démo ou qui dépasse son budget (`BUDGET_KB` dans `scripts/bundle.mjs` : 1 263 Ko, soit 1 148 Ko mesurés le 27 novembre 2026 plus 10 % ; la construction pèse 1 148 Ko ce jour-là, ce qui laisse 115 Ko, soit 9 %, de marge ; elle pesait 1 252 Ko avant la réduction du logo de l'en-tête et des décors). La release (`.github/workflows/release.yml`) et le job CI `package` font ces étapes, et refusent une roue sans `openguildkit/web_dist/index.html`. Le job `package` installe ensuite la roue sur Linux, macOS et Windows (avec `pipx` sous Windows) et vérifie que `openguildkit ui` répond 200 sur `/` avec chaque script de la page (`.github/scripts/check-installed-cli.py`). Dans un dépôt source, le serveur prend la plus récente des deux : `web/dist` ou la copie de `web_dist`.

## Performances

Le serveur garde entre deux commandes ce que chaque commande de la CLI reconstruit : l'analyseur d'arguments, le catalogue validé et le verrou du catalogue. Il les reprend tant que leurs fichiers n'ont pas changé, et chaque commande en reçoit sa propre copie. Une commande lancée par la page prend 2 à 25 ms, contre 70 à 130 ms pour la même commande lancée seule.

- Une réponse JSON ne porte pas le texte imprimé en double. Un écran peut demander d'omettre les champs qu'il n'affiche pas : la fiche d'une quête laisse le texte de la consultation sur le serveur, l'historique ne garde que les dates et les décisions.
- Les réponses de plus de 2 Ko sont compressées quand le navigateur l'accepte, ce qui compte à travers un tunnel SSH ou un port redirigé.
- La vue d'ensemble (quêtes, contrôle des instructions, alertes, partages, veille, catalogue, hôte) part en une seule requête. Elle seule se recharge après une action ; ce qui ne dépend que du catalogue (cerveaux, références, packs, outils, modèles) ne se recharge qu'après `sync`, `update`, `init` ou une modification du profil, et au clic sur « Actualiser ». Le retour sur l'onglet recharge le projet, pas le catalogue.
- Les cerveaux (`brains --json`, 145 Ko dont 97 % de lentilles, de déclencheurs et de sources) ne se chargent que là où on les lit : la recherche les demande après deux lettres, les écrans qui n'affichent que des titres (Conseil, Quêtes, Blueprint) en reçoivent 5,6 Ko (`omit`), la Guilde et les avis du Conseil les lisent en entier.
- Un champ dont le texte entre dans la clé d'une requête (motif et délégués du routage) attend 450 ms de pause avant de la lancer. La réponse d'une question dépassée sort du cache (`transient` dans `useQuery`), et le dernier routage reste affiché pendant le calcul du suivant.
- Le lieu de l'adresse ouverte est chargé avant le premier rendu ; les autres se chargent en arrière-plan ensuite. Changer de lieu ne passe donc jamais par l'écran d'attente que React 19 retient environ 300 ms.

Mesures du 21 novembre 2026 sur le projet d'exemple, avec `node scripts/measure-project.mjs` suivi de l'adresse imprimée par `openguildkit ui` (Chrome, navigateur neuf à chaque exécution, médiane de 3) :

| Écran | Temps d'affichage | Requêtes d'API | Données reçues (décompressées) |
| --- | ---: | ---: | ---: |
| Premier écran (Royaume) | 341 ms | 4 | 508 Ko, dont 219 Ko de React |
| Quêtes, Guilde, Tour de guet, Intendance, Blueprint | 3 à 15 ms | 0 | 2 à 43 Ko |
| Conseil d'une quête | 17 ms | 3 | 31 Ko |
| Forge d'une quête | 28 ms | 3 | 11 Ko |
| Bibliothèque (464 références) | 51 ms | 1 | 308 Ko |
| Chroniques | 50 ms | 1 | 49 Ko |

Mesures du 27 novembre 2026 (Chrome, même projet d'exemple) : premier écran, 3 requêtes d'API au lieu de 4 (plus de `brains --json`) ; « Actualiser » depuis le Royaume, 2 requêtes et 6 Ko décompressés au lieu de 3 et 148 Ko ; 40 caractères tapés dans le motif d'un ajustement, 1 requête `task route` au lieu de 40, et la grille des cerveaux ne disparaît plus (38 fois avant). `tests/e2e/project-requests.spec.ts` compte ces requêtes.

Avant ces optimisations, chaque changement de lieu prenait environ 320 ms, le premier écran environ 900 ms, et les Chroniques recevaient 1,3 Mo.

## Vérifier

```bash
python -m unittest tests.test_webui                    # tests du serveur : hôtes, origine, jeton, refus, chemins, envois, concurrence, cache, compression, profil
cd web && npm test                                     # dont les tests unitaires du mode réel (libellés, citations, signaux, cache) et ceux des composants (formulaires, routage, décision, installation, recherche), sans Chrome ni serveur
npm run build && npm run e2e:project                   # parcours et balayages sur des projets d'exemple neufs
```

`npm run e2e:project` construit un projet d'exemple dans un dossier temporaire et le sert sur le port 7322 (`PW_PROJECT_PORT`), plus deux dossiers vides sur les ports 7323 et 7324 pour l'installation (l'un avec Stripe dans sa pile). Les parcours passent par chaque action de l'interface : nouvelle quête, refus de valider à la place d'une personne, dérogation, levée d'un blocage et autorisation renvoyées au terminal, arbitrage, renvoi au Conseil, cadrage et consultation, passes et avis de chaque cerveau, synthèse, refus d'une action externe, passation, vérifications, résultats et clôture, livrable métier, outil connecté et sa simulation, design system extrait puis généré, import d'un rapport de scanner, revue d'alerte et alerte critique renvoyée au terminal, contrôles, dossier de marché et veille, export Documentalist, partage puis retrait, historique, profil (y compris un profil refusé puis remis, et une protection affaiblie renvoyée au terminal), fichiers de l'agent, bibliothèque, recherche, raccourcis clavier, style Pro, installation d'un dossier vide, fonctionnalité de l'Arsenal activée puis désactivée. Les deux balayages ouvrent 35 routes en RPG sur bureau et en Pro sur mobile : aucune erreur, un seul titre principal, chaque champ et chaque bouton nommés, aucun identifiant en double, pas de défilement horizontal.
