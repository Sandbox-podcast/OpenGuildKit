# Adaptateurs de simulation

> Démonstration Atelier Nova : cette page décrit la maquette, pas le produit. [Ce qui les distingue](interface-projet.md#ce-qui-distingue-la-démonstration)

[`services.ts`](../src/adapters/services.ts) regroupe les services simulés. Le domaine possède l'état des opérations et reçoit les résultats par ses commandes.

| Service | Entrée et résultat actuels | Intégration à prévoir |
| --- | --- | --- |
| Dépôt | Adresse et scénario connu. Retour d'observations avec provenance. | Demander une analyse pour le dépôt et sa révision. Renvoyer les observations séparément des corrections humaines. |
| Conseil | Session, expertise et scénario. Retour d'une contribution ou d'une clarification. | Associer chaque réponse à une session, une expertise et une version du contexte. Conserver les sources et traiter les réponses arrivées après clôture. |
| Forge et contrôles | Exécution, étapes, entrées et contexte simulé. Retour d'un résultat, d'une erreur ou d'un contenu généré. | Attribuer un identifiant à la tentative. Renvoyer les états et résultats avec les versions des entrées. Conserver l'identifiant de la tentative précédente lors d'une relance. |
| Veille | Flux de sources et de signaux fictifs. | Renvoyer les observations avec source et date. Garder faits, interprétations et hypothèses dans leurs champs respectifs. |

Pour connecter une API, dissocier la demande et la réception du résultat. La commande de demande ouvre une opération locale avec les identifiants, les versions de référence et un identifiant d'idempotence. Une commande de réception reprend les gardes du domaine avant d'appliquer le résultat. Le serveur authentifie l'acteur, vérifie ses droits et sépare l'identité technique du service de celle de l'approbateur humain.

Tester les délais, doublons, annulations, retries et réponses arrivées après un changement de version. Les transitions actuelles dans `commands/forge.ts` fournissent la référence pour le cycle d'une exécution.
