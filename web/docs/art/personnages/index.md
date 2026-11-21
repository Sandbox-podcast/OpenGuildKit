# Personnages d'Open Guild Kit

Les quatorze expertises et les six humains d'Atelier Nova ont chacun une silhouette et un visage propres. Un même dessin sert au sprite de la salle, au portrait de la fiche et au petit avatar dans les menus.

Les cinq planches PNG en alpha sont les sources produites avec ImageGen. Le script recadre chaque personnage, fixe l'ancrage des pieds et ramène les fichiers de diffusion à 32 couleurs dérivées du graphite `#020508`, de la menthe `#6EF7C4` et du blanc `#FDFDFD` échantillonnés sur le logo. [Casters et recadrages](../../../scripts/export-characters.py) · [Instructions ImageGen](prompts.md) · [Planche à l'échelle](planche.png)

| Format | Dimensions natives | Usage |
| --- | --- | --- |
| `*-figure.webp` | 80 × 112 | Personnage en pied, centré, pieds alignés à 3 px du bord. |
| `*-portrait.webp` | 96 × 96 | Visage et accessoire quand l'interface offre plus de 32 px. |
| `*-avatar.webp` | 40 × 40 | Cadrage serré du visage pour les usages jusqu'à 32 px. |
| [Grille dérivée](../../../src/shared/pixel/character-miniatures.json) | 16 × 24 | Figurine des décors compacts, ancrage au centre du bord inférieur. |

| Identifiant | Personnage | Repère | Source |
| --- | --- | --- | --- |
| `product` | Stratège | Diadème, demi-cape et registre scellé | [Atelier](01-atelier.png) |
| `engineering` | Bâtisseur | Casque clair, tablier et maillet | [Atelier](01-atelier.png) |
| `architecture` | Cartographe | Tricorne, carte dépliée et boussole | [Atelier](01-atelier.png) |
| `documentation` | Scribe | Tresse, lunettes rondes, livre et plume | [Atelier](01-atelier.png) |
| `design` | Artisan | Béret oblique, pinceau et palette | [Revue](02-revue.png) |
| `security` | Gardien | Casque à crête et bouclier au cadenas | [Revue](02-revue.png) |
| `privacy` | Magistrat | Perruque, robe à rabat, registre et sceau | [Revue](02-revue.png) |
| `quality` | Inspecteur | Casquette à deux visières, col fermé et loupe | [Revue](02-revue.png) |
| `performance` | Alchimiste | Chapeau haut, barbe pointue et sablier | [Systèmes](03-systemes.png) |
| `data` | Savant | Coiffe carrée, lunettes et grille de données | [Systèmes](03-systemes.png) |
| `platform` | Maître des forges | Lunettes de protection sur le front, tablier et pinces | [Systèmes](03-systemes.png) |
| `market` | Éclaireur | Capuche et longue-vue | [Systèmes](03-systemes.png) |
| `marketing` | Barde | Chapeau à plume, cape et instrument à cordes | [Alliance](04-alliance.png) |
| `commerce` | Négociant | Turban, écharpe tissée et registre ouvert | [Alliance](04-alliance.png) |
| `human-1` | Camille Roche | Veste longue, col roulé et carnet | [Alliance](04-alliance.png) |
| `human-2` | Yanis Belkacem | Blouson de travail, plan et crayon | [Alliance](04-alliance.png) |
| `human-3` | Inès Morel | Chignon, lunettes angulaires et porte-documents | [Intendance](05-intendance.png) |
| `human-4` | Théo Garnier | Casque audio, sweat et ordinateur | [Intendance](05-intendance.png) |
| `human-5` | Léa Fontaine | Écharpe claire, gilet long et fiches de suivi | [Intendance](05-intendance.png) |
| `human-6` | Hugo Martin | Cheveux blancs, lunettes rectangulaires et carnet à spirale | [Intendance](05-intendance.png) |

Le script d'export s'exécute depuis la racine avec Python et Pillow.

```text
python web/scripts/export-characters.py
```

Le navigateur charge les WebP locaux selon le format demandé. Les 60 fichiers occupent 127 792 octets au total. [Fichiers de diffusion](../../../public/assets/characters/)

