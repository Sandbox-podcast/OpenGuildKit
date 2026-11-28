# 4. Decide

For: the person who decides on a change, and the agent that prepares the decision.
Step 4 of the [task workflow](../workflow.md).

The person runs the command in their own terminal:

```bash
openguildkit task decide request-status --approve --by CM --reason "Read-only scope agreed with support"
```

`--by` takes the person's initials or team handle, here `CM`, rather than their full name: the record and the seal keep it, and it cannot be replaced afterwards without breaking the approval ([personal data](../personal-data.md)).

The CLI prints the same lines as the decision brief (starting with the verdict count), then the task brief, the review summary with each board's verdict, recommendation, verification, blockers and open questions, the command that prints the full decision brief (`task challenge ID`), the verdict count again, and asks the person to type the task ID,
then the name of each sensitive board the agent removed.
One function writes the lines of the decision brief, so the prompt, `task challenge` and `task decision-payload` show the same ones:

- the verdicts, and the review warnings: two boards or more that give the same recommendation or finding once each board's name is taken out (advice written once and pasted from board to board), a board whose every finding cites one and the same evidence item, a board with no observed finding;
- the conditions of approval, blockers and their resolutions, board removals, open points and objections;
- each check command `task verify` will run as a shell command after the approval, then each command added or removed since the last approval of the project, with who changed it, when and why from the profile's history (or a note that the profile was edited by hand);
- each confirmed critical dependency alert of the task that an import resolved since its last decision, with the report that resolved it ([dependency alerts](../alerts.md#a-report-that-analyzed-nothing)).

`task review` and `task submit` print the same warnings on copied advice as they record it.
The approval records the base Git revision and a seal over what was approved; a project that requires signed approvals verifies the approver's SSH signature instead of the typed ID ([details](../architecture.md#design-decisions)).
Approval fails when stdin is not a terminal, when the typed ID does not match, when the task changed during the decision, when the profile or catalog changed since the consultation, or when `AGENTS.md` is out of date.

A blocker names the finding, its `owner` and `clears_when`, the condition that would clear it.
Use a condition you can verify before implementation.
If the evidence requires code or a test result from the implementation, set `"phase": "verification"` in the blocker.
Approval can proceed while verification blockers are open.
The handoff lists them, `task verify` reports them, and `task complete` waits for their resolution.

Use these commands to list and resolve blockers.

```bash
openguildkit task blockers ID
openguildkit task clear ID security:1 --evidence tests/test_access.py --supports "Cross-account access is refused" --by AM
openguildkit task waive ID security:2 --by CM --reason "Internal pilot only" --scope "Internal users" --until 2026-12-15
```

Clearing is the person's act: the agent proposes the evidence, and the person runs `task clear` in their own terminal and types the task ID to confirm (in a project with signed approvals, their signature replaces the typed ID).
Without a terminal the command checks the evidence and is refused.
Clearing records who cleared, the evidence and what it establishes.
Use an existing project file or folder, or an HTTPS link.
A second attempt to resolve the same blocker is refused and the first resolution stays in place.
The decision brief and the approval prompt show each blocker of phase `verification` as a condition of the approval, and the handoff lists the open ones first.
A waiver requires a project waiver policy (`openguildkit profile set waivers allowed --allowed-by NAME --max-days DAYS`, typed by a person), the named person at a terminal, a reason, a scope and an end date within the limit.
The handoff lists each waiver with its scope and end date.
A waiver holds through its end date, a UTC day, by the real clock (`SOURCE_DATE_EPOCH` does not change it); the next UTC day its blocker is open again: `task blockers` shows `[waiver expired on DATE]`, a reviewed task cannot be approved until the blocker is cleared or waived again, and for an approved task `task list` names what the person can do.
A condition of approval is cleared with its evidence, waived anew (the new waiver keeps the expired one under `replaces`) or the approval withdrawn; a blocker the approval rested on is under the approval's seal, so the person withdraws the approval and the task is consulted again.
`task complete` refuses a task with an expired waiver, and `guard --ci` refuses the record of a task not completed whose waiver expired; a completed task's record is history.
Without a waiver policy, `task waive` names the steps the task can still take: clear the blocker with its evidence, or, before the decision, request changes; for a condition of an approved task, withdraw the approval (`task revoke`, below) when it cannot be met.
`task list` says so for an approved task whose condition is still open.

In a project with signed approvals, `task clear` follows the rule of `task decide`: `--by` names the person, and the signature must verify for `--signer`, an approver of the project; the record keeps both.
Run the command with `--payload clearance.json`, sign that file with `ssh-keygen -Y sign -n openguildkit-decision -f KEY clearance.json`, then rerun the same command with `--signature clearance.json.sig --signer PRINCIPAL` in place of `--payload`.
The signature covers the blocker, its consultation, the person named by `--by`, the evidence and what it establishes.

After upgrading the board catalog, `openguildkit update` names the tasks the change touches before `--apply`, and `update --apply` and the `sync` after it name the same ones, each with what to do:
consult a consulting task again, request changes on a reviewed task and consult it again, consult an approved one again with `task consult ID --reuse-answers`, which keeps the passes of unchanged boards when the approval's seal holds and none for an approval without a valid seal (or open a linked task with `--follows`).
A completed task keeps its record as history and is not listed.

To send the task back:

```bash
openguildkit task decide request-status --request-changes --by CM --reason "Include the empty state in scope"
```

This works without a terminal.
The next `task consult` (`task consult ID --reuse-answers` keeps the recorded answers) archives the previous brief, answers, consultation, review and decision in `rounds`, so the history of the task is kept.
When the change request changes the scope, revise the brief at that consultation, so the approval shows what is approved:

```bash
openguildkit task consult request-status --answers answers.json --brief "Show the status and the empty state of each request"
```

The revised brief is checked like the brief of `task new`.
The approval prompt and `task challenge` of the new round open on one line that recalls the previous round's decision, who made it, when and why, and whether the brief was revised since.

## When an approval no longer holds

One function judges an approval, and every reader prints its answer: `task list`, `check`, `task consult`, `handoff`, `verify`, `result`, `complete`, `export` and the guard.
An approval holds while its seal matches the record, its signature verifies (in a project with signed approvals), the rules, checks and boards of the profile are those it was given under, and the Git revision it was approved at is still in the project history.

Only a change of the rules, the checks or the boards voids an approval: packs and their rules, the sector, the stack, components and patterns, the check commands, the boards, roles and required reviews, the personal-data and people-decision answers, and `ask_every_rule`.
A new convention or tool, the guard mode, the host, the research setting, the approval mode, the waiver policy or the paths of the short lane leave approvals standing (the approval mode and the allowed signers are read again by every reader, through the signature).
An approval recorded by a release older than sealed decisions (0.16.1 and earlier) has no seal, so it no longer holds: until the task is consulted again, `check` exits 1 on it and `handoff`, `verify`, `export` and `complete` refuse it.
Consulting it again keeps no pass, and a completed task keeps its record as history.

After a rebase, a squash or an amended commit, the approved revision leaves the history: every reader says so and names the same command, `task consult ID --reuse-answers`, which consults the task again with the answers it holds and needs no terminal (`--answers FILE` with it replaces the answers the file gives;
a task consulted before the `concerns` question existed is asked it at a terminal, and without one is consulted as `unsure`, which keeps every topic's rules open, with a line that says so).
The task is consulted again under the same ID: `task consult` keeps the earlier approval in `rounds` with the reason, and keeps as done the passes of the boards whose brief, rules and entry template did not change, so only the others review again (`task pass ID BOARD --again` redoes a kept one).
The decision brief lists the kept passes, and the person approves again.
The same applies when the rules changed: the boards whose rules changed review again.
A broken or missing seal keeps no pass.

## Withdrawing an approval

The person withdraws an approval in their own terminal, as they gave it, and types the task ID to confirm:

```bash
openguildkit task revoke request-status --by CM --reason "The test account the condition needs cannot be created"
```

The task goes back to `changes-requested`: the approval goes to `rounds` with who withdrew it, when and why, and the guard no longer counts the task in `covered_by`.
An exported record of that approval still says approved, and `guard --ci` would keep accepting it: `task revoke` names the file, and `check` (exit 1) and `task list --decisions` report it until `task export ID` writes the withdrawal into it (`withdrawn`, with who, why and when; the approval stays as it was and `record_sha256` is computed again).
Commit the record: `guard --ci` refuses it, and once it is on the base revision, refuses a copy of the same approval made before the withdrawal.
`task list --decisions` shows it as withdrawn, a note that does not fail `check`.
`task export` of a withdrawn task without a record writes nothing and says so.
Then consult the task again, or close the work in a linked task with `--follows`.
Without a terminal the command is refused, and `host apply` adds it to the agent's deny rules, like `task decide`; the web interface never runs it.
A completed task keeps its approval as history.
The guard puts no time limit on an approval: withdrawing it is how an abandoned task stops covering edits, and `task list` names the command for an approval older than 14 days with no result recorded.

## Signed approvals

A local approval is sealed with a SHA-256 of data that all sits in the task file.
The seal detects an accidental edit; it does not prove who approved, because anyone who can write the file can recompute it.
With `"guard": "enforce"`, `init`, `host check` and `check` say so in one line until a person requires signed approvals at their terminal, with `openguildkit profile set approval signed --signers .openguildkit/allowed_signers --approver CM --by INITIALS --reason WHY`.
The profile then holds:

```json
"approval": {"mode": "signed", "allowed_signers": ".openguildkit/allowed_signers", "approvers": ["CM"]}
```

The allowed signers file uses the `ssh-keygen` format, one line per approver: `CM ssh-ed25519 AAAA...`.
The principal, here `CM`, is any word: initials keep an email address out of a file the team commits, and a record stays verifiable only while its principal remains listed ([when an approver leaves](../personal-data.md#when-an-approver-leaves)).
Commit it: a signature is verified against the file as Git holds it at `HEAD`, never against a working copy ([what protects it](../architecture.md#design-decisions)).
The approver then decides in three steps:

```bash
openguildkit task decision-payload request-status --by CM --reason "Read-only scope agreed" --output decision.json
ssh-keygen -Y sign -f ~/.ssh/id_ed25519 -n openguildkit-decision decision.json
openguildkit task decide request-status --approve --by CM --reason "Read-only scope agreed" --signature decision.json.sig --signer CM
```

`task decision-payload` prints on stderr the lines of the approval prompt (verdicts, warnings, conditions of approval, removals, check commands), and the file to sign carries the brief and the review summary in clear next to the digests, so the approver reads what they sign.
`task decide` with a signature prints the same lines.
Approvals signed over the payload of earlier releases, without the brief and summary, still verify.

A key protected by a passphrase or a hardware token keeps the agent from signing.
The handoff, `task export`, the guard and the CI check refuse an approval without a valid signature; CI verifies it against the allowed signers of the pull request's base revision.

What signed mode is worth depends on where the check runs:

- **In CI** (`guard --ci`), the approvers and the signers file come from the base revision, which the pull request cannot change: a key the change adds signs nothing there, and a record the base revision does not carry is verified against today's approvers only.
  This is the check that holds against an agent that can write files and commit.
- **In a local copy** (`task list`, `check`, the edit hook, `handoff`), a signature is verified against the signers file committed at `HEAD`.
  An agent that commits its own key to that file and to `approvers` can sign an approval that holds locally while the key is there; the pull request then shows the change to the signers file, and CI refuses the approval.
  When the key is gone from `HEAD` again, the approval holds only through the revision it was signed at, and that revision counts only when the merged branch contains it: `origin/HEAD` (the remote's default branch, which `git clone` sets; `git remote set-head origin --auto` sets it otherwise), or else the branch's upstream.
  A key committed and reverted on a local branch therefore approves nothing, and `task list` names the signer and the revision of every approval that holds this way.
  Local Git references can still be rewritten by whoever has a shell in the repository: locally, signed mode stops an edited file and a key that was never reviewed, and CI on the base revision is what decides.

## Certificates of an authority

Instead of one key per approver, the allowed signers file can trust an SSH authority, the one the company runs behind its single sign-on: one line, `PRINCIPAL cert-authority ssh-ed25519 AAAA...` (the authority's public key).
The approver signs in to the directory, the authority gives them a short certificate for their principal, and they sign with it: `ssh-keygen -Y sign -f ~/.ssh/id_ed25519-cert.pub -n openguildkit-decision decision.json`.
`task decide` and every reader verify it with `ssh-keygen -Y verify`, which checks the authority's signature, the principal, the namespace and the validity of the certificate.
An approver who leaves loses the right to sign when the authority stops issuing: no commit in each repository.
A test signs and verifies with a certificate (`tests/test_decisions.py`).

What it proves: the signature was made with a key that the committed signers file's authority certified for that principal, and the certificate was valid when it was checked.
What it does not prove: what the authority checked before issuing it, that a person and not a program held the key (a passphrase or a hardware token still decides that), or when the person signed.

Verified now, a certificate that expires voids every approval already recorded.
An approver who wants to avoid that adds the time they sign at to the payload:

```bash
openguildkit task decision-payload request-status --by CM --reason "Agreed" --signed-at --output decision.json
ssh-keygen -Y sign -f ~/.ssh/id_ed25519-cert.pub -n openguildkit-decision decision.json
openguildkit task decide request-status --approve --by CM --reason "Agreed" --signature decision.json.sig --signer CM --signed-at 2026-11-27T10:15:30Z
```

`--signed-at` alone writes the current UTC time in the payload; `task decide` takes the same value, in `YYYY-MM-DDTHH:MM:SSZ`, and verifies it because the approver signed it: a changed `signed_at` breaks both the signature and the seal.
Without `--signed-at`, nothing changes.
`task decide` always verifies at the current time, so a key or a certificate that has expired signs no new approval, and refuses a `signed_at` in the future.
An approval already recorded (`task list`, `handoff`, `guard --ci`) is verified at its `signed_at`: it keeps holding after the certificate expires, while the approvers and the signers file it is checked against are unchanged.
`guard --ci` also refuses a new record whose `signed_at` is more than five minutes after the commit that first brings the record (`decision-signed-late`).

`signed_at` is what the signer states.
Someone who still holds an expired certificate and its key can sign a payload that claims an earlier time, and the check accepts it if the time falls in the certificate's validity and is not later than its commit: no clock proves otherwise.
Keep the certificates short, ask for a passphrase or a token, and review who merges.
