# Changelog

What changes for a team that uses OpenGuildKit, version by version. Versions follow Semantic Versioning for the CLI; packs carry their own versions ([catalog format](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/catalog-format.md)). A release copies its section into the GitHub release notes ([release steps](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/GOVERNANCE.md#releases)).

## Unreleased

- A pack rule can bound the size of a file: the `size` check takes `paths` and `max_bytes`, passes when no matching file is larger, and `task verify` names the largest file and its size ([catalog format](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/catalog-format.md#machine-checks-and-named-evidence)). The Node CI coordinator does not evaluate it.
- The agent skill is shorter: `SKILL.md` goes from 28 933 to 14 330 bytes, since an agent reads it again at every turn. It keeps the task journey and its safeguards; setup, deliberation, closing a task, market dossiers, dependency alerts, Storybook and tools are in `references/` files, which `SKILL.md` says when to read. `openguildkit integrations` installs them next to it; a `SKILL.md` you installed earlier is kept until you run it with `--force`.
- New pack `agent-native-engineering` 1.0.0 and method pattern `agent-native-repository`, suggested to the engineering, devops and QA roles and preselected for none: bounded command output and instruction files, a machine-readable repository map, a targeted check, evidence written by tools, oversight files out of the agent's reach, a contract for each subagent and a measured cost per task. It concerns tasks on infrastructure and delivery, and the references `context-engineering`, `agent-execution-limits` and `agent-tool-permissions` now apply it.
- Features: `openguildkit features` lists 20 purposes (documentation portal, issue tracking, payroll, container registry...), each with a lead tool and its three best-known alternatives, and turns an option on or off in the profile with who and why. The web interface shows them in a new place, the Arsenal.
- New bundled tool IDs: `adp`, `apache-spark`, `apigee`, `appdynamics`, `auth0`, `discord`, `docker-hub`, `eclipse`, `gravitee`, `harbor`, `jetbrains`, `jfrog-artifactory`, `keycloak`, `kong`, `lens`, `mattermost`, `microsoft-entra-id`, `npm`, `okta`, `portainer`, `rancher`, `silae`, `sonatype-nexus`, `splunk`, `visual-studio`, `vscode`, `zoom`. Kibana is now an alias of Elastic. If a project catalog already defines one of these tools or names, rename its local entry and update the profile, or remove the project definition to use the bundled tool.
- Dates: decisions, waivers and share end dates are UTC days, like the recorded timestamps and Documentalist's access end. A share is `expired` from 00:00 UTC the day after its last day.
- Shares: `:443`, `:80` and the case of an address no longer make one Documentalist space or reader look like two, and `docs share verify` reaches a local portal without the environment's proxy.
- The web page refuses to read a file whose text holds a credential, whatever its name, and refuses `mcp`.
- `features disable` names the MCP connection the agent keeps and the `tools remove` command; `features enable` proposes `tools plan` only for a tool with an MCP server.
- `tools plan` asks for the real path of the Lens and QuickBooks servers and of a Docker Hub clone, and `tools apply` writes nothing until it is given.
- `check`, `references`, `brains` and `task consult` refuse a project reference that names an unknown pack or brain. The catalog refuses an impossible or future `checked`, `verified` or `reviewed` date.
- Packs: `eu-ai-act` 1.3.3 dates the prohibitions that apply from 2 December 2026, `nis2` names TLD name registries, `european-accessibility-act` 1.0.1 adds EN 301 549 clause 9.7. Each EU text has one address in the catalog.
- On Windows, an act left to a person needs a console: standard input from `NUL` is no longer taken for a terminal.
- A decision record or a `catalog.lock.json` of the wrong shape (a null `schema_version`, a list as `consultation_id`, a lock entry that is not an object) is reported as a problem that names the file, instead of a Python traceback. `guard --ci` reports a record it cannot read or whose shape is wrong as a problem of the check, which still passes in `observe`.
- `openguildkit profile set approval` now says to run `openguildkit host apply`, as `profile set host`, `guard` and `research` do: signed approvals add a rule on the signers file to the host settings, and `check` fails until it is applied.
- A `CLAUDE.md` that quotes `@AGENTS.md` in a code block no longer counts as importing `AGENTS.md`: `sync` adds the real import and `check` reports the instructions out of date until it does.
- `openguildkit guard --ci` outside a Git repository says in one line that it needs one, instead of printing the usage of `git diff --no-index`.
- `alerts import` no longer resolves the alerts of a package that a pip-audit report skipped (an entry with a `skip_reason`), and does not count such an entry as an analyzed dependency.
- A resolved alert that a later report lists again loses the acceptance of its risk, so a confirmed critical alert blocks its tasks again; `alerts import` names each alert whose acceptance it removed.
- `alerts import` warns, and names the previous file, when a report resolves alerts under another file name than the scanner's previous import: a report of another lockfile resolves the alerts of the first. The scanner has one full report per project ([alerts](docs/alerts.md)).
- `alerts import FILE --scope NAME` declares which lockfile or folder a report covers: it resolves, reopens and counts as absent only the alerts of that scope, so the `npm audit` of `front/` no longer resolves the alerts of `admin/`, confirmed critical ones included. An alert with a scope keeps `scope` in the register and an ID that ends with `@NAME`; an import without `--scope` concerns only the alerts without one, and the warning above now says to declare the scope ([alerts](docs/alerts.md#one-report-per-scanner-or-one-scope-per-report)).
- `docs share verify` reports a server that does not answer in valid HTTP like any other unreachable portal, and `docs export` refuses by name an export manifest whose `files` is not a list of paths and an `--openapi` file that is not UTF-8, instead of printing a Python trace or an unnamed decoding error.
- `deliverable check` reads a draft saved with a UTF-8 byte order mark, and `alerts import` reads a report saved as UTF-16 (PowerShell 5.1 `> file`); a file in another encoding is refused with its name and the encoding.
- `docs share add` records the deliverable as a path from the project root, so a share named by its absolute path counts as the same deliverable as one named by its relative path: `--dedicated-space` and the readers of a shared space follow it, and the register keeps no local path.
- `alerts tasks --open` gives each confirmed alert of a package with a long name a task of its own: an ID cut at 64 characters ends with a short digest of the alert ID instead of colliding.
- The web interface refuses a command that names, in one of its options, a file the page itself will not read (`task new --file credentials.md`, `client_secret.json`): it answers `secret-file` instead of copying the file into the task.
- The web interface lists and opens the market dossiers and tasks whose ID contains `password` or `secret` (`password-manager`, `password-reset`), which it hid as if they were secret files.
- The web interface answers a NUL or a lone surrogate in a path, an upload or the Storybook proposals with `bad-request` instead of a server error or a false "project busy", and writes the type, message and trace of a real server error in the terminal that runs `openguildkit ui`.
- The commands the web interface offers to copy now quote a word as the CLI does: typographic apostrophes (‘ ’ ‚ ‛) are doubled for PowerShell, and a leading `=` (POSIX shells) or `@` (PowerShell) goes between quotes.
- The web interface's refusals say what happens: `.git` is refused as a file it does not read, not as "outside the project"; `task alerts --set` on a critical alert gets the alert refusal like `alerts set`; and the list of acts left to a terminal names dismissing a critical alert.
- Routing: a brief that names the European Accessibility Act, the Digital Services Act, pay transparency, PSD2 (DSP2) or a data protection impact assessment (AIPD) now convenes Legal, with HR for pay transparency; 2FA, OAuth, OpenID Connect, JWT, TLS, passwords, RBAC, encryption and single sign-on convene Security; PayPal, Apple Pay, SEPA, refunds and direct debits convene Finance. The names are in English and French.
- Routing: "en vue de", "point de vue" and "vue SQL" no longer select Frontend as Vue, a worker that "reacts to" events is not React, and a possessive ("DORA's change failure rate") no longer hides the longer phrase, so DORA metrics stop convening Legal and Security. `employee attrition` ("attrition des salariés") convenes HR instead of Customer success, Support and Product, and `turnover` and `rotation du personnel` convene HR.
- Pack `github-actions-security` 1.2.0: `declare-workflow-permissions` now fails when any workflow lacks `permissions:` instead of passing when one has it, and the new rule `refuse-write-all-permissions` fails on `write-all`. A `text` check takes `each: true`, which asks every file its paths match to hold one of the texts. Projects that use the pack review the change with `openguildkit update`; their pending approvals need a new consultation.
- `task_check_results` of the project MCP server (`openguildkit --project PATH mcp`) now returns `omitted` and `failed_omitted`: the number of recorded checks it does not list because their name is free text, such as a ChaosFolk scenario `checkout_flow.json`, and how many of them failed. A failed scenario no longer disappears from the answer without a trace.
- A rule `check` can no longer name a path inside `.git` or `.openguildkit` (`.git/config`, `.openguildkit/project.json`): the catalog refuses it with the rule's file and field, where a literal path used to read them although wildcards never did.
- `openguildkit-ci` reads a `--config`, `--answers`, `--evidence`, `--task` or `--brief` file that starts with a UTF-8 byte order mark, as a Windows editor writes it, and names the file when its JSON is invalid.
- `openguildkit-ci` speaks English throughout: the error messages of all its commands and of its two binaries (`releases`, `merge`, `merge-protection`, `brief` and `check`, the profile, rule and waiver errors, the GitHub synchronization and report errors, `reconcile`, `watch`), the questions of `onboard`, the Jenkins helpers and the pilot templates, and the `AGENTS.md` that `brief` writes. A ticket is still read under its French section titles (`Résultat attendu`, `Critères d'acceptation`), since a person writes it.
- A brief or an answer of tens of thousands of characters on one line no longer stalls `task new` and `task consult` for 10 to 30 seconds: the credential and personal data detector and the path search of routing no longer backtrack.
- `task result` replaces a credential in the revision, the pull request, the criteria, the evidence and the reasons with a placeholder, and warns like `task new` does, so `task export` no longer commits it; `docs export` checks its pages again, replaces what a record still holds and warns about an email address, a phone number or a bank account number it publishes.
- The credential detector now replaces `redis://:PASSWORD@host`, the `_authToken` of an `.npmrc`, `secretAccessKey` of the AWS CLI, a PGP private key block, `mdp:`, `--password VALUE`, `--pass VALUE` and the `-p VALUE` of `docker login` and `sshpass`; a requirement such as `Password: required, min 12 chars` is no longer rewritten.
- `market watch`, `market observe --source`, `market change --source`, `docs share add --portal` and `storybook compose --url` refuse a link with a user name, a password or a token in its query, instead of recording it in a committed file; the market commands also refuse a link to a private host.
- `openguildkit task verify` keeps the pack answers of a result, whatever machine checks the packs carry: only a report that answers a pack's rules one by one replaces its pack answer.
- `openguildkit task checks` shows the answer of a rule that a whole-pack answer covers, in the text and in `--json`, instead of "not reported".
- `openguildkit task list --since` and `--until` refuse a value that is not a real day written YYYY-MM-DD, instead of listing nothing or everything.

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

- `openguildkit --project PATH mcp` provides read-only project metadata over stdio. See [Project MCP](docs/tools.md).
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
