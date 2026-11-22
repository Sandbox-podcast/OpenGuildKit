# Vérification de l'application web

La version de départ vient du chantier web local de Claude Code sur `9c48b0f`. Le point de restauration `openguildkit-claude-20261120-223529` contient les sources web d'origine et le registre CLI utilisé par la démo.

## Rejouer les contrôles

Depuis `web/`, avec Node 24 et Chrome installé.

```powershell
npm ci
npm run check
npm run preview -- --port 5208 --strictPort
```

Dans un second terminal, depuis `web/`.

```powershell
$env:PW_PORT = '5208'
npm run e2e
```

| Contrôle | Couverture | Résultat du 22 novembre 2026 |
| --- | --- | --- |
| `npm run check` | TypeScript, tests Vitest (domaine de la démo, mode réel, scripts) et build Vite | Tous réussis, build réussie. Chaque lieu est un fichier chargé à la demande ; aucun bloc ne dépasse 500 kB (le plus gros, le domaine de la démo, fait 316 kB). |
| `npm run e2e` | Scénarios Chrome, dont les étapes d'Atelier Nova et le basculement RPG / Pro | Tous réussis. La série de captures est ignorée sauf avec `CAPTURES=1`. |
| `npm run e2e:project` | Un parcours du mode réel par action de l'interface, et deux balayages de toutes les routes (bureau RPG, mobile Pro, avec axe-core), sur des projets d'exemple neufs servis par `openguildkit ui` | Tous réussis. Demande `npm run build` avant. |
| `python -m unittest tests.test_webui` (racine) | Serveur local : hôte, origine, jeton, décisions réservées au terminal, chemins, envois, requêtes mal formées, concurrence, cache du catalogue, réponses allégées et compressées, profil, fichiers servis | Tous réussis |
| `npm run measure:project -- URL` | Temps d'affichage, requêtes et volumes de chaque lieu du mode réel | Voir [Performances](interface-projet.md#performances) |

Le mode réel charge 5 kB d'amorce, React (219 kB), le cadre du projet (28 kB) et le lieu ouvert (10 à 30 kB). Il ne charge jamais le domaine ni les données de la démonstration. [Interface d'un projet réel](interface-projet.md)

Le parcours principal part d'un fait de profil inconnu et passe par les avis simulés, la décision humaine, la quête, les livrables, l'échec du contrôle, sa correction, la clôture puis le réexamen. Les scénarios ciblés couvrent le lecteur, l'agent IA, la preuve attachée à une version remplacée, les URL hors organisation, le glisser-déposer et son équivalent clavier, le rechargement immédiat, l'import invalide et le mouvement réduit. [Parcours principal](../tests/e2e/journey.spec.ts) · [Tests de vues](../tests/e2e/views.spec.ts)

Le style Pro est couvert par les scénarios de navigation, de brouillon et de mobile : le basculement garde la route, les filtres, le brouillon d'un livrable et le rechargement. Le test de la Bibliothèque lisait les sources avant l'affichage de la fiche et échouait une fois sur quatre. Il attend maintenant la fiche.

Les deux échecs Playwright de la reprise étaient reproductibles. Le glisser-déposer simulé visait une colonne masquée par le défilement horizontal. Le test expose maintenant la source et la cible avant de glisser, puis vérifie le refus et la cause. Le test de rechargement sélectionnait une option cachée du sélecteur de projets. Il vérifie le titre de la quête, et couvre aussi la perte réelle du dernier changement avant la sauvegarde différée de 250 ms.

## Comparaisons visuelles

Chrome 157 sous Windows 11, langue `fr-FR`, fuseau Europe/Paris. Chaque série utilise un contexte vierge, le scénario Atelier Nova au 20 novembre 2026 à 14 h, les mêmes routes, le guide masqué et le mouvement réduit. Chaque série compte dix captures à 1440 × 900 et cinq à 390 × 844.

Les séries RPG (`captures-apres/`) et Pro (`captures-pro/`) sont régénérées par `CAPTURES=1 npm run e2e -- captures` après chaque changement visible de la démonstration. Les séries antérieures ont été retirées du dépôt : l'historique Git les garde.

| Écran | RPG | Pro |
| --- | --- | --- |
| Entrée sur mobile | [PNG](captures-apres/01-entree-mobile.png) | [PNG](captures-pro/01-entree-mobile.png) |
| Royaume et reprise | [PNG](captures-apres/02-royaume.png) | [PNG](captures-pro/02-royaume.png) |
| Conseil préparé | [PNG](captures-apres/03-conseil.png) | [PNG](captures-pro/03-conseil.png) |
| Bibliothèque filtrée | [PNG](captures-apres/04-bibliotheque.png) | [PNG](captures-pro/04-bibliotheque.png) |
| Quête bloquée | [PNG](captures-apres/05-quete-bloquee.png) | [PNG](captures-pro/05-quete-bloquee.png) |
| Livrable dans la Forge | [PNG](captures-apres/06-forge.png) | [PNG](captures-pro/06-forge.png) |
| Preuve à réévaluer sur mobile | [PNG](captures-apres/07-preuve-a-reevaluer-mobile.png) | [PNG](captures-pro/07-preuve-a-reevaluer-mobile.png) |
| Chroniques | [PNG](captures-apres/08-chroniques.png) | [PNG](captures-pro/08-chroniques.png) |

Sur le viewport de 390 px, le document mesurait 1 046 px à l'entrée, 640 px dans les contrôles et 595 px dans les preuves. Ces trois vues tiennent sur 390 px après correction. La fiche issue du lien direct `preuve=prv-ds1` affiche le motif de réévaluation dès le premier écran. L'inventaire reste accessible sous la fiche en largeur mobile.

La relecture des deux styles a fait corriger les chiffres en police pixel. Un 5 se lisait S ou 8 et un 2 ressemblait à un 8 dans les compteurs du Royaume, de la navigation et du parcours. Ils utilisent désormais Inter.

## Mesures locales

Intel Core i7-13700KF, Windows 11, Chrome 157 headless, viewport 1440 × 900, `vite preview` de la dernière build. Cinq passages, chacun dans un nouveau navigateur, sans limitation du débit ni du CPU. La build d'origine n'est plus disponible : cette passe ne compare pas avant et après.

```powershell
npm run build
npm run preview -- --port 5209 --strictPort
node scripts/measure.mjs http://localhost:5209 5
```

| Mesure | Médiane (min – max) |
| --- | --- |
| Interface utilisable (bouton Atelier Nova visible) | 224 ms (218 – 230 ms) |
| Octets transférés jusqu'à l'entrée | 821 Ko |
| Carte du Royaume affichée après chargement du scénario | 21 ms (14 – 33 ms) |
| Ouverture de la Bibliothèque | 30 ms (28 – 32 ms) |
| Filtre « SemVer » dans les 395 références | 28 ms (22 – 42 ms) |
| Octets transférés en tout | 900 Ko |
| Mémoire JS après nettoyage | 5,7 Mo |
| Intervalle entre images, 95e centile, carte au repos | 20,6 ms (20,5 – 20,7 ms) |

Le chargement commence sur l'entrée. La carte est relevée deux images après l'affichage de son panneau et la transition de la Bibliothèque s'arrête quand son champ de recherche est visible. Le filtre prend fin à la première image après l'apparition du résultat. Les octets viennent de `PerformanceResourceTiming` ; les décors d'en-tête et les personnages ne se chargent que sur les écrans qui les affichent. L'intervalle entre images mesure la cadence de Chrome headless sur une page au repos, pas le coût du rendu de la carte.

## Périmètre

Les essais portent sur la démonstration locale et ses rôles. Les avis, exécutions, résultats de contrôles et partages qui traverseraient un service externe utilisent les adaptateurs de simulation. Le journal et les restrictions d'organisation sont vérifiés dans cette maquette navigateur. [Contrats des adaptateurs](adaptateurs.md) · [Couverture par espace](matrice-perimetre.md)
