# SARIF output

`openguildkit check` and `openguildkit guard --ci` print their problems in text. With `--format sarif` they print the same problems as a [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) document, the format that code scanning dashboards read, so that a problem of the project's governance (an approval that no longer holds, instructions that no longer match the profile) can appear next to the other alerts of a pull request.

```bash
openguildkit check --format sarif > openguildkit-check.sarif
openguildkit guard --ci --base origin/main --format sarif > openguildkit-guard.sarif
```

- **The standard output holds the document and nothing else.** The standard error says what the text form says (the lines `check` prints about approvals and warnings, and the error that ends it).
- **The exit code is the one of the text form**: `check` exits 1 on a problem that ends it, `guard --ci` exits 1 on a problem when the guard of the base revision enforces. A file with warnings only comes with exit 0.
- **`--format` is `text` by default.** `--format sarif` and `--json` together are refused with the command to type, and `guard --format sarif` needs `--ci`. `check` has no `--json` form.
- The file is written by [`sarif.py`](architecture.md), which does not know about `check`: `host scan --format sarif` gives it its findings too, under the rules of [its page](host-scan.md#what-the-findings-mean), and [`check_findings.py`](architecture.md) gives the findings of `check` and `guard --ci`.

## What the file holds

One run, with `tool.driver` named `OpenGuildKit`, the version of the package, the address of the repository and `rules`: only the rules that a result uses, each with its `id` (the code below), a `name`, a `shortDescription.text` and a `helpUri`, which is the heading of this page for that rule on the `main` branch.

One `result` per problem, in a fixed order (file, line, code, message):

| Field | Value |
| --- | --- |
| `ruleId`, `ruleIndex` | The rule's code, and its position in `rules`. |
| `level` | `error`, `warning` or `note`, as each rule below says. |
| `message.text` | The line the text form prints, in English, without the project folder. |
| `locations[0].physicalLocation.artifactLocation` | `uri`: the file the problem concerns, relative to the root of the project, with `/` separators and percent-encoded where a URI needs it; `uriBaseId`: `%SRCROOT%`. A problem about no file in particular points at `.openguildkit/project.json`. |
| `partialFingerprints` | `openguildkit/v1`: the SHA-256 of the code, the path and the message joined by vertical bars, the message with its spaces and line breaks collapsed. |

A message says what the text form says, so it can name what a record holds: a task ID, the initials of an approver and the reason of a withdrawal. A dashboard shows it to everyone who can read its alerts.

The file names no folder of the machine: a path is relative, the project folder is taken out of every message (a file inside it keeps its relative path, the folder itself is written "the project folder") and the home folder is written `~`. Two runs on the same project give the same bytes, from any folder and whatever the order the checks found the problems in.

The fingerprint is there so that a dashboard recognizes a problem from one run to the next: the line is not part of it (the commands give none), nor the level. It changes when the message changes, and some messages carry what changed (the changed files that no record lists, the tasks an approval names): that is a new problem for a dashboard, and the old one closes. Two findings of the same code, file and message on two lines of a file get the plain fingerprint on the first line and `:2`, `:3` after it. How a given dashboard uses the key is not tested here.

## What the file does not hold

- **The first problem that ends the command.** `check` reports every approval that no longer holds, then stops at the first of: instructions out of date, host settings missing, catalog lock out of date. The warnings it prints after them (`catalog-update-pending`, `source-undated`, `task-id-clash`, `evidence-unshared`) are in the file only when none of these stopped it. Fix the problem and run it again to see the next. `guard --ci` gathers every problem of the records it reads in one pass.
- **A command that cannot run.** A profile that cannot be read, a base revision Git does not have, a folder that is not a Git repository: the command prints its error on the standard error, exits as before and prints no file. That is a failure of the job, not a finding about the project.
- **A line.** None of these problems has a line: no result carries a `region`. `sarif.py` writes `startLine` when a command gives one, for the commands that will.
- **The lines that report no problem.** `check` prints an approval that holds through the signers of the revision it was signed at, and the exported decisions that name tasks absent from this copy, which is what every checkout of a repository that keeps `tasks/` out of Git shows. Neither is a finding. The exported decisions that are notes for `check` (a withdrawn record, a record exported before digests) are not findings either; `guard --ci` does refuse them.
- **A task record in CI.** `.openguildkit/tasks/` is ignored by Git, so a CI job checks out none of it: `check` there judges the exported decisions, and the results that point at `.openguildkit/tasks/ID.json` come from a workstation, where the file exists.

## Rules

A code is part of what a dashboard keys an alert on: a rule is added or retired here, never renamed. The commands name the rule in the `ruleId` of each result.

For `guard --ci`, a problem is an `error` when the guard mode of the base revision is `enforce` and a `warning` otherwise: the text form says "Flagged, not blocking" and the job passes. A note stays a note.

### The instructions, the host and the catalog (`check`)

#### `instructions-drift`

`error`. `AGENTS.md`, `CLAUDE.md` or `.openguildkit/.gitignore` no longer matches the profile and the catalog lock; one result per file. Run `openguildkit sync`.

#### `instructions-edited`

`error`, on `AGENTS.md`. The managed block was edited by hand. `sync` replaces the block: move your own text outside the markers first.

#### `instructions-ahead-of-lock`

`error`, on the file that is out of date. The instructions follow a newer catalog than the project's lock. Run `openguildkit update` to review the changes and the tasks they touch, then `openguildkit update --apply`; `sync` would write the lock's earlier rules back.

#### `host-settings-missing`

`error`, on the profile. The host agent's settings do not enforce a rule the profile asks for, or `openguildkit` is not on the `PATH` the hooks need. Run `openguildkit host check` for the cause, then `openguildkit host apply`.

#### `catalog-lock-stale`

`error`, on `.openguildkit/catalog.lock.json`. The lock does not cover exactly what the profile uses. Run `openguildkit sync`.

#### `catalog-update-pending`

`warning`, on `.openguildkit/catalog.lock.json`. The installed catalog changes the rules of locked records; the project keeps its locked rules. Run `openguildkit update` to review the changes.

#### `source-undated`

`warning`, on the profile. A record of the project's catalog cites a source without a `checked` date. Open each page and add `"checked": "YYYY-MM-DD"` after its `url` ([catalog format](catalog-format.md#source-dates)).

#### `brain-replaced`

`warning`, on `.openguildkit/catalog/boards/ID.json`. The project catalog replaces the title, the description or a specialist of a bundled brain. Check that the person accepted this change to the brain's review.

#### `approvals-not-signed`

`warning` for `check`, which says it when the guard is `enforce` and approvals are only sealed locally; on the profile. A local seal only detects accidental edits. For `guard --ci` it is a `note` on the same condition, and an `error` (a `warning` outside `enforce`) with `--require-signed`. Require signed approvals ([signed approvals](workflow.md#signed-approvals)).

#### `task-unreadable`

`error`, on `.openguildkit/tasks/ID.json`. A task record cannot be read. Restore it from a backup, or delete it and open a new task.

#### `task-id-clash`

`warning`, on the exported decision. A local task and the exported decision of another task share an ID. Open your work under another ID ([workflow](workflow.md#when-two-copies-use-the-same-task-id)).

#### `evidence-unshared`

`warning`, on `.openguildkit/tasks/ID.json`. A task cites evidence a reviewer cannot open from the repository (ignored by Git, or under `.openguildkit/tasks/`). Move it to a committed folder and record it again.

### The approvals (`check` and `guard --ci`)

`check` reports a task of this copy and an exported decision; `guard --ci` reports the decisions a pull request brings.

#### `decision-stale`

`error`. An approval was given under rules that have changed since: the packs, their rules, the checks or the boards ([when an approval no longer holds](workflow.md#when-an-approval-no-longer-holds)). On the task record, or on the exported decision. Consult the task again (`openguildkit task consult ID`) or open a linked task.

#### `decision-seal-invalid`

`error`, on the task record. The approval has no seal, or its seal does not match the record. Consult the task again.

#### `decision-record-invalid`

`error`, on the exported decision. The record cannot be read, holds a git merge conflict, is not under `.openguildkit/decisions/`, or does not match what was approved (seal, shown content, digest, completion, file name). Export the decision again (`openguildkit task export ID`), or restore the file from Git.

#### `decision-unsigned`

`error`. The project requires signed approvals and the approval is not signed: on the task record, or on the exported decision.

#### `decision-signature-invalid`

`error`. The signature of the approval cannot be verified against the allowed signers file: on the task record, or on the exported decision.

#### `decision-outside-history`

`error`. The approval was given on a revision that is not in the history of this change, as after a rebase or on an abandoned branch. Consult the task again.

#### `decision-withdrawn`

`error`, `guard --ci` only, on the exported decision. The approval the record carries was withdrawn: it covers no change. Open a new task for the work.

#### `decision-withdrawn-here`

`error`, `check` only, on the exported decision. The approval was withdrawn in this copy and the record still says approved. Write the withdrawal into it with `openguildkit task export ID` and commit it.

#### `decision-superseded`

`error`, `guard --ci` only, on the exported decision. The task already had another approval on the base revision: new work needs a new task.

#### `decision-record-unverified`

`error`, `guard --ci` only, on the exported decision. The record was exported by an earlier release, before records carried a digest, so its content is not verified. Export it again.

#### `decision-waiver-expired`

`error`, `guard --ci` only, on the exported decision. A waiver the approval rested on has expired and the task is not completed: its blocker is open again.

### The change (`guard --ci`)

#### `decision-missing`

`error`, on the profile. The changes come with no exported decision, or none of the records they bring is valid. Export the decision of the approved task (`openguildkit task export ID`) and commit it with the change.

#### `decision-files-uncovered`

`error`, on the profile. Changed files are in no decision record of the change. Export the record again once the work is committed, or open a task for the change.

#### `evidence-journal-changed`

`error`, on the exported decision. A journal that the record cites as evidence no longer matches the SHA-256 recorded with it.

#### `guard-no-base-profile`

`note`, on the profile. The base revision has no OpenGuildKit profile, so nothing is enforced: expected for the pull request that adds it.

#### `guard-workflow-edited`

`note`, on each workflow file. The change edits a workflow that runs this check, and GitHub runs the pull request's own copy: have a person review the change ([protect the check](../integrations/README.md#protect-the-check)).

## Upload to GitHub code scanning

GitHub code scanning reads SARIF 2.1.0 files that the `github/codeql-action/upload-sarif` action sends ([GitHub's documentation](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/uploading-a-sarif-file-to-github)). `--format sarif` is not in v0.17.0: install a release that has it. The job below runs `guard --ci` and sends the file even when the command exits 1, so the exit code stays the job's verdict. For `check`, replace the command with `openguildkit check --format sarif > openguildkit-check.sarif` (and drop `--base`); for `host scan`, with `openguildkit host scan --format sarif > openguildkit-scan.sarif`.

```yaml
name: OpenGuildKit guard for code scanning

on:
  pull_request:

permissions:
  contents: read

jobs:
  guard:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
        with:
          python-version: "3.13"
      - name: Install OpenGuildKit
        # A release that has --format sarif, and the wheel's hash from that release's SHA256SUMS.txt (install.md).
        env:
          OPENGUILDKIT_TAG: replace-with-a-release-tag
          OPENGUILDKIT_WHEEL: replace-with-the-wheel-file-name
          OPENGUILDKIT_WHEEL_SHA256: replace-with-the-wheel-hash-from-SHA256SUMS.txt
        run: |
          curl -fsSL -o "$RUNNER_TEMP/$OPENGUILDKIT_WHEEL" \
            "https://github.com/Sandbox-podcast/OpenGuildKit/releases/download/$OPENGUILDKIT_TAG/$OPENGUILDKIT_WHEEL"
          printf '%s  %s\n' "$OPENGUILDKIT_WHEEL_SHA256" "$RUNNER_TEMP/$OPENGUILDKIT_WHEEL" | sha256sum --strict -c -
          python -m pip install "$RUNNER_TEMP/$OPENGUILDKIT_WHEEL"
      - name: Check the decision behind the changes
        env:
          BASE_REF: ${{ github.event.pull_request.base.sha }}
        run: openguildkit guard --ci --base "$BASE_REF" --format sarif > openguildkit-guard.sarif
      - uses: github/codeql-action/upload-sarif@1fc58d04a4d4374f921bdac573c3811c240f9c26 # v4.39.2
        if: always()
        with:
          sarif_file: openguildkit-guard.sarif
          category: openguildkit-guard
```

The action is pinned the way the templates of [`integrations/github/`](../integrations/github) pin theirs: the full SHA of the commit and its tag in a comment. `1fc58d04a4d4374f921bdac573c3811c240f9c26` is the commit of the tag `v4.39.2` (published 2026-11-03), read on 2026-11-25 with the command below; the `action.yml` of its `upload-sarif` folder declares the `sarif_file` and `category` inputs. To move to another version, read its tag the same way:

```bash
gh api repos/github/codeql-action/git/ref/tags/TAG --jq .object
```

The answer names the object a tag points at. When its `type` is `commit`, its `sha` is the one to pin. When it is `tag` (an annotated tag), follow it with `gh api repos/github/codeql-action/git/tags/SHA --jq .object.sha`; that is the commit. Write it as `github/codeql-action/upload-sarif@SHA # vX.Y.Z`, with the version of the tag.

Nothing on this page was sent to GitHub, and the job above was not run: the tests check the structure of the file with the standard library, not against the schema of the standard, and no dashboard has read a file OpenGuildKit wrote. Open the first upload's result in the repository's Security tab before relying on it.
