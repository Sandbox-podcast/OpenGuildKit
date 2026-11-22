# Dependency alerts and vulnerability watch

OpenGuildKit does not scan dependencies. It reads the JSON report of a scanner the project already uses (npm audit, pip-audit, OSV-Scanner, GitHub Dependabot alerts) and keeps the alerts in one register per project, `.openguildkit/alerts.json`. Commit that file: the team shares the reviews, and the scheduled job reads them.

## The register

```bash
npm audit --json > npm-audit.json          # or: pip-audit -f json -o pip-audit.json, osv-scanner --format json -r . > osv.json
openguildkit alerts import npm-audit.json
openguildkit alerts list --status open
openguildkit alerts set npm:semver:ghsa-c2qf-rxjj-qqgw --status dismissed --by AM --reason "Only used at build time"
```

The register holds one entry per package and advisory, whatever scanner reported it. An advisory has several IDs (GHSA, CVE, PYSEC, GO, other OSV IDs); the CLI reads the aliases each report gives and merges the entries that share one. Ecosystem names are normalized (`pip` and `PyPI` are the same, `rust` and `crates.io` too). An entry is named after its GHSA ID, else its CVE, else the scanner's own ID, and any of its IDs finds it: `pypi:jinja2:cve-2024-22195` and `pypi:jinja2:pysec-2024-1` name the same entry. When one scanner gives no severity, the severity reported by another scanner for the same advisory is kept.

Each alert has a status:

| Status | Meaning | Set by |
|---|---|---|
| `open` | Reported, not reviewed yet | An import |
| `confirmed` | A reviewer confirmed the project is affected | `alerts set --status confirmed --by NAME` |
| `dismissed` | Not applicable, with the reason and who decided | `alerts set --status dismissed --by NAME --reason WHY` |
| `resolved` | No scanner that reported it lists it anymore | An import |

Importing the full report of a scanner marks the alerts that this scanner listed before and no longer lists: when no other scanner still lists them, open and confirmed alerts become `resolved`, and keep in `resolved_by` the report that resolved them: scanner, file name, SHA-256, day and number of dependencies analyzed. An alert that reappears goes back to its previous status. A dismissed alert stays dismissed. Each import is recorded with the scanner, the file name, the SHA-256 of the report, the date and the number of dependencies analyzed (the last 20 imports are kept).

### A report that analyzed nothing

A clean report resolves its alerts with no other step: that is the normal case. A report that shows no analyzed dependency resolves nothing, and `alerts import` says so (`The report analyzed no dependency (...): it resolves no alert.`), because an empty file is also what anyone can write to make a critical alert disappear. What counts as analyzed, by scanner:

| Scanner | Analyzed | Resolves nothing when |
|---|---|---|
| npm audit | `metadata.dependencies.total` (or the sum of its counts) | `metadata.dependencies` is missing or counts none |
| pip-audit | the entries of `dependencies`, vulnerable or not | `dependencies` is empty |
| OSV-Scanner | the packages listed under `results` | `results` lists no package: OSV-Scanner lists only vulnerable packages unless it is asked to list every package it scanned |
| GitHub Dependabot | the alerts listed, in any state | the export is an empty list: fetch the alerts of every state, so a fixed alert shows as fixed |

A confirmed critical alert that an import resolved is shown to the person when they decide: the approval prompt, `task challenge` and `task decision-payload` of each task linked to it name the alert and its report, for the resolutions since the task's last decision.

`to-verify`, the status of earlier versions, is read as `open`.

## Severity

`pip-audit` gives no severity: its JSON report lists, for each dependency, the vulnerabilities with their `id`, `aliases`, `fix_versions` and `description`, and nothing else. An alert that only pip-audit reports therefore stays `unknown` and never blocks a task. Two ways give it one:

- import another scanner's report on the same dependencies (OSV-Scanner or Dependabot give a severity); the entries merge on their shared advisory ID;
- have a person set it from the advisory, at an interactive terminal where they type the alert ID:

```bash
openguildkit alerts severity pypi:urllib3:ghsa-q2q7-5pp4-w6pg --level critical --by CM --reason "CVSS 9.8 on the advisory page"
```

`--level` is `low`, `moderate`, `high` or `critical`. The register keeps the previous severity, the person, the reason and the time in `severity_set`. Raising an alert to `critical` makes it block once confirmed, and lowering it stops the blocking, so an agent cannot run the command. A severity set by a person stays when later imports report another one; a person changes it again with the same command.

## Alerts and tasks

A task lists the alerts that concern it:

```bash
openguildkit task alerts ID --import pip-audit.json     # imports into the register and links the report's alerts to the task
openguildkit task alerts ID --link pypi:jinja2:ghsa-h5c8-rqwp-cp95
openguildkit task alerts ID
```

`task consult` carries the task's open and confirmed alerts to the boards; dismissed and resolved alerts stay out. The consultation is a snapshot: when `task alerts ID --import` brings an open or confirmed alert that the task's last consultation does not hold, it says to run `task consult ID` again so the boards see it. A report that brings nothing new asks nothing. Tasks created by an earlier version kept their alerts inside the task record: `task alerts ID` moves them into the register, linked to the task.

A confirmed alert of severity `critical` blocks the approval (`task decide --approve`) and the completion (`task complete`) of each task it is linked to, with a message that names it. It stops blocking when an import shows it resolved, or when a person records why the risk is accepted:

```bash
openguildkit alerts accept npm:form-parser:ghsa-xxxx-yyyy-zzzz --by CM --reason "Only reachable by administrators until 2.0.1 ships"
```

`alerts accept`, and dismissing a critical alert or taking a confirmed critical alert back, need a person at an interactive terminal who types the alert ID, as for a waiver. An agent cannot do them.

## GitHub Dependabot alerts

The Dependabot alerts API returns one page at a time, and `gh api --paginate` follows every page. Recent `gh` releases print the pages of a list as one JSON array; older ones print one array per page, back to back. `openguildkit alerts import` reads both, and also the array of pages that `--slurp` prints:

```bash
gh api --paginate "repos/OWNER/REPO/dependabot/alerts?per_page=100" > dependabot.json
openguildkit alerts import dependabot.json
```

The token needs read access to the repository's Dependabot alerts. The command fetches the alerts of every state: closed ones (fixed or dismissed in GitHub) count as analyzed and are skipped, so they count as no longer listed, and an export where every alert is fixed still resolves them.

Verification note: on 22 November 2026, `gh` 2.100.0 called with `--paginate` and five items per page on a live endpoint of this repository returned one array of 21 items, which `alerts import` reads like a single page; the reading of concatenated and slurped pages, and of exports where alerts are fixed, is tested on synthetic files.

Limit: the Dependabot endpoint itself has never been called for this documentation. No repository with Dependabot alerts is available to the maintainers, and the owner keeps Dependabot alerts disabled on the OpenGuildKit repository, a security setting that is not changed for a test: there the command answers `Dependabot alerts are disabled for this repository. (HTTP 403)`. So the command above, its pagination over several pages of real alerts and the import of its output are not verified against a live repository. A project with Dependabot alerts turned on can check it by running the command with a small `per_page`, then `alerts import`, and comparing the count with the repository's security tab.

## The `dependency-watch` agent

`openguildkit integrations --host claude-code` installs `.claude/agents/dependency-watch.md` next to `guild-board`. When the user asks to check the dependencies, the agent runs the scanners the project already uses, imports their reports with `openguildkit alerts import`, explains each new alert with the files it read, records the reviews the user gives, and opens one task per confirmed alert that no task handles yet (`alerts list --status confirmed --without-task`, then `task new` and `task alerts ID --link ALERT`, or `alerts tasks --open`, below). It never edits the register by hand, never accepts or dismisses a critical alert, and changes a dependency only once its task is approved. Codex and the other hosts install no agent file: the skill (`SKILL.md`, section "Dependency alerts") carries the same limits, word for word, and the same steps, and the agent of such a host follows them itself; a test compares the two lists of limits.

## One task per confirmed alert

```bash
openguildkit alerts tasks           # the confirmed alerts no task handles, with the task each one gets
openguildkit alerts tasks --open    # opens each task as a draft and links its alert to it
```

A confirmed alert that no task handles and no person accepted gets a task of its own. Its ID comes from the package and the advisory (`dep-form-parser-ghsa-xxxx-yyyy-zzzz`), so it is the same in every copy of the project and every scheduled run: the register links the alert to that ID, and whoever takes the work creates the task with it (`task new "BRIEF" --id ID`), already linked. Its brief names the alert, the affected version and the fixed one. `--json` prints the list for a script.

## Scheduled watch

[`integrations/github/openguildkit-dependency-watch.yml`](../integrations/github/openguildkit-dependency-watch.yml) runs every Monday:

1. it runs the scanner (pip-audit in the template; replace it with the project's own) and imports the report, listing the new, reopened and resolved alerts in the job summary, or why a report that analyzed nothing resolves nothing;
2. it opens one task per confirmed alert that no task handles (`alerts tasks --open`): the register links the alert to the task's ID, and an issue titled `OpenGuildKit task ID: dependency alert ALERT` tracks it, with the commands to create the task in a copy of the project and consult its boards; an issue already opened, open or closed, is not opened again;
3. it proposes the updated register in a pull request from the branch `openguildkit/dependency-watch`, with the alerts to review in its description. A person reviews each new alert on that branch (`alerts set ALERT --status confirmed` or `--status dismissed --reason WHY`, at a terminal for a critical alert), commits the register and merges. The next run opens a task for each alert confirmed there.

The job writes the register to the branch through the GitHub API with its own token, which never reaches `.git/config`; the repository setting that allows GitHub Actions to create pull requests must be on. It changes no dependency: a fix goes through its task and the person's approval. Its actions are pinned by commit SHA.
