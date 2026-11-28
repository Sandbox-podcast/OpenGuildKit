# Evidence changed after it was accepted

For: the person who accepted evidence, and the agent that reports a change to it.
A part of the [task workflow](../workflow.md).

`task clear` records a fingerprint of the evidence that clears a blocker, under `fingerprint` in the clearance: `sha256:` and the SHA-256 of a file's bytes, or of the list of a folder's files (their names, not their content, Git's folder and `.openguildkit/` left out), or `external` for an https link, which no one here can check.
In a project with signed approvals the fingerprint is part of the payload the person signs, so a clearance signed before the file changed no longer verifies.
`task result` records the same fingerprint for each named evidence it accepts as `passed` with a project path.

When a fingerprinted file changes or disappears afterwards:

- `task blockers` says the state of each clearance's evidence: `fingerprint: unchanged since it was cleared`, `changed since it was cleared`, `the evidence is missing since it was cleared`, or `external link, cannot be checked`; `--json` adds `evidence_state`;
- `task list` adds a line under the task, such as `changed evidence: docs/aipd.md changed since blocker security:1 was cleared (cleared on 2026-11-20 by CM)`, and `--json` gives the task `evidence_changed`;
- `task complete` keeps it as an open point of the group "Evidence changed since it was accepted": the task closes as `done-with-reservations`, and `task show ID --closing` prints it again.
  A file changed and then restored to the bytes that were accepted is no longer a point;
- `task export` carries `evidence_states`, each evidence with what it was for and its state at the export, and the fingerprint in each clearance.

Behaviour retained until a decision is taken (question Q2 of the plan: should a changed evidence fail `guard --ci` in `enforce`?): a changed evidence is an open point of the closing and a line of `task list`, and `guard --ci` does not read it, in `observe` or in `enforce`.
A clearance recorded before fingerprints reads without error: `task blockers` shows it with `no fingerprint: cleared before OpenGuildKit recorded one`, it is never an open point, and a record that has none exports as before.
