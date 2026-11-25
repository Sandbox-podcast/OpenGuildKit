# Changelog

What changes for a team that uses OpenGuildKit, version by version. Versions follow Semantic Versioning for the CLI; packs carry their own versions ([catalog format](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/catalog-format.md)). A release copies its section into the GitHub release notes ([release steps](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/GOVERNANCE.md#releases)).

## Unreleased

- New pack `agent-native-engineering` 1.0.0 and method pattern `agent-native-repository`, suggested to the engineering, devops and QA roles and preselected for none: bounded command output and instruction files, a machine-readable repository map, a targeted check, evidence written by tools, oversight files out of the agent's reach, a contract for each subagent and a measured cost per task. It concerns tasks on infrastructure and delivery, and the references `context-engineering`, `agent-execution-limits` and `agent-tool-permissions` now apply it.
- Features: `openguildkit features` lists 20 purposes (documentation portal, issue tracking, payroll, container registry...), each with a lead tool and its three best-known alternatives, and turns an option on or off in the profile with who and why. The web interface shows them in a new place, the Arsenal.
- New bundled tool IDs: `adp`, `apache-spark`, `apigee`, `appdynamics`, `auth0`, `discord`, `docker-hub`, `eclipse`, `gravitee`, `harbor`, `jetbrains`, `jfrog-artifactory`, `keycloak`, `kong`, `lens`, `mattermost`, `microsoft-entra-id`, `npm`, `okta`, `portainer`, `rancher`, `silae`, `sonatype-nexus`, `splunk`, `visual-studio`, `vscode`, `zoom`. Kibana is now an alias of Elastic. If a project catalog already defines one of these tools or names, rename its local entry and update the profile, or remove the project definition to use the bundled tool.
- The web interface refuses a command that names, in one of its options, a file the page itself will not read (`task new --file credentials.md`, `client_secret.json`): it answers `secret-file` instead of copying the file into the task.
- The web interface lists and opens the market dossiers and tasks whose ID contains `password` or `secret` (`password-manager`, `password-reset`), which it hid as if they were secret files.

## 0.17.0

- `openguildkit --project PATH mcp` provides read-only project metadata over stdio. See [Project MCP](docs/tools.md).

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
- Signed approvals are verified against the signers file as Git holds it at HEAD. An approval signed by an approver who has left since is verified against the approvers and signers file of the revision it was signed at, so it keeps holding while their new signatures are refused ([when an approver leaves](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/personal-data.md#when-an-approver-leaves)). That revision counts only once the merged branch (`origin/HEAD`, or else the upstream branch) contains it, so a key an agent commits and then reverts on a local branch approves nothing; `task list` and `check` name the signer and the revision of an approval that holds this way. [Signed approvals](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/workflow.md#signed-approvals) says what the signed mode is worth in a local copy and in CI. `host apply` keeps the agent away from that file, the alert register and the project catalog. In `enforce`, `host apply` also writes `"disableAllHooks": false`, and it reports the approval rule as partial, which it is.

### Tasks

- Each brain reviews in its own pass: `openguildkit task pass` gives one brain what it needs, `task submit` records its review and refuses a malformed one with all its problems, `task progress` shows which passes are done. The brains answer each other's objections with `task deliberate` and `task respond`.
- Rule relevance: `task result --template` and `task checks` ask only the rules that concern the task, and list the others as not concerned, with the reason.
- Blockers are cleared with evidence (`task clear`) or waived within the project's policy (`task waive`) before the approval. An approval is sealed to what was approved; a project can require signed approvals (`task decision-payload`).
- Closing statuses: `task complete` closes a task as `done`, or as `done-with-reservations` with the points left open, the most serious first.
- Decision records: `task export` writes a sealed record to `.openguildkit/decisions/`, and `openguildkit guard --ci` checks in a pull request that an approved decision covers the changes.
- `openguildkit task list` lists the project's tasks with their status and next open point. `task authorize` records a person's decision on an external action outside the authorized scope.
- `task revoke ID --by NAME --reason WHY` withdraws an approval, at a terminal only; the guard stops counting it. After a rebase or a change of rules, every command gives the same reason and the same command, `task consult ID --reuse-answers`, which reopens the task under the same ID with its recorded answers, without a terminal, and keeps the passes of the boards whose brief did not change. `task list` says who took the current decision: `approved by`, `changes requested by`, `withdrawn by X (approved by Y)`, or that the approval no longer holds; `--owner` filters on that person.
- A waiver ends on its `until` day, by the real clock: after it the blocker is open again (`task blockers` shows `[waiver expired on DATE]`), `task list` names the person's options, and `task complete` and `guard --ci` refuse the task until it is resolved again. A decision, a withdrawal, a clearance, a waiver and an authorization are dated by the real clock whatever `SOURCE_DATE_EPOCH` says, so an approval's age is right; only the replayed exports follow the variable.
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
- Shares record the Documentalist space they open, which is the whole space; `--until` records the last day, to set in the portal too: Documentalist enforces it from commit `46976a9`, and an older instance keeps the access until it is removed. `share add` warns about a second share of the same space to the same person, and a local portal may use http.
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

### Third audit

- `guard --ci` refuses a decision record placed below `.openguildkit/decisions/`, an approval whose revision the pull request does not contain, and a record that carries a withdrawal: after `task revoke`, `task export` writes the withdrawal into the record. `task export` names the new files Git does not track yet; the README closes with commit, export, then commit of the record.
- Signed approvals: an earlier revision's signers count only when the merged branch contains that revision. Waivers expire on their last day (real clock), people's decisions are dated on the real clock, and `task consult ID --reuse-answers` reopens a task without a terminal.
- `openguildkit ui` serves the page on a host name drawn for each run (`ogk-….localhost`), so its key never reaches another local server. The detector recognizes more passwords and tokens, and the page refuses more credential files.
- `init --answers` needs `personal_data`; `market checked` is refused under `local-only`; with `openguildkit` off the PATH, `host apply` says so and exits non-zero.
- The page records named evidence with who provided it, marks required evidence and rules not asked correctly, speaks French in the framing questions, and `task complete` asks the person to confirm data protection, security or AI rules set aside.
- `task result` flags one evidence cited for passed rules of three packs or more; `task verify` counts the rules to report instead of listing them; working files go in `.openguildkit/work/` (run `openguildkit sync`). French routing no longer sends "le client paie" to HR, and Stripe Elements packages are detected.
- The catalog and lock caches compare file contents; the dependency watch scans in a read-only job; CI runs four macOS jobs instead of nine.

### Upgrading from 0.16.1

- Run `openguildkit sync`: it writes `.openguildkit/catalog.lock.json`, which 0.16.1 did not have, and names the tasks consulted under the earlier rules. A task reviewed but not decided waits for the person to request changes (`openguildkit task decide ID --request-changes`), then it is consulted again.
- A 0.16.1 profile has no agent host, so it counts as `other` and `host apply` writes nothing and exits 1. For Claude Code or Codex, set the host first (`openguildkit profile set host claude-code --by NAME --reason WHY`, or `codex`), then run `openguildkit host apply` (new deny rules and hook setting).
- Approvals recorded by 0.16.1 have no seal, so none of them holds any more: until each approved task that is not completed is consulted again, `check` exits 1 on it, and `handoff`, `verify`, `export` and `complete` refuse it. `sync` names them. Consult each again with `openguildkit task consult ID --reuse-answers` (or open a linked task with `--follows`): every board reviews again, since an approval without a seal keeps no pass, and the person approves again. Their answers predate the `concerns` question: it is asked at a terminal, and without one the task is consulted as `unsure` unless `--answers FILE` gives it. A completed task keeps its record as history.
- Signed approvals need the project and its signers file committed in Git.
- Answer files of a new consultation need `concerns`, and setup answers for e-commerce or financial services answer the European Accessibility Act norm.

## 0.16.1 and earlier

See the [GitHub releases](https://github.com/Sandbox-podcast/OpenGuildKit/releases).
