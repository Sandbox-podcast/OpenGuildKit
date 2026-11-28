# Dependencies between tasks

For: the agent that opens a task that depends on another.
A part of the [task workflow](../workflow.md).

When a decision is split into several tasks, a task can wait for others:

```bash
openguildkit task new "Show the status page" --id portal --after api-schema --after auth-flow
```

`task new` prints the ID, then says on standard error what the task waits for and the status of each: `Waits for api-schema (approved) and auth-flow (draft).` It refuses an unknown ID (with the closest one), the task itself and a cycle, which only a task deleted and opened again under the same ID can close.
The record keeps the IDs under `after`; a task without `--after` is written as before, and `--follows`, the link to an earlier decision, is unchanged.

`task list` adds a line `waits for: auth-flow (draft)` under each task held back, and `--json` gives each such row `after` and `waiting_for`, the tasks not done yet with their status.
A task is done when its status is `done` or `done-with-reservations`; one whose record is gone still holds the task back, as `unknown`.
`task list --ready` lists only the open tasks nothing holds back.
The handoff of an approved task that still waits for another starts with `Waits for auth-flow (draft): deliver it first; the order stays the person's decision.`: it blocks nothing.
In the web interface, the card of a task held back says how many tasks it waits for, and its sheet lists them with their status.
