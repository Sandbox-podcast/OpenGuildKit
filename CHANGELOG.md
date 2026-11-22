# Changelog

What changes for a team that uses OpenGuildKit, version by version. Versions follow Semantic Versioning for the CLI; packs carry their own versions ([catalog format](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/catalog-format.md)). A release copies its section into the GitHub release notes ([release steps](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/GOVERNANCE.md#releases)).

## 0.17.0

Changes since 0.16.1, the pre-release of 20 November 2026. The wheel now ships the web interface, and no command of 0.16.1 was removed.

### Install

- Install the wheel of the release with `pipx install` or `uv tool install`: both put `openguildkit` on the PATH, which the hooks of the board guard need. OpenGuildKit is not on PyPI ([install guide](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/install.md)).
- The release builds the web interface into the wheel and refuses a wheel without it. The workflow templates for the guard, the market watch and the dependency watch install the 0.17.0 wheel, checked against its hash, instead of the `main` branch.

### Setup and profile

- `openguildkit init` asks each norm that the sector, the roles and personal data imply, with the reason it is proposed, then the tools of the company, the agent host and the board guard. New projects start with the guard in `observe`. `openguildkit detect` proposes the components and versions of an existing repository, and `openguildkit preview` shows the rule packs before they are written.
- `openguildkit profile adopt`, `decline`, `add`, `remove` and `set` change the profile after setup: they record who, when and why, and rewrite `AGENTS.md`. A change that weakens a protection needs a person at a terminal.
- `.openguildkit/catalog.lock.json` pins the catalog records a project uses. `openguildkit update` shows what a newer catalog changes and `openguildkit update --apply` adopts it.
- `openguildkit host check` and `openguildkit host apply` show and install the rules the agent host can enforce, with the hooks that bring the board to the agent before every change. `openguildkit integrations` installs the agent skill and the board, market analyst and dependency watch subagents of the same version.

### Tasks

- Each brain reviews in its own pass: `openguildkit task pass` gives one brain what it needs, `task submit` records its review and refuses a malformed one with all its problems, `task progress` shows which passes are done. The brains answer each other's objections with `task deliberate` and `task respond`.
- Rule relevance: `task result --template` and `task checks` ask only the rules that concern the task, and list the others as not concerned, with the reason.
- Blockers are cleared with evidence (`task clear`) or waived within the project's policy (`task waive`) before the approval. An approval is sealed to what was approved; a project can require signed approvals (`task decision-payload`).
- Closing statuses: `task complete` closes a task as `done`, or as `done-with-reservations` with the points left open, the most serious first.
- Decision records: `task export` writes a sealed record to `.openguildkit/decisions/`, and `openguildkit guard --ci` checks in a pull request that an approved decision covers the changes.
- `openguildkit task list` lists the project's tasks with their status and next open point. `task authorize` records a person's decision on an external action outside the authorized scope.

### Web interface

- `openguildkit ui` opens the project in the browser, on 127.0.0.1: tasks by state, the board consultation and each brain's pass, blockers, checks and results, alerts, market dossiers, deliverables, tools, documentation exports and shares. Every action runs a CLI command; approvals and the other decisions of a person stay in the terminal, and the page shows the command to type.

### Tools, alerts, market and deliverables

- Tool registry and mocks: `openguildkit tools` lists the tools of a company stack with their MCP servers, connects them (`tools plan`, `tools apply`) and rehearses a task with mock servers (`tools apply --mock`, `tools call`, `tools scenario`).
- Dependency alerts: `openguildkit alerts` imports scanner reports into a register, links alerts to tasks, and asks a person to accept or set the severity of an alert. A confirmed critical alert linked to a task blocks its approval.
- Market dossiers: `openguildkit market` keeps a dossier of competitors and lists the sources due for review; the market watch template opens an issue for each.
- Storybook: `openguildkit storybook` composes the company Storybook, records its stories and extracts a design system from an existing application.
- Documentation export: `openguildkit docs export` writes the documentation of completed tasks for Documentalist, and `openguildkit docs share` keeps a register of who it is shared with.
- `openguildkit deliverable` turns an approved task into a business deliverable with its checks.

### Catalog

- A brain for each discipline of a software publisher, each with specialist lenses, the evidence it asks for, its methods and references. A project adds or completes a brain in `.openguildkit/catalog/boards/` (`openguildkit brains --new ID`).
- Stack patterns for mainstream web, mobile and cloud stacks; rule packs with machine checks and named evidence; every source carries the date it was last checked.

## 0.16.1 and earlier

See the [GitHub releases](https://github.com/Sandbox-podcast/OpenGuildKit/releases).
