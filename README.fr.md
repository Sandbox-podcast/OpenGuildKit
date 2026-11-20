<p align="center">
  <img src="assets/brand/logo.png" alt="Open Guild Kit" width="460">
</p>

<p align="center"><a href="README.md">English version</a></p>

OpenGuildKit est un framework open source pour les équipes qui développent avec des agents IA. Tu choisis les règles que tes agents doivent suivre et tu consultes les métiers concernés avant de valider un changement.

https://github.com/user-attachments/assets/8a6ec7e6-e7c3-4f95-bd21-6dcd1d960d8f

## Essayer la démo

Utilise Python 3.11 ou une version plus récente.

```bash
git clone https://github.com/Sandbox-podcast/OpenGuildKit.git
cd OpenGuildKit
python -m pip install -e .
python examples/request-status/replay.py
```

La [démo](examples/request-status/) crée un projet temporaire et utilise des avis préparés sur le suivi des demandes support. Lance-la dans un terminal pour comparer les avis, valider le périmètre et lire le brief d'implémentation.

## Configurer ton projet

Depuis ton dépôt, indique ta stack, ton secteur et les métiers concernés. Le questionnaire repère les combinaisons techniques connues et te laisse choisir les méthodes que ton équipe applique. Dans un dépôt existant, `openguildkit detect` propose d'abord tes composants et leurs versions, et chaque pattern s'applique au composant qui utilise ses technologies.

```bash
openguildkit detect
openguildkit init
openguildkit preview
openguildkit check
```

`init` enregistre ton profil dans `.openguildkit/project.json` et écrit les règles dans un bloc géré de `AGENTS.md`. Il ajoute un import dans `CLAUDE.md` pour Claude Code. Les règles en vigueur sont figées dans `.openguildkit/catalog.lock.json` : après une mise à jour d'OpenGuildKit, `openguildkit update` montre ce qui changerait et `openguildkit update --apply` l'adopte. [Installe le skill](integrations/) pour répondre au questionnaire dans Claude Code ou Codex et lancer des tâches depuis la conversation.

```mermaid
flowchart TB
    S["Configurer le projet"] --> R["Profil et règles dans AGENTS.md"]
    R --> B["Cadrer une tâche avec l'agent"]
    B --> V["Consulter les boards concernés"]
    V --> D{"Tu décides"}
    D -- demander des modifications --> B
    D -- valider --> H["Brief d'implémentation avec périmètre et contrôles"]
```

Avec `"guard": "enforce"` dans le profil, le board n'est plus facultatif : les hooks de l'agent le rappellent à chaque demande, refusent toute modification de fichier tant qu'aucune tâche n'est approuvée, et un contrôle CI exige la décision approuvée dans chaque PR. [Board automatique](integrations/README.md#the-board-before-every-change)

La CLI choisit les boards et enregistre leurs avis en local. Ton agent rédige ces avis et utilise ses outils pour les recherches que tu autorises. Tu valides le périmètre dans ton terminal avant que la CLI affiche le brief d'implémentation.

Chaque brain traite la demande sous plusieurs angles. Il confronte la proposition à une alternative et te montre les preuves, les objections et les tests qui permettraient de décider. [Brains métier](docs/brains.md)

## Parcourir le catalogue

```bash
openguildkit catalog
openguildkit references
openguildkit patterns --role project-management
openguildkit patterns --role hr
openguildkit patterns --id python-fastapi-postgresql
openguildkit brains --id product
```

`catalog` liste les packs, les boards et les secteurs. L'index donne accès aux sources et aux méthodes. Chaque pattern indique quand il s'applique et quels packs alimentent `AGENTS.md`. [Références](docs/references.md) · [Choix des patterns](docs/patterns.md)

## Documentation

- [Installer les paquets d’une release GitHub](docs/install.md)

- [Vérifier une règle de catalogue en CI](examples/export-expiry/README.md)
- [Coordonner les vérifications de PR avec GitHub Actions et Jenkins](integrations/ci/README.md)

- [Architecture](docs/architecture.md) et [parcours d'une tâche](docs/workflow.md)
- [Dossiers marché et veille concurrentielle](docs/market.md)
- [Documentation du projet et partage avec Documentalist](docs/documentation.md)
- [Tests de bout en bout avec ChaosFolk, en option](integrations/chaosfolk/)
- [Contribuer](CONTRIBUTING.md) et [format du catalogue](docs/catalog-format.md)
- [Feuille de route](docs/roadmap.md) et [licence MIT](LICENSE)
