# Troubleshooting

For: an administrator or a developer who reads a refusal of `openguildkit` and wants to know the cause and the next command, and the agent that meets one.

Each row starts with the beginning of a message as the CLI prints it, after the `OpenGuildKit: ` prefix. `tests/test_doc_pages.py` fails when a message of this page is no longer in the code. A command prints its error on standard error and exits with 1; [exit codes](exit-codes.md) lists the exceptions.

## Setup

| Message | Cause | What to do |
|---|---|---|
| `No OpenGuildKit project found for` | The command ran in a folder under no `.openguildkit/project.json` | `cd` into the project, or pass `--project PATH`. Run `openguildkit init` only to set up a new project |
| `Project is already initialized.` | `init` ran in a project that has a profile | Change the profile with `openguildkit profile` ([profile reference](profile-reference.md)) |
| `needs a terminal or --answers PATH.` | `init` or `task consult` ran without a terminal and without an answers file | For `init`: run `openguildkit init --questions`, write the answers, then `openguildkit init --answers FILE`. For `task consult`: `openguildkit task questions ID`, then `--answers FILE` |
| `Ask the person about each norm the project meets` | The answers say `personal_data` is `yes` or `unsure`, or another answer proposes a norm, and `norms` is missing | Paste the `"norms": {...}` object the message prints into the answers file; decline a norm with `{"answer": "no", "by": "NAME", "reason": "WHY"}` |
| `Cannot open` | A file named in the command does not exist or cannot be read | Check the path given to `--file`, `--answers` or the argument; the message names the file |

## Host settings and the guard

| Message | Cause | What to do |
|---|---|---|
| `The host settings do not enforce:` | The profile names a host and its settings or hooks are absent | `openguildkit host check` gives the cause, `openguildkit host apply` writes the settings |
| `is not on this workstation's PATH` | The hooks call `openguildkit` by name and the command is not on the PATH of the process that starts the agent | Install the CLI with `pipx` or `uv tool install`, or start the agent from the activated environment. `host apply` cannot fix it ([what the host enforces](../integrations/README.md#what-the-host-enforces)) |
| `no approved task covers new work in this project` | In `enforce`, an agent tried to edit a file and no approved task covers the work; the hook ends the sentence with `Edit refused for: FILE` | Open a task (`openguildkit task new BRIEF`), consult the boards, and have the person approve it. In `observe` the same sentence flags the edit without refusing it |
| `guard is enforce but approvals are not signed` | The guard enforces and the approvals are sealed locally, which an agent that can write files could forge | A person runs `openguildkit profile set approval signed ...` at a terminal ([signed approvals](workflow.md#signed-approvals)) |
| `Approval requires a person at an interactive terminal.` | `task decide --approve` ran from a pipe, a script or an agent | The person runs it in their own terminal and types the task ID |
| `not found: pass --base REF` | `guard --ci` could not find its base revision, `origin/main` by default, as in a shallow clone | Fetch the base branch, or pass `--base REF` |

## Tasks and results

| Message | Cause | What to do |
|---|---|---|
| `Unknown task:` | No task has this ID; the message gives the closest ID when one is near | `openguildkit task list` |
| `Run checks for an approved task that is not done yet` | `task verify` ran on a task that is not approved, or already closed | `openguildkit task show ID` gives the status and the next command |
| `Results belong to an approved task that is not done yet.` | `task result` ran before the approval, or after the closing | Approve the task first, or open a linked task with `task new --follows` |
| `The result has` | A result file has several problems; the message lists each under its entry (`criteria[1]`, `checks[2]`) | Fix every line, then run `task result ID --file FILE` again; `task result ID --template` shows the shape |
| `Project files changed since the approved revision` | The work changed project files and the result names neither a revision nor a pull request | Add `revision` (a commit SHA) or `pull_request` to the result |
| `The task changed meanwhile. Retry.` | Another command wrote the task between the read and the write | Run the command again |

## Catalog and CI

| Message | Cause | What to do |
|---|---|---|
| `The catalog lock does not match the profile.` | The profile changed after the lock was written | `openguildkit sync` |
| `Run openguildkit update` | The instructions follow a newer catalog than the lock, or the installed catalog changes locked rules | `openguildkit update` lists the changes, `openguildkit update --apply` adopts them ([upgrade](install.md#upgrade)) |

When a message is not here, run `openguildkit check` for a project that does not conform, and read [the task workflow](workflow.md) for the status a command needs.
