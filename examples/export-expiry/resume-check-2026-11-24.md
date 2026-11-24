# Reprise des contrôles après interruption, 24 novembre 2026

Vérification locale pour [#261](https://github.com/Sandbox-podcast/OpenGuildKit/issues/261), sur l'archive Node 0.17.0 construite avant publication. Elle reprend les essais de reprise de la [répétition du 23 novembre](pilot-rehearsal-2026-11-23.md) et du [test du watcher](../../integrations/ci/test/watch.test.mjs), cette fois par la commande `openguildkit-ci watch` de l'archive installée et par son vrai code d'appel à `gh`.

## Versions et commandes

- Code : branche `v017/261`, commit `a8e9df09d3066f4644ec93b9ddfe373727637f70` (tête de la PR #318, `main` et correctifs du troisième audit).
- Archive : `openguildkit-0.17.0.tgz`, SHA-256 `d9ef2625d03d0d3f439e2a086a033ed6282cb6db2ef14355e6bf7299180f04bd`, construite comme dans `release.yml` ; `--version` répond `0.17.0`.
- Poste : macOS, Node v26.13.0 (le workflow de publication utilise Node 24), npm 11.20.0, Git 2.50.1.

```sh
npm pack ./integrations/ci --ignore-scripts --pack-destination release
shasum -a 256 release/openguildkit-0.17.0.tgz
node examples/export-expiry/resume-check/rehearse.mjs --archive release/openguildkit-0.17.0.tgz --work DOSSIER_VIDE
(cd integrations/ci && npm test)
```

## Montage

[`rehearse.mjs`](resume-check/rehearse.mjs) extrait l'archive, crée des dépôts Git nus (`team/policies`, `team/portal`, `team/service`), des clones complets pour l'agent Jenkins et un `integration.json` au format du [guide du coordinateur](../../integrations/ci/README.md#recheck-one-or-more-repositories). Les auteurs et les dates des commits sont fixes : deux exécutions donnent les mêmes SHA et les mêmes clés de travail.

[`fake-gh.mjs`](resume-check/fake-gh.mjs) remplace `gh` dans le `PATH`. Il répond aux appels que fait `watch` : liste des PR ouvertes, lecture de `pilot/recheck.json` et `pilot/recheck-kit.sha256`, `workflow run`, liste des exécutions par `display_title`, `run view`, `run download`. Une exécution déclenchée rejoue les étapes de [`recheck-workflow.yml`](../../integrations/ci/pilot/recheck-workflow.yml) avec la même archive : contrôle de l'empreinte épinglée, lecture des références au démarrage, refus d'une autre clé de travail, puis `reconcile --run`. Les `git fetch` vers `https://github.com/...` sont redirigés vers les dépôts nus par `url.insteadOf`. Aucun appel ne part vers GitHub.

Preuves conservées : [chronologie](resume-check/timeline-2026-11-24.jsonl) (sortie du script, heure UTC, code de sortie, identifiants d'exécution, tentatives, SHA) et [appels reçus par le faux GitHub](resume-check/github-calls-2026-11-24.jsonl). Les identifiants de tentative sont des UUID tirés à chaque exécution ; les heures changent aussi.

## Scénario 1 : interruption après acceptation

Lot de trois contrôles sur la règle `1c44b3f597b1` (60 min) : `team/portal#1` (45 min, `3a55f4eea8a4`), `team/portal#2` (30 min, `00a0b78c8a05`), `team/service#1` (20 min, `a8ca0a418983`). Le faux GitHub tue le processus `watch` par `SIGKILL` juste après avoir accepté le deuxième déclenchement.

| Étape | Observation |
| --- | --- |
| Passage 1 | Exécutions 101 et 102 acceptées, `watch` tué (signal `SIGKILL`, aucune sortie). État : `ba67f08924b9` en `dispatched` (101), `4d4bd81b14ff` en `requesting` avec la tentative envoyée à 102. `watch.lock` reste en place. Trois preuves locales sont déjà écrites. |
| Passage 2, même état | Verrou du processus mort remplacé. 102 retrouvée par sa tentative (`recovered: true`), 101 suivie, `team/service#1` déclenché une fois (103). Code de sortie 0. |
| Passage 3, exécutions terminées | Les trois contrôles passent à `verified`. Chaque preuve téléchargée porte le commit de la PR et la règle `1c44b3f597b1`. |
| Passage 4 | Aucun nouveau déclenchement. |

Bilan : trois exécutions pour trois contrôles, une seule par clé de travail, un seul fichier de preuve locale par clé, verrou libéré à la fin.

## Scénario 2 : règle ou commit modifiés pendant un contrôle

Un contrôle, `team/portal#1`, export à 45 min au commit `40229caae1f8`.

| Étape | Observation |
| --- | --- |
| A1, règle `deffe6ee5029` (60 min) | Exécution 101 déclenchée, en cours. Verdict local conforme. |
| Règle passée à 30 min (`4bd386e25b92`) pendant 101 | Le passage A2 calcule une nouvelle clé `deb77876a8b3`, verdict local en écart, exécution 102. La preuve conforme de l'ancienne règle reste sous sa propre clé et n'est pas reprise. |
| A3, 101 terminée | Seul le contrôle sur `4bd386e25b92` figure dans le rapport. 101 n'est ni suivie ni comparée. |
| A4, 102 terminée | `verified`, preuve portant sur `4bd386e25b92`. L'enregistrement de l'ancienne clé reste en `dispatched` (101), comme historique. |
| B1, nouveau commit de PR `19c61ca86728` (30 min) | Nouvelle clé `af709361227b`, exécution 103. Le faux GitHub sert pour 103 la preuve de 102, calculée sur l'ancien commit. |
| B2 | `mismatch`, code de sortie 2, message qui donne la commande `--reset`. La preuve sur `40229caae1f8` ne satisfait pas le contrôle. |
| B3 et B4, `--reset` puis exécution 104 | `verified` avec une preuve sur `19c61ca86728`. |
| C1, règle à 20 min (`bd5430316ee2`) | Exécution 105 acceptée mais pas démarrée. |
| Règle passée à 45 min (`1bff077d12cc`) avant le démarrage de 105 | C2 déclenche 106 sur la nouvelle clé `c664c6499fab`. |
| C3, 105 et 106 terminées | 105 lit la règle active à son démarrage, calcule une autre clé et échoue (« This workflow computed another work key »). 106 est `verified` sur `1bff077d12cc`. |

Seules les preuves portant sur le commit de PR, le profil et la règle actifs ont satisfait un contrôle. Les preuves antérieures restent dans le dossier d'état.

## Suite de tests

`npm test` dans `integrations/ci` : 53 tests, 53 réussis, aucune modification du coordinateur.

## Défauts

Aucun défaut trouvé dans ces scénarios. Pas de correctif ni de nouveau test de régression.

## Limites

- Archive construite localement depuis le commit ci-dessus, pas l'archive de la release `v0.17.0` qui n'est pas publiée ([#254](https://github.com/Sandbox-podcast/OpenGuildKit/issues/254)). L'empreinte devra être comparée à celle de `SHA256SUMS.txt`.
- GitHub est simulé. Ne sont pas vérifiés : la sortie réelle de `gh workflow run --json`, le délai avant qu'une exécution apparaisse dans la liste (au-delà de 2 minutes, le coordinateur relance la tentative), l'exécution sur un runner hébergé, les artefacts réels et l'accès aux dépôts privés.
- L'interruption porte sur le processus `watch` de l'agent Jenkins. L'arrêt d'un runner GitHub en cours d'exécution n'est couvert que par les tests unitaires de relance (`conclusion`, `missing`, `timeout`).
- `--publish` (rapports et statuts sur les PR) n'a pas été exercé.
- Node 26 au lieu de Node 22 ou 24, macOS au lieu de Windows et Jenkins.

Les critères de #261 qui demandent un environnement de recette avec une acceptation réelle par GitHub restent à faire, sur les dépôts pilotes autorisés, une fois la release publiée.
