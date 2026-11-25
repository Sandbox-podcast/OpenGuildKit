# Reprise des contrôles sur l'archive publiée, 25 novembre 2026

Vérification de l'archive Node publiée `v0.17.0` pour [#261](https://github.com/Sandbox-podcast/OpenGuildKit/issues/261). Elle reprend la [répétition du 24 novembre](resume-check-2026-11-24.md), cette fois sur le fichier publié, sous Windows.

## Versions et commande

- Archive : `openguildkit-0.17.0.tgz` de la release, SHA-256 `b8780eefcbaf6c4bd89c692b3177a766daa4a72246e59f4828a0b83d4445c14c`. `--version` répond `0.17.0`.
- Poste : Windows 10.0.26320, Node v22.20.0, Git 2.49.0.windows.1.
- Le coordinateur de l'archive n'est pas modifié. Seul le montage local l'est, pour que `gh` et `git fetch` restent sur la machine.

```sh
node examples/export-expiry/resume-check/rehearse.mjs --archive openguildkit-0.17.0.tgz --work DOSSIER_VIDE
```

Les deux scénarios se terminent avec le code 0. Les commits, les règles et les clés de travail sont les mêmes que le 24 novembre. Les identifiants de tentative et les heures changent à chaque exécution.

Preuves : [chronologie](resume-check/timeline-2026-11-25.jsonl) et [appels reçus par le faux GitHub](resume-check/github-calls-2026-11-25.jsonl).

## Montage sous Windows

Trois adaptations du script, sans effet sur macOS ou Linux :

- `url.insteadOf` est écrit avec des barres obliques. Git traite les barres obliques inverses de `C:\...` comme des échappements, et le fetch ne trouvait plus le dépôt nu.
- Node résout `gh.exe` avant un `gh.cmd` placé plus tôt dans `PATH`. Le script compile avec `csc.exe` un petit `gh.exe` qui relaie vers [`fake-gh.mjs`](resume-check/fake-gh.mjs). La variable `Path` est remplacée, pas doublée par une variable `PATH`.
- Ce relais est le parent du script. Pour l'interruption, le faux `gh` arrête donc le parent de `gh.exe`, c'est-à-dire `watch`. Windows ne renvoie pas le signal `SIGKILL` : le processus sort avec le code 1, sans rapport.

## Scénario 1 : interruption après acceptation

Même lot que le 24 novembre : règle `1c44b3f597b1`, `team/portal#1` `3a55f4eea8a4` (clé `ba67f08924b9`), `team/portal#2` `00a0b78c8a05` (clé `4d4bd81b14ff`), `team/service#1` `a8ca0a418983` (clé `c25170462123`).

| Étape | Observation |
| --- | --- |
| Passage 1 | Exécutions 101 et 102 acceptées, `watch` arrêté (code 1, aucun rapport). `ba67f08924b9` en `dispatched` (101), `4d4bd81b14ff` en `requesting`. `watch.lock` reste en place. Trois preuves locales sont déjà écrites. |
| Passage 2 | 102 retrouvée par sa tentative (`recovered: true`), 101 suivie, `team/service#1` déclenché une fois (103). Code 0. |
| Passages 3 et 4 | Les trois contrôles passent à `verified`, puis aucun nouveau déclenchement. Les preuves portent la règle `1c44b3f597b1` et le commit de chaque PR. |

Trois exécutions, une par clé de travail, un fichier de preuve locale par clé, verrou libéré à la fin.

## Scénario 2 : règle ou commit modifiés pendant un contrôle

Mêmes références que le 24 novembre : règle initiale `deffe6ee5029`, commit `40229caae1f8`, puis `4bd386e25b92`, `19c61ca86728`, `bd5430316ee2` et `1bff077d12cc`. Les clés `3fb9c424e6e7`, `deb77876a8b3`, `af709361227b`, `64d8a5d431ef` et `c664c6499fab` sont inchangées.

| Étape | Observation |
| --- | --- |
| A1 à A4 | 101 reste en historique `dispatched`. 102 est `verified` sur `4bd386e25b92`. La preuve conforme de l'ancienne règle reste sous `3fb9c424e6e7`. |
| B2 | `mismatch`, code 2, preuve de `40229caae1f8` refusée pour le commit `19c61ca86728`. |
| B4 | Après `--reset`, 104 est `verified` sur `19c61ca86728`. |
| C3 | 105 échoue : « This workflow computed another work key ». 106 est `verified` sur `1bff077d12cc`. |

## Défauts

Aucun défaut du coordinateur sur ces scénarios. Le résultat est le même que sur l'archive construite localement le 24 novembre.

## Limites

- GitHub est simulé. Ne sont pas vérifiés : un dépôt réel, un runner hébergé, les artefacts réels, l'accès aux dépôts privés et `--publish`.
- L'interruption porte sur le processus `watch` de l'agent. L'arrêt d'un runner GitHub n'est pas rejoué ici.
- Sous Windows, la répétition a besoin de `csc.exe` (.NET Framework) pour placer le faux `gh.exe` devant le `gh` installé.

Le critère de #261 qui demande une acceptation sur de vrais dépôts GitHub reste à faire, sur les dépôts pilotes autorisés.
