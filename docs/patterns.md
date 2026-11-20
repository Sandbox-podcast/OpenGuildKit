# Work and stack patterns

A pattern links a recurring project context or team method to versioned rule packs. A Python API with FastAPI and PostgreSQL can reuse instructions for interface compatibility, data access and migrations. A project manager can select Scrum or Kanban according to how the team delivers work.

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
  "name": "Claims API",
  "sector": "insurance",
  "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16"],
  "roles": ["engineering", "project-management", "security"]
}
```

```text
openguildkit recommend --answers answers.json
openguildkit recommend --answers answers.json --json
openguildkit init --answers answers.json
```

The preview shows the matching technologies, the recommended packs and work methods for the selected roles. The sector narrows patterns that specify a sector list. Technology aliases handle names such as PostgreSQL and Postgres. A compound pattern requires a match for each technology group. Versions in the declared stack stay in the project profile.

The interactive questionnaire defaults to the matching stack patterns. For an answers file, omitting both `packs` and `patterns` applies the same defaults. Set `patterns` to the full list you want if you also choose a work method. Use `[]` to skip patterns. Omit `packs` to keep the baseline and language recommendations or set it to the exact additional packs you want. The required workflow pack and the packs linked from your selected patterns still apply.

The selected pattern IDs go into `.openguildkit/project.json`. During `init` or `sync`, their packs and dependencies are written in `AGENTS.md` and reused for a task consultation. Use `openguildkit recommend` from an initialized project to preview matches against its current stack. Edit the profile and run `sync` to apply a new selection.

## Contribute a pattern

Add `src/openguildkit/registry/patterns/<id>.json`, or place the same format in your project's `.openguildkit/catalog/patterns/` for a local addition.

```json
{
  "id": "insurance-python-api",
  "title": "Python API for insurance",
  "description": "Apply the team's API and data rules to services using FastAPI and PostgreSQL.",
  "roles": ["engineering"],
  "match": {
    "stack": [["Python", "Python3"], ["FastAPI"], ["PostgreSQL", "Postgres"]],
    "sectors": ["insurance"]
  },
  "packs": ["api-design", "fastapi", "postgresql"],
  "sources": [{"title": "FastAPI documentation", "url": "https://fastapi.tiangolo.com/"}]
}
```

Every technology group needs a match. Within a group, one alias is enough. Omit `match` for a method the team chooses, such as a sales qualification framework. Use `exclusive_group` only for patterns that would impose competing choices in the same scope. If multiple automatic matches share that group, the CLI asks the team to choose one.

Link existing packs where they cover the same rules. For new rules, cite the primary source and describe the evidence a reviewer can check. The [catalog format](catalog-format.md) shows how to write a pack.
