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
- `init` proposes the European Accessibility Act to e-commerce and financial services, and a `software-publisher` sector proposes ISO 27001 and the Cyber Resilience Act, each with the condition that makes it apply.
- New profile commands for the protections: `profile set approval local|signed`, `profile set waivers`, `profile set ask-every-rule`, `profile add|remove required-board|required-rule`. Only a change of rules, checks or boards voids an approval: a new tool or convention keeps them, and the commands name the approvals a change voids before writing it.
- Signed approvals are verified against the signers file as Git holds it at HEAD, and `host apply` keeps the agent away from that file, the alert register and the project catalog. In `enforce`, `host apply` also writes `"disableAllHooks": false`, and it reports the approval rule as partial, which it is.

### Tasks

- Each brain reviews in its own pass: `openguildkit task pass` gives one brain what it needs, `task submit` records its review and refuses a malformed one with all its problems, `task progress` shows which passes are done. The brains answer each other's objections with `task deliberate` and `task respond`.
- Rule relevance: `task result --template` and `task checks` ask only the rules that concern the task, and list the others as not concerned, with the reason.
- Blockers are cleared with evidence (`task clear`) or waived within the project's policy (`task waive`) before the approval. An approval is sealed to what was approved; a project can require signed approvals (`task decision-payload`).
- Closing statuses: `task complete` closes a task as `done`, or as `done-with-reservations` with the points left open, the most serious first.
- Decision records: `task export` writes a sealed record to `.openguildkit/decisions/`, and `openguildkit guard --ci` checks in a pull request that an approved decision covers the changes.
- `openguildkit task list` lists the project's tasks with their status and next open point. `task authorize` records a person's decision on an external action outside the authorized scope.
- `task revoke ID --by NAME --reason WHY` withdraws an approval, at a terminal only; the guard stops counting it. After a rebase or a change of rules, every command gives the same reason, and `task consult` reopens the task under the same ID and keeps the passes of the boards whose brief did not change.
- A new consultation needs the `concerns` answer (`money`, `ai`, `people-decisions`, `credentials`, `none` or `unsure`). Passes, handoff and closing judge each rule with one function; each pack has a subject, so DORA, ISO 27001, the DSA notice-and-action rules and pay transparency reach the tasks they apply to. A task limited to one component runs that component's checks and consults the board of its stack.
- Lighter along the way: `task questions --follow-ups`, `task show --closing`, passes after the first of a sequence that leave out the shared instructions, a refusal that names the command the task's state allows, and commands printed with quoting a shell gives back unchanged.
- The decision prompt and `task challenge` show the check commands, advice copied between boards, and a critical alert an import resolved. Exported records list the files of the change and each blocker with how it was cleared; `guard --ci` refuses a file no record covers and fails on local approvals with `--require-signed`.

### Web interface

- `openguildkit ui` opens the project in the browser, on 127.0.0.1: tasks by state, the board consultation and each brain's pass, blockers, checks and results, alerts, market dossiers, deliverables, tools, documentation exports and shares. Every action runs a CLI command; approvals and the other decisions of a person stay in the terminal, and the page shows the command to type.
- The page opens only from the address `openguildkit ui` prints (its key becomes a cookie). Each refusal carries a stable code and a French text; the setup page answers each proposed norm; a task takes several concerns; single-key shortcuts can be turned off; Pro mode uses the words of the glossary; lists hold 500 tasks.
- The wheel ships the project interface without the demo; `?demo=1` says how to start the demo from the source tree.

### Tools, alerts, market and deliverables

- Tool registry and mocks: `openguildkit tools` lists the tools of a company stack with their MCP servers, connects them (`tools plan`, `tools apply`) and rehearses a task with mock servers (`tools apply --mock`, `tools call`, `tools scenario`).
- Dependency alerts: `openguildkit alerts` imports scanner reports into a register, links alerts to tasks, and asks a person to accept or set the severity of an alert. A confirmed critical alert linked to a task blocks its approval.
- Market dossiers: `openguildkit market` keeps a dossier of competitors and lists the sources due for review; the market watch template opens an issue for each.
- Storybook: `openguildkit storybook` composes the company Storybook, records its stories and extracts a design system from an existing application.
- Documentation export: `openguildkit docs export` writes the documentation of completed tasks for Documentalist, and `openguildkit docs share` keeps a register of who it is shared with.
- Shares record the Documentalist space they open, which is the whole space; `--until` is a reminder, `share add` warns about a second share of the same space to the same person, and a local portal may use http.
- `alerts tasks --open` opens one task per confirmed alert, and the dependency watch template proposes the register in a pull request. A scanner report that analyzed nothing resolves no alert.
- The credential detector recognizes the tokens of the registry's tools, `Authorization` headers and `api_key=`-style settings. A project tool cannot take the name of a bundled one, and `check` and `task consult` name a bundled brain the project catalog replaces.
- `docs/personal-data.md` lists every name the tool records, where, why and how to replace it; examples now use initials for `--by`.
- `SOURCE_DATE_EPOCH` dates what exports write; share expiry, waiver length, approval age and market ages follow the real clock.
- `openguildkit deliverable` turns an approved task into a business deliverable with its checks.

### Catalog

- A brain for each discipline of a software publisher, each with specialist lenses, the evidence it asks for, its methods and references. A project adds or completes a brain in `.openguildkit/catalog/boards/` (`openguildkit brains --new ID`).
- Stack patterns for mainstream web, mobile and cloud stacks; rule packs with machine checks and named evidence; every source carries the date it was last checked.
- GDPR rules for the notice to people, consent to trackers and automated decisions (Art. 22); PCI DSS and ISO 27001 requirements a development team meets first; OWASP ASVS 5.0 requirements; the dates from which the AI Act and CRA rules apply; methods for QA (test strategy) and data (definitions), and a licence policy pack. 23 rules carry a machine check, and each regulation rule a person verifies says why.

### Speed

- Commands start without the web server; the edit hook starts without the CLI and reads no catalog with the guard off; one walk of the project tree serves detection, checks and Storybook; `check` reads each task once; routing compiles each trigger once.

### Upgrading from 0.16.1

- Run `openguildkit sync` and `openguildkit host apply` (new deny rules and hook setting), then `task export` again for decisions still in progress: records exported before list no files.
- Signed approvals need the project and its signers file committed in Git; a `decision.json` produced by 0.16.1 is generated again with `task decision-payload`.
- Answer files of a new consultation need `concerns`, and setup answers for e-commerce or financial services answer the European Accessibility Act norm.

## 0.16.1 and earlier

See the [GitHub releases](https://github.com/Sandbox-podcast/OpenGuildKit/releases).
