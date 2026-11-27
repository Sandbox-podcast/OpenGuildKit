# Direction artistique et assets

Open Guild Kit se déroule dans une ville de montagne de nuit. La carte montre les ateliers, le cours d'eau et les projets qui occupent les terrasses. Dans la Guilde et au Conseil, les lampes menthe éclairent les postes de travail et la table d'arbitrage. Toute la palette vient du logo : graphite `#020508`, blanc `#FDFDFD` et menthe `#6EF7C4`, échantillonnés sur `assets/brand/logo.png`. Les bâtiments, personnages et signes appartiennent à l'univers d'Open Guild Kit.

L'interface a deux styles, choisis par l'interrupteur RPG / Pro de la barre du haut. RPG montre les scènes illustrées. Pro garde les mêmes composants, données, filtres et brouillons sur des surfaces claires et neutres, sans scène.

## Règles de composition

- Le logo du dépôt donne les contours en escalier, le graphite, le blanc et la menthe. Les fonds de travail sont mats. La menthe identifie une action ou une sélection. L'ambre et le corail signalent les exceptions et les blocages.
- La carte se lit de dessus en trois quarts. Les chemins et les ponts relient les entrées. Un bâtiment a une silhouette, une étiquette HTML et un lien. Les maisons prennent la couleur du produit. Les terrains s'ajoutent par lignes de quatre.
- Les salles ont un plan frontal surélevé. Le paysage reste en arrière-plan. Les points les plus lumineux sont les fenêtres, les papiers et les lampes. Les personnages et les libellés sont intégrés au-dessus des images. À faible largeur, les postes et les sièges passent en grille sous le décor.
- Pixelify Sans est réservé aux titres d'espaces et aux éléments courts. Inter sert aux formulaires, listes, tableaux, messages et à tous les chiffres : en police pixel, un 5 se lit comme un S ou un 8 à petite taille. Pro remplace Pixelify Sans par Inter. Les cadres à angles coupés partagent un trait de 2 px. Les composants utilisent des espacements de 8 à 16 px et un contour de focus indépendant de la couleur d'état.
- Le style Pro conserve les composants de travail et retire les scènes en grand format. Les effets de fumée et de lumière accompagnent une exécution ou des avis en cours. Les scènes restent statiques au repos.

[Tokens CSS](../src/styles/tokens.css) · [Cadres et états](../src/styles/components.css) · [Navigation et en-têtes](../src/styles/shell.css) · [Carte et Conseil](../src/styles/spaces.css)

## Manifeste

| Identifiant | Usage et ancrage | Grille native ou dimensions | Source et fichier servi |
| --- | --- | --- | --- |
| `brand/logo` | Logo de l'écran d'installation et de l'entrée de la démo, aligné à gauche | PNG 2 172 × 724, WebP 543 × 181 au quart exact, transparence conservée | [Origine dépôt](../../assets/brand/logo.png), le [WebP sans perte](../public/assets/brand/logo.webp) est servi à ces écrans |
| `brand/logo-header` | Logo de l'en-tête, affiché à 108 × 36 pixels CSS, aligné à gauche | WebP sans perte 216 × 72 (11 Ko, contre 46 Ko pour le grand), transparence conservée | [WebP](../public/assets/brand/logo-header.webp), tiré du PNG d'origine : `magick assets/brand/logo.png -filter Lanczos -resize 216x72 png:- \| cwebp -lossless -z 9 -o web/public/assets/brand/logo-header.webp -- -` |
| `brand/favicon` | Icône d'onglet | PNG du chantier initial | [favicon.png](../public/assets/brand/favicon.png) |
| `world/guildhall` | Panorama de l'entrée, bâtiment à droite, recadrage mobile centré sur le bâtiment | PNG 1 536 × 1 024, WebP 1 536 × 1 024 et 558 × 512 | [Source](art/guildhall.png), [bureau](../public/assets/world/guildhall.webp), [mobile](../public/assets/world/guildhall-mobile.webp) |
| `world/atelier-guilde` | Quatre postes, liens ancrés devant les bureaux à 16, 40, 63 et 86 % | PNG 1 900 × 828, WebP 1 440 × 628 et 720 × 314 | [Source](art/atelier-guilde.png), [bureau](../public/assets/world/atelier-guilde.webp), [mobile](../public/assets/world/atelier-guilde-mobile.webp) |
| `world/salle-conseil` | Table et fenêtre en arrière-plan des sièges, portraits répartis le long de la table | PNG 1 939 × 811, WebP 1 440 × 602 et 720 × 301 | [Source](art/salle-conseil.png), [bureau](../public/assets/world/salle-conseil.webp), [mobile](../public/assets/world/salle-conseil-mobile.webp) |
| `night-town` | Sol, rivière, végétation, voirie et terrasses. Origine en haut à gauche. Bâtiments placés selon `PLACE_POS` | 560 × 349 pour une ligne de produits, +59 px par ligne | [terrain.ts](../src/shared/pixel/terrain.ts) |
| `building:<lieu>` | Un bâtiment par espace, contour transparent et porte reliée au chemin | De 46 × 98 à 82 × 74, dimensions détaillées ci-dessous | [buildings.ts](../src/shared/pixel/buildings.ts) |
| `cottage:<couleur>:<archivé>` | Maison de projet, au pied de la terrasse, toiture de la couleur du produit, toiture éteinte si archivé | 22 × 20, fond transparent | [buildings.ts](../src/shared/pixel/buildings.ts) |
| `rooms/<lieu>` | Douze décors d'en-tête RPG, sujet à droite après le fondu | WebP 768 × 192 en qualité 82 (19 à 29 Ko, 292 Ko les douze), recadrés en 4:1 depuis trois planches | [Manifeste](art/rooms/README.md), [fichiers servis](../public/assets/rooms) |
| `characters/<expertise ou humain>` | 14 expertises et 6 humains : personnage en pied, portrait et avatar, 32 couleurs dérivées du logo | WebP 80 × 112, 96 × 96 et 40 × 40 (60 fichiers, 128 Ko), fond transparent | [Manifeste](art/personnages/index.md), [fichiers servis](../public/assets/characters), [export](../scripts/export-characters.py) |
| Icônes et marqueurs | Navigation, contrôle, état et guide. Icône centrée dans son bouton ou son badge | SVG sur grille 9 × 9, ancrage au centre, couleur courante | [icons.tsx](../src/shared/pixel/icons.tsx) |

Les trois panoramas, les douze décors d'en-tête et les personnages sont des images originales générées avec ImageGen intégré pendant le chantier de l'interface, puis déclinées en WebP ; elles sont entrées dans le dépôt le 21 novembre 2026 (#199). Les PNG d'origine et les instructions de génération restent dans `web/docs/art` (22 Mo), parce que ce sont les sources des fichiers servis : il faut les reprendre pour recadrer ou redessiner un décor, et les retirer de l'arbre n'allégerait pas un clone, puisque l'historique Git les garde. Aucune image tierce n'est reprise. Les conditions d'usage d'ImageGen n'ont pas eu de lecture juridique : le dépôt ne dit pas si elles permettent de publier ces images sous la licence MIT, et cette lecture reste à faire hors du dépôt.

La carte, les bâtiments, les maisons et les icônes sont dessinés par le code du dépôt. Leur rastérisation utilise un canevas par asset et un cache de PNG. Les transitions de carte sont pilotées par le CSS. La fumée dure 1,4 s en quatre pas, la lueur 2,4 s en trois pas. Elles bouclent pendant le travail concerné. Le repos conserve la scène et les états textuels. [Prompts de génération](art/prompts.md)

| Bâtiment | Pixels | Bâtiment | Pixels |
| --- | --- | --- | --- |
| Royaume | 78 × 72 | Blueprint | 64 × 62 |
| Guilde | 82 × 66 | Conseil | 82 × 74 |
| Quêtes | 74 × 62 | Bibliothèque | 66 × 80 |
| Forge | 74 × 64 | Tour de guet | 46 × 98 |
| Observatoire | 70 × 74 | Documentation | 62 × 60 |
| Chroniques | 54 × 82 | Intendance | 76 × 58 |

Pixelify Sans et Inter sont distribuées par Fontsource sous licence OFL. L'interface ne sert que leurs fichiers WOFF2 latins ([fonts.css](../src/styles/fonts.css)) : 149 Ko au lieu de 316 Ko ; un caractère cyrillique, grec ou vietnamien s'affiche avec la police du système. La licence du code est celle du dépôt. [Pixelify Sans OFL](../node_modules/@fontsource/pixelify-sans/LICENSE) · [Inter OFL](../node_modules/@fontsource-variable/inter/LICENSE) · [MIT](../../LICENSE)

## Références étudiées

| Source | Observation | Application |
| --- | --- | --- |
| [Eastward, Pixpil et Chucklefish](https://eastwardgame.com/media/) | Les rues à étages se lisent grâce aux contours foncés et aux éclairages placés sur quelques objets. | Séparer les plans et concentrer la lumière sur les portes, fenêtres et ateliers. |
| [Stardew Valley, ConcernedApe](https://www.stardewvalley.net/media/) | Des chemins clairs cernent des parcelles distinctes. | Réserver une terrasse par produit avec sa couleur et un accès identifiable. |
| [Sea of Stars, Sabotage Studio](https://sabotagestudio.com/presskits/sea-of-stars/#screenshots) | Dans le port, l'eau et les massifs sombres découpent chemins et bâtiments. | Contraster les chemins et la rivière avec les bordures végétales. |
| [CrossCode, Radical Fish Games](https://www.radicalfishgames.com/crosscode/en/home) | Les plans urbains se découpent contre le paysage et les commandes reposent sur un fond uni. | Garder des panneaux calmes sous des scènes détaillées. |

Les jeux et la maquette de Lou ont servi de références de composition. Les fichiers servis proviennent des sources locales recensées ci-dessus.
