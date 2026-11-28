# Dependency alerts

For: the agent and the person who handle a dependency alert.
A part of the [task workflow](../workflow.md).

The CLI does not scan dependencies.
It reads the JSON report of a scanner the project already uses into the project's alert register, `.openguildkit/alerts.json`, and links the report's alerts to the task:

```bash
npm audit --json > npm-audit.json          # or: pip-audit -f json, osv-scanner --format json, gh api --paginate (see docs/alerts.md)
openguildkit task alerts ID --import npm-audit.json
openguildkit alerts set npm:semver:ghsa-c2qf-rxjj-qqgw --status dismissed --by AM --reason "Only used at build time"
openguildkit task alerts ID
```

The register keeps one entry per package and advisory across scanners, with a status: `open`, `confirmed`, `dismissed` with a reason, or `resolved` once the scanner's next report no longer lists it.
`task consult` carries the task's open and confirmed alerts to the boards.
A confirmed critical alert blocks the task's approval and completion until it is resolved or a person records why it is accepted.
A fix is a change like any other: open a task for it, for example with `--follows`.
[Dependency alerts](../alerts.md) describes the register, the `dependency-watch` agent and the scheduled watch.
