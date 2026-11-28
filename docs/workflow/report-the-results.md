# 6. Report the results

For: the agent that verifies and reports a task, and the person who closes it.
Step 6 of the [task workflow](../workflow.md).

After implementing an approved task, the agent proves what was delivered:

```bash
openguildkit task checks ID            # the checks that concern the task, then what is not asked and why
openguildkit task verify ID            # runs the check commands and the rules' machine checks, with their evidence
openguildkit task result ID --template > result.json   # JSON only: the criteria, rules and named evidence to report
openguildkit task result ID --file result.json
openguildkit task complete ID
```

## Only the rules that concern the task

A project can carry dozens of packs.
A task answers only the rules that concern it; the others are listed as not concerned, with the reason, in `task checks`, in the template's `not_concerned` and in the closed task's record, and need no answer.

Each bundled pack has a subject, the task answers that call for it, and for a few packs the boards the task consults or the words of its brief.
A pack concerns the task when its subject meets the task's `kind`, `surface`, `data` and `concerns`, and the way it reached the project still holds.
Having a board of its role, or personal data, does not bring a pack by itself.
For each regulatory pack, `relevance.LEGAL_BASIS` gives the subject retained and its legal reason.

| Subject | Called for by | Packs |
|---|---|---|
| Every change | always | `agent-workflow`, `secure-sdlc` |
| The project's code | surface `service`, `customer` or `infrastructure` | language and framework packs (`python`, `typescript`, `fastapi`, `django`, `postgresql`...) |
| The user interface | surface `customer` | `react`, `vue`, `nextjs`, accessibility (including `france-rgaa-accessibility`), trackers (`france-cookies-and-trackers`), web performance, mobile, i18n, `playwright`... |
| A new customer feature | kind `feature` and surface `customer` | design, user research, experiments, product discovery, SEO, support readiness, release communication |
| A backend service | surface `service` | `backend-data-safety`, `public-api-docs`, and `service-reliability` (also `infrastructure`) |
| Infrastructure and delivery | surface `infrastructure` | containers, Kubernetes, Terraform, AWS IAM, CI security, incident response, release management, supply chain |
| The tools and instructions agents work with | surface `infrastructure` | `agent-native-engineering` |
| Cloud and vendor spending | surface `infrastructure`, or surface `business` with concern `money` when `finance` or `devops` reviews the task | `finops-cost-management` |
| Personal data | data `personal` or `regulated` | `gdpr`, `minors-data-protection`, `health-data-protection`, `france-health-data-hosting` |
| Security-sensitive changes | data `regulated`, concern `credentials`, surface `infrastructure`, or data `personal` on surface `customer` or `service` | `threat-modeling`, `owasp-asvs`, `iso-27001`, `france-public-sector-security` |
| The ICT systems of a regulated entity | data `regulated`, surface `infrastructure`, or a `feature` or `maintenance` with data `personal` on surface `customer` or `service` | `dora`, `nis2` |
| The systems of an aviation organisation | data `regulated`, or surface `service`, `customer` or `infrastructure` | `aviation-information-security` |
| Airborne software and systems | surface `service`, `customer` or `infrastructure` | `airborne-software-assurance`, `airworthiness-security` |
| Security incidents and vulnerabilities | surface `infrastructure` or concern `credentials` | `cyber-resilience-act`, `incident-notification` (each of its rows also follows its regulation, below) |
| AI | concern `ai` or `people-decisions` | `llm-evaluations`, `nist-ai-risk`, `eu-ai-act` |
| An AI agent or an MCP server | concern `ai`, or a brief that names an MCP server or an AI agent (MCP, Model Context Protocol, AI agent, agentic, function calling, LangGraph, CrewAI...) | `agentic-application-security` |
| Money | concern `money` | revenue, SaaS metrics, VAT, French e-invoicing (`france-e-invoicing`), financial planning, deal approval |
| Payment card data | data `regulated`, or concern `money` when the brief names cards or payments (card, payment, checkout, Stripe...) | `pci-dss` |
| Pay and recruitment | concern `people-decisions`; or the `hr` board with concern `money` (pay) or a brief that names hiring (interview, candidate, job posting...) | `pay-transparency`; `structured-hiring` without the pay case |
| A business process | surface `business` | sales, partners, campaigns, HR processes, procurement, governance and delivery methods |
| Selling to consumers or insurance | surface `customer` with concern `money` | `online-consumer-sales`, `insurance-distribution` |
| The software and the software updates of a road vehicle | surface `service`, `customer` or `infrastructure` | `unece-r155`, `unece-r156` |
| Content users publish | the `trust-and-safety` board reviews the task (the brief speaks of reports, moderation or illegal content) | `notice-and-action` |

An answer left open (`unsure`, `other`, or not given) calls for the packs of that subject.
On top of the subject, a pack brought by a method pattern needs a board of the role that brought it (the pattern's roles the profile lists) among the task's boards, and a pack brought for some components needs a file changed since the approved revision in them; files changed in a component other than the whole project bring its packs even when the answers do not.
A component at the project root (path `.`) holds every file, so there the subject decides.
A pack of the project's own catalog has no subject: a regulation pack concerns tasks on personal or regulated data, a pack needed by another (`depends_on`) follows the packs that need it, and the others concern every task.
A pack or rule listed in `required_rules` is always asked.

A brief names a subject the way it routes a board: whole words, a regular plural, and a negated mention ("no card payments") names nothing.
`incident-notification` holds one row per regulation: each row is asked when the pack of its regulation (`gdpr`, `nis2`, `dora`, `cyber-resilience-act`, `eu-ai-act`) concerns the task, and the pack, with its matrix rule, concerns the task when one of its rows does or when its own subject does.

Inside a data protection pack that concerns the task, the rules about creating or changing a processing are left out of a task of kind `bug` or `maintenance`, which fixes or maintains a processing the project already runs:
in `gdpr`, the record of processing and the DPIA decision (with their named evidence), the lawful basis of a new purpose, the retention of new data, and rights over new data; the age of consent, parental consent, the DPIA for pupils and the default protections of a new flow in `minors-data-protection`;
the Art. 9 condition, the DPIA and the medical device qualification and planning in `health-data-protection`.
The rules on minimising what the change touches, protecting health data, advertising to minors, notices for children and documenting a changed component stay asked.
The `gdpr` rules on a new processor (Art. 28) and a transfer outside the EEA (Chapter V) are left out of a `bug` only: a migration to a hosted service often adds one, a fix almost never.
A feature, or any other kind, keeps every rule; `required_rules`, `--all` and `ask_every_rule` keep them too.
Each rule left out says why.

A named evidence with a condition on the task's `data` is asked only when the data meets it.
To see or answer every rule, run `task checks ID --all` or `task result ID --template --all`; to ask every rule on every task, run `openguildkit profile set ask-every-rule yes --by INITIALS --reason WHY`.

## The result file

`task verify` runs the commands listed in the profile's `checks`, in the project root, and records each exit code with its log under `.openguildkit/tasks/`.
It also evaluates the machine checks of the rules that concern the task (a file that exists, a text present or absent, a field of a JSON or TOML file, a file within a size in bytes, or a command from the project's own catalog;
see [catalog format](../catalog-format.md#machine-checks-and-named-evidence)) and records what it found, such as `export.json: downloadLinkMinutes = 90 (above 60).`; `task result` cannot report these checks.
The template writes nothing but JSON on standard output; it lists the checks `task verify` records under `recorded_by_verify`.
`result.json` names the delivered `revision` or `pull_request`: the template fills in the revision `task verify` read from Git (or `working tree` outside a repository), and a report that leaves it out keeps the one already recorded;
the acceptance `criteria` (`met` or `not-met`, with evidence) and an outcome for each rule: `passed` or `failed` with evidence, or `skipped` or `not-applicable` with a reason and an owner.
An entry left with an empty status is not answered yet.
Later reports update earlier outcomes check by check.
Only `task verify` records the command checks (`command:N`) and only `task verify --chaosfolk` the replays (`chaosfolk:*`): `task result` refuses them, and refuses a `passed` check with a non-zero `exit_code`.
When the task's answers name an `outcome`, the result needs at least one criterion.
Each refusal names the file, the accepted values and `task result ID --template`.
`task verify`, `task result` and `task complete` refuse a task whose approval no longer holds, as the handoff does.
Before any `task result`, `task verify` counts the rules and named evidence still to report in one line instead of listing them, since the template lists them; once a report answered one, it lists those left one by one.

The owner of a `skipped` or `not-applicable` answer is the person who decides it, and the reason is theirs: the agent proposes, the person confirms, and the agent never writes a name it was not given.
One answer can cover every rule of a pack: the template lists under `packs` each pack whose rules can be answered together (none is required, records a value, is selected by the task's data or concerns, or protects data, security or AI), with its rules, so the file stays short.
A pack entry takes the statuses of a rule: `passed` or `failed` with evidence, `skipped` or `not-applicable` with a reason and an owner, for example `{"pack": "react", "status": "not-applicable", "reason": "No interface changes.", "owner": "CM"}`.
It stands for each of its rules not reported one by one; to answer one of them apart, add it to `checks`.
It never covers a rule of `required_rules`, a machine check or evidence that must be supplied.
Any other pack can be answered the same way.
When the task's data or concerns select a pack declared not applicable as a whole (personal data and GDPR, for example), the result records a warning, and so it does when rules they select are declared not applicable with the same reason as other answers.
It warns too when one evidence item is cited for the passed rules of three packs or more: a warning on the result is an open point, so the task then closes with reservations.
A data protection, security or AI pack declared not applicable as a whole is an open point that only a person closes over (`task complete --by`).
Each report that gives `packs` replaces the earlier pack answers, and a pack whose rules a later report answers one by one loses its answer: the warnings describe the result as it stands.
A criterion can name `verified_by`: a check command such as `command:1` or a test file of the project.
The output counts the met criteria tied to a check or a test, those tied to a check command that has not passed (the exported record says so too), and those only declared, and warns when a met criterion's evidence says it was not run.

## Named evidence belongs to its owner

A rule can name evidence kept outside the code, such as the record of processing activities or the DPIA decision of the GDPR pack.
These documents belong to the data controller (in practice the data protection officer or the person accountable for the processing), not to the task: keep them where the organisation keeps its compliance records (an intranet page, or a folder such as `docs/privacy/` that the owner maintains), and cite the same record from every task it covers.
The handoff lists first the evidence the closing will ask for and who provides each.
The template marks each one with the statuses it accepts: `"requirement": "passed"` (it cannot be declared not applicable: the profile's `required_rules` lists it, or it applies to the task's `data`) or `"passed-or-not-applicable"`; `task checks` prints the same word.
A supplied evidence is `passed` with a project path that exists or an `https://` link, and `owner`: the person who provided or confirmed it.
OpenGuildKit checks that the path exists; it never reads the document, and says so in `task complete` and in the exported record, with the name of the person who confirmed it.
It warns when one file is cited for several different evidences, and when a file looks like configuration, code or an image (a `Dockerfile`, a `.py` or `.png` file).

A result that lacks only named evidence is recorded: an evidence that is missing, declared not applicable where it must be supplied, or cited at a path that does not exist is held back with the reason (`Not recorded: ...`), and the task waits.
`task result` and `task list` name the evidence and who provides it, and `task show` and the exported record carry `waiting_for` next to the status.
When an answer is not recorded, the output says whether an earlier answer for the same check stays recorded, and does not call the task ready.
The person can hand the missing evidence to a follow-up task that the owner will close: open it with `task new "BRIEF" --follows ID`, then run `task complete ID --defer EVIDENCE=FOLLOW-UP --by INITIALS` at a terminal.
The task closes with that reservation visible.

## Closing the task

Every project command is mandatory.
A profile can make rules mandatory too with `openguildkit profile add required-rule secure-sdlc python/run-tests --by INITIALS --reason WHY`, which writes `"required_rules": ["secure-sdlc", "python/run-tests"]`.
`task complete` refuses while a mandatory check has not passed, an asked check is not reported, a criterion is not met or a required evidence is awaited, and lists what is missing.
Otherwise it closes the task:

- `done` when nothing is left open: a single line on standard output;
- `done-with-reservations` when points stay open, listed one per line, grouped by nature and the most serious first: data protection, security or AI rules skipped or failed (or such a pack declared not applicable as a whole); board blocks not lifted (a `block` whose blockers were waived rather than cleared); project checks that could not run in this environment;
  blockers waived rather than cleared; disagreements between boards left open, each with its point, its two boards and the decision the person must take; named evidence handed to a follow-up task; other rules skipped or failed; warnings on the result; and, for the record, the board verdicts that asked for changes at approval.
  It gives the command for a linked follow-up: `openguildkit task new "BRIEF" --follows ID`.

Closing over a data protection, security or AI rule that concerns the task and is skipped or failed, or over such a pack declared not applicable as a whole, needs the person: `task complete ID --by INITIALS`, at a terminal, typing the task ID.
The open points are shown once, before the person types the ID.
When only such a point is left, `task verify` and `task result` say the task is ready to close with the person at a terminal rather than plain `Ready`.
The handoff of a closed task speaks of its checks in the past.
`task export --output /dev/stdout` prints the record: an output reached through a link to a device is written to, while a link to a regular file is refused.
`check` warns about evidence a reviewer cannot open (ignored by git, or under `.openguildkit/tasks/`) wherever the result cites it: named evidence, rule and pack answers, criteria and their `verified_by`, and blocker clearings; the logs `task verify` keeps for the check commands are left out.
When the profile lists no check command, `task complete` says that no project command ran.
Notes on what was not run or not read go to standard error.
`task list`, `task show`, `task export`, `docs export`, `deliverable` and the guard read both closed statuses.
`task export` adds the evidence supplied and who confirmed it, the evidence declared not applicable, the pack answers, the warnings, the deferred evidence, the criteria with what verified them and the open points.

## Project checks

`init` proposes the test command each component of the repository shows: `npm test` for a `test` script in `package.json` (not the `npm init` placeholder), and `npm run lint` too when it has a `lint` script, `python -m pytest` when the Python manifests name pytest, `python -m unittest discover -s tests` for a `tests/test_*.py` folder without pytest,
`python -m unittest discover` for `test_*.py` files in the component's own folder, `go test ./...`, `cargo test`, `mvn test` (or `./mvnw test`), `gradle test` (or `./gradlew test`) and `dotnet test`.
A command of a component outside the root runs from its folder, as in `cd apps/web && npm test`.
`init --questions` lists them under `proposed` in the `checks` question; nothing is kept until the person says yes to each one, and `init` names the commands found but not kept.

Every project check is mandatory: the task cannot be done while one fails.
When a command fails, `task verify` prints its cause (exit code, command not found, a missing dependency or network, a time-out), its last three lines of output, the next step and the path of its log under `.openguildkit/tasks/ID-checks/`; `task complete` repeats it.
Install the project's dependencies before `task verify` (`npm ci`, `pip install -e .`, ...).
The handoff lists the commands `task verify` will run and recalls this.
After running them, `task verify` lists every point that still keeps the task from being done, one per line, then their count; when the profile lists no check command it says so and how to add one.
A rule's machine check prints what it found or did not find, such as `Found SECURITY.md.` or `Not found: none of SECURITY.md exists.`

When a command cannot run in this environment for this task (no network, a missing service), the person records it at a terminal, with their initials and the reason:

```bash
openguildkit task verify ID --cannot-run command:1 --by CM --reason "The sandbox has no network for npm ci."
```

The command runs first: one that passes here cannot be declared.
The reason takes at least three words, and a declaration is not combined with `--chaosfolk`.
`task verify` prints the command as `skipped`, with who declared it and why.
The command then no longer blocks completion, and the task closes as `done-with-reservations` with that point listed.
A later `task verify` runs the command again and keeps the declaration while it still fails, saying so; the declaration ends when the command passes, or when the person who made it withdraws it with `task verify ID --withdraw command:1 --by INITIALS` at a terminal, which runs the command and records its outcome.

`task verify` exits with status 1 when a mandatory check command failed, so a script or a CI job can tell; it exits with 0 when only answers remain to give (the listed points say which).
When a command fails, the message starts with the first line of its output that names the error ("Cannot find module 'express'") and ends with its last lines, then the log path.

A check that cannot run on the team's workstations, because it needs the network, a service or credentials, does not belong in `checks`:
leave it out at setup, or ask the person to run `openguildkit profile remove check 'COMMAND' --by INITIALS --reason WHY` at their terminal (a check removed weakens a protection), then run it in CI and name it under `conventions` (for example "The integration tests run in CI: tests/integration needs the payment sandbox") so the agent and the reviewers know where its result comes from.
