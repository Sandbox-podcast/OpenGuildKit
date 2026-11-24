# Partager un livrable avec des droits limités dans Documentalist

Proposition de cadrage pour l'issue [#266](https://github.com/Sandbox-podcast/OpenGuildKit/issues/266), à valider par les mainteneurs d'OpenGuildKit et de Documentalist. Elle est écrite en français, comme l'issue, pour la discussion. Le guide de référence reste [Share a deliverable](documentation.md#share-a-deliverable).

Code lu : [azerothl/documentalist](https://github.com/azerothl/documentalist) à `947429b` (branche `main` au 24 novembre 2026), et la PR [azerothl/documentalist#25](https://github.com/azerothl/documentalist/pull/25) à `8e36a7c`, non fusionnée. Les chemins ci-dessous sont ceux de ce dépôt. Rien ici n'a été rejoué sur une instance, sauf ce que cite le [rapport du 23 novembre](../examples/documentalist/reports/2026-11-23-space-isolation.md).

## Portée actuelle : l'espace

Un lecteur reçoit un espace entier, jamais une page.

- **Invitation.** L'espace porte `accessMode` (`public`, `password` ou `magic_link`) et la liste `allowedEmails` (`src/lib/types.ts`). L'invitation ajoute l'adresse à cette liste et crée un jeton (`src/app/api/spaces/[spaceId]/access/invites/route.ts`, `updateSpaceAllowedEmail` dans `src/lib/store.ts`). Les tables `portal_magic_tokens` et `portal_access_sessions` ne contiennent qu'un espace et une empreinte d'adresse, aucun document (`src/lib/database.ts`, lignes 148-149).
- **Navigation.** La page `src/app/p/[spaceSlug]/[[...path]]/page.tsx` vérifie l'espace avec `portalAllowed` (`src/lib/auth.ts`), puis `publicPortalData` (`src/lib/portal.ts`) renvoie toutes les pages publiées de la langue, sauf les pages masquées et celles placées sous un parent masqué. Le composant client `PortalView` reçoit ces pages avec leur contenu.
- **Recherche.** `PortalSearch` cherche dans le navigateur, sur les pages reçues par `PortalView` (`allPages`). La route `/api/search` exige un compte d'équipe (`secureRoute` sans `public`, `src/lib/api.ts`) : un lecteur du portail ne l'atteint pas.
- **Lien direct.** `findByPath` (`src/lib/tree.ts`) cherche la page dans l'instantané publié. Le seul contrôle est `portalAllowed`, au niveau de l'espace.
- **Session.** Le cookie s'appelle `portal-{spaceId}` et vaut pour le chemin `/p/{slug}` (`src/app/api/portal/magic-link/consume/route.ts`) : une session n'ouvre qu'un espace.
- **Masquage.** `hidden` retire une page pour tous les lecteurs de l'espace, pas pour un seul.
- **Autres espaces.** Le sélecteur de versions ne liste que les espaces publics du groupe (`page.tsx` du portail), et la page d'accueil que les espaces publics publiés (`src/app/page.tsx`). La demande de lien répond `ok` dans tous les cas (`src/app/api/portal/magic-link/request/route.ts`) : elle ne révèle pas si une adresse est invitée.
- **Échéance (PR #25).** `allowedEmailExpirations` ajoute un dernier jour par adresse et par espace (`src/lib/portal-invitations.ts`). La granularité reste l'espace.

Le README de Documentalist dit seulement que « les adresses invitées sont propres à l'espace ». Il ne dit pas qu'un lecteur voit toutes les pages publiées de cet espace.

## Options

### A. Un espace privé par livrable

Aucun changement dans Documentalist. Chaque livrable dont l'accès doit être donné ou retiré seul a son espace, en mode lien magique, avec sa liste de lecteurs.

| Question | Effet |
|---|---|
| Navigation, recherche | Bloquées par construction : l'espace ne publie que le livrable. Vérifié le 23 novembre sur deux espaces (rapport cité plus haut). |
| Lien direct vers un autre livrable | L'autre espace demande une session à son nom : `portalAllowed` échoue et le portail affiche le formulaire de demande de lien. |
| Déplacement | Documentalist ne déplace pas une page d'un espace à un autre : `documentPatchSchema` (`src/lib/validation.ts`) n'accepte pas `spaceId`. Une page passe dans un autre espace par copie (import ou téléversement). Seuls les invités de la destination la lisent. La source sert l'ancien instantané jusqu'à sa prochaine publication. Un déplacement dans l'espace (`parentId`, onglet) change l'adresse de la page, pas ses lecteurs. |
| Nouvelle publication | `publishSpace` (`src/lib/store.ts`) remplace l'instantané par tous les documents de l'espace. Les mêmes invités voient la nouvelle version. Toute page ajoutée à l'espace entre-temps devient visible : l'espace ne doit contenir que le livrable. |
| Révocation | « Retirer l'accès » appelle `revokePortalMagicAccess(spaceId, email)` (`src/lib/auth.ts`) : liens et sessions de cette adresse pour cet espace sont supprimés aussitôt. Les autres espaces du même lecteur restent ouverts. |
| Espaces existants | Inchangés. |
| Coût | Un espace, un réglage d'accès et une publication par livrable. Avec l'import GitHub, un dossier par livrable. Une page commune à plusieurs livrables est copiée dans chaque espace. Limite lue : 500 invitations par espace (`updateSpaceAllowedEmail`). Aucune limite du nombre d'espaces n'a été trouvée. |

Ce qu'OpenGuildKit ajoute sans toucher à Documentalist : `docs share add --dedicated-space` enregistre l'espace comme réservé au livrable. Le registre refuse ensuite tout autre livrable dans cet espace, et `share list` et `share check` signalent, pour un espace non réservé, les autres livrables que ses lecteurs peuvent lire. OpenGuildKit ne voit pas ce que l'espace publie : il faut toujours vérifier depuis une session de lecteur ([guide](documentation.md#share-one-deliverable-in-an-isolated-space)).

### B. Des droits par document dans Documentalist

L'invitation (espace, adresse) porterait une liste de documents permis, ou de sous-arbres. Absence de liste : tout l'espace, comme aujourd'hui.

Points à modifier, tous côté serveur, avant que les données partent vers le navigateur :

- `portalAllowed` doit rendre l'adresse de la session, pas un booléen ;
- la page du portail doit filtrer les documents avant `PortalView`, sinon la liste entière part dans la réponse et la recherche la parcourt ;
- un lien direct vers une page non permise doit répondre 404, et `generateMetadata` ne doit pas renvoyer son titre ;
- les catégories parentes d'une page permise doivent rester visibles sans exposer leurs autres enfants ;
- les liens internes d'une page permise vers une page non permise doivent être neutralisés ou mener au 404.

Effets à fixer :

- **Déplacement.** Un droit par identifiant suit la page dans l'espace. Un droit par sous-arbre se perd si la page en sort. Avec la synchronisation GitHub ou GitLab, un fichier retiré puis remis crée une page avec un nouvel identifiant (voir [Synchronization](documentation.md#synchronization)) : le droit est perdu.
- **Nouvelle publication.** Les droits s'appliquent à l'instantané publié. Une page nouvelle reste invisible tant qu'elle n'est pas permise (refus par défaut).
- **Révocation.** Retirer l'adresse retire tout l'espace. Retirer une page de la liste doit valoir pour les sessions ouvertes, donc être vérifié à chaque requête.
- **Compatibilité.** Une invitation sans liste garde l'espace entier.

C'est l'option la plus fine, et la plus large à tester : chaque endroit qui sert l'instantané est une fuite possible. Elle demande une PR dans Documentalist, avec ses tests HTTP.

### C. Un lien signé par document

Un jeton lié à (espace, document, adresse), avec une échéance, ouvrirait une vue d'une seule page, sans navigation ni recherche. Il faut une nouvelle table, une nouvelle route et une vue réduite.

- Navigation et recherche sont absentes de la vue. La session ouverte par le jeton ne doit pas satisfaire `portalAllowed`, sinon les liens directs vers les autres pages s'ouvrent.
- Un jeton porteur se transmet. S'il est lié à une adresse, on retrouve le parcours du lien magique, page par page.
- **Déplacement** dans l'espace : l'identifiant reste, le lien aussi. Vers un autre espace : lien mort. **Nouvelle publication** : le lien montre la dernière version publiée. **Révocation** : invalider le jeton.
- Les espaces existants ne changent pas.

Elle double le portail pour un cas que l'option A couvre déjà.

## Recommandation

Retenir l'option A pour le pilote : c'est la seule qui ne demande aucun changement dans Documentalist, elle a été vérifiée sur deux espaces, et OpenGuildKit l'enregistre et la protège maintenant avec `--dedicated-space`. Rouvrir l'option B si le nombre d'espaces devient une charge pour les équipes, avec la liste de points ci-dessus comme cahier des charges pour Documentalist. Écarter l'option C.

## Ce qui reste à décider

1. Valider l'option A comme modèle, ou en choisir une autre (premier critère de #266).
2. Rejouer la recette du 23 novembre sur la version de Documentalist retenue : la révision du build alors utilisé n'est pas connue. Si la PR #25 est fusionnée, la rejouer avec une échéance.
3. Valider les effets d'un déplacement, d'une nouvelle publication et d'une révocation décrits pour l'option A.
4. Écrire la portée dans Documentalist (quatrième critère, « dans les deux outils ») : une phrase dans son README et son guide, disant qu'un lecteur invité lit toutes les pages publiées non masquées de l'espace. Cela demande une PR dans `azerothl/documentalist`.
