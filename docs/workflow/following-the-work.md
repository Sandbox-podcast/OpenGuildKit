# Following the project's work

For: a team that follows its tasks through Git, and the agent that reads them.
A part of the [task workflow](../workflow.md).

```bash
openguildkit task list                              # every task, its status, decision owner and next open point
openguildkit task list --status approved --owner CM --since 2026-11-01
openguildkit task new "Add request history" --follows request-status
openguildkit task export request-status --output shared/request-status.json
```

`task list` names who took each task's current decision and, when a person closed it with `--by`, who closed it (`[done-with-reservations, approved by CM, closed by AM]`): `changes requested by AM` after a change request, `withdrawn by AM (approved by CM)` after a withdrawal, and `approved by CM, approval no longer holds` when the approval no longer holds.
`--owner NAME` keeps the tasks whose current decision that person took: the approval, the change request or the withdrawal.
An approval that holds through the approvers and signers file of the revision it was signed at, its signer having left since, shows a `note:` line with the signer and the revision, which `check` prints too ([signed approvals](decide.md#signed-approvals)).
It gives each task's next step, from its real state: results to record, a failing check to fix, evidence awaited from its owner.
An approved task whose approval no longer holds (rules, checks or boards changed since, seal broken or missing, signature that fails, approved revision gone from the history after a rebase) shows why and what to run instead, in the same words as `task verify`:
it is an error, so `check` names it and exits 1, and `handoff`, `export`, `verify`, `result` and `complete` refuse it ([when an approval no longer holds](decide.md#when-an-approval-no-longer-holds)).
A completed task whose rules changed afterwards is history: `task list` and `task show` say so, `task export` still writes its record, and `check` stays quiet.
An approval written by a release older than sealed decisions counts as missing its seal until the task is consulted again, unless the task was completed.
`check` also names exported records that no longer hold.
`task list` marks an unreadable task record so the team can restore it from a backup.

`task export` writes the brief, the board recommendations and verdicts, the sealed approval, and the decisions from earlier review rounds.
It includes the recorded reasons and owners for checks marked skipped or not applicable, and each blocker of the review (`blockers`) with its phase and, once resolved, who cleared or waived it, when, the evidence and what it establishes, or the waiver's reason, scope and end date: teammates and CI see only the record, so the conditions of the approval travel with it.
It lists in `files` the files Git tracks that changed since the approved revision, committed or not (the decision records left out), which `guard --ci` compares with the pull request; a task approved before the project had a Git revision lists none.
A new file Git does not track yet is not in the list: `task export` names those files, so `git add` them, or commit the work, before exporting.
Review the file before sharing it.
Detailed evidence and specialist findings stay in the local task record.

What the record shows is checked by every reader (`check`, `task list --decisions`, `task show` of a task known only by its record, `guard --ci`, `guard --json`).
The approval's seal covers a digest of the brief, the review summary, each board's verdict and recommendation and the earlier rounds; a second digest, `record_sha256`, covers the whole record as exported, completion and results included.
A record whose content, file name or digests no longer match is refused, with the command to export it again or the advice to restore it from git.
What the digests prove, and what they do not:

- The seal's digest proves that the brief, summary, verdicts, recommendations and earlier rounds are those the approval was given on, as long as nobody recomputed the seal.
  In a project with signed approvals, the approver's signature covers it, so it cannot be recomputed without their key.
- `record_sha256` only proves that the file was not edited by someone who did not recompute it.
  Anyone can recompute it.
- The list of `files` is written by `task export` after the approval and sealed by nobody: it stops a record from being copied as it is into another change, and a reviewer compares it with the diff, but whoever rewrites it and recomputes `record_sha256` passes.
  The person's signature covers the approval, never the files.
  Two checks of `guard --ci` limit what a rewritten list can reach: a new approval must have been given on a revision of the pull request's history (an approval from an abandoned branch is refused, as `task list` refuses it locally), and an approval already on the base revision covers only the files its base record listed, wherever below `.openguildkit/decisions/` that record sits.
  A record outside the folder itself is refused.
- The completion state (`completed`, `completed_at`, the result and its closing) is written by `task complete` and sealed by nobody.
  Readers only check that it is consistent: a record that says completed carries a completion time and the closing `task complete` writes, its status is `done` when the closing lists no open points and `done-with-reservations` when it does, and a record that does not say completed carries none of them.
  A completion forged consistently passes; the task record in the copy that completed it, and the delivered revision, are what show it.
  A record exported by an earlier release carries neither: it still loads, is shown as not verified with the command to export it again, does not make `check` fail, and is refused by `guard --ci` when a pull request adds it.

## What git shares and what stays local

| Shared through git | Local to each copy (`.openguildkit/.gitignore`) |
|---|---|
| `project.json`, `catalog.lock.json`, the project catalog, `AGENTS.md` and `CLAUDE.md` | `tasks/`: task records, board passes, check logs |
| `decisions/`: the records written by `task export` | `shares/`, the project lock and temporary files |

A task lives in the copy where it was opened.
What a teammate sees of it is its exported record, so export a task once its work is committed, to open the pull request, and again after `task complete`, then commit the record (the order is: commit the work, `task export`, commit the record):
a record exported before completion says `"completed": false`, `task export` warns on screen, and `task complete` gives the command to export again and commit the record.
`guard --ci` accepts that last export in the pull request of the work, or in a pull request of its own once the first record is merged: a record of an approval the base revision already holds (same seal, same consultation) may add the completion, the result and a longer list of files, and covers only the files its base version listed.
A new approval under an ID the base revision already used is refused: new work needs a new task.
`task new --id ID` refuses an ID that an exported decision of the repository already uses, and `task export` never replaces a record written by another task: a record is this task's own when it names the same task and the same creation time (for a record from an earlier release, one of the task's consultations).

```bash
openguildkit task list --decisions          # the exported decisions, teammates' included, with status and rule match
openguildkit task show status-filter        # a task known here only by its exported record prints that record
```

`task list --decisions` (with `--json`) shows each record of `.openguildkit/decisions/` with its status, its approver, whether the task was completed, whether it was approved under the current rules, and whether the task record exists in this copy.
`check` adds two warnings, without changing its exit code: exported records naming tasks absent from this copy (normal for a teammate's task; after a deleted `tasks/` folder, the records are what remains), and evidence a task cites (named evidence, a cleared blocker) that git ignores or that sits under `.openguildkit/tasks/`, where a reviewer cannot open it.

`guard --json` reports in `covered_by` the approved tasks of this copy that cover new edits: a teammate's approval does not authorize your agent's edits, so a pulled record never fills it.
`exported_decisions` lists the exported records that match the current rules; in CI, `guard --ci` checks the records the pull request adds, and that each changed file is in the `files` of one of them ([the CI check](../../integrations/README.md#the-board-before-every-change)).

## Reuse the profile in another repository

A team that equips a second repository runs, in the first one:

```bash
openguildkit profile export > answers.json   # then, in the second repository:
openguildkit init --answers answers.json
```

`profile export` writes, in the format of `init --questions`, the sector, stack, roles, the answers on personal data, the patterns, the packs (with `"replace_default_packs": true`, so the same packs apply), the boards, the required boards and rules, `ask_every_rule`, the tools, the host, the guard, the research policy, the conventions and the pack resolutions.
The new project takes the second folder's name.
It reads the profile and writes nothing.

It never carries what belongs to people or to the first repository, and says so on its last lines:
the project name, the history of changes, people's names, the signers file, component paths (each pattern applies to the whole new project until the person scopes it), check commands (add the second repository's with `openguildkit profile add check`) and the host's tool connections (`tools apply` writes them per repository).
A credential in a convention or a resolution reason is replaced with a placeholder.

A setting that names a person, or that lowers a protection, is left out and typed again by the person at a terminal in the second repository, like any change that weakens a protection.
The command prints each one with what to type: signed approvals (`openguildkit profile set approval signed --signers PATH --approver NAME`), a waiver policy, the short lane, a guard below `observe` (the new project starts at `observe`; `openguildkit profile set guard off --by INITIALS --reason WHY` lowers it), and public research.
A norm the first repository declined comes back active, since its decline names who decided: the person declines it again with `openguildkit profile decline ID --by INITIALS --reason WHY`.

## When two copies use the same task ID

Task IDs are chosen in each copy.
When two people open a task with the same ID before pulling, both export `.openguildkit/decisions/ID.json` and git reports a conflict in that file.
`check` and `task list --decisions` then name the file as a git merge conflict, with each side's label and approver.
Keep the teammate's side (`git checkout --theirs .openguildkit/decisions/ID.json`, then `git add`), open your own work under another ID with `openguildkit task new "BRIEF" --id NEW-ID`, and take it through consultation and approval again: an approval is bound to its task ID.
Until then, `check` and `task list` say that your local task and the record of the same ID are different tasks, and `task export` refuses to replace the teammate's record.

One file per task means two people never edit the same record.
When a pull brings a conflict in the code, read the pulled records of the tasks that touch the same files (`task list --decisions`, then `task show ID`): their brief, review summary and board recommendations say what the other change was approved to do (the full approved scope stays in the teammate's task record), and a merge that goes beyond either needs its own task.
