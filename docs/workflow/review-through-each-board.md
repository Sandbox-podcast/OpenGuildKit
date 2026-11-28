# 3. Review through each board

For: the agent that runs the board passes and writes the review.
Step 3 of the [task workflow](../workflow.md).

`task template ID` prints the review skeleton with the `consultation_id` and one entry per selected board.
Keep that ID to tie the review to the current scope.
Each [brain](../brains.md) has a set of specialist lenses.
The agent records their separate findings, challenges the proposed change, then reconciles the boards and preserves disagreements in the summary.
The [request status example](../../examples/request-status/review.json) shows a complete review.

## One pass per board

The host agent can run each board as a separate pass, with a subagent or one after the other:

```bash
openguildkit task pass ID security --mode subagent    # prints the task, the security brief, its rules and the entry to return
openguildkit task brief ID --board security          # prints the same pass again, without starting it
openguildkit task submit ID --file security.json     # records that board's entry
openguildkit task progress ID                         # done, failed, started or missing, per board
openguildkit task review ID --summary "Where the boards agree and disagree, and the next step"
```

`task pass` gives each board, in this order: the task and its answers, with the components it touches and their paths; its own brief (questions, the lenses to fill with their focus, the evidence to inspect, the challenge and decision criteria); how to fill the entry and the entry to return; a reading list of five sources; then the rules of its own packs that concern the task.
Which packs concern the task is decided as for the results (`relevance.py`): from how each pack reached the project and from the task's answers, not from shared words.
The pass, the handoff and `task checks` decide rule by rule with the same function (`relevance.judge_rules`): a pass prints only the rules the closing will ask, and a pack in force that a board's packs depend on, such as `incident-notification` for `gdpr`, is printed with them.
They are printed most specific first (the stack of the components the task names in its answers or in a path of its brief, the other stacks, regulations, the board's methods, then the baseline), as long as the pass stays under 10 KB;
the packs that do not fit are named, and `task brief ID --pack PACK` prints one pack in full: each rule with how it is verified, the check `task verify` runs and the evidence the result asks, then the sources of the pack.
The board's packs and rules that do not concern the task are named in the pass with their reason, grouped, so that the pass needs no other command to say why.
A decision task delivers no implementation: its passes ask no rule, and `task brief ID --pack PACK` still prints a pack's rules when a board weighs an option against them.
Nothing from the other boards is printed, and the shared project scope is named by one line with the command that prints it.
What each lens verifies, the whole reading list and the board's methods: `openguildkit brains --id BOARD`.
A test keeps every pass under 10 KB and the consultation under 30 KB, on the bundled example and on a monorepo with every role.
Running `task pass` again for a pass already started prints it again without counting an attempt.
On a pass whose entry is already submitted, `task pass` only prints it, says so and keeps the entry; `task pass ID BOARD --again` redoes it on purpose and counts an attempt, as does starting a failed pass again.
`task submit` refuses an entry whose pass was not started on the current consultation.
It validates the entry against the template and reports every problem at once, each with its key path (such as `marketing.challenge.verdict`), the value received and the accepted values; an invalid entry is recorded as a failed pass with the reasons, and sending the corrected file again with `task submit` records it.
A recorded entry prints `done`, then, on standard error, how many passes are left and the command that comes next (`task review --summary` once none is left).
A pass that was started and never submitted shows as `started`: treat it as interrupted; `task list` names it apart from the passes still to run.
Run `task pass` again for that board only; the other boards keep their entries.
When one agent runs the passes one after the other (`--mode sequential`, the default), the first pass of the consultation prints how to fill an entry and the shapes of an evidence item and a blocker, and each later pass names that first pass instead of printing them again, about 1.5 KB less each; it prints the same rules.
`task brief ID --board BOARD` always prints a pass whole, and each pass run with `--mode subagent` is whole, since a subagent reads only its own.
Once every board is done, `task review --summary` assembles the review and records whether the passes ran as subagents, in sequence or both (`execution`).
A new consultation starts the passes again.
Passes can run at the same time: each `task pass` and `task submit` waits its turn for the project lock, up to 10 seconds by default.
Set `OPENGUILDKIT_LOCK_TIMEOUT` to another number of seconds (0 to 3600) when a slow disk or many boards need longer.
Writing the whole review in one file with `task review --file` still works.

Rules enforced by `task review ID --file review.json`:

- `consultation_id` must match the current consultation.
- `summary` and every `recommendation` must contain text.
- There must be exactly one entry per selected board, and no other board.
- `open_questions` is a list of non-empty strings and `evidence` a list of evidence items in the shape of the template's `evidence_item` (both can be empty lists).
  A `project-file` or `test` item must name a file or folder of the project, and a `date` must be a real day, not in the future.
- The refusal names the file and lists the problems of every board at once.
- For a brain, each specialist needs exactly one finding with an evidence basis (`observed`, `assumption` or `missing`).
  An observed finding cites `evidence_refs`: positions in that entry's own `evidence` list, counted from 1, so `[1, 3]` cites its first and third items.
  A board records its verdict (`proceed`, `revise`, `block` or `insufficient-evidence`), confidence (`low`, `medium` or `high`), alternative, failure mode, verification and blockers.
  The template shows the accepted values of each choice in place of the value to write.
- A lens of the catalog can name the surfaces it applies to (`"applies_to": ["customer"]`).
  When none of them is among the task's surfaces, the board's pass lists the lens as not concerned and the entry does not ask for it.
  A task whose surface is `unsure` or `other` keeps every lens.
  A lens can also name the concerns it needs (`"applies_to_concerns": ["money"]`, among `money`, `ai`, `people-decisions` and `credentials`): the pay lens of HR is not asked of an onboarding checklist whose concerns are `none`.
  A missing, `unsure` or `other` answer keeps the lens.

A well-formed review is recorded, but the CLI adds `warnings` to it when the boards do not look independent: two boards with the same recommendation word for word, the same finding in several lenses, or a board whose every finding is an assumption or missing.
The decision brief and the approval prompt list them.

Run `openguildkit task challenge ID` to show how the verdicts differ, what each board recommends and which checks can change the decision.
It starts with plain lines: the count of verdicts and a warning when boards say revise, block or insufficient-evidence, the review warnings, the boards added or removed with their reason, the open points of the scoping, the objections never deliberated or, after `task respond`, each objection once as resolved or left open with the rule that resolves one,
the verdicts that differ without any objection between them and why, the boards whose advice is addressed to no other board, and each blocker with how it was resolved and the evidence given.
The agent shows this brief to the person before implementation.
