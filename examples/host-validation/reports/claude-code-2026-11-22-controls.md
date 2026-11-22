# Claude Code, 2026-11-22: the controls that host apply writes, in a live session

Host: Claude Code 2.1.328 (the `claude` command of the desktop application), macOS, started headless with `claude -p ... --model sonnet --permission-mode acceptEdits --output-format stream-json --verbose --include-hook-events --debug-file`. OpenGuildKit from the integration branch of the second audit (commit `459d51d`, `openguildkit 0.17.0+source`), run from source through an `openguildkit` launcher on the PATH. Project: a copy of `project/` outside the repository, committed in a new Git repository, with `host` set to `claude-code` and `guard` to `observe`; steps 1 and 2 of [A live Claude Code session](../README.md#a-live-claude-code-session).

## What the session showed

| Step | Observed |
|---|---|
| Setup | `init`, `integrations --host claude-code` and `host apply` wrote `.claude/settings.json`. `host check` printed `[enforced] The board is consulted before each change`, `[partial] The agent cannot run the approval command` and `[enforced] Public research stays off when the policy is local-only`. |
| Settings loaded | The debug log of the session reads `Adding 31 deny rule(s) to destination 'projectSettings'`, the 31 rules `host apply` wrote (the approval, withdrawal, waiver and allow commands in every documented form, terminal emulators, Python pseudo-terminals, WebSearch and WebFetch, and the edits of the guard's own files). |
| `UserPromptSubmit` | The hook ran before the request reached the model: `Hooks: UserPromptSubmit [openguildkit guard --hook prompt] finished with status 0 (236ms)`, then `provided additionalContext (225 chars)`. The stream holds its answer: `OpenGuildKit: no approved task covers new work in this project. If this request changes the project, open a task first (openguildkit task new BRIEF), consult the boards and wait for the person's approval before editing files.` |
| The request | The model was never called: the command answered `Not logged in · Please run /login` (`apiKeySource: none`). The `claude` command of this machine is not signed in for headless use, and signing in is the person's act. |

## Not observed

- The `PreToolUse` hook on an edit: flagged in `observe`, refused with exit code 2 in `enforce` (steps 2 and 3). No edit was attempted, because the model did not answer.
- The deny rules refusing `openguildkit task decide` under `--allowedTools "Bash"` (step 4): the rules were loaded, but no command was proposed.
- Codex: not run (no Codex tokens).

`tests/test_written_host_controls.py` runs the same hook commands through the shell with the input Claude Code documents, and matches every written deny rule against the person's commands; this report adds that the host loads those settings and runs the request hook. A maintainer signed in to Claude Code completes steps 2 to 4 with the commands of the README and adds the lines they quote here.
