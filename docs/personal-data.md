# Personal data the tool records

OpenGuildKit records who decided what: who approved a task, cleared or waived a blocker, set a rule aside, closed the task, reviewed a dependency alert, changed the profile or shared a deliverable. This page lists each field that holds a person's name or address, the file it is in, whether Git tracks that file, why it is kept, how long, and how to remove or replace it. A team that keeps a record of processing activities can describe the tool's own processing from it.

Read in the code of version 0.17.0 and tried on test projects on 22 November 2026 ([what was tried](#what-was-tried)).

[README](../README.md) · [Task workflow](workflow.md) · [Glossary](glossary.md) · [Security policy](../SECURITY.md)

## Write initials, not full names

`--by` records whatever you type. Give it your initials (`CM`) or the short handle your team already uses for you, not your full name, and use the same identifier everywhere the tool names a person:

- `--by` of `task decide`, `task clear`, `task waive`, `task revoke`, `task complete`, `task verify --cannot-run`, `task authorize`, `profile`, `alerts` and `docs share`, `--by` of `market provided` and `--verified-by` of `market change`, `--owner` of `task list`, and the name in `--delegate BOARD=NAME`;
- the `owner` of each rule you set aside, and of each document you confirm, in a result file;
- `waivers.allowed_by`, since the `--by` of `task waive` must be one of its entries;
- in a project with signed approvals, the principal of your line in the allowed signers file, `approval.approvers` and `--signer`. A principal is any word `ssh-keygen` matches: it need not be an email address.

Three reasons. Names are copied into files the team commits and shares. The approver's name is inside the approval's seal and, in a signed project, inside what they signed: it cannot be replaced afterwards without breaking the approval ([the approver](#the-approver)). And a signed approval is verified against the principal in the approvers and the allowed signers file, today's or those of the revision it was signed at ([when an approver leaves](#when-an-approver-leaves)): a principal that is not an address keeps one out of every revision of those files.

Keep the list of who is behind each identifier outside the repository, in the team's directory. Initials remain personal data for anyone who knows the team: they keep full names and addresses out of the committed files, they do not make the records anonymous. Use one identifier per person: a shared name such as `security-team` does not say who approved, cleared, waived or closed.

## What the tool writes

The tool deletes none of these on its own. A file Git tracks keeps every earlier version in the repository's history, for as long as that history exists. A file Git ignores stays on the machine that wrote it until someone deletes it: `.openguildkit/.gitignore`, which `init` and `sync` write, ignores `tasks/` and `shares/`.

### Files the team commits

| Field | File | Written by | Why |
|---|---|---|---|
| `changes[].by`, and the approvers or waiver holders that `openguildkit profile set` writes in `changes[].change` | `.openguildkit/project.json` | every `profile` command; a profile saved in `openguildkit ui` (the name typed in the page, or `web interface`) | who changed the rules, when and why |
| `declined[].by` | `.openguildkit/project.json` | `profile decline`, the `init` questionnaire, the `norms` of an answers file | who declined a norm, when and why |
| `approval.approvers`, and in the file `approval.allowed_signers` names, one principal and public key per line | `.openguildkit/project.json`, the allowed signers file (for example `.openguildkit/allowed_signers`) | `profile set approval signed`; the person writes the signers file | who may sign an approval |
| `waivers.allowed_by` | `.openguildkit/project.json` | `profile set waivers allowed` | who may waive a blocker |
| the same declines, adoptions, approvers and waiver holders, as sentences | the managed block of `AGENTS.md` | `init`, `sync`, every `profile` command | the agent reads the rules in force |
| `decision.by`, `decision.payload.by`, `decision.signer`, `rounds[].decision.by` | `.openguildkit/decisions/ID.json` | `task export` | who approved, or requested changes in an earlier round |
| `requested_by`, `decision.payload.requested_by` | `.openguildkit/decisions/ID.json` | `task export`, from `task new --requested-by` | who asked for the work, so that a project that separates the requester from the approver can check they differ ([requester and approver](workflow.md#requester-and-approver)) |
| `blockers[].owner`, `blockers[].resolution.by`, `blockers[].resolution.signer` | `.openguildkit/decisions/ID.json` | `task export`, from the review and from `task clear` or `task waive` | who must resolve a blocker, and who did |
| `result.check_exceptions[].owner`, `result.evidence_not_applicable[].owner`, `result.evidence_supplied[].confirmed_by`, `result.packs[].owner` | `.openguildkit/decisions/ID.json` | `task export`, from the result file | who set a rule aside, or provided or confirmed a document |
| `result.deferred[].by`, `result.closing.by` | `.openguildkit/decisions/ID.json` | `task export`, from `task complete --by` | who handed evidence to a follow-up task, who closed over open points |
| `declined[].by` | `.openguildkit/decisions/ID.json` | `task export`, from the consultation | the declines in force when the task was consulted |
| `alerts[].by`, `alerts[].severity_set.by`, `alerts[].accepted.by` | `.openguildkit/alerts.json` | `alerts set`, `task alerts --set`, `alerts severity`, `alerts accept` | who reviewed an alert, set its severity or accepted its risk |
| `watch.sources[].provided_by`, `watch.changes[].verified_by` | `.openguildkit/market/ID.json` | `market provided`, `market change` | who read a page under `local-only`, who verified a competitor's change |

A decision record also carries free text: the `brief`, the review `summary`, each board's `recommendation`, reasons and evidence references, with whatever names people and the agent typed in them. From version 3 of the approval payload, the brief and the summary are also in clear inside `decision.payload`, under the seal.

### Files that stay on one machine

| Field | File | Written by | Why |
|---|---|---|---|
| everything the exported record shows, plus `rounds[].revoked.by`, the `by` and `signer` of `blocker_resolutions` and `verification_blocker_resolutions`, `result.checks[].owner` (a person's declaration that a command cannot run included), `authorizations[].by`, `follows.decision.by`, and the person named with `--delegate`, in `consultation.delegations` and `review.boards[].reviewer` | `.openguildkit/tasks/ID.json` | the `task` commands | the task's history, from which `task export` writes the record |
| `recipients` (email addresses), `by`, `revoked_by` | `.openguildkit/shares/shares.json` | `docs share add`, `docs share revoke` | the only record of who received access to what, and until when ([sharing](documentation.md#share-a-deliverable)) |
| whatever the agent writes in them: the answers, the boards' entries, the deliberation, the result | `.openguildkit/work/` | the agent, before it passes them to a `task` command | working files; the task record keeps what the commands accept |
| `recipient` (email address), intended and observed dates, verification time and source | `.openguildkit/shares/portal-observations.json` | `docs share verify` | the last comparison of the register with a portal's invitation settings; each new verification replaces that space's observation |
| `ogk-ui:decider`, `ogk-ui:signer` | the browser's local storage for the page's address (`http://ogk-….localhost:7311`, a host name drawn at each start) | `openguildkit ui`, when you type who decides or who signs | to fill the field again while the server runs |
| `by`, `signer`, the task and the paths of each event, and `change`, which names the people a profile command adds as approvers or waiver holders | `.openguildkit/audit/audit.jsonl` | the guard hook, and `task decide`, `task revoke`, `profile` and `host apply`, only when a person turns the audit log on ([audit log](audit-log.md)) | what OpenGuildKit did and who did it, for the organization's log collector; the tool never deletes it, retention is the collector's, and deleting the file ends the chain |
| each call to a mock and its arguments | the file `--log` names | `tools mock ID --log FILE`, `tools plan` or `tools apply` with `--mock --log FILE` | so a test can check what the agent called; mocks serve synthetic data |

The task record also keeps the brief, the answers, the boards' reviews, the reasons and the evidence. `task new`, `task consult` and `task result` replace what looks like a credential with a placeholder, and warn when a brief, answers or a result hold an email address, a phone number or a bank account number: they record them anyway, and `docs export` warns again before it publishes them. `task list --json` shows the approver as `owner` and the person who closed the task as `closed_by`. The tool does not store what commands print, but a CI log keeps what the commands it runs print.

### Read and shown, never written

The `owners` of each rule of the project's CODEOWNERS (`.github/CODEOWNERS`, `CODEOWNERS` or `docs/CODEOWNERS`) are often handles or email addresses. The decision brief and the handoff name the owners of the paths a task touches, read again from that file at each display ([code owners](workflow.md#code-owners-of-the-touched-paths)). No task record, exported record or other file of the tool keeps them: whether a committed record may is still undecided. The file is the team's own, and the same advice holds: a team handle such as `@org/team-api` rather than a person.

### The CI coordinator

`integrations/ci`, the Node.js coordinator of the export-expiry pilot, reads people it does not write: `adoption.approver` in the pilot profile, `waiverApprovers` in its configuration and the `approver` of each waiver in the registry of the policy repository. `openguildkit-agent` copies `approver` into the `brief.json` it writes, and the pull request report names the approver of the waiver that applies. People write those files in the repositories they choose; the same advice holds: a handle such as `@security`, not a name.

### Fields named like a person that hold none

`resolved_by` in `alerts.json` is the scanner report that resolved an alert, and `seen_by` lists scanners. The `verified_by` of a result criterion, in the task and in the exported record, is a check command or a test file. A named evidence's `owner_role`, and the `waiting_for` it fills, name a role from the catalog. `generated_by` in `catalog.lock.json` is the OpenGuildKit version. `covered_by` in the output of `guard` lists task IDs. `approved_by` is a field `deliverable check` asks you to remove from a draft. `signers` is a guard outcome, `--signers` and `allowed_signers` give the path of the signers file, and `--approver` fills `approvers`.

## How long

OpenGuildKit sets no retention period. The records exist to show later who decided what, so the team sets how long it keeps them in its record of processing, for example as long as it maintains the product the decisions cover. The alert register keeps the last 20 imports, which name no one; nothing else is pruned.

## Remove or replace a name

### In the profile, the alert register and the market dossiers

These files have no seal. Replace the identifier in a text editor (the web interface refuses a profile whose `changes` differ from the saved ones), then:

- after `project.json`, run `openguildkit sync`: it rewrites the managed block of `AGENTS.md`, which repeats the declines, adoptions, approvers and waiver holders, and `check` reports that block as edited by hand until you do. Approvals stand: who declined or changed what is left out of what an approval rests on;
- after a market dossier, `openguildkit market check ID` validates it.

Commit the files. Replacing an entry of `approval.approvers` or `waivers.allowed_by` also changes who may approve or waive: use `profile set` for that, and read [when an approver leaves](#when-an-approver-leaves) first.

### In exported decision records

A record carries two digests. The approval's `seal` covers `decision.payload`, which holds the approver's name; `record_sha256` covers the whole record. `check`, `task list --decisions` and `guard --ci` recompute both, and a signed project also verifies the signature over `decision.payload`. `guard --ci` checks only the records a pull request changes, and accepts a record that the base branch already holds only if it carries the same approval: the same seal over the same consultation. What happens then depends on the field.

#### Names outside the approval

The answers' `owner`, `confirmed_by`, `closing.by`, `deferred[].by`, the `owner` of a blocker and the `by` and `signer` of its resolution, and `declined[].by` are covered by `record_sha256` only, which anyone can recompute.

1. When the task record is still on your machine and the name is in its `result` (the owners of the answers, `closing.by`, `deferred[].by`), replace it there and run `openguildkit task export ID` again. The record gets the new identifier and a new `record_sha256`; the seal does not change, and `guard --ci` accepts the record as the same approval.
2. The blockers and the declines are under the approval's seal in the task record: replacing a name there makes `task export` refuse ("The record of ID no longer matches what was approved"). Replace them in the exported record instead, then recompute its `record_sha256`. No command does it; this line does, with Python alone:

   ```bash
   python3 -c "import hashlib, json, sys; p = sys.argv[1]; r = json.load(open(p, encoding='utf-8')); r.pop('record_sha256', None); r['record_sha256'] = hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest(); open(p, 'w', encoding='utf-8').write(json.dumps(r, indent=2, ensure_ascii=False) + '\n')" .openguildkit/decisions/ID.json
   ```

   On Windows, run `python` or `py` in place of `python3`. Then delete the task record, `.openguildkit/tasks/ID.json`: an export from it would write the old name back.

Without the new digest, `check` exits 1 and `guard --ci` reports that the record "was changed after it was exported".

#### The approver

`decision.by`, `decision.payload.by`, `rounds[].decision.by` and `decision.signer` are inside the seal, and so are `requested_by` and `decision.payload.requested_by` when the task names its requester, and in a signed project inside what the approver signed. No path keeps the approval valid under another name:

- replaced without a new seal, `check` and `task list --decisions` report "the seal does not match the approval it records", and `guard --ci` fails under `enforce`;
- with the seal recomputed (and the payload's `shared_sha256` too, when an earlier round names them), which anyone can do for a local approval, `check` passes, but `guard --ci` compares the record with the base branch and reports "task ID already had another approval on the base revision";
- in a signed project, a recomputed seal no longer matches the signature ("The signature does not verify for PRINCIPAL"); if the approver signs the new payload, `check` passes and `guard --ci` still reports another approval;
- `task export` rebuilds the record from the task record, where the name is sealed: replacing it there makes the export refuse, and exporting the unchanged task writes the old name back.

So the approver's name stays, or the record changes in a pull request whose `guard --ci` fails under `enforce`: merging it anyway is up to whoever may bypass that required check. Later pull requests check only the records they change. A pull request that only deletes a record passes `guard --ci`: the approval then has no record in the branch, only in its history.

#### In the history

Earlier commits keep every replaced name. Removing them means rewriting the repository's history with a Git tool, outside OpenGuildKit. An approved task not yet completed whose approved commit leaves the history must then be consulted again; a completed task's record stays as history ([when an approval no longer holds](workflow.md#when-an-approval-no-longer-holds)). This was not tried.

### When an approver leaves

In a signed project, `check`, `task list --decisions` and the commands that read an approval verify each signature against `approval.approvers` and the allowed signers file as Git holds them at `HEAD`. When the signer is no longer in either, the approval is verified against `approval.approvers` in `.openguildkit/project.json` and the allowed signers file as Git holds them at the revision the approval was signed at: `task decide` records that revision in what the approver signs, and verifies the signature against the signers file committed there. The approval holds when that revision is in the history of `HEAD` and on the merged branch (`origin/HEAD`, or else the branch's upstream), both files are committed in it, and the signature verifies against them. `task list` and `check` say so, with the signer and the revision. A revision only a local branch holds does not count: a key an agent committed and then reverted approves nothing ([signed approvals](workflow.md#signed-approvals)).

So remove a departed approver's principal from `approvers` and their key from the allowed signers file, and commit both: what they approved while they were an approver keeps holding, and `task decide` refuses their new signature ("PRINCIPAL is not an approver for this project"). `guard --ci` verifies a record that a pull request brings against the approvers and signers of its base revision, unless the base revision already carries the same approval: a departed approver's new record fails it. A record they signed by hand with an old revision passes `check` on a copy that holds it, and fails `guard --ci` in the pull request that brings it.

An approval signed with a dirty working tree is verified the same way, against the committed files of its revision. A signed clearance carries no revision: the clearance of a verification blocker is verified again by `task verify` and `task complete`, against the current approvers and signers file only. Complete such a task before removing the approver who cleared it, or have a current approver clear the blocker again. Rewriting the history so that the approval's revision leaves it ends the fallback, as it ends the approval of a task not yet completed.

### In the task records and the shares register

Both are ignored by Git and stay on the machine that wrote them. Delete a task record once the task is completed and its record exported: `task list --decisions` still reads the exported record, but `task show`, `docs export` and `task export` of that task no longer can. Keep a share in the register until its access is removed in Documentalist and recorded with `docs share revoke`; then delete its entry from `shares.json`. Delete the matching space entry from `portal-observations.json` or delete the file when the comparison is no longer needed. The next verification recreates it.

### In the browser

Empty the field in the page, or clear the site data of the `ogk-….localhost` addresses in the browser.

## What was tried

On a test project in a temporary folder: a Git repository with local approvals and `"guard": "enforce"` on the base branch, one task approved by "Camille Martin", a blocker cleared and the task closed by "Alex Moreau" (fictional names), exported and committed. Each change below was committed on a branch of its own, then checked with `openguildkit check`, `openguildkit task list --decisions` and `openguildkit guard --ci --base BASE`.

| Change | `check` | `guard --ci` |
|---|---|---|
| In the record, the owners, `closing.by` and the blocker's `by` replaced, digest kept | exit 1, "was changed after it was exported" | exit 1, same message |
| The same, digest recomputed | exit 0 | exit 0, "Covered by the decision of task request-status" |
| In the record, the approver replaced, seal kept | exit 1, "the seal does not match the approval it records" | exit 1, same message |
| In the record, the approver replaced, seal and digest recomputed | exit 0 | exit 1, "already had another approval on the base revision" |
| The record deleted | exit 0 | exit 0 |
| In the task record, the owners and `closing.by` replaced, then `task export` | exit 0 | exit 0; the blocker's `by` keeps the old name |
| In the task record, the approver replaced, then `task export` | the export is refused: "The record of request-status no longer matches what was approved" | |
| The record from the second line, then `task export` from the unchanged task record | the old name is back in `closing.by` | |

On a second test project with signed approvals (a key made with `ssh-keygen -t ed25519`): with the approver replaced and a new seal, `task list --decisions` reported "The signature does not verify for camille@example.test"; signed again with the same key, it accepted the record, and `guard --ci` still reported "already had another approval on the base revision". Before 22 November 2026, with the principal `camille@example.test` replaced by `AM` in the allowed signers file and in `approvers`, `task list --decisions` reported "camille@example.test is not an approver for this project. Approvers: AM." and `check` exited 1. Since then the record holds, and a new approval signed by `camille@example.test` is refused (`tests/test_decisions.py`, `test_an_approval_signed_by_a_departed_approver_keeps_holding`).

In `project.json`, `declined[].by` and `changes[].by` replaced by hand: `check` exited 1 on the managed block of `AGENTS.md` until `openguildkit sync`, then 0.
