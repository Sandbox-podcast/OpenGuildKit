# 5. Hand off

For: the agent that implements an approved task.
Step 5 of the [task workflow](../workflow.md).

```bash
openguildkit task handoff request-status
```

The handoff exists only for approved tasks whose approval still holds: its seal matches the record and its rules are the current ones.
Otherwise it fails with the same message as `task list`, `task show`, `check`, `task export` and `guard --ci`, which names what changed (`pack gdpr added`, `rule secure-sdlc/threat-model changed`) and the next command: `task consult ID` reopens the task under the current rules, keeping the earlier approval in `rounds` with the reason, or `task new "BRIEF" --follows ID` opens a linked task.
It contains the approval (who and why), the approved scope snapshot, the rules to apply and the board review.
The rules to apply are the ones `task checks` asks, pack by pack, then one line names the packs and rules that do not concern the task, with how many of each; `task checks ID` gives each reason.
The handoff of a decision task has no rules to apply.
The agent implements that scope, runs the project checks and brings any scope change back to the person.

On a completed task, `task handoff` shows the same handoff for reference, headed with the task's status and saying that nothing is left to implement.
On a task already decided, `task decide` says so, with the status, who decided and when, and the one command that fits next: `task handoff` for an approved task, `task new "BRIEF" --follows ID` for a completed one, `task consult ID` after a change request.
Once the review is recorded, `task progress` shows each board as `done (in review)`.

A task answered with `kind: decision` asks for a recommendation.
Its handoff contains the approved decision, scope and review.
`task result --template` lists its acceptance criterion when the answers name an outcome.
The approval already records the process evidence, so the decision has no implementation checks to fill in.
After recording the criterion, run `task complete`.
When the answers give no outcome, you can complete the task directly.

If tracked project files differ from the approved Git revision, the CLI asks for the delivery revision or pull request.
It ignores the exported decision records.
`task complete` gives the `task new --follows` command so that applying the decision gets its own review and approval.

## Code owners of the touched paths

When the project has a CODEOWNERS file, the decision brief of `task challenge` and the handoff of `task handoff` add one line naming who owns what the task touches, so that the person knows whom to tell or ask before deciding (#437):

```text
Code owners, read from .github/CODEOWNERS (shown here, never recorded): api/ @team-api; web/ no owner declared.
```

- **What the task touches.** Its short-lane paths (a glob reads as the folder before its first wildcard), the folders of the components its answers name, and the project paths its brief and answers name that exist.
  None of them: the line reads `whole project`.
  A folder shows the rule that covers its files in general; a rule for some files inside it, such as `*.sql` or a sub-folder, is not shown.
  Eight paths at most, then a count.
- **GitHub's rules,** as its page [About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners) states them, read on 2026-11-26 (the page shows no date of its own): the file is `.github/CODEOWNERS`, `CODEOWNERS` or `docs/CODEOWNERS`, searched in that order, and only the first one found is read;
  patterns follow gitignore, the last matching pattern wins, a pattern without owners leaves its paths without one, paths are case sensitive, and a file of 3 MB or more is not loaded.
  The page says `!` negation and `[ ]` ranges do not work: OpenGuildKit skips those lines and names them in the line.
  How GitHub itself treats such a line beyond "does not work" is not verified.
- **Shown, never recorded.** Owners are often people's names or emails ([personal data](../personal-data.md)).
  Whether a committed record may keep them is an open decision (Q9 of the benchmark), so they stay out of the task record, the exported decision record and every file the CLI writes: they are read again from CODEOWNERS at each display.
- **What does not change.** A project without CODEOWNERS sees nothing more.
