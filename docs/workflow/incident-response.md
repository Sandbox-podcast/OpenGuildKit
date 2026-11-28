# Incident response

For: an administrator or a tech lead who answers an incident.
A part of the [task workflow](../workflow.md).

When a model is compromised, a malicious MCP server is found or a secret leaks, two options of the profile stop what agents can do.
Both are off in every project: a project that sets neither behaves as before, and its task records, approvals and exports are read as they were.
Both only restrict, so they are set without a terminal, with `--by` and `--reason` like every profile change.
Lifting or loosening one weakens a protection: a person at an interactive terminal types the command and its value to confirm it, as for `light-paths` or `approval signed`.

```bash
openguildkit profile set freeze on --by CM --reason "Model compromised, 2026-11-27"
openguildkit profile set freeze off --by CM --reason "All clear"          # a person, at a terminal
openguildkit profile set max-approval-age 30 --by CM --reason "Reconsult monthly"
openguildkit profile set max-approval-age 60 --by CM --reason "Back to two months"   # looser: a person, at a terminal
```

- **Freeze.** `freeze on` writes `frozen` (`by`, `on`, `reason`) in the profile and in its history.
  The edit hook then refuses every edit inside the project, even under an approved task and in `observe`, with `Edit refused: the project is frozen by CM since 2026-11-27: REASON`, and each request reminds the agent.
  The approvals stand: `guard --json` still lists them in `covered_by`, and the freeze voids none.
  `guard --ci` reads the freeze at the base revision, as it reads the mode, so a pull request cannot lift it for itself: it fails every change (`guard-frozen`, whatever the guard mode) except the one that does nothing but lift the freeze, which touches only the profile, the catalog lock and decision records, drops `frozen` and adds the entries of `profile set freeze off` to the history.
  That change is then judged like any other and needs its decision.
  A freeze needs the guard on: with `"guard": "off"` the hook does not run, and the command says so.
  The freeze does not reach what runs outside the guard: an agent with a shell, a host that does not run the hooks, a change made through Cursor or Copilot before CI.
- **Longest age of an approval.** `approval.max_age_days` (1 to 366) ends the cover of an approval older than that:
  `guard --json` no longer lists it in `covered_by`, the edit hook refuses the edits it covered, and `task list`, `check` (`decision-expired`), `handoff`, `verify`, `result`, `complete` and `export` name the approval and the command that consults the task again, the same as for an approval given under earlier rules.
  A completed task is history and is not reached.
  An approval whose date cannot be read does not cover.
  `guard --ci` does not date records: it judges the change a pull request brings.
  The stale flag after 14 days stays a message for a project without a limit.
- **What is not here.** A freeze or a limit for the whole organization, pushed to every repository by a policy file or a workstation configuration, needs the organization policy of the same audit and is not part of this option.
