# Claude Code, 2026-11-21: a host without subagents, a disagreement and the whole path

Host: a Claude Code agent session (Sonnet model) that could not start subagents, so it reviewed the boards one after the other, as the skill allows. Project: a copy of `project/` with `project/research-notes.md`, `host` set to `claude-code` and `boards` limited to `product` and `security`; research policy `local-only`. OpenGuildKit from `main` on the day of the run, installed with `openguildkit integrations --host claude-code` and `openguildkit host apply`. The person's part (answers, change request, approval, review of the result) was played by the maintainer who ran the test, in a separate terminal.

The agent session took its permissions from the session that started it, not from the project's `.claude/settings.json`: the deny rules written by `host apply` were not exercised.

The request (task 3 of `tasks.json`, the share link) was given in plain words, with the instruction to have Product and Security review it separately.

| Step | Observed |
|---|---|
| Scoping | The agent read `AGENTS.md`, `CLAUDE.md` and the skill, ran `task new` and `task questions`, proposed the four scoping answers and asked the person to confirm them, the affected people, the outcome and the constraints. It stopped and changed nothing. A task ID in capitals was refused with a clear message and it chose a valid one. |
| First consultation | `task route`, `task consult`, then `task pass ... --mode sequential` and `task submit` for each board. Both entries were accepted at the first submission; `task review --summary` recorded `execution: sequential`. |
| First verdicts | Product: `revise`. Security: `block`, with one blocker (the owner's email shown to an unauthenticated reader, a link that never expires and cannot be revoked) naming the data owner and what would clear it. |
| `task deliberate` | No objection was generated: at the time, an objection was raised only against a board that would proceed. A board that blocks now also objects to a board that asks to revise (issue 129). |
| The person asks for changes | `task decide --request-changes` in the person's terminal: drop the email, random token, 7-day expiry, revocation. The first round was archived. |
| Second consultation | The agent updated the answers and consulted both boards again. Product: `proceed`. Security: `revise`, no blocker, with the tests it wants before release. |
| Disagreement | `task deliberate` listed the objection `security-to-product`. The agent recorded both answers with `task respond`: Security maintains, Product amends and accepts Security's tests as conditions. One submission was refused ("position must be maintain, concede or amend") and corrected. The objection stayed open in the decision brief, with the decision the person had to take. |
| Decision | The agent gave the `task decide` commands and said it would not run the approval. The person approved in a terminal, with Security's tests as conditions. |
| Implementation | `task handoff`, then the share link in `project/app.py` with ten new tests (token from `secrets`, only its hash stored, same answer for unknown, expired and revoked tokens, exactly three fields returned). |
| Results | `task verify` ran the project check (11 tests, passed). The agent asked the person before recording the rule checks, recorded the reviewer's decision as the evidence of `verify-before-handoff`, and would not mark a criterion as met that the approved scope did not cover: `task complete` refused ("Criterion not met"), the person chose to move those points to a new task, and the agent recorded the result again without them. |
| Completion | `task complete` printed `done`, `task export` wrote `.openguildkit/decisions/share-link.json`, and the agent opened `share-link-followup` for the remaining points. |

## What this run showed about OpenGuildKit

- The format of the result file took three attempts (an empty file, statuses `passed` instead of `met`, then the accepted file). `task result ID --template` now prints a file to fill.
- The agent linked the follow-up task by naming the first one in its brief: it did not find `task new --follows`. The handoff, the completion message and the skill now give that command (issue 99).
- A blocking verdict facing a request for revision produced no confrontation. Fixed since (issue 129).

## Not covered by this run

- Board passes given to subagents: see the report of 2026-11-20.
- The deny rules and hooks of `.claude/settings.json`, which a Claude Code session opened in the project would load.
