# OpenGuildKit

OpenGuildKit est un projet open source pour les équipes qui développent avec des agents IA sur plusieurs dépôts. Sa promesse est de **définir une règle d’organisation à un seul endroit et d’utiliser la même version pour les consignes de l’agent et les contrôles en intégration continue (CI)**. Dans la pull request (PR), le mainteneur peut retrouver la règle applicable, le commit contrôlé et le résultat. L’équipe garde la responsabilité de la revue et de la fusion.

## Démarrer avec une équipe pilote

La recette CI utilise l’archive npm 0.15.0. L’équipe fixe la version et son empreinte SHA-256 dans la configuration de CI. Les équipes peuvent héberger l’archive dans leur dépôt de distribution interne. [Archive privée de recette](https://github.com/azerothl/openguildkit-demo-a/releases/tag/v0.15.0) · [Recette du MVP](pilot/mvp-acceptance.md)

1. Choisir une règle et deux dépôts. Utiliser Node.js 22 ou plus récent, Git et GitHub CLI pour installer et exécuter le kit.
2. Générer un profil avec le questionnaire et le faire approuver par le mainteneur. [Adoption et approbation](#préparer-ladoption-sur-un-dépôt-existant-avec-le-kit-040)
3. Installer le workflow GitHub de réévaluation et planifier `watch --publish` dans Jenkins. Lancer le pilote en observation et vérifier les liens depuis les PR. [Relance des deux CI](#relancer-github-actions-et-jenkins-avec-le-kit-090)
4. Évaluer les écarts du pilote avec les mainteneurs avant de rendre un contrôle obligatoire. [Condition de fusion](#calculer-la-condition-de-fusion-et-les-dérogations-avec-le-kit-060)

### Suivre les versions du kit

Le kit 0.13.0 ajoute la commande `releases`. Elle consulte le dépôt de distribution choisi par l’équipe et indique si une version numériquement plus récente est disponible. Le canal `stable` est utilisé par défaut. Le canal `pilot` inclut les préversions GitHub. L’archive `openguildkit-X.Y.Z.tgz` doit être publiée avec une empreinte SHA-256. La commande fournit sa référence, son empreinte et le lien vers les notes de version. Elle laisse la version épinglée dans les CI à la décision du mainteneur. [Versions GitHub](https://docs.github.com/en/rest/releases/releases#list-releases)

```text
openguildkit releases --repo equipe/kit --channel pilot --installed 0.12.0
```

Sans `--installed`, la commande compare la version du kit qui s’exécute. Un job d’inventaire peut lui passer la version épinglée et lire le champ JSON `status`. La valeur `available` signale une mise à jour. Les autres valeurs sont `up-to-date`, `ahead` et `no-release`. Le champ `incomplete` indique les versions plus récentes ignorées faute d’archive vérifiable. Le résultat est informatif et retourne `0`. Une erreur d’accès ou de configuration retourne `2`.

Les membres d’une équipe peuvent recevoir les avis GitHub en choisissant **Watch**, puis **Custom** et **Releases** sur le dépôt de distribution. Ils vérifient ensuite si la version concerne leur installation avec `releases`. [Notifications GitHub](https://docs.github.com/en/subscriptions-and-notifications/get-started/configuring-notifications#configuring-your-watch-settings-for-an-individual-repository)

La recette a publié la préversion 0.13.0 dans le dépôt privé de distribution. Les deux projets ont détecté sa disponibilité avec le canal `pilot`, en conservant leur version 0.12.0. L’empreinte indiquée correspond à l’archive téléchargée. [Résultats de la recette](pilot/github-release-discovery-results.json)

## Installer le kit pilote 0.1.0 du prototype

Le kit nécessite Node.js 22 et Git. Depuis les sources d’OpenGuildKit, `npm test` vérifie le scénario et `npm pack` produit `openguildkit-0.1.0.tgz`. Depuis un dépôt pilote doté d’un projet npm, installer l’archive et créer le profil.

```text
npm install --save-dev /chemin/vers/openguildkit-0.1.0.tgz
npx --no-install openguildkit init --owner @equipe-plateforme
```

La commande `init` crée `openguildkit.json` avec le responsable et les chemins des fichiers à lire. La PR d’installation permet aux mainteneurs de valider ce profil. Pour la règle pilote, le dépôt des règles contient `policy/export-link.json` avec `id`, `version` et `maxMinutes`, et le dépôt à vérifier contient `export.json` avec `downloadLinkMinutes`. Le profil permet d’adapter les deux chemins.

GitHub Actions et Jenkins peuvent appeler la même commande. Mettre le profil approuvé et les deux dépôts à disposition du job, avec les commits concernés présents dans les clones. Pour une PR, fournir le profil de la branche de confiance définie par l’équipe et le SHA exact de la contribution.

```text
npx --no-install openguildkit check --profile openguildkit.json --policy-repo ../regles --policy-commit SHA_REGLE --commit SHA_PR --output resultat-openguildkit
```

Le dossier de sortie contient la consigne `AGENTS.md` et `evidence.json`. Le rapport indique le verdict, les deux SHA Git, la version du kit, l’empreinte du profil et le responsable. Archiver ce dossier dans le job pour rendre le résultat consultable après l’exécution. Le mode informatif retourne `0` en cas d’écart avec la règle. Ajouter `--enforce` pour retourner `1` sur un écart. Une erreur de profil ou de lecture Git retourne `2` dans les deux modes.

### Recette d’installation du kit dans les deux CI

Les PR d’installation sont ouvertes pour revue dans les deux dépôts de démo. [GitHub Actions, dépôt A](https://github.com/azerothl/openguildkit-demo-a/pull/2) · [Jenkins, dépôt B](https://github.com/azerothl/openguildkit-demo-b/pull/2)

Chaque job télécharge la même [prérelease privée 0.1.0](https://github.com/azerothl/openguildkit-demo-a/releases/tag/v0.1.0), vérifie le SHA-256 fixé dans `openguildkit-kit.json` et lit les octets du profil dans Git. Les tests ont utilisé les profils proposés dans les PR d’installation. Chaque statut pilote renvoie à la preuve depuis la PR évaluée.

| CI et PR | Commit | Règle à 60 min | Règle à 30 min |
| --- | --- | --- | --- |
| GitHub Actions, A #1 | `a436b71` | [Conforme](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44710199770) | [Écart informatif](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44710271780) |
| Jenkins, B #1 | `dc2b04f` | Conforme | Conforme |

Les [preuves de la recette](pilot/installed-kit-results.json) contiennent les liens des quatre vérifications, les commits d’installation, les SHA des règles et l’empreinte commune du profil. Les deux PR d’installation attendent la validation du mainteneur. La recette utilise des relances manuelles en observation.

## Réévaluation des PR dans le kit 0.2.0

`openguildkit reconcile` lit les références Git courantes et calcule le verdict applicable à chaque PR. Un contrôle est identifié par le projet, le numéro de PR, son commit, les révisions de profil et de règle et la version du kit. Toute évolution de ces références produit un nouveau contrôle en attente. Le rapport précédent reste consultable dans le dossier d’état.

Le fichier de configuration est fourni par le coordinateur. Il recense les PR ouvertes et désigne le profil approuvé, sur une référence distincte de la branche proposée. Les chemins de dépôts sont relatifs à ce fichier. La procédure d’intégration doit actualiser les clones et la liste des PR avant chaque passage.

```json
{
  "policyRepo": { "path": "./regles", "ref": "refs/remotes/origin/main" },
  "projects": [
    {
      "id": "equipe/portail",
      "path": "./portail",
      "profileRef": "refs/remotes/origin/main",
      "pullRequests": [{ "number": 42, "ref": "refs/pull/42/head" }]
    }
  ]
}
```

```text
openguildkit reconcile --config integration.json --state etat-openguildkit
openguildkit reconcile --config integration.json --state etat-openguildkit --run
```

La première commande planifie et affiche les contrôles courants. La seconde exécute ceux qui sont encore en attente, puis relit les références Git avant d’afficher le résultat. Après interruption, une nouvelle exécution reprend les contrôles dépourvus de preuve. Le dossier d’état doit être persistant et permettre les liens physiques locaux. Les preuves et les contrôles planifiés se trouvent respectivement dans `evidence/` et `work/` sous ce dossier.

Un job de CI de confiance peut aussi exécuter `openguildkit check` avec les SHA complets de la règle, de la PR et du profil fournis dans le plan. L’option `--profile-commit SHA_PROFIL` lit le profil dans Git. Le coordinateur peut ensuite enregistrer son résultat avec `openguildkit record --state etat-openguildkit --work ID --evidence resultat/evidence.json`. Une preuve tardive est conservée sous le contrôle correspondant à ses références. Une relance identique réutilise la preuve. Si deux résultats se contredisent pour les mêmes références, le statut devient `error`.

### Synchroniser les PR GitHub avec le kit 0.3.0

`openguildkit github` découvre les PR ouvertes dans les dépôts configurés, actualise les objets Git sans changer le contenu des clones et fait passer ces références au coordinateur. Les branches de règle et de profil sont choisies côté configuration. Sur des dépôts d’équipe, utiliser les branches sur lesquelles les mainteneurs valident ces fichiers.

```json
{
  "policyRepo": { "id": "equipe/regles", "path": "./regles", "ref": "refs/heads/main" },
  "projects": [
    {
      "id": "equipe/portail",
      "path": "./portail",
      "profileRef": "refs/heads/main"
    }
  ]
}
```

Les chemins mènent à des clones Git existants. `gh` doit pouvoir lire les dépôts privés. Le champ optionnel `prNumbers` limite l’observation à une liste de PR ouvertes pendant le pilote.

```text
openguildkit github --config gh-pilote.json --state etat-openguildkit --run
openguildkit github --config gh-pilote.json --state etat-openguildkit --run --publish
```

`--publish` requiert l’accès en écriture aux statuts de commit. Il publie un statut d’observation par PR, après vérification de son commit courant. Avec `--report-url URL`, le statut renvoie au rapport de la CI. Une répétition avec les mêmes références, le même résultat et le même lien réutilise la preuve et le statut. Planifier la commande dans le coordinateur d’équipe pour actualiser la liste des PR et traiter les changements. Les jobs 0.1.0 existants restent distincts de ce statut pilote. La condition de fusion du MVP doit faire l’objet d’une recette séparée.

### Relancer GitHub Actions et Jenkins avec le kit 0.9.0

Dans la configuration du coordinateur GitHub, ajouter à chaque projet un champ `"workflow": {"file":"openguildkit.yml","ref":"pilot/recheck-base"}`. Utiliser le [workflow de réévaluation](pilot/recheck-workflow.yml) sur une branche de confiance. Configurer le profil approuvé, le fichier `pilot/recheck-kit.sha256` avec l’empreinte de l’archive installée et le fichier `pilot/recheck.json` avec `policyRepository` et `policyRef`.

Pour une règle privée partagée, les workflows pointent vers le même dépôt de règles. GitHub Actions peut y lire via `OPENGUILDKIT_POLICY_READ_TOKEN` ou une clé de déploiement en lecture seule enregistrée comme `OPENGUILDKIT_POLICY_DEPLOY_KEY`. Avec une clé, la partie publique est ajoutée au dépôt central. La partie privée reste dans un environnement GitHub Actions accessible à la branche de confiance du workflow consommateur. [Clés de déploiement GitHub](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) · [Environnements GitHub Actions](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

```text
openguildkit watch --config gh-pilote.json --state etat-openguildkit
```

Programmer cette commande dans un job Jenkins périodique sans exécutions concurrentes. Archiver son résultat JSON et conserver le même dossier d’état entre les exécutions. La commande recalcule les entrées actives de chaque PR, exécute uniquement les contrôles manquants côté Jenkins, puis déclenche GitHub Actions avec l’identifiant de la vérification. Elle reprend les exécutions déjà enregistrées au passage suivant, vérifie les deux rapports et conserve l’historique par commit de PR, profil et règle. L’écart métier figure dans les preuves. Le code `2` signale une erreur d’exécution ou une divergence de preuves.

Le kit 0.12.0 écrit également un identifiant de tentative avant de demander l’exécution. Avec le workflow mis à jour, si la réponse se perd, le prochain passage recherche cet identifiant sur GitHub et reprend l’exécution retrouvée. Il attend deux minutes avant de soumettre une nouvelle tentative si l’exécution reste introuvable. Les preuves restent liées à la révision demandée même si deux exécutions se chevauchent. [Liste des exécutions GitHub Actions](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)

La recette a interrompu le processus du job Jenkins juste après que GitHub a accepté chaque lancement, avant l’enregistrement de son identifiant. Le minuteur a retrouvé les deux exécutions et publié les preuves sur les deux PR. GitHub a enregistré une seule exécution par vérification. L’essai portait sur le processus du job, avec le service Jenkins et Windows en marche. [Preuves de la reprise](pilot/github-dispatch-recovery-results.json)

#### Installer le job Jenkins sur un agent

Mettre les sources du kit à disposition de l’agent sur un emplacement contrôlé par l’équipe. L’agent doit pouvoir lancer Node.js 22, Git, GitHub CLI et `tar`. Le compte du job a besoin d’un accès en lecture au dépôt de distribution, aux règles et aux projets concernés, ainsi que du droit de déclencher leurs workflows. Les chemins `path` de la configuration peuvent pointer vers des dépôts Git initialisés avec `git init --bare`. Ils sont résolus par rapport au fichier de configuration. Le coordinateur y charge ensuite les références distantes.

Préparer un fichier `kit.json` avec `repository` (sous la forme `équipe/dépôt`), `version` et `sha256`. La version doit correspondre à celle épinglée dans les workflows GitHub Actions. Dans un job **Freestyle**, planifier la commande suivante, désactiver les exécutions simultanées et archiver `result.json` même en cas d’échec. Utiliser un dossier d’état persistant sur un volume qui permet les liens physiques. [Archivage Jenkins](https://www.jenkins.io/doc/pipeline/steps/core/#archiveartifacts-archive-the-artifacts)

```text
node /chemin/vers/OpenGuildKit/pilot/run-watch-jenkins.mjs --kit /chemin/vers/kit.json --config /chemin/vers/projets.json --state /chemin/vers/etat-openguildkit
```

Le lanceur télécharge l’archive épinglée au premier passage et revérifie son empreinte avant chaque exécution. Le job utilise le même dossier d’état pour son cache et pour reprendre les vérifications déjà lancées. Ajouter `--publish` si l’équipe souhaite publier les liens depuis les PR et que le compte du job dispose des droits correspondants.

Le lanceur a été vérifié dans un nouveau job Jenkins, avec deux dépôts Git vides et un dossier d’état neuf. Le premier passage a téléchargé l’archive et lancé les deux contrôles. Le second a utilisé le cache et vérifié les mêmes exécutions GitHub Actions. Un essai séparé a également confirmé le rejet d’une archive altérée. [Résultats de l’installation](pilot/jenkins-clean-install-results.json)

La [recette sur deux dépôts](pilot/github-jenkins-recheck-results.json) utilise le job Jenkins périodique `pilot-recheck-09`. Avec le premier profil, les deux CI ont relevé un écart sur A et une conformité sur B. La publication du nouveau profil A a relancé A seul sur son commit de PR d’origine. Les deux CI ont validé le fichier d’export désormais sélectionné avec le même commit de règle. Pour cette recette, les approbations ont été simulées et le dépôt B a lu une copie Git du même commit de règle.

Une recette ultérieure avec le kit 0.11.1 a publié le seuil de 30 minutes uniquement dans le dépôt A. GitHub Actions sur B a lu ce dépôt directement avec la clé en lecture seule. Jenkins et GitHub Actions ont produit le même verdict et le même SHA de règle pour chaque PR, sur les commits d’origine. L’observation des deux rapports a pris 138 secondes après la publication, cadence du minuteur comprise. [Preuves de la lecture centrale](pilot/github-central-policy-results.json)

Pour cette mise à jour, les deux builds Jenkins ont duré 32,5 s et 36,5 s. Les jobs GitHub Actions ont duré 9 s sur A et 10 s sur B. Les durées mesurent l’activité des tâches de CI. Le temps de revue humaine et le coût facturé restent à mesurer avec les équipes. [Exécution GitHub Actions A](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44723666552) · [Exécution B](https://github.com/azerothl/openguildkit-demo-b/actions/runs/44723670490)

### Retrouver le rapport des deux CI depuis la PR

Avec le kit 0.11.1, prévoir une branche d’archives contrôlée par l’équipe et la déclarer dans la configuration de chaque projet, par exemple `"workflow": {"file":"openguildkit.yml","ref":"pilot/recheck-base","evidenceBranch":"pilot/ci-reports"}`. Donner au compte du job Jenkins le droit de publier un statut et d’écrire sur cette branche. Ajouter `--publish` à la commande `watch`.

Le statut informatif `openguildkit/report-pr-N` suit le résultat courant. Lorsque les deux CI ont produit des preuves concordantes, son lien ouvre le rapport à un commit Git précis. Le rapport indique le verdict, le profil, la règle, le commit évalué, la consigne et l’exécution GitHub Actions. Il renvoie au ticket si la PR utilise le marqueur `OpenGuildKit-Ticket: #NUMERO`. L’ancienne preuve reste consultable quand une règle, un profil ou une dérogation change.

Sur les deux PR privées de recette, le passage de 25 à 20 minutes a remplacé le lien courant sur le même commit de contribution. Les anciens rapports restent consultables à leur propre SHA. Une relance sans changement a conservé les mêmes identifiants de statut. Le dépôt B a utilisé un miroir Git mis à jour avant la publication centrale. [Preuves de la recette](pilot/github-ci-report-results.json)

## Préparer l’adoption sur un dépôt existant avec le kit 0.4.0

1. Dans le dépôt de règles, versionner `policy/catalog.json`. Le [catalogue d’exemple](pilot/catalog.example.json) décrit la règle de durée d’un lien d’export. Chaque entrée indique son domaine, son responsable, sa justification, sa consigne et le fichier source. `openguildkit catalog --policy-repo ../regles --policy-commit SHA_REGLES` indique la version et si le kit sait exécuter la règle.
2. Depuis le dépôt pilote, générer un questionnaire avec le même SHA. Avec `--inspect`, le kit suggère la stack, les fichiers de convention, les CI visibles, une commande de test et une règle selon les fichiers du commit. L’inspection lit les fichiers versionnés sans lancer leurs commandes. Sans cette option, le questionnaire est produit sans inventaire des fichiers.
3. Remplir `answers` dans le JSON, en confirmant aussi les suggestions. Une liste vide indique qu’aucun élément n’est autorisé ou requis pour la question. Pour les données, indiquer les catégories et droits retenus. Passer le fichier rempli à `--answers` à la même révision pour préparer le profil en observation.

```text
openguildkit onboard --policy-repo ../regles --policy-commit SHA_REGLES --inspect > questionnaire.json
openguildkit onboard --policy-repo ../regles --policy-commit SHA_REGLES --answers questionnaire.json --profile openguildkit.json
```

Le profil porte initialement `adoption.state` à `proposed`. Le mainteneur désigné relit les réponses et le périmètre dans la PR d’installation. Après validation, consigner `adoption.state` à `approved` et `adoption.approver` au nom du mainteneur. La CI lit ce profil sur la branche de confiance après revue par les mainteneurs. Le champ JSON conserve leur décision. L’identité de l’approbateur est vérifiée par le processus de revue Git de l’équipe.

### Vérifier l’approbation du profil sur GitHub avec le kit 0.10.0

Dans les réponses, renseigner `project` sous la forme `equipe/depot` et `owner` sous la forme `@login`. Enregistrer la proposition produite par `onboard` dans `.openguildkit/proposal.json` et la soumettre dans une PR. Le mainteneur désigné la relit et la fusionne sur la branche de confiance. Puis générer le profil actif à partir de cette fusion.

```text
openguildkit github-approve-profile --repo equipe/depot --pr 42 --base main --maintainer login
```

La commande retourne le profil au format JSON. Le publier dans `openguildkit.json` sur la branche de confiance. L’entrée `adoption.approval` enregistre le mainteneur GitHub, le numéro de PR, les SHA de la proposition et de la fusion, et l’empreinte de la proposition.

Ajouter `"profileMaintainer": "login"` à la configuration du projet pour que le coordinateur revérifie cette approbation avant toute évaluation. Le profil doit correspondre à la proposition fusionnée, dont le commit de fusion doit appartenir à l’historique de la branche de confiance. Le mode initial `observation` conserve les écarts dans le rapport sans imposer de condition de fusion.

La [recette d’adoption GitHub](pilot/github-onboarding-results.json) a vérifié ce parcours sur deux dépôts privés. Le kit a rejeté les propositions encore ouvertes et les fusions attribuées à un autre mainteneur que celui configuré. Après activation, une PR à 45 minutes a signalé un écart et une PR à 21 minutes a passé la même règle de 25 minutes. Les statuts publiés sont informatifs. Le même compte a ouvert et fusionné les deux propositions de recette.

Un profil proposé est refusé par la vérification. En mode `observation`, un écart est consigné et le job CLI réussit. Une révision approuvée en mode `required` fait retourner `1` sur un écart de règle. La CI doit encore faire appliquer ce retour dans sa condition de fusion. Les profils simples du pilote 0.1.0 restent utilisables.

## Préparer le brief d’un agent avec le kit 0.5.0

Le mainteneur fournit un ticket, le résultat attendu et les critères qu’il souhaite faire vérifier. Le kit associe ces éléments aux versions approuvées du profil et de la règle. L’adresse du ticket doit être accessible au relecteur de la PR.

```json
{
  "ticket": { "url": "https://github.com/equipe/portail/issues/42", "title": "Réduire la durée des liens d’export" },
  "outcome": "Limiter la validité des nouvelles URL d’export.",
  "criteria": ["Un lien expire au bout de 30 minutes au maximum."]
}
```

```text
openguildkit brief --policy-repo ../regles --policy-commit SHA_REGLE --profile-commit SHA_PROFIL --task ticket.json --output agent-bundle
openguildkit-agent --bundle agent-bundle
```

Le dossier de sortie, créé pour ce brief, contient `AGENTS.md` et `brief.json`. Le fichier `AGENTS.md` porte la règle et les références de confiance. Le résultat attendu et les critères du ticket sont dans `brief.json`. L’adaptateur lit une demande JSON par ligne sur son entrée standard. Les méthodes `brief` et `guidance` renvoient les deux documents. Par exemple, `{"id":1,"method":"brief"}`. Les autres méthodes sont refusées et chaque tentative est consignée sur la sortie d’erreur.

L’adaptateur donne accès au brief et à la consigne sur cette interface. Les droits du processus de l’agent sur le système, la forge et les outils sont configurés séparément par l’équipe, selon le profil approuvé.

```text
openguildkit check --policy-repo ../regles --policy-commit SHA_REGLE --profile-commit SHA_PROFIL --commit SHA_PR --brief agent-bundle/brief.json --pull-request URL_PR --output resultat-openguildkit
```

Le rapport identifie la PR, le ticket, le contrôle exécuté et le SHA du brief remis à l’agent. Le job doit fournir le commit de la PR, vérifier que ce commit correspond à la PR et rendre le rapport accessible depuis celle-ci. Si la règle ou le profil a changé, le kit refuse le brief et demande une vérification avec les références courantes.

### Lire le ticket depuis GitHub avec le kit 0.7.0

Dans la description de la PR, indiquer `OpenGuildKit-Ticket: #42` sur sa propre ligne. Le ticket appartient au dépôt de la PR. Son corps comporte les sections `## Résultat attendu` et `## Critères d’acceptation`, avec les critères sous forme de liste à puces. Le kit relit la PR ouverte et son SHA exact avant de charger le ticket. Le brief mémorise le SHA de la PR et la date de révision du ticket. Un rapport lié à ce brief doit porter sur la même PR et le même commit.

```text
openguildkit github-brief --repo equipe/portail --pr 43 --commit SHA_PR --policy-repo ../regles --policy-commit SHA_REGLE --profile-commit SHA_PROFIL --output agent-bundle
```

Le [workflow de recette](pilot/agent-workflow.yml) sépare la lecture du ticket, l’exécution de l’adaptateur et la publication du statut. Le job qui prépare et vérifie le brief utilise un jeton GitHub en lecture. L’étape qui exécute l’adaptateur reçoit le dossier du brief. Le job de publication relit le SHA de la PR et affiche le lien vers le ticket et le rapport. Il publie un statut informatif.

La [recette GitHub 0.7.0](pilot/github-agent-results.json) relie une PR ouverte au ticket de démonstration et archive le brief, le journal de l’adaptateur et la preuve de CI. GitHub a refusé les appels d’écriture et de publication effectués avec le jeton de lecture du premier job.

### Rejouer le même contrôle dans Jenkins

Le [lanceur Jenkins](pilot/run-agent-jenkins.mjs) reçoit un fichier de recette avec `repository`, `pr`, `commit`, `profileCommit`, `policyCommit`, `checkout` et `kit`. `checkout` désigne un clone qui contient les commits de la PR, du profil et de la règle. `kit` contient le dépôt de release, la version et le SHA-256 de l’archive. Le job doit archiver le dossier de résultat. La lecture par l’adaptateur s’exécute avec un environnement sans jeton GitHub et dans le dossier du brief. Le job Jenkins utilise sa propre connexion GitHub pour charger les références et publier la preuve.

```text
node pilot/run-agent-jenkins.mjs agent-recipe.json resultats-jenkins
node pilot/jenkins-publish.mjs equipe/portail resultats-jenkins/control/evidence.json openguildkit/agent-jenkins-pr-43
```

Le second appel revérifie le commit courant avant de publier le statut informatif. Il réutilise la preuve versionnée et le statut s’ils existent déjà. La [recette Jenkins](pilot/jenkins-agent-results.json) compare le rapport et les décisions d’accès aux résultats de GitHub Actions sur la même PR.

## Calculer la condition de fusion et les dérogations avec le kit 0.6.0

Pour un profil approuvé en mode `required`, le job de CI peut exécuter `gate` pour la PR et le SHA qu’il doit vérifier. `--github` relit les PR ouvertes et leurs références sur GitHub. `--run` exécute un contrôle en attente et relit les références après l’exécution. Le coordinateur doit conserver son dossier d’état entre les passages.

```text
openguildkit gate --github --config gh-pilote.json --state etat-openguildkit --project equipe/portail --pr 42 --commit SHA_PR --run
```

Le code `0` indique une preuve conforme ou un écart couvert par une dérogation active. Le code `1` laisse la condition insatisfaite sur preuve en attente ou écart. Le code `2` signale une erreur, un conflit, un profil en observation ou une PR dont le SHA a changé. Pour appliquer la condition à la fusion, configurer le job sur une branche de confiance et le déclarer obligatoire dans la forge. Le statut informatif publié par `github --publish` est destiné à la revue.

Pour autoriser les dérogations, indiquer `waiversPath` dans `policyRepo` et `waiverApprovers` pour le projet dans la configuration du coordinateur. L’équipe maintient ce registre sur la branche de règles approuvée. Chaque entrée contient les références complètes du contrôle couvert.

```json
{
  "schemaVersion": 1,
  "waivers": [
    {
      "id": "migration-export-42",
      "project": "equipe/portail",
      "pullRequest": 42,
      "commit": "SHA_PR",
      "profileCommit": "SHA_PROFIL",
      "policyCommit": "SHA_REGLE",
      "rule": "export-link-expiry",
      "approver": "@securite",
      "reason": "Migration du service d’export en cours",
      "approvedAt": "2026-11-20T09:00:00Z",
      "expiresAt": "2026-11-21T09:00:00Z"
    }
  ]
}
```

La revue Git authentifie la décision sur le registre, et la configuration du coordinateur désigne les personnes autorisées. Une dérogation couvre un écart constaté pour ces références. La preuve brute reste en écart. Le rapport conserve le motif, l’approbateur, l’échéance et le SHA du registre. À l’expiration, le passage suivant reprend le verdict de la preuve brute. L’historique des décisions, y compris celle qui accordait la dérogation, est conservé dans `decisions/` du dossier d’état.

### Recette de la condition de fusion dans GitHub

Le [workflow de recette](pilot/required-workflow.yml) utilise le profil et la règle de la branche protégée `pilot/merge-gate-base`. Il vérifie l’identité de la PR et de son commit, installe l’archive figée par SHA-256, archive le résultat et publie `openguildkit/required-pilot` sur le commit évalué. Le code de la PR est lu dans Git par le kit. Le job est exécuté depuis la branche de confiance.

GitHub exige ce contrôle, sa provenance GitHub Actions et une branche de PR à jour. Le mode strict permet à une mise à jour de la base qui contient le profil et la règle de rendre l’ancien succès insuffisant. La recette déclenche le workflow manuellement sur la branche dédiée. Un déclenchement par événement demande l’installation et la validation du workflow sur les branches pertinentes du dépôt.

Cette recette concerne une règle et un profil dans la même base protégée. Une règle hébergée dans un autre dépôt ou une dérogation qui expire sans commit demande une validation fraîche dans le parcours de fusion. Un statut GitHub déjà publié ne reflète pas à lui seul ces évolutions.

### Vérifier une dérogation au moment de la fusion sur GitHub

Le mainteneur peut examiner la décision courante avec le kit 0.8.0. La commande sans `--execute` ne fusionne rien. Ajouter `--execute` après la revue pour demander la fusion du SHA indiqué.

```text
openguildkit merge --config gh-pilote.json --state etat-openguildkit --project equipe/portail --pr 42 --commit SHA_PR --base main
```

Avant la demande de fusion, le kit recharge le registre, la règle et le profil approuvé, vérifie que la PR est toujours ouverte sur la même base pour le même commit, puis contrôle l’heure d’expiration. GitHub reçoit le SHA exigé et applique ses protections de branche. Le rapport indique la décision, les références et, si GitHub confirme la fusion, le SHA qui en résulte.

La [recette GitHub 0.8.0](pilot/github-waiver-merge-results.json) a repris la même PR à 45 minutes, soumise à une règle de 25 minutes. L’aperçu a reconnu la dérogation active. Après expiration, la commande de fusion a refusé la demande et GitHub a confirmé que la PR était toujours ouverte sur le même SHA. Après renouvellement explicite, GitHub a confirmé la fusion sur la branche privée de recette.

Le dossier d’état doit résider sur un volume qui prend en charge les liens physiques, par exemple NTFS sous Windows. Le kit s’en sert pour publier les preuves atomiquement. L’équipe contrôle la configuration et l’accès à ce dossier.

Pour imposer ce contrôle à chaque fusion, limiter le droit de fusion au compte qui exécute cette vérification. GitHub vérifie le SHA de la PR lors de la fusion. La lecture de la règle et du registre et la fusion restent deux opérations distinctes. Une équipe qui exige une garantie contre une modification simultanée doit coordonner les mises à jour des références de confiance et les fusions.

Le [workflow de fusion protégée du pilote](pilot/broker-workflow.yml) commence avec le jeton GitHub Actions en lecture seule. Il vérifie l’empreinte SHA-256 de l’archive du kit à partir de `pilot/broker-kit.sha256`, conservé sur la branche de confiance. La demande du mainteneur désigne la PR et le SHA relu. Si l’aperçu est favorable et que le mainteneur demande la fusion, le workflow utilise un jeton éphémère d’une application GitHub dédiée, recalcule la décision et archive les preuves.

Pour l’adapter à un dépôt, appliquer une règle **Restrict updates** à la branche cible. Y autoriser exclusivement l’application dédiée, en mode **For pull requests only**. Conserver les revues et les autres exigences dans une protection distincte pour qu’elles s’appliquent aussi à l’application. Installer l’application sur les seuls dépôts concernés avec `Contents: write` et `Pull requests: read`. Dans le workflow, adapter les branches et l’autorisation du mainteneur. Réserver l’environnement de fusion à la branche qui porte le workflow de confiance, puis y configurer la variable `OPENGUILDKIT_APP_CLIENT_ID` et le secret `OPENGUILDKIT_APP_PRIVATE_KEY`. L’identité de fusion doit rester distincte du jeton de l’agent.

Avec le kit 0.14.0, renseigner aussi `OPENGUILDKIT_RULESET_ID` avec l’identifiant de la protection du dépôt. Le workflow vérifie que la restriction est active avant de demander le jeton dédié. Il la vérifie à nouveau juste avant la demande de fusion. Avec un compte autorisé à modifier la protection, le mainteneur peut aussi vérifier que l’application est la seule exception. Cette vérification ne change aucun réglage GitHub. [API des protections GitHub](https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset)

```text
openguildkit merge-protection --repo equipe/depot --base main --ruleset ID_PROTECTION --app-id ID_APPLICATION
```

GitHub masque la liste des exceptions aux comptes en lecture seule. Le workflow vérifie la protection active avec son droit de lecture. Le mainteneur vérifie la liste des exceptions à l’installation et après un changement de protection.

Avec le kit 0.15.0, configurer aussi `OPENGUILDKIT_APP_ID` avec le même identifiant numérique que celui vérifié par le mainteneur. Le workflow compare cet identifiant à l’application qui vient d’émettre le jeton, puis demande à GitHub de confirmer que le jeton donne accès au seul dépôt cible. Une différence bloque le workflow avant la demande de fusion. [Jeton d’application GitHub](https://github.com/actions/create-github-app-token) · [Dépôts accessibles à l’installation](https://docs.github.com/en/rest/apps/installations#list-repositories-accessible-to-the-app-installation)

La recette a utilisé un jeton GitHub Actions en lecture seule. Elle a accepté son dépôt et son identité attendus, puis rejeté un autre identifiant d’application et un autre dépôt. Elle a exercé les vérifications qui précèdent la fusion. [Résultats du contrôle du jeton](pilot/github-merge-installation-check-results.json)

Un workflow GitHub Actions en lecture seule a confirmé la restriction active sur la branche de fusion du pilote et l’absence de cette restriction sur `main`. La lecture avec le compte administrateur a confirmé que l’application testée ne disposait pas de l’exception attendue. [Résultats du contrôle préalable](pilot/github-merge-protection-check-results.json)

La recette de protection native a d’abord confirmé le refus de fusion directe malgré un aperçu favorable. Après installation de l’application privée sur le seul dépôt A, le workflow 0.15.0 a refusé une dérogation expirée avant de demander le jeton. Avec une dérogation valide, GitHub a ensuite confirmé la fusion du même commit de PR par l’application. La branche cible est restée protégée et l’application était sa seule exception, en mode pull request uniquement. [Refus de fusion directe](pilot/github-protected-merge-results.json) · [Preuve des deux exécutions](pilot/github-protected-app-merge-results.json)

Pour cette recette, le workflow était figé sur une branche de confiance distincte de la branche cible. L’environnement de fusion était ouvert à cette seule branche. Le workflow vérifiait le SHA attendu de la branche cible avant l’exécution. [Workflow exact de recette](https://github.com/azerothl/openguildkit-demo-a/blob/3407ab7b480236fbabbe72e2f747b0eaecae778b/.github/workflows/openguildkit.yml)

Le [rapport de recette GitHub](pilot/native-gate-results.json) conserve les refus de fusion, les SHA et les liens vers les rapports. La PR d’export a été fusionnée sur la branche de recette après un contrôle conforme au seuil de 25 minutes.

## Premier test

Le test porte sur **une règle, deux dépôts existants et une mise à jour pendant qu’une PR est ouverte**. Il doit montrer si OpenGuildKit facilite la mise à jour d’une règle commune et permet de vérifier ce qui s’applique à une PR en cours.

**Règle choisie.** Un lien de téléchargement d’un export expire au bout de 60 minutes au maximum en version 1. La version 2 réduit cette durée à 30 minutes. Les deux dépôts GitHub utilisent la même stack et proposent chacun un export.

1. **Établir le point de comparaison.** Appliquer la version 1 aux deux dépôts avec un workflow GitHub Actions réutilisable et des consignes versionnées. Dans le dépôt A, ouvrir une PR qui fixe la durée à 45 minutes. Vérifier qu’elle satisfait la version 1, puis la laisser ouverte.
2. **Faire évoluer la règle.** Publier la version 2. Relever le travail nécessaire pour mettre à jour les consignes et le contrôle dans les deux dépôts. Relancer le contrôle de la PR ouverte sur le même commit. Les 45 minutes doivent échouer avec la version 2. Une fois la PR corrigée à 30 minutes, vérifier que le nouveau commit passe. Dans le dépôt B, vérifier que la prochaine PR qui touche un export applique bien la version 2.
3. **Rejouer le scénario avec OpenGuildKit.** Repartir du même état initial et réutiliser les mêmes tests et le même workflow. Un fichier de règles versionné fournit le seuil aux consignes de l’agent et au contrôle. Chaque résultat dans la PR indique la version de la règle, le commit contrôlé et le verdict. Le passage à la version 2 déclenche une nouvelle vérification de la PR ouverte. Le résultat historique de la version 1 reste consultable.

## Critères de réussite

- **Cohérence.** Les consignes et le contrôle utilisent la version 2 dans les deux dépôts. La réussite obtenue avec la version 1 ne vaut pas validation pour la version 2.
- **Lisibilité.** Un autre mainteneur peut retrouver les dépôts concernés, expliquer pourquoi la PR échoue sur le même commit après la mise à jour et identifier la correction attendue.
- **Gain.** Comparer le temps passé, le nombre de modifications manuelles et les écarts entre consignes et contrôles. Le prototype mérite d’être étendu si la mise à jour demande moins de travail et que le mainteneur peut reconstituer la décision à partir de la PR.

## Résultat de la démonstration

Les deux dépôts de démo sont privés. La [règle active](https://github.com/azerothl/openguildkit-demo-a/blob/main/policy/export-link.json) se trouve sur `main` dans le dépôt A. Les deux dépôts exécutent le même [workflow](prototype/demo/.github/workflows/openguildkit.yml).

| Pull request | Commit vérifié | Règle | Durée proposée | Résultat |
| --- | --- | --- | --- | --- |
| [A #1](https://github.com/azerothl/openguildkit-demo-a/pull/1) | `a436b71` | v1, max. 60 min | 45 min | [Réussite](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44637928612) |
| A #1 | `a436b71` | v2, max. 30 min | 45 min | [Échec attendu](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44638015717) |
| [B #1](https://github.com/azerothl/openguildkit-demo-b/pull/1) | `dc2b04f` | v2, max. 30 min | 30 min | [Réussite](https://github.com/azerothl/openguildkit-demo-b/actions/runs/44638032629) |

La PR A reste ouverte à 45 minutes pour que le changement de verdict reste visible sur le même commit. Le dépôt B valide le cas conforme à 30 minutes.

### Relancer les contrôles

Avec Node.js et `gh` connecté à un compte autorisé sur les deux dépôts, exécuter cette commande depuis la racine du projet après avoir publié une nouvelle version de la règle sur `main` du dépôt A.

```text
node prototype/recheck.mjs azerothl/openguildkit-demo-a "azerothl/openguildkit-demo-a#1" "azerothl/openguildkit-demo-b#1"
```

Le script lit la règle à une révision précise, affiche la consigne correspondante pour l’agent et déclenche le workflow pour le commit courant de chaque PR indiquée. GitHub Actions publie le verdict sur ce commit et conserve le détail dans le résumé de l’exécution. Le lancement se fait à la demande et le statut est informatif dans les dépôts de démo.

## Comparatif du passage de 60 à 30 minutes

Le test du 20 novembre 2026 a rejoué les deux approches sur des branches dédiées, avec le même workflow réutilisable et les deux mêmes commits de PR. Avec le workflow partagé seul, le seuil était central côté CI, et les deux dépôts avaient chacun une consigne `AGENTS.md` à tenir à jour. Avec OpenGuildKit, le script a lu la règle centrale, affiché la consigne et transmis le seuil au même workflow.

| Mesure | Workflow partagé seul | OpenGuildKit |
| --- | ---: | ---: |
| Fichiers à modifier | 3 | 1 |
| Dépôts à mettre à jour | 2 | 1 |
| De la première modification à la fin du déclenchement | 8,1 s | 8,2 s |
| De la première modification au dernier verdict CI | 14,0 s | 13,4 s |

À 60 minutes, les deux commits passent dans les deux approches. À 30 minutes, le même commit A à 45 minutes échoue et le même commit B à 30 minutes passe. Les deux PR sont restées ouvertes. [Verdicts à 30 minutes avec le workflow partagé sur A](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44642567886) et [sur B](https://github.com/azerothl/openguildkit-demo-b/actions/runs/44642571562). [Verdicts avec OpenGuildKit sur A](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44642680298) et [sur B](https://github.com/azerothl/openguildkit-demo-b/actions/runs/44642685032).

Une seule mise à jour chronométrée par approche, avec des opérations scriptées et une installation préalable. Le gain observé porte sur les deux copies de consigne à maintenir. La mesure ne permet pas de conclure à un gain de temps humain ou de CI. Si les consignes sont déjà dérivées d’une source centrale, le gain de maintenance reste à évaluer.

### Comparaison avec une règle centrale dans GitHub Actions

Le second essai utilise un workflow GitHub partagé et une action composite qui lit le fichier de règle du dépôt A à la révision du workflow. Avec OpenGuildKit, le script lit ce même fichier sur une révision précise et transmet son contenu au workflow. Dans les deux cas, la CI génère un `AGENTS.md` téléchargeable et vérifie le commit exact de la PR. Les fichiers générés à 60 puis à 30 minutes ont été téléchargés et vérifiés dans les deux dépôts.

| Mesure | GitHub Actions avec règle centrale | OpenGuildKit |
| --- | ---: | ---: |
| Fichiers à modifier | 1 | 1 |
| Dépôts à mettre à jour | 1 | 1 |
| De la première modification à la fin du déclenchement | 6,9 s | 7,8 s |
| De la première modification au dernier verdict CI | 15,0 s | 17,5 s |

Les deux approches fournissent les mêmes consignes et verdicts, avec la version et le commit source de la règle. Le commit A à 45 minutes passe à 60 puis échoue à 30. Le commit B à 30 minutes passe aux deux seuils. [GitHub Actions sur A](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44645128294) et [sur B](https://github.com/azerothl/openguildkit-demo-b/actions/runs/44645132728). [OpenGuildKit sur A](https://github.com/azerothl/openguildkit-demo-a/actions/runs/44645263455) et [sur B](https://github.com/azerothl/openguildkit-demo-b/actions/runs/44645269370).

Sur cet essai, la référence GitHub couvre le besoin avec le même nombre de modifications. Le script OpenGuildKit fournit une commande commune qui lit la règle, affiche la consigne avant le lancement et déclenche les contrôles des PR sélectionnées. La comparaison repose sur une seule mise à jour scriptée par approche, hors installation.

## Parité entre GitHub Actions et Jenkins

Quatre builds sur une instance Jenkins locale ont été comparés aux quatre exécutions GitHub Actions OpenGuildKit de l’essai précédent. Jenkins a lu la règle dans le dépôt A et le fichier d’export dans le dépôt concerné, aux SHA exacts. Les deux CI ont produit le même `AGENTS.md` octet pour octet, le même verdict, le même commit de PR et le même commit source de la règle pour chacun des quatre cas.

| PR | Commit de PR | Durée | Règle v1 (`47cd4dd`, 60 min) | Règle v2 (`8bc4383`, 30 min) |
| --- | --- | ---: | --- | --- |
| A #1 | `a436b71` | 45 min | Réussite | Échec attendu |
| B #1 | `dc2b04f` | 30 min | Réussite | Réussite |

Les [preuves du test](prototype/ci-parity-results.json) contiennent les SHA complets, les consignes, les références des builds Jenkins et les liens vers les exécutions GitHub Actions. Le test Jenkins a été déclenché sur des commits fixés à l’avance.

L’adaptateur utilisé dans les jobs Jenkins s’exécute dans un environnement qui dispose de Git, de Node.js et des deux dépôts clonés. Il écrit `AGENTS.md` et `evidence.json` dans le dossier de sortie.

```text
node prototype/verify-refs.mjs DEPOT_REGLE SHA_REGLE DEPOT_PR SHA_PR DOSSIER_SORTIE
```

## Relance automatique à la publication d’une règle

Le job Jenkins local `poll-central-rule` tourne toutes les minutes. Il vérifie le dernier commit qui modifie `policy/export-link.json` sur la branche surveillée. Au changement, il relève le SHA courant de chaque PR ouverte dans les deux dépôts, applique la règle dans Jenkins et déclenche GitHub Actions avec les mêmes SHA. Si le commit source de la règle est inchangé, le job ne relance aucun contrôle.

Sur chaque PR, les contextes `openguildkit/jenkins` et `openguildkit/export-link-expiry` indiquent le verdict et le SHA complet de la règle. Jenkins conserve aussi un rapport par SHA et vérifie que le verdict GitHub Actions correspond au sien. Le job reprend les relances en cours depuis son fichier d’état si une exécution échoue.

Pour reprendre cette configuration dans Jenkins, créer un job avec le déclencheur périodique `* * * * *`, désactiver les exécutions concurrentes et archiver `result.json`, y compris pour les builds en échec. Utiliser le chemin absolu du script si le projet se trouve hors de l’espace de travail Jenkins. Le processus Jenkins doit pouvoir exécuter Node.js et utiliser un compte `gh` autorisé à lire les dépôts, lancer leurs workflows et publier leurs statuts.

```text
node prototype/watch-rule.mjs CONFIG_JSON ETAT_JSON
```

```json
{
  "policyRepo": "azerothl/openguildkit-demo-a",
  "policyRef": "main",
  "repositories": ["azerothl/openguildkit-demo-a", "azerothl/openguildkit-demo-b"]
}
```

L’installation de démo fonctionne tant que l’instance Jenkins locale est en marche. Le prototype couvre les PR dont la branche source appartient au même dépôt.

Les [preuves des relances automatiques](prototype/automatic-recheck-results.json) couvrent le passage de 60 à 30 minutes sur la branche de test et la première vérification de la règle active sur `main`. Elles contiennent le numéro et la cause du build Jenkins, les SHA vérifiés et les liens vers GitHub Actions.

### Redémarrage sous Windows

La tâche Windows **OpenGuildKit Jenkins** démarre l’instance à l’ouverture de la session utilisateur. Jenkins, le script de surveillance et le dernier état traité sont conservés dans `%LOCALAPPDATA%\OpenGuildKit\Jenkins`. La tâche utilise la connexion GitHub CLI du compte Windows et Jenkins écoute uniquement sur la boucle locale. Le [script d’installation](prototype/windows/install-jenkins-watch.ps1) prépare les fichiers et enregistre la tâche.

Au premier passage du minuteur après le démarrage, Jenkins relit la règle active sur `main` et la compare au dernier SHA traité. Si une règle a été publiée pendant l’arrêt, les deux CI vérifient les PR ouvertes avec cette révision.

Le [test de rattrapage](prototype/restart-recovery-results.json) a arrêté Jenkins, publié la règle v3 à 30 minutes et redémarré Jenkins via la tâche Windows. Le minuteur a ensuite réévalué les deux PR sur leurs commits d’origine dans Jenkins et dans GitHub Actions. Le test a simulé l’arrêt de la machine au niveau de Jenkins.

Le [test avec redémarrage réel de Windows](prototype/windows-reboot-results.json) a confirmé le démarrage automatique de Jenkins à l’ouverture de session et la réévaluation des deux PR avec le SHA `7bbc2751780369e8bf9772cc59ae61016ce563bb`. GitHub a publié cette règle v4 à 07 h 34 min 36 s, et Windows a consigné son arrêt à 07 h 37 min 23 s, heure de Paris. La publication a eu lieu pendant la séquence de redémarrage, avant l’arrêt effectif consigné par Windows.
