# Requester and approver

For: an administrator who separates the requester from the approver.
A part of the [task workflow](../workflow.md).

RFC #445 asks whether the person who asks for a change may also approve it.
Until the project decides, OpenGuildKit offers an option, `separate-requester`, which is off in every project: a project that leaves it off behaves exactly as before, and its task records, sealed and signed approvals and exported records read and verify as they did.

## Record who asked

`task new` takes the person who asked for the work, whether or not the option is on:

```bash
openguildkit task new "Add a retry to the export job" --id export-retry --requested-by "Ann Lee"
```

The task records `requested_by`; the decision brief (the approval prompt, `task challenge` and `task decision-payload`) shows `Requested by Ann Lee.`; the approval's seal covers it, so a requester changed in the task file voids the approval; and `task export` writes `requested_by` in the record and in its payload.
A task opened without `--requested-by` records nothing and seals what it sealed before.

## Turn it on

A person types it at their terminal, with who and why, and types `on` to confirm:

```bash
openguildkit profile set separate-requester on --by CM --reason "The person who asks does not approve"
```

Turning it on or off changes who may approve, so both follow the rule of every setting that touches the protection (`light-paths`, `approval signed`): a person at an interactive terminal, a typed confirmation, and an agent without a terminal is refused with the command to type and nothing is written.
The web page cannot change it either.
The profile keeps who, when and why in `changes`, AGENTS.md tells the agent to open each task with `--requested-by`, and `profile export` does not carry it (it prints the command to type in the other repository).
The option is not part of what an approval rests on, so turning it on or off voids no approval.

## What it enforces

- **`task new`** refuses a task without `--requested-by NAME` and writes nothing.
- **`task decide --approve`** refuses an approval whose `--by` names the requester, compared without case or spaces (`Ann Lee`, ` ann  LEE ` and `AnnLee` are the same person), and says to have another person approve it.
  `task decision-payload` refuses the same name before anyone signs.
  A request for changes stays open to the requester.
- **A task opened before the option** names no requester and cannot be approved while the option is on: open the work again with `--requested-by`.
- **Signed approvals** also compare the requester to the signer's principal (`--signer`).
  In a project with signed approvals, `task new` takes as `--requested-by` only a principal of the allowed signers file (a pattern such as `*@ops.example.org` counts), read from the working copy, and refuses `Ann Lee` with the principals it knows: a requester who signs as `ann@example.org` is recorded as `ann@example.org`, so the comparison is exact.
- **The seal** of an approval given with the option on records `"separate_requester": true`, and the exported record carries it in `decision`.
- **`guard --ci`** reads the option at the base revision, as it reads `light_paths`, so a pull request cannot turn it off for itself.
  When it is on there, a record whose approver (`by`, or the signer) is its requester is refused (`decision-requester-approved`), and so is a new record that names no requester (`decision-requester-missing`).
  A record whose `requested_by` differs from the sealed one is invalid (`decision-record-invalid`).
- **Tasks for dependency alerts** (`alerts tasks --open`) name `openguildkit alerts` as their requester when the option is on: the watch asked for them, and any person approves them.
