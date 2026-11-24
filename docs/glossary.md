# Glossary · Glossaire

The words OpenGuildKit uses in its commands, questions and output, in English and in French. Each entry gives the word as the CLI writes it, then its French gloss, then one sentence in each language. The entries follow the order of a task, from setup to closing.

Les mots qu'OpenGuildKit emploie dans ses commandes, ses questions et ses messages, en anglais et en français. Chaque entrée donne le mot tel que la CLI l'écrit, puis sa traduction, puis une phrase dans chaque langue. Les entrées suivent l'ordre d'une tâche, de la configuration à la clôture.

[README](../README.md) · [Version française](../README.fr.md) · [Task workflow](workflow.md)

## Project setup · Configuration du projet

### `task` · tâche

**EN** One request to the team (a feature, a fix, upkeep or a decision) that the boards review and a person approves before work starts, from `task new` to `task complete`.

**FR** Une demande faite à l'équipe (une fonctionnalité, une correction, de l'entretien ou une décision) que les boards relisent et qu'une personne approuve avant le travail, de `task new` à `task complete`.

### `pattern` · modèle de projet

**EN** A description of a stack, a work method or a regulation that says when it applies to a project and which rule packs it brings.

**FR** Une description de stack, de méthode de travail ou de réglementation, qui dit quand elle s'applique au projet et quels packs de règles elle apporte.

### `norm` · norme

**EN** A pattern for a regulation or standard (GDPR, DORA, PCI DSS, the AI Act...) that the questionnaire proposes because of your sector, your personal data, decisions about people or a payment provider in your stack, for you to keep or decline one by one; it is active only once accepted, and a decline records who, when and why.

**FR** Un pattern de réglementation ou de norme (RGPD, DORA, PCI DSS, AI Act...) que le questionnaire propose à cause de ton secteur, de tes données personnelles, de décisions sur des personnes ou d'un prestataire de paiement de ta stack, et que tu gardes ou refuses une par une ; elle n'est active qu'une fois acceptée, et un refus enregistre qui, quand et pourquoi.

### `core method` · méthode de base

**EN** The one or two methods of a role whose rules fit any work of that job; setup selects them for the role, and suggests the role's other methods with one line saying why.

**FR** La ou les deux méthodes d'un rôle dont les règles valent pour tout travail de ce métier ; la configuration les retient pour le rôle et suggère ses autres méthodes, avec une ligne qui dit pourquoi.

### `unsure` · je ne sais pas

**EN** The answer to give a setup question you cannot answer: `init` then applies what the question's `unsure` field announces, the default or the answer that keeps a protection, and says so.

**FR** La réponse à donner à une question de configuration quand tu ne sais pas : `init` applique alors ce qu'annonce le champ `unsure` de la question, le défaut ou la réponse qui garde une protection, et le dit.

### `pack` · pack de règles

**EN** A set of rules and checks for the agent that `init` writes into `AGENTS.md`, such as the rules for React or for GDPR.

**FR** Un ensemble de règles et de contrôles pour l'agent, que `init` écrit dans `AGENTS.md`, par exemple les règles de React ou du RGPD.

### `component` · composant

**EN** A part of the repository with its own folder and stack, such as `apps/web`, that `detect` finds; a pattern applies to the component that uses its technologies.

**FR** Une partie du dépôt avec son dossier et sa stack, comme `apps/web`, que `detect` repère ; un pattern s'applique au composant qui utilise ses technologies.

### `host` · agent hôte

**EN** The AI coding agent that works in the project and runs the commands: `claude-code`, `codex` or `other`.

**FR** L'agent de code IA qui travaille dans le projet et lance les commandes : `claude-code`, `codex` ou `other`.

### `hook` · déclencheur

**EN** A small command the host runs by itself at set moments, such as each request or each file edit; `host apply` installs the hooks of the guard.

**FR** Une petite commande que l'agent hôte lance de lui-même à des moments précis, à chaque demande ou à chaque modification de fichier ; `host apply` installe les déclencheurs du garde-fou.

### `guard` · garde-fou

**EN** The project setting that says how firmly the board is brought to the agent: `off` (nothing reminds it), `observe` (an edit without an approved task is flagged) or `enforce` (that edit is refused).

**FR** Le réglage du projet qui dit avec quelle fermeté le board est rappelé à l'agent : `off` (rien ne le rappelle), `observe` (une modification sans tâche approuvée est signalée) ou `enforce` (elle est refusée).

## Boards and review · Les boards et la revue

### `board` · comité métier

**EN** The reviewers of one discipline (security, legal, marketing...) that OpenGuildKit selects for a task and that give it a verdict.

**FR** Les relecteurs d'un métier (sécurité, juridique, marketing...) qu'OpenGuildKit choisit pour une tâche et qui rendent un verdict.

### `brain` · cerveau métier

**EN** What a board knows: its specialists, what each one checks, the evidence it asks for, its objections, its decision criteria and the methods of its discipline.

**FR** Ce que sait un board : ses spécialistes, ce que chacun vérifie, les preuves qu'il demande, ses objections, ses critères de décision et les méthodes de son métier.

### `lens` · angle de spécialiste

**EN** One specialist inside a brain, such as the revenue accountant of finance, who gives one finding on each task.

**FR** Un spécialiste au sein d'un brain, comme le comptable des revenus de la finance, qui rend un constat sur chaque tâche.

### `surface` · zone touchée

**EN** The answer that says which areas a task affects: `customer` (what customers see), `service`, `infrastructure` or `business`; several can apply.

**FR** La réponse qui dit quelles zones la tâche touche : `customer` (ce que voient les clients), `service`, `infrastructure` ou `business` ; plusieurs peuvent s'appliquer.

### `open point` · point ouvert

**EN** Something the scoping left unclear, such as an `unsure` answer or a missing outcome; it does not stop the consultation, and each board says how it affects its advice.

**FR** Ce que le cadrage laisse flou, comme une réponse `unsure` ou un résultat attendu manquant ; il n'arrête pas la consultation, et chaque board dit en quoi il pèse sur son avis.

### `pass` · passage d'un board

**EN** One board's own review of the task, started with `task pass` and returned with `task submit`, without seeing the other boards.

**FR** La revue de la tâche par un seul board, lancée avec `task pass` et rendue avec `task submit`, sans voir les autres boards.

### `not concerned` · non concerné

**EN** A lens or a rule left out of a task because the task does not touch its area; it is listed with the reason and needs no answer.

**FR** Un angle ou une règle écarté d'une tâche parce que la tâche ne touche pas son domaine ; il est listé avec la raison et ne demande aucune réponse.

### `evidence` · preuve

**EN** What supports a finding: a project file, a test, a measurement, a public source or the requester's words, each with what it establishes.

**FR** Ce qui appuie un constat : un fichier du projet, un test, une mesure, une source publique ou les mots du demandeur, chacun avec ce qu'il établit.

### `evidence_refs` · renvois aux preuves

**EN** The numbers of the items, counted from 1, that a finding or an answer cites in its board's own evidence list: `[1, 3]` cites the first and the third.

**FR** Les numéros des éléments, comptés à partir de 1, qu'un constat ou une réponse cite dans la liste de preuves de son board : `[1, 3]` cite le premier et le troisième.

### `challenge` · mise à l'épreuve

**EN** The part of a board's review that compares the proposal with an alternative and names the failure to watch for; `task challenge` prints the decision brief built from all the boards.

**FR** La partie de l'avis d'un board qui compare la proposition à une autre option et nomme l'échec à surveiller ; `task challenge` imprime la note de décision tirée de tous les boards.

### `deliberate` · délibérer

**EN** The step where boards that disagree answer each other's objections on the same point, with `task deliberate` then `task respond`.

**FR** L'étape où les boards en désaccord répondent aux objections des autres sur le même point, avec `task deliberate` puis `task respond`.

### `maintain` · maintenir

**EN** A board's answer to an objection when it keeps its position, citing its evidence.

**FR** La réponse d'un board à une objection quand il garde sa position, en citant ses preuves.

### `amend` · amender

**EN** A board's answer to an objection when it changes its position to meet the other board's point, and says how.

**FR** La réponse d'un board à une objection quand il modifie sa position pour tenir compte de l'autre board, et dit comment.

### `concede` · céder

**EN** A board's answer to an objection when it accepts the other board's point; the objection is then resolved.

**FR** La réponse d'un board à une objection quand il accepte le point de l'autre board ; l'objection est alors résolue.

## Decision · La décision

### `blocker` · point bloquant

**EN** A condition a board sets, with its owner and what would clear it, that must be cleared or waived by a person before approval.

**FR** Une condition qu'un board pose, avec son responsable et ce qui la lèverait, et qu'une personne doit lever ou couvrir par une dérogation avant l'approbation.

### `condition of approval` · condition de l'approbation

**EN** A blocker of phase `verification`: you can approve the task, but it cannot close until a person clears the blocker with evidence from the implementation.

**FR** Un point bloquant de phase `verification` : tu peux approuver la tâche, mais elle ne se clôt pas tant qu'une personne n'a pas levé ce point avec une preuve tirée de la réalisation.

### `clear` · lever

**EN** What a person does, at a terminal with `task clear`, to record the evidence that resolves a blocker.

**FR** Ce que fait une personne, dans son terminal avec `task clear`, pour enregistrer la preuve qui résout un point bloquant.

### `waive` · accorder une dérogation

**EN** To accept, at a terminal with `task waive`, that a blocker stays unresolved, with a reason, a scope and an end date, when the project's waiver policy allows it.

**FR** Accepter, dans son terminal avec `task waive`, qu'un point bloquant reste non résolu, avec une raison, un périmètre et une date de fin, quand la politique de dérogation du projet le permet.

### `approval` · approbation

**EN** The decision of a person, at a terminal with `task decide --approve` or by a signature, that the reviewed scope can be implemented; the interface never records it.

**FR** La décision d'une personne, dans son terminal avec `task decide --approve` ou par une signature, que le périmètre relu peut être réalisé ; l'interface ne l'enregistre jamais.

### `revoke` · retirer une approbation

**EN** What a person does, at a terminal with `task revoke ID --by NAME --reason WHY`, to withdraw an approval that should no longer cover the work; the web interface refuses it and gives the command.

**FR** Ce que fait une personne, dans son terminal avec `task revoke ID --by NAME --reason WHY`, pour retirer une approbation qui ne doit plus couvrir le travail ; l'interface web le refuse et donne la commande.

### `seal` · sceau

**EN** A fingerprint of what was approved, recorded with the approval, that detects a later accidental change; only a signed approval proves who approved, and the approver's name is part of what it covers, so it cannot be replaced afterwards ([personal data](personal-data.md#the-approver)).

**FR** Une empreinte de ce qui a été approuvé, enregistrée avec l'approbation, qui détecte une modification accidentelle ultérieure ; seule une approbation signée prouve qui a approuvé, et le nom de la personne qui approuve en fait partie : il ne peut plus être remplacé ensuite ([données personnelles](personal-data.md#the-approver)).

### `handoff` · brief d'implémentation

**EN** What `task handoff` gives the agent once the task is approved: the approved scope, the rules in force, the checks to run and the boards' review.

**FR** Ce que `task handoff` remet à l'agent une fois la tâche approuvée : le périmètre approuvé, les règles en vigueur, les contrôles à lancer et l'avis des boards.

## Closing · La clôture

### `named evidence` · pièce justificative

**EN** A document kept outside the code that a rule asks for, such as the record of processing activities or the DPIA decision; its owner provides it as a project path or an `https://` link, and the agent never writes it.

**FR** Un document tenu hors du code qu'une règle demande, comme le registre des traitements ou la décision d'AIPD ; son responsable le fournit sous forme de chemin du projet ou de lien `https://`, et l'agent ne le rédige jamais.

### `done-with-reservations` · terminée avec réserves

**EN** The closing status of a task that is done while some points stay open, such as a skipped rule, a check that could not run or a disagreement; `task complete` lists them, the most serious first.

**FR** Le statut de clôture d'une tâche terminée alors que des points restent ouverts, comme une règle écartée, un contrôle qui n'a pas pu tourner ou un désaccord ; `task complete` les liste, du plus grave au moins grave.

## Tools · Les outils

### `MCP` · MCP

**EN** Model Context Protocol, the standard way for an agent to read and act in a tool such as Jira or Zendesk through a server; `tools plan` and `tools apply` connect them.

**FR** Model Context Protocol, la façon standard pour un agent de lire et d'agir dans un outil comme Jira ou Zendesk par un serveur ; `tools plan` et `tools apply` les branchent.

### `mock` · simulation

**EN** A stand-in MCP server that answers with made-up data, for a demo or a test without accounts or network (`tools apply --mock`).

**FR** Un serveur MCP de remplacement qui répond avec des données inventées, pour une démonstration ou un test sans compte ni réseau (`tools apply --mock`).

### `scenario` · scénario des simulations

**EN** A file written by `tools scenario` that gives the mocks records about your project instead of the generic sample data.

**FR** Un fichier écrit par `tools scenario` qui donne aux simulations des données sur ton projet à la place des exemples génériques.

## Regulation and marketing · Réglementation et marketing

### `DPIA` · AIPD

**EN** Data Protection Impact Assessment, the study the GDPR requires before a processing likely to put people's rights at high risk.

**FR** Analyse d'impact relative à la protection des données, l'étude que le RGPD impose avant un traitement susceptible d'engendrer un risque élevé pour les droits des personnes.

### `UTM` · paramètres UTM

**EN** Tags added to a link (`utm_source`, `utm_medium`, `utm_campaign`) so that analytics tools know which campaign brought a visit; `deliverable utm` builds such a link.

**FR** Des étiquettes ajoutées à un lien (`utm_source`, `utm_medium`, `utm_campaign`) pour que l'outil de mesure d'audience sache quelle campagne a amené la visite ; `deliverable utm` construit ce lien.

## Web interface words · Les mots de l'interface web

**EN** `openguildkit ui` has two styles. The Pro style uses the French terms of this glossary. The RPG style keeps game words for a task and a lens, and names each place of the project; this table gives the CLI term and the Pro word for each.

**FR** `openguildkit ui` a deux styles. Le style Pro emploie les termes français de ce glossaire. Le style RPG garde des mots de jeu pour une tâche et un angle de spécialiste, et donne un nom à chaque lieu du projet ; ce tableau donne pour chacun le terme de la CLI et le mot du mode Pro.

| RPG | CLI | Pro |
| --- | --- | --- |
| quête | `task` | tâche |
| lentille | `lens` | angle de spécialiste |
| scellée | `approved` | approuvée |
| Conseil | `task consult`, `task review`, `task decide` | Consultation |

Each place of the interface, with what it shows. · Chaque lieu de l'interface, avec ce qu'il montre.

| Lieu RPG | Pro | CLI |
| --- | --- | --- |
| Royaume | Projet | `task list`, `check` |
| Blueprint | Profil et règles | `.openguildkit/project.json`, `preview`, `detect` |
| Guilde | Cerveaux | `brains` |
| Conseil | Consultation | `task questions`, `task consult`, `task review`, `task decide` |
| Quêtes | Tâches | `task list`, `task show`, `task new` |
| Bibliothèque | Bibliothèque | `references`, `patterns`, `catalog` |
| Forge | Réalisation | `task handoff`, `task verify`, `task result`, `deliverable`, `tools` |
| Tour de guet | Contrôles | `check`, `host check`, `guard`, `alerts` |
| Observatoire | Marché | `market` |
| Documentation | Documentation | `docs export`, `docs share`, `task export` |
| Chroniques | Historique | `task show` |
| Intendance | Réglages | `host apply`, `update`, `integrations` |
| Arsenal | Fonctionnalités | `features`, `tools plan` |
