# Work and stack patterns

A pattern links a recurring project context or team method to versioned rule packs. A Python API with FastAPI and PostgreSQL can reuse instructions for interface compatibility, data access and migrations. A project manager can select Scrum, Kanban or both, as a team that runs Scrumban does.

## Browse and preview

```text
openguildkit patterns --role project-management
openguildkit patterns --role marketing
openguildkit patterns --role hr
openguildkit patterns --id python-fastapi-postgresql
openguildkit references --family work-patterns "SEO"
```

To preview a project, save this example as `answers.json`.

```json
{
  "name": "Support API",
  "sector": "general",
  "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16"],
  "roles": ["engineering", "project-management", "security"]
}
```

```text
openguildkit recommend --answers answers.json
openguildkit recommend --answers answers.json --json
openguildkit init --answers answers.json
```

The preview lists the preselected patterns with the reason of each one, then the patterns to consider and the recommended packs. A pattern is preselected for one of these reasons:

- `stack Python, FastAPI, PostgreSQL`: its technologies match the stack (in its sectors, when it lists some).
- `sector financial-services`: the project's sector is in its `match.sectors`. `dora-financial-entity` is preselected for financial services and insurance whatever the roles, `nis2-essential-entity` for critical infrastructure, and each other sector preselects its own regulation pattern (`openguildkit catalog` shows which).
- `personal data`: the project answered yes to the personal data question, which preselects `gdpr-personal-data`.
- `role security`: a work method linked to a selected role. Two methods whose packs conflict stay under the patterns to consider until the team picks one. Scrum and Kanban do not conflict: a team can keep both.

A regulation pattern (`"kind": "regulation"`) is never preselected because of a role: it appears under the patterns to consider for its roles, so a legal role still sees GDPR, DORA, NIS 2, the AI Act and the Cyber Resilience Act without any of them being imposed.

Preselected is not imposed. The person keeps or removes each pattern. A regulation pattern the person removes during the interactive `init` is recorded in the profile under `declined`, and `recommend` lists it as declined instead of proposing it again. Add an ID to `declined` by hand to the same effect, or remove it from there to see the proposal again:

```json
"declined": ["dora-financial-entity"]
```

Technology aliases handle names such as PostgreSQL and Postgres. A framework stands for its platform: Next.js activates the React rules without React in the stack, ASP.NET Core does not need .NET listed, and Spring Boot matches Java and Kotlin services. The same holds for Django, Rails, Express, Vue (or Nuxt), Angular and Laravel. An iOS app is recognised by iOS, SwiftUI or UIKit, not by Swift alone, and an Android app by Android, so a server written in Swift or Kotlin gets no app store rules. Mobile patterns add the `mobile-accessibility` and `mobile-store-release` packs to the platform pack. GitLab CI, Docker and AWS each select their own pattern (`gitlab-ci-security`, `docker-images`, `aws-iam`). A compound pattern requires a match for each technology group. Versions in the declared stack stay in the project profile.

## Components and versions

`openguildkit detect` proposes components from local manifests and includes the file behind each technology. It reads package and build files, Docker and Compose images, Terraform, Helm and Kustomize files, Kubernetes YAML documents, `dbt_project.yml`, Vite config files and WordPress project markers. Gradle modules declared in `settings.gradle` or `settings.gradle.kts` share their build's component. Android SDK levels and Android Gradle Plugin versions have separate labels.

The output keeps declared constraints such as `Express >=4.0.0 <5`. Pattern matching uses the lowest bound stated by the range when it checks a minimum version. A database inferred from a driver has no version. An image such as `postgres:16` supplies the server version. Detection reads local files and runs offline.

```text
openguildkit detect
openguildkit detect --json
```

`init --questions` defaults to the root `package.json` name, or the folder name if the package has none. It also shows the detected components. A single root component remains the default when the answers leave `components` out and give an empty `stack`. An explicit `components` answer or a populated manual stack takes precedence.

Use `e` in the interactive questionnaire to correct a component's stack and versions. For JSON answers, edit the component's path and stack before saving the file.

```json
{
  "name": "Support portal",
  "components": [
    {"id": "web", "path": "apps/web", "stack": ["Next.js 14.2", "React 18.3", "TypeScript"]},
    {"id": "api", "path": "services/api", "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16"]}
  ]
}
```

With components, every technology group of a pattern must match inside the same component. A FastAPI service and a separate PostgreSQL job do not activate the FastAPI and PostgreSQL pattern. The profile records where each pattern applies, for example `{"id": "nextjs-react", "components": ["web"]}`, and `AGENTS.md` lists the components and the scope of each pack. The project `stack` becomes the list of all component technologies.

A pattern can set a minimum version. The Next.js pattern needs Next.js 13.4 or later because its rules concern the App Router: a project on Next.js 10 gets the React rules only, and the preview says why. When the stack gives no version, the pattern still matches and the preview asks you to confirm the version.

After you change the stack, the components or a version, `openguildkit sync` and `openguildkit recommend` list the selected patterns that no longer match, with the reason. Profiles written before components existed keep working unchanged.

The interactive questionnaire asks each norm that the sector or personal data implies on its own, with the reason it is proposed, then prints the other preselected patterns and why and uses them as the default answer. For an answers file, every omitted question takes the default `init --questions` shows: omitting `patterns` applies the same preselection, whether or not `packs` is given; `"personal_data": true` (or `"yes"`) answers the personal data question, and `"norms": {"dora-financial-entity": "no"}` declines a norm. Set `patterns` to the full list you want if you also choose a work method. Use `[]` to select none. `packs` lists packs added to the recommended baseline and language packs; add `"replace_default_packs": true` when the list must replace them instead. The required workflow pack and the packs linked from your selected patterns still apply. A saved `.openguildkit/project.json` is read as written: its `packs` are never completed with recommendations.

The selected pattern IDs go into `.openguildkit/project.json`. During `init` or `sync`, their packs and dependencies are written in `AGENTS.md` and reused for a task consultation. Use `openguildkit recommend` from an initialized project to preview matches against its current stack, sector and roles. Edit the profile and run `sync` to apply a new selection. Preselection only happens in `init` and `recommend`: `sync` and an upgrade never add a pattern to a saved profile, so a project created before sectors preselected anything keeps its packs until the team edits the profile.

## Review the rules before applying them

`openguildkit preview --answers answers.json` shows what `init` would write, before anything changes in the repository: each pack with its version, why it is active (required, selected, from a pattern, or a dependency of another pack; a pattern without a stack says what brought it, such as `pattern threat-modeling (role security)` or `pattern dora-financial-entity (sector financial-services)`) and the components it applies to, then the team conventions and checks. On an initialized project, `openguildkit preview` reads the saved profile. Add `--json` for the agent. The interactive `init` shows the same preview and asks for confirmation.

A pack can declare that it conflicts with another when their rules cannot both apply to the same scope, for example a project pack that freezes the work of a sprint next to `kanban-delivery`, which lets new items start whenever work in progress allows. When both apply to a common scope, whether they come from a pattern or from a direct selection, the preview lists the conflict and `init`, `sync` and `check` stop until the team records its choice in the profile:

```json
"resolutions": [
  {"packs": ["fixed-sprint-scope", "kanban-delivery"], "keep": ["kanban-delivery"], "reason": "Support work arrives continuously."}
]
```

`keep` can name one pack or both. `AGENTS.md` lists the decision and its reason under "Rule decisions", leaves out the pack that was not kept, and the consultation and handoff carry the same choice. Packs that apply to different components do not conflict. A recorded choice stays in force when a catalog update stops declaring the conflict: a team that kept `kanban-delivery` instead of `scrum-delivery` before the two packs became compatible keeps that choice until it removes the resolution.

## Contribute a pattern

Add `src/openguildkit/registry/patterns/<id>.json`, or place the same format in your project's `.openguildkit/catalog/patterns/` for a local addition.

```json
{
  "id": "team-python-api",
  "title": "Team Python API",
  "description": "Apply the team's API and data rules to services using FastAPI and PostgreSQL.",
  "roles": ["engineering"],
  "match": {
    "stack": [["Python", "Python3"], ["FastAPI"], ["PostgreSQL", "Postgres"]],
    "sectors": ["general"]
  },
  "packs": ["api-design", "fastapi", "postgresql"],
  "sources": [{"title": "FastAPI documentation", "url": "https://fastapi.tiangolo.com/"}]
}
```

Every technology group needs a match. Within a group, one alias is enough. Add `"min_versions": {"next.js": "13.4"}` to `match` when the rules only hold from a given version; the key must be one of the aliases. Omit `match` for a method the team chooses, such as a sales qualification framework: it is preselected for its roles.

A pattern can match on its sector alone, or on personal data, without a stack. Mark it `"kind": "regulation"` so that its roles only see it as a suggestion:

```json
{
  "id": "retail-banking-dora",
  "title": "DORA for the bank",
  "description": "Preselected for retail banking: keep it when the bank is a financial entity under DORA.",
  "roles": ["legal", "security"],
  "packs": ["dora"],
  "kind": "regulation",
  "match": {"sectors": ["retail-banking"]},
  "sources": [{"title": "Regulation (EU) 2022/2554, Digital Operational Resilience Act", "url": "https://eur-lex.europa.eu/eli/reg/2022/2554/oj/eng"}]
}
```

`match` takes `stack`, `sectors` and `"personal_data": true`, and needs at least one of them. With a stack, `sectors` limits the pattern to those sectors; without one, it preselects the pattern there. The sector can come from the project's own catalog (see [Sectors](catalog-format.md#sectors)). Use `exclusive_group` only for patterns that would impose competing choices in the same scope. If multiple automatic matches share that group, the CLI asks the team to choose one.

Link existing packs where they cover the same rules. Keep one method per pack, so that a pattern activates only the rules of its method: the A/B testing pattern uses `controlled-experiments`, not the UTM rules of `campaign-measurement`. For new rules, cite the primary source and describe the evidence a reviewer can check. Add `"references": [...]` with the IDs of the [reference entries](references.md) behind the packs the pattern activates; a reference that presents the pattern names it back in its `pattern` field. The [catalog format](catalog-format.md) shows how to write a pack.
