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

`task consult` carries the task's open and confirmed alerts to the boards; dismissed and resolved alerts stay out. The consultation is a snapshot: when `task alerts ID --import` brings an open or confirmed alert that the task's last consultation does not hold, it says to consult the task again with `task consult ID --reuse-answers` so the boards see it. A report that brings nothing new asks nothing. Tasks created by an earlier version kept their alerts inside the task record: `task alerts ID` moves them into the register, linked to the task.

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

On 23 November 2026, a private synthetic repository with Dependabot enabled supplied five real alerts over five pages. The import, repeated import, cross-scanner matching, fixed-alert handling and a separate read-only access check are recorded in the [validation report](../examples/dependabot-validation/2026-11-23.md).

## The `dependency-watch` agent

`openguildkit integrations --host claude-code` installs `.claude/agents/dependency-watch.md` next to `guild-board`. When the user asks to check the dependencies, the agent runs the scanners the project already uses, imports their reports with `openguildkit alerts import`, explains each new alert with the files it read, records the reviews the user gives, and opens one task per confirmed alert that no task handles yet (`alerts list --status confirmed --without-task`, then `task new` and `task alerts ID --link ALERT`, or `alerts tasks --open`, below). It never edits the register by hand, never accepts or dismisses a critical alert, and changes a dependency only once its task is approved. Codex and the other hosts install no agent file: the skill (`references/dependency-alerts.md`, which `SKILL.md` says when to read) carries the same limits, word for word, and the same steps, and the agent of such a host follows them itself; a test compares the two lists of limits.

## One task per confirmed alert

```bash
openguildkit alerts tasks           # the confirmed alerts no task handles, with the task each one gets
openguildkit alerts tasks --open    # opens each task as a draft and links its alert to it
```

A confirmed alert that no task handles and no person accepted gets a task of its own. Its ID comes from the package and the advisory (`dep-form-parser-ghsa-xxxx-yyyy-zzzz`), so it is the same in every copy of the project and every scheduled run: the register links the alert to that ID, and whoever takes the work creates the task with it (`task new "BRIEF" --id ID`), already linked. Its brief names the alert, the affected version and the fixed one. `--json` prints the list for a script.

## Scheduled watch

[`integrations/github/openguildkit-dependency-watch.yml`](../integrations/github/openguildkit-dependency-watch.yml) runs every Monday:

1. it runs the scanner (pip-audit in the template; replace it with the project's own) in a job whose token can only read the repository, and hands the report to a second job as an artifact; that second job, which holds the write permissions, installs only OpenGuildKit and imports the report, listing the new, reopened and resolved alerts in the job summary, or why a report that analyzed nothing resolves nothing;
2. it opens one task per confirmed alert that no task handles (`alerts tasks --open`): the register links the alert to the task's ID, and an issue titled `OpenGuildKit task ID: dependency alert ALERT` tracks it, with the commands to create the task in a copy of the project and consult its boards; an issue already opened, open or closed, is not opened again;
3. it proposes the updated register in a pull request from a fresh `openguildkit/dependency-watch-RUN-ATTEMPT` branch, with the alerts to review in its description. A person reviews each new alert on that branch (`alerts set ALERT --status confirmed` or `--status dismissed --reason WHY`, at a terminal for a critical alert), commits the register and merges. The next run opens a task for each alert confirmed there.

While an earlier watch pull request to the same base is open, the next run leaves its branch and review commits intact. Once that pull request is merged or closed, a subsequent run can propose a fresh register.

The job writes the register to the branch through the GitHub API with its own token, which never reaches `.git/config`; the repository setting that allows GitHub Actions to create pull requests must be on. It changes no dependency: a fix goes through its task and the person's approval. Its actions are pinned by commit SHA.

A scanner such as pip-audit installs the dependencies it audits (its README calls `pip-audit -r requirements.txt` "functionally equivalent to `pip install -r`"), so their code runs during the scan. That is why the scan has a job of its own, with `contents: read` only: a dependency's code never runs next to a token that can push, open issues or open pull requests.

### The pull request and the guard

The register decides what blocks an approval, so `.openguildkit/alerts.json` is work like any other file: in guard mode `enforce`, `openguildkit guard --ci` refuses the job's pull request with `The changes come with no exported decision` until the branch carries a decision record that lists the register. The person who reviews the alerts gives it one:

```bash
git checkout main                                   # the base branch of the pull request
openguildkit task new "Review the alerts of the weekly dependency watch." --id alert-review-2026-11-23
openguildkit task consult alert-review-2026-11-23   # then the boards' review, as for any task
openguildkit task decide alert-review-2026-11-23 --approve --by NAME --reason WHY
gh pr checkout PR_NUMBER
openguildkit alerts set ALERT --status confirmed --by NAME   # or --status dismissed --reason WHY, for each new alert
git commit -am "Review the new dependency alerts"
openguildkit task export alert-review-2026-11-23
git add -f .openguildkit/decisions/alert-review-2026-11-23.json && git commit -m "Decision of the alert review"
git push
```

Approve the task on the base branch, before checking out the job's branch: the record lists the files changed since the approved revision, so it then covers the register the job imported as well as the reviews. A task approved on the job's branch covers only what changed after its approval. In modes `off` and `observe`, the pull request needs no record.

GitHub does not start workflows from events that the job's `GITHUB_TOKEN` causes in the usual way: the `pull_request` runs of the pull request the job opens wait for a maintainer's approval (GitHub documentation, "Triggering a workflow", read on 23 November 2026), so its checks, the guard among them, show as waiting. The reviewer's push above starts them; a maintainer can also approve the waiting runs in the pull request.
