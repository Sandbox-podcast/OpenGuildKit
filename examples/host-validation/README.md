# Host validation scenario

A fictional support portal (`project/`, synthetic data only) and three tasks (`tasks.json`) to check that an agent host can run the whole OpenGuildKit flow: board passes with evidence, a disagreement between boards, a board without enough evidence, a person's decision and the results of the work.

| Task | What it exercises |
|---|---|
| `request-export` (feature, personal data) | Board passes with evidence on the project files, objections between boards, a blocker to clear, approval, `task verify`, `task result`, `task complete` |
| `pricing-comparison` (decision, local research, no market data) | A board added by the requester, `insufficient-evidence` verdicts, the decision brief |
| `request-share-link` (feature, personal data, with `project/research-notes.md`) | Product evidence that pulls one way and a security concern that pulls the other: a blocker, a change request, a second round, an objection and its answers |

## A blocker against a request to revise

In a run with an agent host, Product answered `revise` and Security `block` with an open blocker on `request-export`. `task deliberate` used to list no objection, because only a board that proceeds was challenged, and the person received two opinions that never met. Now Security objects to Product on the point of its blocker (`security-to-product`, from `block` to `revise`), and Product answers on that point with `maintain`, `concede` or `amend`. When you see these verdicts in a host, check that `task deliberate` lists that objection, that both boards answer it, and that `task challenge` shows the agreement or the disagreement left open. When verdicts differ without any objection between them (`revise` and `insufficient-evidence`, as in `pricing-comparison`), the decision brief says so and why.

## Rehearse with the CLI

```bash
python examples/host-validation/rehearse.py --report report.json
```

The rehearsal plays a host without subagents: it runs `task pass ... --mode sequential` for each board with prepared answers, records the deliberation and the blocker, approves through a pseudo-terminal on Linux and macOS (as the person deciding would), runs the project check and completes the task. CI runs it (`tests/e2e/test_host_rehearsal.py`).

## Run it in a host

1. Copy `project/` to an empty folder, install OpenGuildKit and the agent files (`openguildkit integrations --host claude-code` or `--host codex`), and run `openguildkit init --answers profile.json` there, with `"host"` set to the host you test. Run `openguildkit host apply`.
2. Ask the agent, in its own words, for each task's brief from `tasks.json`. Do not tell it the commands: the skill and `AGENTS.md` must lead it.
3. Answer its questions with the `answers` in `tasks.json`. Check that it runs `task route` and one `task pass` per board, as subagents when the host has them, and that it stops before the decision.
4. Take the decision yourself in your terminal, then ask the agent to implement and report. Check that it runs `task verify`, `task result` and `task complete`.
5. Fill in a report like the ones in `reports/`, with what you observed: commands run, entries refused and corrected, `execution` recorded, objections, the decision brief, the final state. Use synthetic data only and keep keys and private details out of the report.

## Reports

- [Claude Code, 2026-11-20](reports/claude-code-2026-11-20.md): board passes as subagents, up to the decision brief.
- [Claude Code, 2026-11-21](reports/claude-code-2026-11-21.md): a host without subagents, a disagreement between two boards, a change request, the decision, the implementation and the results, to `done`.
- [Codex, 2026-11-21](reports/codex-2026-11-21.md): the export task from the request to `done` with board passes as subagents, the case without evidence, and a case with blockers.

Not yet observed in a live host: the controls that `host apply` writes (deny rules, hooks, Codex rules), which need a session opened in a trusted project.
