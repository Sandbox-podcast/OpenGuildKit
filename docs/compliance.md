# Controls of OpenGuildKit and the frameworks they may answer

An auditor or a security officer asks which controls OpenGuildKit itself provides, where each is held in the code, what it does not cover, and which requirement of a framework it answers. This page lists the controls and keeps the answer to the last question empty until someone has read the framework.

It does not state that a project, an organization or OpenGuildKit complies with any framework. No text of a framework is copied here, and no clause is written from memory.

## How to read it

The tables below are generated from [`src/openguildkit/registry/controls.json`](../src/openguildkit/registry/controls.json) by `python scripts/build_compliance.py`, and a test fails when the page differs from the file.

- Each control names the commands that run it and the file and line of the code that holds it, which a test looks up again. Its last column says what the control does not cover.
- The second table puts each control against six frameworks of the [catalog](references.md). A cell holds a clause only with the address of the source that was read and the day it was read. A cell that says `to verify` has no source read for it yet and stays empty.

## Controls and frameworks

<!-- controls:start -->
#### The controls

| Control | What OpenGuildKit guarantees | Where to check it | Not covered by OpenGuildKit |
|---|---|---|---|
| `human-approval`: A person approves a task before an agent works on it | task decide --approve needs the person to type the task ID at an interactive terminal, or, in a project with signed approvals, an SSH signature by an approver (a board removal is still typed at the terminal); without either the command is refused and the task stays reviewed. | `task decide ID --approve --by NAME --reason WHY`; `src/openguildkit/tasks_cli.py:541` (_decide); `src/openguildkit/terminal.py:11` (interactive); dossier: `decisions.jsonl` | It does not identify the person behind the terminal: the name is the one typed with --by. |
| `edit-gate`: Edits through the agent host are refused until an approved task covers them | With guard enforce and a host that has hooks (Claude Code, Codex, Gemini CLI), the hook before an edit refuses it with exit code 2 unless a task whose approval still holds covers it; guard observe flags the edit and lets it through. | `guard --hook pre-edit`; `host check`; `src/openguildkit/guard.py:236` (hook_answer); `src/openguildkit/guard.py:282` (guard_hook); `src/openguildkit/hosts.py:19` (HOOK_HOSTS) | A shell command does not go through the hooks, and a host without hooks has none: guard --ci is then the only barrier. host check and host scan say which tools have no hook. |
| `sealed-decision`: An approval is sealed over what was approved | The approval carries a SHA-256 seal over the consultation, the review, the rules in force, the approver, the reason and the Git revision; a record changed after its export, or approved under other rules, no longer holds, and check, task list --decisions and guard --ci say so. | `check`; `task list --decisions`; `src/openguildkit/decisions.py:98` (decision_payload); `src/openguildkit/decisions.py:142` (seal); `src/openguildkit/guard.py:667` (_record_fault); dossier: `decisions.jsonl` | A local seal is not a signature: an agent that writes files can forge a record and compute its digests again. The completion of a task is checked for consistency, not sealed by a person. |
| `signed-approval`: In a signed project an approval carries an SSH signature checked against the committed signers | With approvals in signed mode, task decide --approve needs an SSH signature of the decision payload by an approver; ssh-keygen verifies it against the allowed signers file as Git holds it at HEAD, and guard --ci verifies each record against the signers of the base revision. | `profile set approval signed --signers PATH --approver NAME`; `task decision-payload ID --by NAME --reason WHY`; `src/openguildkit/decisions.py:177` (verify_signature); `src/openguildkit/decisions.py:150` (committed_signers); `src/openguildkit/decisions.py:267` (verify_recorded_signature); dossier: `decisions.jsonl`, `signers-history.jsonl` | It shows that a key listed in the signers file signed. Who holds the key, and how it is kept, is outside OpenGuildKit. |
| `separate-requester`: The person who asked for the work does not approve it (option, off by default) | With separate-requester on in the profile, every new task names its requester, task decide refuses an approval by that person, and guard --ci refuses a record whose approver is its requester when the base revision has the option on. | `task new BRIEF --requested-by NAME`; `profile set separate-requester on`; `src/openguildkit/requester.py:46` (approval_problem); `src/openguildkit/requester.py:72` (record_problem); `src/openguildkit/guard.py:1039` (ci_guard); dossier: `decisions.jsonl`, `profile-changes.jsonl` | Off unless a person turns it on. Names are compared without case or spaces, and a signed approval compares the requester to the signer's principal: a requester named otherwise than their principal is not caught. |
| `ci-decision-gate`: A change must come with a valid exported decision, judged under the rules of the base revision | guard --ci checks each file changed since the base against the exported records the change brings; the mode, the profile, the catalog lock and the allowed signers come from the base revision, so a pull request cannot weaken the rules it is judged by. | `guard --ci --base REV`; `src/openguildkit/guard.py:1039` (ci_guard) | That the check must pass before a merge is a setting of the Git host, which OpenGuildKit does not read. |
| `exported-decision-record`: An approval can be exported as a record the team commits | task export writes .openguildkit/decisions/ID.json with the approval payload, its signature, the brief, the board verdicts and a SHA-256 of the whole record; trace and task list --decisions read every record, teammates' included, and say whether it still holds. | `task export ID`; `trace FILE`; `src/openguildkit/guard.py:396` (export_decision); `src/openguildkit/guard.py:804` (exported_decisions); `src/openguildkit/trace_cli.py:59` (trace); dossier: `decisions.jsonl` | Work done without a task has no record: guard --ci then reports a missing decision. A record exported outside Git lists no files and covers no path. |
| `rules-in-force`: An approval holds only under the rules it was given under | The approval records the fingerprint of the rules, checks and boards in force; when they change the approval no longer holds, check exits 1 and the hook stops covering edits with it. check also fails when the instructions of the project no longer match its profile and its catalog lock. | `check`; `src/openguildkit/project.py:1286` (Fingerprints); `src/openguildkit/guard.py:661` (_rules_hold); `src/openguildkit/cli.py:1263` (_check); dossier: `decisions.jsonl` | Only a change of the rules, checks and boards voids an approval: the guard mode, the host, the research setting, the approval mode and the waiver policy leave approvals standing. |
| `profile-change-history`: Each change to the profile records who made it, when and why | Every profile command appends its change, the person, the day and the reason to changes in .openguildkit/project.json; a change that lowers a protection (guard, signed approvals, public research) is typed by a person at an interactive terminal. | `profile set guard enforce --by NAME --reason WHY`; `src/openguildkit/profile_cli.py:499` (write_change); `src/openguildkit/profile_cli.py:127` (weakening_changes); `src/openguildkit/project.py:566` (_changes); dossier: `profile-changes.jsonl` | A hand edit of project.json is not an entry: Git holds it, and OpenGuildKit does not read that history except for the signers file. |
| `alert-register`: Dependency alerts are kept with who decided what, and a confirmed critical alert blocks approval | alerts import merges the reports of the project's scanners (npm audit, pip-audit, OSV-Scanner, GitHub Dependabot) into .openguildkit/alerts.json; severity, status, acceptance and dismissal record who, why and when; a confirmed critical alert that no person accepted blocks the approval and the completion of its tasks. | `alerts import FILE`; `alerts set ID --status confirmed --by NAME`; `alerts accept ID --by NAME --reason WHY`; `src/openguildkit/alerts.py:347` (import_report); `src/openguildkit/alerts.py:441` (set_status); `src/openguildkit/alerts.py:471` (accept_alert); `src/openguildkit/alerts.py:514` (blocking_alerts); dossier: `alerts.jsonl` | It reads the reports it is given and runs no scanner: a dependency no report lists is not in the register. |
| `agent-surface-inventory`: The agent tools, MCP servers and instruction files of a repository are listed and scanned | host scan lists the agent tools whose files the repository holds, the MCP servers they configure and the permissive settings, and reports hidden characters, phrases that cancel the rules and downloads piped into an interpreter in the files an agent reads; projects --surfaces lists them for a folder of repositories. | `host scan`; `projects FOLDER --surfaces`; `src/openguildkit/surfaces.py:875` (discover); `src/openguildkit/surfaces.py:417` (scan); `src/openguildkit/projects_cli.py:175` (_inventory) | It reads files, offline: a tool with no file in the repository cannot be seen, and what an agent does is not observed. |

#### The controls against the frameworks

| Control | `eu-ai-act` | `iso-iec-42001` | `nist-ai-rmf` | `soc-2` | `dora` | `nis-2` |
|---|---|---|---|---|---|---|
| `human-approval` | to verify | to verify | to verify | to verify | to verify | to verify |
| `edit-gate` | to verify | to verify | to verify | to verify | to verify | to verify |
| `sealed-decision` | to verify | to verify | to verify | to verify | to verify | to verify |
| `signed-approval` | to verify | to verify | to verify | to verify | to verify | to verify |
| `separate-requester` | to verify | to verify | to verify | to verify | to verify | to verify |
| `ci-decision-gate` | to verify | to verify | to verify | to verify | to verify | to verify |
| `exported-decision-record` | to verify | to verify | to verify | to verify | to verify | to verify |
| `rules-in-force` | to verify | to verify | to verify | to verify | to verify | to verify |
| `profile-change-history` | to verify | to verify | to verify | to verify | to verify | to verify |
| `alert-register` | to verify | to verify | to verify | to verify | to verify | to verify |
| `agent-surface-inventory` | to verify | to verify | to verify | to verify | to verify | to verify |

- `eu-ai-act`: Artificial Intelligence Act, Regulation (EU) 2024/1689
- `iso-iec-42001`: ISO/IEC 42001:2023
- `nist-ai-rmf`: NIST AI Risk Management Framework 1.0
- `soc-2`: SOC 2, Examination and attestation report
- `dora`: Digital Operational Resilience Act (DORA), Regulation (EU) 2022/2554
- `nis-2`: NIS 2 Directive, Directive (EU) 2022/2555
<!-- controls:end -->

## What OpenGuildKit does not cover

OpenGuildKit does not run, monitor or assess the AI system a team builds. It holds no policy, risk assessment or training record of the organization, and it issues no certificate or attestation. The last column of the first table says what each control leaves out.

## The evidence dossier

```bash
openguildkit evidence export --since 2026-10-01 --until 2026-12-31 --output audit-2026-q4
openguildkit evidence verify audit-2026-q4
```

`evidence export` gathers into a new folder what OpenGuildKit already knows about the project for a period, so that a person does not collect it by hand from `.openguildkit/decisions/` and the Git history. It reads the project and writes only that folder, which must be new or empty, inside the project and outside `.openguildkit/`. `--since` and `--until` are UTC days, both included, and each may be left out.

- `decisions.jsonl`: one line for each exported decision record whose decision falls in the period, with the task, the record and the SHA-256 of its file, the status, who decided, when and why, and three states. The seal is `holds`, `broken` or `missing`. The digest of the whole record is `holds`, `broken` or `absent` (a record exported by an earlier release). The signature is `verified`, `verified-earlier-signers`, `not-verified`, `unsigned` or `not-checked`, with whether the project requires it. Last, whether the decision still holds under the rules in force, with the problem when it does not. A file of the folder that cannot be read is listed too, with no date.
- `profile-changes.jsonl`: the profile changes of the period, with the change, who made it, the day and the reason.
- `signers-history.jsonl`: the Git commits of the period that changed the allowed signers file of a signed project, with the principals the file listed and the object ID of the file. It carries no key.
- `alerts.jsonl`: the alerts of the register with a dated event in the period (first or last seen, decided, accepted, resolved), as they stand now, since the register keeps the latest decision on an alert and not each step; then the scanner imports of the period.
- `controls.json`: the registry above, as this version of OpenGuildKit ships it.
- `MANIFEST.json`: the version of OpenGuildKit, the commit of the repository and whether files differ from it, the period, a summary of the profile (guard, host, approvals, separate requester, fingerprint of the rules), the SHA-256 of `project.json` and of the catalog lock, the SHA-256 and size of each file, a note for each file that could not be filled, and a statement that the files state no conformity.

`evidence verify DOSSIER` (a relative name is read from the project root, as `--output` is) recomputes the SHA-256 of each file the manifest lists and exits 1 when one differs, is missing or is not a plain file of the folder, or when the folder holds a file the manifest does not list. It prints the SHA-256 of `MANIFEST.json`.

Two limits. `verify` catches a file changed after the export, not a dossier rewritten together with its manifest: the person who hands the dossier over gives the SHA-256 of `MANIFEST.json` by another route, and the auditor compares it with the one printed. And a decision of a task that was never exported has no line: `task list` shows those.

The dossier holds the names people typed with `--by`, and their reasons: [personal data](personal-data.md) lists them, and the dossier is handed to the auditor, not committed.

## Filling a cell

1. Read the official text of the framework, from the publisher's own page.
2. In `controls.json`, add to `maps_to` of the control an entry with `reference` (an ID of the catalog that `frameworks` lists), `clause` (where to look, 80 characters at most, never a sentence of the text), `source` (the https address of the page read) and `checked` (the day it was read).
3. Run `python scripts/build_compliance.py`, which also sets the lines, and commit both files.

A test refuses an entry whose reference is not in the catalog or whose clause, source or `checked` day is missing, malformed or in the future.
