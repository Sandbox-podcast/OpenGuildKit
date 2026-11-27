# Exit codes

For: the person who writes a CI job or a script around `openguildkit`, and the agent that reads its result.

Read the code of a command in two steps: the general rule below, then the table of the commands that depart from it. The table is read by `tests/test_exit_codes.py`, which runs one case for each row.

## The general rule

| Code | Meaning |
|---|---|
| 0 | Success, also when the reader of the output stops early, as `head` does in a pipe |
| 1 | The command refused or found a problem: a validation or state error (message on stderr, prefixed `OpenGuildKit:`), or a check that failed |
| 2 | A usage error of the command line (an unknown option, a missing argument), printed by the parser |
| 130 | Cancelled with Ctrl+C |

Code 1 covers two different things on most commands: the project does not conform, or the command could not evaluate it. The message on stderr tells them apart, not the code. The only commands that give a code of their own to a command that could not run are `ci-check` (2) and `tools apply`.

## The commands that depart from it

| Command | Code | Meaning |
|---|---|---|
| `guard --hook` | 2 | Refused: an agent's edit tool is about to change a file and no approved task covers it, in `enforce`. The hosts read 2 as "block"; 1 would not stop the edit. In `observe` the hook exits with 0 and flags the edit. |
| `guard --ci` | 1 | Problem: a changed file is covered by no valid decision record, or a record fails its checks, in a project whose guard enforces. |
| `guard --ci` | 1 | Not evaluated: Git has no such base revision, the folder is not a Git repository, or the profile cannot be read. Nothing tells it from a problem but the message (and, with `--format sarif`, the absence of a file: [SARIF output](sarif.md)). |
| `check` | 1 | Problem: the instructions, the host settings, the catalog lock or an approval do not match the profile. |
| `check` | 1 | Not evaluated: the folder is in no OpenGuildKit project (`No OpenGuildKit project found`), or the profile cannot be read. |
| `ci-check` | 2 | Not evaluated: any error of the evaluation (the pack is not selected in the trusted profile, an unreadable file, a Git failure). `ci-check` exits with 0 when the commit conforms or the profile only observes, and with 1 when the rule fails under `--enforce` or a required profile. The coordinator's `check` and `gate` use the same codes ([CI coordinator](../integrations/ci/README.md#results-and-errors)). |
| `tools apply` | 2 | Partial: some requested tools are connected and others are not; the last line lists the others. 0 when every tool is connected, 1 when none could be or the command was refused. |
| `host scan --strict` | 1 | Finding: any finding, a note included. Without `--strict`, only a finding of level `error` gives 1. |
| `task verify` | 1 | Failed: a mandatory check command failed. 0 when only answers remain to give. |
| `docs share check` | 1 | Expired: a share not recorded as revoked is past its last day of access, or one deliverable shares a space with another. |

## What each stream carries

Standard output carries the result the command was asked for; a redirected result holds nothing else. Standard error carries the errors, the warnings (`Warning: ...`), the notes and the next step. `tests/test_error_forms.py` fails when a `Warning:` line is printed to standard output.
A list that is empty says so on one line (`No share recorded.`), and an error about a file names it in words, never as the `[Errno 2]` text of Python.

## Open decision

A job cannot tell a project that does not conform from a command that could not evaluate it on `check`, `guard --ci` and `host scan`: both give 1. Reserving a distinct code, such as 3, would change what every existing job reads. The maintainer decides; until then, read the message on stderr, or the `ci-check` convention above.
