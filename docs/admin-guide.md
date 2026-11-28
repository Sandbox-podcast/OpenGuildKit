# Administration guide

For: an administrator or a tech lead who rolls OpenGuildKit out to a team or to many repositories, runs it, and answers an incident. Every command below is typed by a person; none is run by the agent for them.

This guide follows the order of the work and sends to the page that holds the detail. The commands are read by `tests/test_doc_pages.py`: each one must be accepted by the CLI, and each link must lead to a page and a heading that exist.

## 1. Install on each workstation

Install a given release on every workstation, with its hash checked, and pin the version: [install a GitHub release](install.md). Check `openguildkit --version`. The hooks of a host call `openguildkit` by name, so the command must be on the PATH of the process that starts the agent (`pipx` or `uv tool install` put it there). [Troubleshooting](troubleshooting.md) names the refusal when it is not.

## 2. Set up the first repository

```bash
openguildkit init
openguildkit host apply
openguildkit check
```

`init` asks the questions of the setup and writes the profile, `AGENTS.md` and the catalog lock. `host apply` writes the settings and hooks of the agent host the profile names. `check` must pass before the team commits `AGENTS.md`, `.openguildkit/project.json` and `.openguildkit/catalog.lock.json`.
[The profile, field by field](profile-reference.md); [what the host enforces](../integrations/README.md#what-the-host-enforces); [what each host and surface covers](host-coverage.md).

## 3. Give the same profile to N repositories

```bash
openguildkit profile export > answers.json
openguildkit init --answers answers.json
```

Run the first command in the repository that holds the profile and the second in each other repository. The export carries the patterns, packs, boards, guard and conventions.
People's names, the history of changes, the signers file, component paths and check commands stay behind, and a setting that names a person or lowers a protection is typed again by a person at a terminal there ([reuse the profile](workflow.md#reuse-the-profile-in-another-repository)). `init --answers` needs `norms` when `personal_data` is `yes` ([troubleshooting](troubleshooting.md#setup)).

## 4. Require the check in CI

`openguildkit guard --ci` and `openguildkit check` are the controls of a pull request.
Start from the [guard workflow template](../integrations/github/openguildkit-guard.yml), pin the release, and protect the check from the change it judges: list `.github/workflows/` in `CODEOWNERS`, or require the workflow from an organization ruleset ([protect the check](../integrations/README.md#protect-the-check)). Start with `"guard":
"observe"`, which flags an edit without refusing it, and move to `enforce` once the team follows the path. Code 1 of `check` and `guard --ci` means a problem or a command that could not evaluate: [exit codes](exit-codes.md).

## 5. Make approvals verifiable

A local approval detects an accidental edit and proves nobody. When the guard enforces, require signed approvals at a terminal:

```bash
openguildkit profile set approval signed --signers .openguildkit/allowed_signers --approver CM --by INITIALS --reason WHY
```

Repeat `--approver` for each approver, add the key of each to the allowed signers file, and commit both ([signed approvals](workflow.md#signed-approvals)). An approver joins by the same two edits.
An approver leaves by removing their principal from `approvers` and their key from the file: what they approved keeps holding and their new signature is refused ([when an approver leaves](personal-data.md#when-an-approver-leaves)).

## 6. See all the repositories

```bash
openguildkit projects ~/code
```

One line per project: the guard mode, whether approvals are signed, the tasks by status, the approvals that no longer hold and the open points. `projects` writes nothing ([several projects at once](workflow.md)).

## 7. Upgrade

Install the new release, then in each repository:

```bash
openguildkit update
openguildkit update --apply
openguildkit check
```

`update` shows what the installed catalog would change, rule by rule, and names the tasks it touches; `update --apply` adopts it once the team agrees ([upgrade](install.md#upgrade)). Which versions receive fixes, and what a team may rely on across versions: [support policy](support.md).

## 8. React to an incident

| What happened | What to do |
|---|---|
| An approval must stop holding | The person who approved runs `openguildkit task revoke ID --by INITIALS --reason WHY`, then `openguildkit task export ID` and commits the record: `guard --ci` then refuses it ([task workflow](workflow.md)) |
| An agent wrote outside an approved scope | `guard --ci` refuses the pull request when no valid record covers the file. Review the change against the approved brief and open a new task for what is outside it |
| A key may be compromised | Remove the principal and the key as in step 5 and commit; a new signature of that principal is refused |
| A credential or a name reached a record | [Personal data](personal-data.md) says where each field is kept and how to replace a name |
| A vulnerability in OpenGuildKit | Report it privately, as [SECURITY.md](../SECURITY.md) says; never in a public issue |

What OpenGuildKit does not cover during an incident (a leaked secret in the repository, an agent that ran outside every hook, a cloud session) is in [host coverage](host-coverage.md) and in the [threat model](threat-model.md).
