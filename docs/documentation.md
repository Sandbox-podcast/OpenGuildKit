# Project documentation and sharing

Completed tasks already hold what a reader needs: the brief, the expected behaviour, the acceptance criteria that were met, the delivery and the project version. The project profile says what the project is and which rules apply. `openguildkit docs export` turns the profile and the tasks you select into Markdown pages that [Documentalist](https://github.com/azerothl/documentalist) imports from a Git repository.

## Export

```bash
openguildkit docs export --tasks request-status,request-history --output docs-site --version 1.4.0
openguildkit docs export --tasks request-status --output docs-site --version 1.4.0 --sections reference,blog --openapi openapi.yaml
```

Only tasks in the `done` state can be exported: their checks passed and their results are recorded. The pages carry the brief, the behaviour and criteria that were met, the number of checks passed, the pull request or revision and the version. They never carry the boards' reviews, the evidence paths, open questions or anything else from the local task records, and tasks you do not name are not exported.

| Folder | Documentalist tab | Content |
|---|---|---|
| `project/` | Learn | `overview.md`: the project's name, sector, stack, components with their stack, conventions, the rule packs in force with their version and rules, and the boards that review changes |
| `reference/` | Reference | One page per task: behaviour, verification, source |
| `learn/` | Learn | A guide draft per task, marked for review before publication |
| `blog/` | Blog | A dated release note per task (`date` in the front matter and in the file name) |
| `openapi/` | OpenAPI import | The file given with `--openapi`, for Documentalist's one-time OpenAPI import |

`SUMMARY.md` fixes the order of the pages and each page carries `sidebar_position`. Paths depend only on the task ID and, for the blog, the completion date, so exporting again rewrites the same files: commit them, and Documentalist's synchronization updates each page by its source path instead of creating a new one. Pages of tasks you no longer select are removed. The export refuses to write into a folder it did not create, or through a symbolic link that leads out of it.

The project page is written with the default sections, or with `--sections project`, and keeps one path, so a new export rewrites it. It holds only what the profile and the active packs say: no component path, no check command, no local path and nothing from the tasks. Import `docs-site/project` as a Learn folder, or leave it out of `--sections`.

The export records the files it wrote in `docs-site/.openguildkit-export.json`. That manifest is committed with the pages, so anyone can edit it: the next export only removes an entry that names a page it writes (`reference/`, `learn/`, `blog/`, `openapi/`, `SUMMARY.md`, `README.md`) and stays inside the output folder once `..` and symbolic links are resolved. Any other entry, such as `../notes.txt` or an absolute path, is left in place and printed as `kept`.

Review the pages before committing them, especially the Learn drafts. The [example](../examples/documentalist/) shows the export of the fictional request status task, with the inputs and a script that replays it byte for byte.

## Reproducible dates

Every date OpenGuildKit writes in a record (task creation, board passes, decisions, completion, deliverable drafts, shares and revocations) and every "today" it compares with (share end dates, waiver lengths, market and Storybook ages) comes from one clock. When the environment variable `SOURCE_DATE_EPOCH` is set, following the reproducible builds convention, its value in seconds since 1970-01-01 UTC replaces the current time. A replay run with the same value therefore writes the same dated blog page on any day:

```bash
SOURCE_DATE_EPOCH=1795176000 openguildkit task complete request-status   # recorded as 2026-11-20T12:00:00+00:00
```

Leave it unset in normal use: approvals, shares and waivers would otherwise be stamped and checked against the fixed date. A value that is not a whole number of seconds is refused.

## Import into Documentalist

In a Documentalist space, an administrator opens Tools → Integrations → Import from GitHub and sets the repository and the three folders: `docs-site/reference` for Reference, `docs-site/learn` for Learn and `docs-site/blog` for Blog. After a new export is committed, "Relancer sync" (or the automatic synchronization) updates the existing pages. The OpenAPI file goes through the separate OpenAPI import, which is a one-time copy.

The folder layout, the order rules and the blog dating follow the Documentalist README at commit [`947429b`](https://github.com/azerothl/documentalist/tree/947429b19da6) (2026-11-11). Documentalist publishes no licence file: its code is not redistributed by OpenGuildKit, and reusing it beyond running it requires its author's permission. The exported Markdown belongs to your project.

## Share a deliverable

Documentalist controls access: a portal can be public, protected by a shared code, or limited to invited addresses with magic links, and "Retirer l'accès" revokes an address. OpenGuildKit keeps the register of what you shared, with whom and until when, so expired access does not stay open:

```bash
openguildkit docs share add --deliverable docs-site/reference/request-status.md --recipient client@example.org --until 2026-12-31 --portal https://docs.example.org/p/support-portal --by "Camille Martin"
openguildkit docs share list
openguildkit docs share check        # exit code 1 while a share past its last day is not recorded as revoked
openguildkit docs share revoke --id ID --by "Camille Martin"
```

The owner chooses the deliverable, the recipients and the last day of access (`YYYY-MM-DD`, after today and at most 366 days ahead) before inviting them in the portal. A revocation records who removed the access and when; a second revocation of the same share is refused, so the first record stays.

What OpenGuildKit does not do: it creates no magic link and revokes no access in Documentalist. Inviting the recipients and pressing "Retirer l'accès" happen by hand in the portal's reader settings; `share add` and `share revoke` only record that you did it. Keeping the portal and the register in step is your job until a Documentalist connector exists, and the live import into Documentalist is not part of OpenGuildKit either.

What `share check` reads: only the local register, `.openguildkit/shares/shares.json`. It lists every share and exits with code 1 when a share that is not recorded as revoked has a last day of access before today. It does not contact Documentalist, so it cannot see an access removed in the portal without `share revoke`, nor an invitation sent without `share add`. The register is ignored by Git because it contains email addresses: the check runs where the register is, usually the owner's machine (for example from a scheduled task there), not in CI on a fresh clone, where it finds no share and passes. Writes to the register hold the project lock, so shares recorded at the same time are all kept. The boards' reviews stay in the local task records and are never part of a share.
