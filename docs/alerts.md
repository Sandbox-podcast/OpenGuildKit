# Dependency alerts and vulnerability watch

OpenGuildKit does not scan dependencies. It reads the JSON report of a scanner the project already uses (npm audit, pip-audit, OSV-Scanner, GitHub Dependabot alerts) and keeps the alerts in one register per project, `.openguildkit/alerts.json`. Commit that file: the team shares the reviews, and the scheduled job reads them.

## The register

```bash
npm audit --json > npm-audit.json          # or: pip-audit -f json -o pip-audit.json, osv-scanner --format json -r . > osv.json
openguildkit alerts import npm-audit.json
openguildkit alerts list --status open
openguildkit alerts set npm:semver:ghsa-c2qf-rxjj-qqgw --status dismissed --by "Alex Moreau" --reason "Only used at build time"
```

The register holds one entry per package and advisory, whatever scanner reported it. An advisory has several IDs (GHSA, CVE, PYSEC, GO, other OSV IDs); the CLI reads the aliases each report gives and merges the entries that share one. Ecosystem names are normalized (`pip` and `PyPI` are the same, `rust` and `crates.io` too). An entry is named after its GHSA ID, else its CVE, else the scanner's own ID, and any of its IDs finds it: `pypi:jinja2:cve-2024-22195` and `pypi:jinja2:pysec-2024-1` name the same entry. When one scanner gives no severity (pip-audit), the severity reported by another scanner for the same advisory is kept. A pip-audit report alone carries no severity, so its alerts stay `unknown` and never block a task: import an OSV-Scanner or Dependabot report of the same project as well to get a critical alert that blocks. After an import for a task that was already consulted, run `task consult` again so that the boards see the alerts.

Each alert has a status:

| Status | Meaning | Set by |
|---|---|---|
| `open` | Reported, not reviewed yet | An import |
| `confirmed` | A reviewer confirmed the project is affected | `alerts set --status confirmed --by NAME` |
| `dismissed` | Not applicable, with the reason and who decided | `alerts set --status dismissed --by NAME --reason WHY` |
| `resolved` | No scanner that reported it lists it anymore | An import |

Importing the full report of a scanner marks the alerts that this scanner listed before and no longer lists: when no other scanner still lists them, open and confirmed alerts become `resolved`. An alert that reappears goes back to its previous status. A dismissed alert stays dismissed. Each import is recorded with the scanner, the file name, the SHA-256 of the report and the date (the last 20 imports are kept).

`to-verify`, the status of earlier versions, is read as `open`.

## Alerts and tasks

A task lists the alerts that concern it:

```bash
openguildkit task alerts ID --import pip-audit.json     # imports into the register and links the report's alerts to the task
openguildkit task alerts ID --link pypi:jinja2:ghsa-h5c8-rqwp-cp95
openguildkit task alerts ID
```

`task consult` carries the task's open and confirmed alerts to the boards; dismissed and resolved alerts stay out. Tasks created by an earlier version kept their alerts inside the task record: `task alerts ID` moves them into the register, linked to the task.

A confirmed alert of severity `critical` blocks the approval (`task decide --approve`) and the completion (`task complete`) of each task it is linked to, with a message that names it. It stops blocking when an import shows it resolved, or when a person records why the risk is accepted:

```bash
openguildkit alerts accept npm:form-parser:ghsa-xxxx-yyyy-zzzz --by "Camille Martin" --reason "Only reachable by administrators until 2.0.1 ships"
```

`alerts accept`, and dismissing a critical alert or taking a confirmed critical alert back, need a person at an interactive terminal who types the alert ID, as for a waiver. An agent cannot do them.

## GitHub Dependabot alerts

The Dependabot alerts API returns one page at a time. `gh api --paginate` follows every page and prints one JSON array per page, back to back; `openguildkit alerts import` reads that output, and also the single array of pages that `--slurp` prints:

```bash
gh api --paginate "repos/OWNER/REPO/dependabot/alerts?state=open&per_page=100" > dependabot.json
openguildkit alerts import dependabot.json
```

The token needs read access to the repository's Dependabot alerts. Closed alerts (fixed or dismissed in GitHub) are skipped, so they count as no longer listed.

Verification note: the reading of concatenated and slurped pages is tested on synthetic files. The `gh` command above was not verified against a live repository.

## The `dependency-watch` agent

`openguildkit integrations --host claude-code` installs `.claude/agents/dependency-watch.md` next to `guild-board`. When the user asks to check the dependencies, the agent runs the scanners the project already uses, imports their reports with `openguildkit alerts import`, explains each new alert with the files it read, records the reviews the user gives, and opens one task per confirmed alert that no task handles yet (`alerts list --status confirmed --without-task`, then `task new` and `task alerts ID --link ALERT`). It never edits the register by hand, never accepts or dismisses a critical alert, and changes a dependency only once its task is approved.

## Scheduled watch

[`integrations/github/openguildkit-dependency-watch.yml`](../integrations/github/openguildkit-dependency-watch.yml) runs every Monday: it runs the scanner (pip-audit in the template; replace it with the project's own), imports the report, lists the new, reopened and resolved alerts in the job summary, keeps the updated register as an artifact, and opens one issue per confirmed alert that has no issue yet (open or closed, matched by title). New alerts stay open until a person reviews them; commit the reviewed register so the next run sees the confirmations. The job changes no dependency. Its actions are pinned by commit SHA.
