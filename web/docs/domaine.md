# Domaine

> Démonstration Atelier Nova : cette page décrit la maquette, pas le produit. [Ce qui les distingue](interface-projet.md#ce-qui-distingue-la-démonstration)

`AppState` contient les organisations, les utilisateurs, les tables d'objets, le catalogue local, la session et les préférences. Un produit regroupe des dépôts et modules. Un projet de travail référence son produit principal, son responsable et la version du Blueprint qu'il suit. Les relations entre produits conservent leurs périmètres respectifs. [Types](../src/demo/domain/types.ts)

Une session de Conseil garde le contexte et les règles examinés, les expertises, leurs contributions et les options. Une décision peut produire une quête. La quête relie tâches, critères, livrables, contrôles et approbations. Un résultat relie une exécution et ses entrées à des preuves. Les Chroniques parcourent ces relations dans les deux sens. [Sélecteurs](../src/demo/domain/selectors.ts)

`execute` applique la commande sur une copie de travail et conserve l'état précédent en cas de refus. `check` utilise les mêmes gardes pour les commandes proposées par l'interface. Les événements et le résultat sont enregistrés avec les autres mutations. [Moteur](../src/demo/domain/engine.ts)

## États et transitions

[`machines.ts`](../src/demo/domain/machines.ts) définit les états, leurs libellés, les transitions autorisées et la capacité requise. [`transition`](../src/demo/domain/commands/transitions.ts) vérifie l'état de départ, le périmètre, l'acteur, la justification et les gardes spécifiques à l'objet avant d'appliquer les effets.

| Objet | Chemin principal | Autres issues |
| --- | --- | --- |
| Blueprint | Brouillon, en revue, publié | Retour en brouillon, archivage |
| Conseil | Préparé, en cours, en attente d'arbitrage, terminé | Suspension et reprise, réouverture des échanges, annulation |
| Décision | Brouillon, en revue, approuvée | Révision, refus, remplacement après approbation de la nouvelle version, annulation |
| Quête | À préparer, prête ou démarrée, en cours, en revue, terminée | Blocage et déblocage, annulation, réouverture |
| Tâche | À préparer ou prête, en cours, terminée | Blocage et déblocage, annulation, réouverture |
| Livrable | Brouillon, en revue, approuvé, publié | Demande de changements, remplacement, archivage |
| Exécution | En attente, en cours, terminée | Suspension et reprise, erreur, annulation. Une relance ouvre une tentative liée. |
| Approbation | Attendue, approuvée | Refus, révocation, expiration |
| Exception | Brouillon, demandée, approuvée | Refus, révocation, expiration |
| Partage local | Actif | Expiration, révocation |

Le résultat de contrôle distingue non évalué, réussi, échoué, non concluant et non applicable. `resultFreshness` évalue séparément la validité du résultat en comparant ses entrées au contexte courant. Le résultat initial reste accessible. [Validité](../src/demo/domain/selectors.ts)

## Règles et couverture

`Domaine` renvoie à [`rules.test.ts`](../tests/domain/rules.test.ts). `Parcours` désigne le [scénario du domaine](../tests/domain/journey.test.ts) et son [rejeu navigateur](../tests/e2e/journey.spec.ts). `Interface` renvoie aux [scénarios ciblés](../tests/e2e/views.spec.ts). Une couverture partielle indique ce que ces tests démontrent et sépare les cas seulement relus dans le code.

| Règle | Point d'application | Vérification |
| --- | --- | --- |
| RG-01 Périmètre | `engine.ts` (`list`, `must`), `workspace.switchOrg` | Domaine, changement d'organisation. |
| RG-02 Responsable et archivage | `workspace.createProject`, `archiveProject`, `restoreProject`, `authorize` | Revue du code. Cycle complet d'archivage et restauration sans test ciblé. |
| RG-03 Provenance et inconnues | `questionnaire.ts`, `blueprint.confirmInferred`, `transition` | Domaine, publication initiale et arbitrage bloqué. Parcours, résolution de l'inconnue. |
| RG-04 Immutabilité et versions | `blueprint.startBlueprintDraft`, `setFact`, transition Blueprint | Domaine et Parcours, refus de modifier une version publiée et publication après revue. |
| RG-05 Héritage | `selectors.resolveRules`, `blueprint.addRule`, `arbitrateConflict` | Domaine, adaptation interdite et conflits. Parcours, arbitrage avant publication. |
| RG-06 Adoption après examen | `selectors.blueprintImpacts`, `blueprint.adoptBlueprint` | Parcours, adoption puis réexamen avec décision antérieure conservée. |
| RG-07 Nature et sources | `adapters/catalogue.ts` (`referenceSchema`, `parseCatalogueMarkdown`) | Domaine, import et comptage. Interface, recherche par sigle et sources. |
| RG-08 Applicabilité | `questionnaire.suggestReferences`, `knowledge.setApplicability`, `validateApplicability` | Parcours, proposition puis validation. |
| RG-09 Règle locale versionnée | `types.RuleVersion`, `blueprint.addRule`, `editRule` | Domaine, règle ajoutée et adaptation contrôlée. Structure et champs obligatoires relus. |
| RG-10 Activation et contrôle | `blueprint.adoptBlueprint`, `forge.launchControl`, `advanceRun` | Parcours, adoption avant exécution et résultats distincts. |
| RG-11 Certification | Exports Blueprint et états `result` dans `machines.ts` | Revue des libellés et de la note d'export. Aucun test dédié. |
| RG-12 Capacités | `permissions.authorize`, `engine.check`, `engine.execute` | Domaine et Interface, refus pour le lecteur, y compris dans la palette. |
| RG-13 Restrictions des agents | `AGENT_CAPABILITIES`, `knowledge.restrictTools`, `transition` | Domaine, refus d'approbation, d'élargissement des outils et d'auto-validation. |
| RG-14 Validation humaine | `engine.check`, `transitions.approvalGuard` | Domaine, Interface et Parcours, approbation refusée à l'agent. |
| RG-15 Version approuvée | `selectors.approvalValidity`, `transitions.createApproval` | Domaine, ancienne approbation invalide pour la nouvelle version. |
| RG-16 Séparation des identités | `transitions.approvalGuard`, `selectors.requiresDistinctApprover` | Domaine, auto-approbation refusée après changement de rôle. Parcours, approbatrice distincte. |
| RG-17 Dossier du Conseil | `work.createCouncil`, `produceContribution` | Parcours, six contributions et version prise en compte par la décision. |
| RG-18 Options et désaccords | `work.annotateCouncil`, `proposeDecision`, garde de transition | Parcours, options, annotation et refus d'arbitrer avant les avis. |
| RG-19 Révision de décision | `work.reviseDecision`, transition `decision.approve` | Revue du code. Remplacement d'une décision après approbation de la révision sans test ciblé. |
| RG-20 Conversion unique | `work.convertDecision` | Domaine et Parcours, conversion répétée sans deuxième quête. |
| RG-21 Origine et critères d'une quête | `work.createQuest`, `convertDecision`, `setCriterion`, `selectors.closureReport` | Parcours de conversion et d'acceptation. Origine de la création directe relue dans le code. |
| RG-22 Préconditions et motifs | `machines.ts`, `commands/transitions.ts` | Parcours et Interface, préconditions et mouvements refusés. Couverture partielle des motifs. |
| RG-23 Dépendances | `work.setDependency`, `selectors.wouldCycle` | Domaine, cycle refusé. |
| RG-24 Clôture par déplacement | `transition` et `selectors.closureReport` | Interface, déplacement du tableau vers Terminé refusé. |
| RG-25 Conditions de clôture | `selectors.closureReport`, `coveringException`, transition `quest.close` | Domaine, contrôle échoué, exception recevable et exception interdite. Parcours, preuve et approbation requises. |
| RG-26 Exécution et résultat | `forge.launchControl`, `advanceRun`, `types.Run` et `Result` | Parcours, exécution et résultats successifs. |
| RG-27 Erreur et absence de preuve | `forge.advanceRun`, `oversight.markNotApplicable`, `selectors.closureReport` | Domaine, erreur technique sans réussite. Justification du non-applicable relue dans le code. |
| RG-28 Traçabilité de la preuve | `forge.advanceRun`, `types.Evidence`, `selectors.lineage` | Parcours, chaîne vers contrôle, exécution et preuve. Champs relus dans le modèle. |
| RG-29 Fraîcheur et adoption | `selectors.resultFreshness`, `blueprint.adoptBlueprint`, `forge.adoptDeliverableVersion` | Domaine et Parcours, preuve périmée après adoption et résultat conservé. |
| RG-30 Annulation, relance et budgets | Transition `run.cancel`, `forge.advanceRun`, `retryRun` | Domaine, finalisation tardive ignorée, nouvelle tentative et budget atteint. |
| RG-31 Dossier d'exception | `oversight.saveException`, transition `exception.request` | Domaine, demande incomplète conservée en brouillon. |
| RG-32 Règle non dérogeable | `selectors.ruleIsDerogable`, transition `exception.approve` | Domaine, refus d'une exception non dérogeable. |
| RG-33 Échéance et réexamen | `oversight.tick`, `transitions.reopenAfterException`, `selectors.approvalValidity` | Domaine, exception expirée. Parcours, changement de contexte. |
| RG-34 Versions des livrables | `forge.editDeliverable`, `adoptDeliverableVersion`, `restoreDeliverableVersion` | Domaine, proposition sur un livrable approuvé. Parcours, correctif et nouvelle preuve. |
| RG-35 Documentation liée | `forge.regenerateDeliverable`, `selectors.docUpdateReasons` | Parcours, publication et chaîne de versions. Régénération et restauration sans test dédié. |
| RG-36 Sources et signaux de veille | `oversight.collectSignals`, `updateSignal`, modèle `Signal` | Revue du code et des données de simulation. Aucun test dédié. |
| RG-37 Mise à jour proposée | `forge.checkSkillUpdate`, `decideSkillUpdate`, `knowledge.proposeReferenceUpdate`, `restoreReference` | Revue du code. Propositions de skill et de référence. Les packs locaux sont éditables via `savePack`, sans cycle de mise à jour équivalent identifié. |
| RG-38 Partage local | `oversight.createShare`, `openShare`, `selectors.shareStatus` | Domaine et Parcours, audience, refus, révocation. Domaine, échéance. |
| RG-39 Chroniques et compensation | `engine.execute`, `oversight.compensateEvent` | Parcours, chaîne d'objets dans les Chroniques. Compensation disponible pour les actions listées dans `COMPENSABLE`, sans test dédié. |
| RG-40 État dérivé | `selectors.kingdomStats`, `notifications`, `allReferences`, `app/store.ts` | Domaine et Interface, comptage du catalogue. Parcours, guide à 20 étapes selon les objets. |
| RG-41 Import | `adapters/storage.ts`, `adapters/catalogue.ts`, `knowledge.applyCatalogueImport`, `demo/ui/content.tsx` | Domaine et Interface, sauvegarde invalide. Domaine, doublons et protocoles d'URL. Rendu des aperçus relu. |
| RG-42 Récupération et répétition | `engine.execute`, `app/store.ts`, `adapters/storage.ts`, `forge.retryRun`, `app/App.tsx` | Domaine, sauvegarde illisible, conversion et relance. Interface, rechargement et route inexistante. |
