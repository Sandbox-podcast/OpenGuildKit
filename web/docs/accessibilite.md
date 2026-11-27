# Accessibilité de l'interface web

Les contrôles couvrent Chrome, le clavier, le mouvement réduit et les écrans étroits, dans les deux modes : l'interface d'un projet (`openguildkit ui`) et la démonstration Atelier Nova. Les parcours et limites de la vérification sont consignés dans [Vérifications](verification.md).

## Interface d'un projet

- Le premier Tab atteint le lien « Aller au contenu », qui place le focus sur le contenu principal. Chaque lieu a un seul titre principal.
- Ctrl+K (Cmd+K sur Mac) ouvre la recherche, même depuis un champ ; `/` l'ouvre hors d'un champ. Entrée dans la recherche ouvre le premier résultat.
- Hors d'un champ et hors d'un dialogue, `g` suivi de l'initiale d'un lieu y mène (`g q` pour les quêtes, `g f` pour la Forge), et `m` passe du style RPG au style Pro. Ces raccourcis à une touche ne s'activent pas pendant la saisie.
- À faible largeur, la navigation s'ouvre par un bouton ; Échap la referme. Chaque lien de lieu porte son nom et, en description, son rôle et son compteur.
- Une décision réservée à une personne (approuver, lever ou déroger à un blocage, clore par-dessus des points sensibles) ouvre un dialogue qui affiche la commande à taper dans le terminal, avec un bouton de copie. Échap ferme le dialogue.
- Les deux balayages de `npm run e2e:project` ouvrent 35 routes, en RPG sur bureau et en Pro à 375 px : un seul titre principal, chaque champ et chaque bouton nommés, aucun identifiant en double, pas de défilement horizontal.

## Démonstration

- Le premier Tab atteint le lien "Aller au contenu". Entrée place le focus sur le contenu principal. Un changement de page y ramène le focus. Une recherche dans la page garde le focus sur son champ.

- Le premier Tab atteint le lien "Aller au contenu". Entrée place le focus sur le contenu principal. Un changement de page y ramène le focus. Une recherche dans la page garde le focus sur son champ.
- À faible largeur, le menu place le focus sur l'organisation à l'ouverture. Échap le rend au bouton. Les sélecteurs d'organisation, de projet et de style (RPG / Pro) restent dans le menu.
- Les formulaires associent le libellé, l'aide et l'erreur au même champ. Notifications et confirmations utilisent un dialogue natif. Échap ferme le dialogue et rend le focus à l'élément déclencheur.
- La carte a une liste équivalente. Les postes de la Guilde ouvrent les fiches avec Entrée. Les sièges du Conseil deviennent des liens à réception des avis. Ces liens ouvrent et focalisent l'avis choisi.
- Le tableau de quêtes propose une action de déplacement et un raccourci clavier. Les blocages gardent leur motif. Les résultats, leurs dates de validité et les simulations sont signalés par du texte et une icône.

## Raccourcis clavier

La démo et l'interface d'un projet partagent les mêmes raccourcis (`src/shared/shortcuts.ts`). <kbd>Ctrl</kbd> + <kbd>K</kbd> (<kbd>Cmd</kbd> + <kbd>K</kbd> sur Mac) ouvre la recherche. Les raccourcis à une touche, <kbd>/</kbd> pour la recherche, <kbd>g</kbd> puis une lettre pour changer de lieu, <kbd>m</kbd> pour passer de RPG à Pro et <kbd>?</kbd> pour l'aide de la démo, ne jouent ni pendant la saisie ni quand un dialogue est ouvert. Ils se désactivent dans Intendance › Interface (projet) ou dans le dialogue "Raccourcis clavier" de la démo, ouvert par <kbd>?</kbd> ou par le menu d'identité (critère WCAG 2.1.4). Le choix est gardé dans le navigateur, pour les deux interfaces ; <kbd>Ctrl</kbd> + <kbd>K</kbd> reste actif.

Le balayage `tests/e2e/project-sweep.spec.ts` parcourt les 35 routes du projet en RPG et en Pro, sur bureau et à 375 px. Il vérifie qu'un contenu qui défile se rejoint au clavier, que chaque en-tête de tableau a un nom, que les cibles de la carte et des liens de site font au moins 24 px et que le nom d'un lien contient les mots qu'il affiche. Il lance axe-core quand il est installé, ou quand `AXE_CORE_PATH` désigne son `axe.min.js`, et échoue sur une violation sérieuse ou critique.

## Contrastes mesurés

Valeurs calculées à partir des couleurs sRGB de [tokens.css](../src/styles/tokens.css). Les rapports portent sur les paires opaques suivantes. Un texte atteint 4,5:1 et le contour d'un contrôle 3:1 (seuils du WCAG, numéros de critère à vérifier). Le contour d'un champ au repos est la bordure forte, sur le fond du champ (fond profond), sur le panneau et sur le fond de page. `tests/project/contrast.test.ts` recalcule ces rapports depuis les jetons, échoue sous le seuil et compare ce tableau : une valeur qui change ici change aussi dans le tableau.

| Premier plan | Fond | Rapport |
| --- | --- | ---: |
| Texte principal | Panneau | 15,98:1 |
| Texte secondaire | Panneau | 9,88:1 |
| Texte secondaire | Surface haute | 7,17:1 |
| Texte tertiaire | Surface haute | 5,36:1 |
| Texte atténué | Surface haute | 5,47:1 |
| Encre du bouton principal | Menthe | 12,08:1 |
| Lien et contour de focus | Surface haute | 7,79:1 |
| Avertissement | Surface haute | 6,79:1 |
| Erreur | Surface haute | 4,92:1 |
| Texte de simulation | Surface haute | 8,01:1 |
| Bordure forte et contour d'un champ | Fond profond | 4,59:1 |
| Contour d'un champ | Panneau | 3,65:1 |
| Contour d'un champ | Fond de page | 4,07:1 |

Le style Pro utilise la palette claire de [pro.css](../src/styles/pro.css). Mêmes méthode et seuils.

| Premier plan | Fond | Rapport |
| --- | --- | ---: |
| Texte principal | Panneau | 16,31:1 |
| Texte principal | Fond de page | 15,12:1 |
| Texte secondaire | Panneau | 8,51:1 |
| Texte secondaire | Surface haute | 7,17:1 |
| Texte tertiaire | Surface haute | 5,49:1 |
| Texte atténué | Surface haute | 4,53:1 |
| Lien et contour de focus | Panneau | 6,98:1 |
| Lien actif | Teinte de sélection | 8,43:1 |
| Encre du bouton principal | Vert d'action | 6,86:1 |
| Réussite | Teinte de réussite | 6,97:1 |
| Avertissement | Teinte d'avertissement | 6,77:1 |
| Erreur | Teinte d'erreur | 6,27:1 |
| Simulation et IA | Teinte IA | 7,02:1 |
| Bordure forte et contour d'un champ | Fond profond | 3,50:1 |
| Contour d'un champ | Panneau | 3,56:1 |
| Contour d'un champ | Fond de page | 3,30:1 |

Les chiffres des compteurs et des statistiques utilisent Inter. En police pixel, un 5 devenait un S et un 2 ressemblait à un 8.

Le contraste des images et des superpositions varie avec le décor. Les libellés cliquables des scènes s'affichent sur un fond opaque. Leur lisibilité a été revue sur les captures.

## Mouvement et limites

Le mode système suit `prefers-reduced-motion`, dans les deux modes. La préférence "Mouvement réduit" neutralise aussi les boucles, sans retirer les informations de progression. Le son est désactivé à la création d'un espace de démonstration. La revue n'inclut pas de test avec lecteur d'écran ni de mesure de chaque cible tactile.
