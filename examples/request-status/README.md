# Example: support request status

A team wants signed-in customers to see the status and next step of their support requests. The example describes a fictional portal and calls for synthetic accounts and requests in future checks. The end-to-end tests and CI replay these files.

| File | Used by |
|---|---|
| `profile.json` | `init --answers` (sector `general`, Python and React stack) |
| `brief.md` | `task new --file` |
| `answers.json` | `task consult --answers` (feature, customer-facing, personal data, local research) |
| `review.json` | `task review --file` (findings and recommendation per board) |
| `replay.py` | Runs the whole flow in an empty folder |

## Replay

From the repository root:

```bash
python examples/request-status/replay.py
```

The script creates a temporary project, runs every step and prints the boards it selected. In a terminal, it asks your name, lets you approve, and prints the handoff. Without a terminal, it stops before the decision and prints the two commands to run yourself.

The script copies the current `consultation_id` from `task template` before recording the review. To replay by hand, run `openguildkit task template request-status`, add its `consultation_id` to a copy of `review.json`, then run `task review` with that copy.

## What to look at

After `init`, `AGENTS.md` contains the workflow and packs from the matched stack patterns. The Python, FastAPI and PostgreSQL combination adds API and database checks. `CLAUDE.md` imports the generated instructions.

`task consult` selects six boards and says why:

| Board | Reason |
|---|---|
| product | Feature scope and customer outcome |
| engineering | Implementation and integration |
| qa | Acceptance and regression checks with synthetic test data |
| design | Customer experience |
| marketing | Customer expectations and market evidence |
| security | Personal data access |

`review.json` records findings from 24 specialist lenses. The product board supports a read-only scope, security requests further access checks, and marketing reports insufficient evidence for a competitor comparison. The replay prints the decision brief so you can compare verdicts and see what would change them.

`task decide --approve` asks you to type `request-status` in the terminal. Once approved, `task handoff` prints the scope.
