# Accessibilité de la démo web

Les contrôles couvrent Chrome sous Windows, le clavier, le mouvement réduit et les écrans étroits. Les parcours et limites de la vérification sont consignés dans [Vérifications](verification.md).

## Clavier et lecture

- Le premier Tab atteint le lien "Aller au contenu". Entrée place le focus sur le contenu principal. Un changement de page y ramène le focus. Une recherche dans la page garde le focus sur son champ.
- À faible largeur, le menu place le focus sur l'organisation à l'ouverture. Échap le rend au bouton. Les sélecteurs d'organisation, de projet et de style (RPG / Pro) restent dans le menu.
- Les formulaires associent le libellé, l'aide et l'erreur au même champ. Notifications et confirmations utilisent un dialogue natif. Échap ferme le dialogue et rend le focus à l'élément déclencheur.
- La carte a une liste équivalente. Les postes de la Guilde ouvrent les fiches avec Entrée. Les sièges du Conseil deviennent des liens à réception des avis. Ces liens ouvrent et focalisent l'avis choisi.
- Le tableau de quêtes propose une action de déplacement et un raccourci clavier. Les blocages gardent leur motif. Les résultats, leurs dates de validité et les simulations sont signalés par du texte et une icône.

## Contrastes mesurés

Valeurs calculées à partir des couleurs sRGB de [tokens.css](../src/styles/tokens.css). Les rapports portent sur les paires opaques suivantes.

| Premier plan | Fond | Rapport |
| --- | --- | ---: |
| Texte principal | Panneau | 14,36:1 |
| Texte secondaire | Panneau | 9,88:1 |
| Texte secondaire | Surface haute | 7,17:1 |
| Texte tertiaire | Surface haute | 5,36:1 |
| Texte atténué | Surface haute | 5,47:1 |
| Encre du bouton principal | Menthe | 11,48:1 |
| Lien et contour de focus | Surface haute | 7,79:1 |
| Avertissement | Surface haute | 6,79:1 |
| Erreur | Surface haute | 4,92:1 |
| Texte de simulation | Surface haute | 5,71:1 |
| Bordure forte | Fond profond | 4,24:1 |

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
| Bordure forte | Fond profond | 3,50:1 |

Les chiffres des compteurs et des statistiques utilisent Inter. En police pixel, un 5 devenait un S et un 2 ressemblait à un 8.

Le contraste des images et des superpositions varie avec le décor. Les libellés cliquables des scènes s'affichent sur un fond opaque. Leur lisibilité a été revue sur les captures.

## Mouvement et limites

Le mode système suit `prefers-reduced-motion`. La préférence "Mouvement réduit" neutralise aussi les boucles, sans retirer les informations de progression. Le son est désactivé à la création d'un espace. La revue n'inclut pas de test avec lecteur d'écran ni de mesure de chaque cible tactile.
