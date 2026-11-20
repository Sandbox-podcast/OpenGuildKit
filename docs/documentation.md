# Project documentation and sharing

Completed tasks already hold what a reader needs: the brief, the expected behaviour, the acceptance criteria that were met, the delivery and the project version. `openguildkit docs export` turns the tasks you select into Markdown pages that [Documentalist](https://github.com/azerothl/documentalist) imports from a Git repository.

## Export

```bash
openguildkit docs export --tasks request-status,request-history --output docs-site --version 1.4.0
openguildkit docs export --tasks request-status --output docs-site --version 1.4.0 --sections reference,blog --openapi openapi.yaml
```

Only tasks in the `done` state can be exported: their checks passed and their results are recorded. The pages carry the brief, the behaviour and criteria that were met, the number of checks passed, the pull request or revision and the version. They never carry the boards' reviews, the evidence paths, open questions or anything else from the local task records, and tasks you do not name are not exported.

| Folder | Documentalist tab | Content |
|---|---|---|
| `reference/` | Reference | One page per task: behaviour, verification, source |
| `learn/` | Learn | A guide draft per task, marked for review before publication |
| `blog/` | Blog | A dated release note per task (`date` in the front matter and in the file name) |
| `openapi/` | OpenAPI import | The file given with `--openapi`, for Documentalist's one-time OpenAPI import |

`SUMMARY.md` fixes the order of the pages and each page carries `sidebar_position`. Paths depend only on the task ID and, for the blog, the completion date, so exporting again rewrites the same files: commit them, and Documentalist's synchronization updates each page by its source path instead of creating a new one. Pages of tasks you no longer select are removed. The export refuses to write into a folder it did not create.

Review the pages before committing them, especially the Learn drafts. The [example](../examples/documentalist/docs-site/) shows the export of the fictional request status task.

## Import into Documentalist

In a Documentalist space, an administrator opens Tools → Integrations → Import from GitHub and sets the repository and the three folders: `docs-site/reference` for Reference, `docs-site/learn` for Learn and `docs-site/blog` for Blog. After a new export is committed, "Relancer sync" (or the automatic synchronization) updates the existing pages. The OpenAPI file goes through the separate OpenAPI import, which is a one-time copy.

The folder layout, the order rules and the blog dating follow the Documentalist README at commit [`947429b`](https://github.com/azerothl/documentalist/tree/947429b19da6) (2026-11-11). Documentalist publishes no licence file: its code is not redistributed by OpenGuildKit, and reusing it beyond running it requires its author's permission. The exported Markdown belongs to your project.

## Share a deliverable

Documentalist controls access: a portal can be public, protected by a shared code, or limited to invited addresses with magic links, and "Retirer l'accès" revokes an address. OpenGuildKit keeps the register of what you shared, with whom and until when, so expired access does not stay open:

```bash
openguildkit docs share add --deliverable docs-site/reference/request-status.md --recipient client@example.org --until 2026-12-31 --portal https://docs.example.org/p/support-portal --by "Camille Martin"
openguildkit docs share list
openguildkit docs share check        # exit code 1 while an expired share is not revoked
openguildkit docs share revoke --id ID --by "Camille Martin"
```

The owner chooses the deliverable, the recipients and the end date before inviting them in the portal. `share check` can run on a schedule: it fails when a share has passed its end date and its access was not removed in Documentalist. The register lives in `.openguildkit/shares/`, ignored by Git, because it contains email addresses. The boards' reviews stay in the local task records and are never part of a share.
