# Claude Code, 2026-11-20

Host: Claude Code desktop app on macOS. Board passes ran as subagents (one general-purpose subagent per board, Sonnet model), each given only the output of `openguildkit task pass request-export BOARD --mode subagent`. Project: a copy of `project/` with `boards` limited to `product` and `security` to keep the run short; research policy `local-only`. OpenGuildKit from the `feat/host-scenario` branch.

## Observed

| Step | Result |
|---|---|
| `task consult` | Consultation created for `product` and `security`. |
| `task pass` × 2 | Each subagent received the scope, its own brief and its entry template, nothing from the other board. `task progress` showed both `started (mode subagent)`. |
| Board work | Each subagent read `app.py` and `test_app.py`, did no web search, and returned a JSON entry with four specialist findings, structured evidence (`project-file`, `test`, `requester`) and a verdict. Both answered `revise` with medium confidence. Product asked to confirm demand and the exported fields; Security asked to take identity from the session, neutralise CSV formula injection and add denied-access tests. |
| `task submit` × 2 | Both entries were accepted at the first submission. |
| `task review --summary` | Review assembled with `execution: subagents`. |
| `task deliberate` | No objection: no board recommended proceeding. |
| `task challenge` | Verdicts `revise: product, security`, two decisive evidence items per board, open questions listed. |
| Decision | Not taken: the agent stops for the person's decision, as the skill requires. The approval, results and completion steps are covered by the CLI rehearsal. |

## Not covered by this run

- A disagreement between boards, insufficient evidence and the steps after the decision: covered by `rehearse.py`, not by a live host run.
- Codex: not run.
