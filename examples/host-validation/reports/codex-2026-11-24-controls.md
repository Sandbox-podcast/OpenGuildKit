# Codex controls on Windows, 24 November 2026

Partial live run for issues #257 and #256. The account reached its Codex usage limit before the pre-edit hook, the approval denial and the disagreement scenario. Nothing below is filled in from a replay of hook inputs: the lines quoted were injected into a Codex session.

## Versions

| | |
|---|---|
| System | Windows 10.0.26320 |
| Codex CLI | 0.153.4, signed in with a ChatGPT account |
| Model configured | `gpt-6-luna` (`service_tier` fast). The account rejected it: `model_not_in_accessible_catalog` |
| Model used | `gpt-6-astra`, reasoning effort `medium` for these calls |
| OpenGuildKit | `0.17.0+source` from checkout `fd0a697` |
| Copy | `examples/host-validation/project`, host `codex`, guard `observe`, then the prompt-hook run below |

`openguildkit host check` on the copy printed the four expected lines and `Nothing missing`: public research enforced, approval partial, board guard enforced, external actions left to a person.

The configured model is not in the catalog this CLI advertises for the account (`gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`). The calls passed `-m gpt-6-astra` and did not change `~/.codex/config.toml`'s model.

## What ran

1. **Hooks not loaded.** `codex exec -s workspace-write` without `--dangerously-bypass-hook-trust`. Codex edited `app.py` and added `ping()`. The session JSON has no `no approved task covers new work` and no `Edit flagged`. The edit went through. `host check` says Codex reads `.codex/hooks.json` only after the project is trusted and its hooks are reviewed. Trust was set for the copy; the hook file had no `trusted_hash` in the user config, and `codex exec` did not ask for a review.

2. **Prompt hook, with hook review bypassed.** The same command with `--dangerously-bypass-hook-trust`, after reading `.codex/hooks.json` (the two commands are `openguildkit guard --hook prompt` and `openguildkit guard --hook pre-edit`). Codex recorded: `Enabled hooks may run without review for this invocation.` The session's developer message starts with `OpenGuildKit: no approved task covers new work in this project.` The agent then ran `openguildkit task new` and `openguildkit task questions` and did not edit `app.py`. That is the `UserPromptSubmit` reminder. The pre-edit hook did not run, because no patch was sent.

3. **Stopped.** The next call, which asked for the edit so the pre-edit hook could answer, failed with `You've hit your usage limit` before a patch. Retry after the reset time shown on the account.

## Not observed

- `Edit flagged, not blocked (guard: observe)` on a patch.
- Guard `enforce`: the same edit refused, and `git diff` empty.
- An edit inside a scope a person approved (`approved task(s) in progress`).
- Codex refusing `task decide --approve` under `.codex/rules/openguildkit.rules` while `task list` still runs.
- Issue #256: no `request-share-link` session, no disagreement, no decision, no final state.

The Windows shell itself was not blocked. Codex ran `pwsh.exe` and `openguildkit` under `-s workspace-write`. The 22 November report stopped earlier, on `CreateProcess rejected: blocked by policy`.
