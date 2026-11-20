# Example: claim tracking for an insurance portal

A fictional insurer's customer portal adds online claim tracking. This folder holds every input of the flow, so you can replay it and get the same consultation. The end-to-end tests in `tests/e2e/` and the CI use these exact files.

| File | Used by |
|---|---|
| `profile.json` | `init --answers` (sector `insurance`, Python and React stack) |
| `brief.md` | `task new --file` |
| `answers.json` | `task consult --answers` (feature, customer-facing, personal data, local research) |
| `review.json` | `task review --file` (one recommendation per selected board) |
| `replay.py` | Runs the whole flow in an empty folder |

## Replay

From the repository root:

```bash
python examples/insurance-claims/replay.py
```

The script creates a temporary project, runs every step and prints the boards it selected. In a terminal, it asks your name, lets you approve, and prints the handoff. Without a terminal, it stops before the decision and prints the two commands to run yourself.

`review.json` has no `consultation_id`, because a new one is generated at every consultation. The script copies it from `task template` before recording the review. To replay by hand, do the same: run `openguildkit task template claim-status`, add its `consultation_id` to a copy of `review.json`, then run `task review` with that copy.

## What to look at

After `init`, the project has `AGENTS.md` with the insurance context, the workflow and packs from the matched stack patterns. The Python, FastAPI and PostgreSQL combination adds API and database checks. `CLAUDE.md` imports the generated instructions.

`task consult` selects six boards and says why:

| Board | Reason |
|---|---|
| product | Feature scope and outcome; customer outcome |
| engineering | Implementation and integration |
| qa | Acceptance and regression checks |
| design | Customer experience |
| marketing | Customer expectations and market evidence |
| security | Personal data access |

`review.json` records findings from 24 specialist lenses. The product board supports a read-only scope, security requests further access checks, and marketing reports insufficient evidence for a competitor comparison. The replay prints the decision brief so you can compare verdicts and see what would change them.

`task decide --approve` asks you to type `claim-status` in the terminal. Only then does `task handoff` print the approved scope.
