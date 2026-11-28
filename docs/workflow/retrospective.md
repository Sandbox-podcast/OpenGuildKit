# Retrospective

For: the person who runs a retrospective, and the agent that prepares its draft.
A part of the [task workflow](../workflow.md).

```bash
openguildkit task retro request-status       # what one closed task set aside, left open or waived
openguildkit task retro --all                # what comes back in the project's closed tasks, with the profile command a person could type
openguildkit task retro --all --min 2 --json # a lower minimum, for a program
openguildkit task retro --all --draft-rules drafts  # also a draft project rule pack, for a person to write
```

A retrospective reads and counts; it records nothing.
Unless the person asks for a [draft rule pack](#a-draft-project-rule) with `--draft-rules`, it writes no file, and it changes no field of a task or of the profile, so there is nothing for [personal data](../personal-data.md) to list and nothing to migrate: a closed task of an earlier release is read as it is, and a field it lacks reads as empty.
It calls no model, makes no estimate, opens no connection and starts no process.
Every number is a count taken from a record, and two runs print the same bytes whatever the order the files were read in.

## What it reads

- The task records in `.openguildkit/tasks/` whose status is `done` or `done-with-reservations`.
  An unreadable record is left out and counted: `task list` names it.
- The exported decision records in `.openguildkit/decisions/` of closed tasks that have no task record here (a teammate's tasks, or a deleted `tasks/` folder).
  A record counts only if it says the task was completed and its `record_sha256` holds; one that does not is left out and counted, and `check` names it.
  A task with both a task record and an exported record counts once, by its task record.

No field that holds a person is printed: not the approver, the person who closed the task, the owners of the rules set aside, nor who waived a blocker, and the name in parentheses at the end of a line of the closing is taken out.
The `task list` of the same project shows the approver and the closer, so the retrospective reveals no name that it did not already.
What people typed in a reason, a finding or a reservation is copied as recorded: a name typed there is printed.

## One task

`task retro ID` gives four lists.
Text is short, one line for each group of findings, and `--json` gives each rule, committee, reservation and waiver.

| List | What it holds | Where it comes from |
|---|---|---|
| Rules not applied | The rules and named evidence the result declared `skipped` or `not-applicable`, with the reason recorded; those that `failed`, with the evidence given; a pack declared as a whole; then the packs and evidence the task was not asked, with the reason `relevance.py` gave | `result.checks`, `result.packs` and `result.closing.not_concerned`. An exported record keeps the reason of a rule set aside but only the status of a rule that failed |
| Boards | The boards convened whose verdict was `proceed`, with no blocker, that neither raised nor received an objection | `consultation.boards`, `review` and the objections that `task respond` recorded or, when it never ran, those the review gives, as `task challenge` shows them |
| Open reservations | The open points of the closing, as it wrote them, most serious first (the skipped and failed rules are only counted: the first list gives them) | `result.closing.open_points` |
| Blockers waived | Each blocker covered by a waiver rather than cleared: its board, finding, reason, scope and end date | `blocker_resolutions` and `verification_blocker_resolutions`, or `blockers` of an exported record |

Two limits.
A rule has no waiver in OpenGuildKit, since a waiver covers a blocker (fourth list), so the first list holds the rules a person set aside or that failed.
And a board is listed only when it said `proceed` and nothing else: one that asked for changes, said it lacked evidence, blocked, or whose advice another board objected to is not, because each did something.
The list says nothing about the value of a recommendation's text, only that the board raised no blocker or objection.
An exported record keeps each board's verdict but not the objections between boards, so for a task known only by its record the output says that the boards are not in it, and the full record where the task was closed gives them.

The proposal behind this command also listed the questions that had no effect on routing.
That list is not offered: a task record keeps the answers and the reasons each board was selected, never which answer led to which board, and nothing records what routing would have done with another answer.
Computing it again would use today's catalog, not the one the task was consulted under, and would say what no record says.

## The project

`task retro --all` counts what comes back in at least `--min N` closed tasks (3 by default).
A finding counts once per task, so the number is a number of tasks, not of occurrences.
Three, the number the proposal named, because a repeat in two tasks is often one team's habit twice in a row, and the minimum is there to lower: `--min 1` lists everything a closed task set aside.

| Finding | Counted as | Profile command written for it |
|---|---|---|
| A rule skipped or declared not applicable | The same rule or pack answer, the same status and the same reason; case, spacing and a final stop are ignored | For a pack answer, `profile remove pack PACK`, or `profile decline PATTERN` when a single active pattern brings the pack. For one rule set aside in at least 3 tasks, whatever `--min` says, `profile decline rule PACK/RULE` (RFC #447), typed at a terminal; none for a rule the profile requires or already declines, or for a named evidence |
| A rule that failed | The same rule, whatever the evidence | `profile add required-rule PACK/RULE`, or `PACK` for a pack that failed as a whole |
| A board that brought nothing | The tasks where it was convened and brought nothing, among the tasks that have a task record, with how many tasks that is | `profile remove board BOARD`, only when it brought nothing in every task where it was convened and the profile lists its boards |
| A reservation | The same wording, ignoring dates, the number of a blocker and the name of a follow-up task. The lines about skipped and failed rules are counted as rules, and the board verdicts, which the closing keeps only as a record, are not counted | `profile remove check 'COMMAND'` for a check command that could not run |

A command is written only when the profile accepts it as of today and it does what the finding asks: a pack that the profile lists and a pattern also brings is stopped by neither command alone, so none is written.
A command that stops a pack names the other packs that leave with it.
Every command is written and none is run; `--by INITIALS` is the person's to fill in, and a command that lowers a protection stays the person's decision at an interactive terminal, as when they type it unprompted ([profile commands](../patterns.md)).

The `--reason` comes filled in with what comes back and the tasks behind it, for example `--reason 'task retro: rule:typescript/strict-type-checking failed in 3 tasks (a2, a3, a4)'`, followed for a rule set aside by the reason the tasks recorded.
Once the person runs the command, the profile history (`changes` in `.openguildkit/project.json`) keeps that reason, so the change stays linked to the retrospective.
The person can edit it before running the command.
It is one line of at most 240 characters: the recorded reason is cut first, then the wording of the finding; past five tasks it names the first five and how many more.
It holds no field that names a person, only the task IDs and what the records already say.
The reason is quoted like the rest of the command: single quotes for a POSIX shell, and the same with a doubled single quote inside for PowerShell on Windows.
`--json` gives it in `proposed_reason` next to `command` (`null` when there is no command), and keeps `tasks` and the other keys as they were.

A recurrence is a question for the team, not a verdict: a rule skipped three times for one reason may be a rule the project does not need, or a habit worth changing.
The declines already in the profile are not counted, since they stand for every task consulted after them.

If a task is unknown, or not closed, `task retro ID` says so with the status and the command that moves it on, as every command does.
An exported record written before its task was completed has no closing to read, and `--all` without any closed task says there is nothing to count.

## A draft project rule

A reservation that comes back has no profile command: no setting of the profile keeps it from coming back, a rule of the project might.
`task retro --all --draft-rules FOLDER` also writes a project rule pack in draft, one rule per reservation that comes back, for a person to write (RFC #447).
Without the option the retrospective stays read-only.

- The file is `FOLDER/retro-draft-YYYY-MM-DD.json`, in the [catalog format](../catalog-format.md#packs): the catalog reads it as it is once copied.
  `FOLDER` is a path inside the project and outside `.openguildkit/`, so no catalog reads the draft where it is written, and an existing file is never overwritten.
- It is marked draft: its description starts with `DRAFT written by openguildkit task retro`, and each rule's instruction and verification start with `TODO:`, with the reservation as recorded and the tasks behind it.
  The draft says what came back, never what to do about it: that is for the person to write.
- It is never active on its own.
  A profile refuses a pack whose description is still the draft's, whether `profile add pack` adds it or a pattern brings it: the person writes each rule, replaces each `TODO:` and the description, copies the file to `.openguildkit/catalog/packs/`, then runs `openguildkit profile add pack ID --by INITIALS --reason WHY`.
- A rule set aside or failed has its profile command instead, and a board that brought nothing is a question for the team, not a rule: neither is drafted.
  When no reservation comes back, nothing is written and the output says so.
  `--json` gives the file, the pack ID and its number of rules under `draft`.

## Every month in CI

[`integrations/github/openguildkit-retro.yml`](../../integrations/github/openguildkit-retro.yml) runs `task retro --all --json` on the first day of each month, on GitHub Actions.
Copy it to `.github/workflows/` and set the release your project uses.
The retrospective reads the exported records too, so it counts the closed tasks whose decision the project commits in `.openguildkit/decisions/` even when `.openguildkit/tasks/` is not committed.

- When nothing comes back, it opens no issue.
- When a finding comes back, it opens one issue, `OpenGuildKit retrospective YYYY-MM`, with each finding, its number of tasks and the profile command a person could type, never run.
- A retrospective issue still open from an earlier month is updated and renamed instead, so there is one at a time.
  Once a person closes the issue of the month, a second run that month opens no other.

The job asks for `contents: read` and `issues: write` and nothing else: it writes nothing to the repository.
What people typed in a reason or a reservation reaches the issue, with each `@` broken so that it notifies nobody.
Add `--min N` to the command in the template to change the minimum.
