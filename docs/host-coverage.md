# Host coverage

For: a security architect who decides whether the tool may be used, and an administrator who rolls it out.
One page: what is held by a hook, what is not, and what nobody has established.

OpenGuildKit cannot stop an agent from using its tools.
It writes the settings and hooks that some hosts honour, and it checks every pull request in CI.
This page puts side by side, for each host and each surface where an agent runs, what each control does.
[What the host enforces](../integrations/README.md#what-the-host-enforces) gives the detail of each rule; this page is the one to hand to a security committee.

## What holds, in three sentences

- **Whatever the agent.** `guard --ci` refuses a pull request whose changed files no valid decision record covers, under the rules of the base revision.
  Signed approvals are the only approval that resists an agent that can write files.
  Requiring the workflow in the organization's rulesets keeps a pull request from editing the check ([protect the check](../integrations/README.md#protect-the-check)).
- **On a workstation.** The hooks of `claude-code`, `codex` and `gemini-cli` refuse an edit through the host's file-edit tools when no approved task covers it, in `enforce`.
  They do not stop a write by the shell or by a script, a hook that cannot start, or a session where the hooks do not run.
- **What OpenGuildKit does not do.** It makes no call to a model and opens no network connection of its own (one command a person asks for aside), so it chooses no model and prevents no leak at the network level.
  It sets no cost budget: `scripts/agent_cost.py` reads a transcript after the fact, with the four prices written in the script (lines 19 to 22).
  For those, turn to the administration console of the host's vendor and to your network controls.

## Each host and surface

Statuses: `enforced` (a control stops it, as the host documents), `partial` (a control stops it for the tools named and says what gets around it), `instruction` (the agent follows the written instruction and the CI check catches the rest), `none` (no control exists there, as the page read says) and `not established` (no page was read, or the page says nothing: treat it as no control).
A cell `enforced` or `none` names the page read and the day.
The status of a hook is for the edit tools of the host, nothing else.

| Host | Surface | Hook before an edit | Approval command refused | Pages read |
|---|---|---|---|---|
| `claude-code` | Terminal, with `host apply` | `partial`: the hooks run on `Edit`, `Write`, `MultiEdit` and `NotebookEdit`; a write by the shell or by a script is not stopped | `partial`: deny rules match a command line; a script file gets around them | [Hooks](https://code.claude.com/docs/en/hooks) and [permissions](https://code.claude.com/docs/en/permissions), read 2026-11-21 |
| `claude-code` | Editor extension, desktop application | `not established`: the settings page says they read the same files as the terminal; no session was run | `not established` | [Settings](https://code.claude.com/docs/en/settings), read 2026-11-28 |
| `claude-code` | Cloud thread in a project (claude.ai/code) | `none`: none of the repository's `.claude/settings.json` hooks apply | `none`: none of its permission rules apply | [Settings](https://code.claude.com/docs/en/settings), read 2026-11-28 |
| `claude-code` | Cloud session on one repository, outside a project's threads | `not established`: the page says `.claude/settings.json` is read; whether the hook's `openguildkit` is installed in the cloud environment is not | `not established`: the page says the file is read; no session was run | [Settings](https://code.claude.com/docs/en/settings), read 2026-11-28 |
| `claude-code` | Cloud session on several repositories | `none`: only `enabledPlugins` and `extraKnownMarketplaces` are read from each `.claude/settings.json` | `none`: permission rules are not read | [Settings](https://code.claude.com/docs/en/settings), read 2026-11-28 |
| `claude-code` | Action or headless run in CI | `not established` | `not established` | None read |
| `codex` | Terminal, trusted project, with `host apply` | `partial`: `.codex/hooks.json` runs before `apply_patch`; Codex reads project settings only once the project is trusted | `partial`: `.codex/rules/openguildkit.rules` forbids the commands as written, and an exact prefix does not match `--project /other/path` | [Rules](https://learn.chatgpt.com/docs/agent-configuration/rules) and [hooks](https://learn.chatgpt.com/docs/hooks), read 2026-11-21 |
| `codex` | Cloud, CI | `not established` | `not established` | None read |
| `gemini-cli` | Terminal, with `host apply` | `partial`: the hooks on `BeforeAgent` and `BeforeTool` cover `write_file` and `replace`; a hook that cannot start lets the action through | `instruction` | [Hooks](https://geminicli.com/docs/hooks/), [hooks reference](https://geminicli.com/docs/hooks/reference/) and [configuration](https://geminicli.com/docs/reference/configuration/), read 2026-11-25 |
| `gemini-cli` | Non-interactive mode, IDE, GitHub Action | `not established`: the pages say nothing about them | `not established` | [Hooks](https://geminicli.com/docs/hooks/), read 2026-11-25 |
| `cursor` | Any | `none`: no page shows the file an edit tool changes, so no hook is written | `instruction` | [Hooks](https://cursor.com/docs/agent/hooks), read 2026-11-26 |
| `copilot` | Any, including the cloud agent | `none`: no page shows the file an edit tool changes, so no hook is written | `instruction` | [Hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference) and [Copilot CLI hooks reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference), read 2026-11-26 |
| Any other agent (`other`) | Any | `instruction`: the AGENTS.md instruction and `guard --ci` | `instruction` | Not applicable |

No host was started in a live session to check these settings: the hooks are run through the shell with the input each host documents (`tests/test_written_host_controls.py`, `tests/test_gemini_host.py`).
A row that says `partial` is a claim about the documentation, not about a session.

### What the Claude Code page says about a cloud session

Read again on 2026-11-28 at https://code.claude.com/docs/en/settings, section "Settings in cloud sessions".
It says that "in a cloud thread in a project, none of a repository's `.claude/settings.json` permission rules, hooks, or `env` apply".
It says that a session with one repository outside a project's threads reads `.claude/settings.json`, as part of the clone, and that a session with several repositories reads only `enabledPlugins` and `extraKnownMarketplaces` from it.
It also says that "a `managed-settings.json` file or MDM profile on your device doesn't reach a cloud session", while the organization's server-managed settings do.

OpenGuildKit writes its hooks and deny rules to `.claude/settings.json`.
In a cloud thread of a project, and in a session on several repositories, neither applies, and the pull request check (`guard --ci`) is the only barrier there.
In a session on one repository, the file is read, but the hook runs `openguildkit`, and whether the cloud environment has it installed is not established: count on `guard --ci`.
A managed settings file deployed by `host managed` does not reach any cloud session.

## Agents launched in CI

An agent that runs in CI writes to a branch like any other; the barrier is the pull request check, which runs in a trusted workflow and not on the agent's machine.
`guard --ci` reads the mode, the profile and the allowed signers from the base revision, so a pull request cannot loosen the rules it is judged by.
On `pull_request`, GitHub runs the pull request's own copy of a workflow: list `.github/workflows/` in `CODEOWNERS`, or require the workflow from an organization ruleset, so that the check itself is not edited by the change it judges.
Whether a given host loads its hooks in a CI run is `not established` in the table above.

## Keeping this page true

The table above is printed by `openguildkit host check --matrix`, and `openguildkit host check --matrix --json` gives the same rows to a fleet view; neither needs a project.
Its rows come from `host_coverage.py`: the hosts of the first rows are the ones `host apply` writes hooks for (`HOOK_HOSTS` in `hosts.py`, with the edit tools of `EDIT_MATCHERS`), and the rows `cursor` and `copilot` are the tools it knows to have no usable hook (`UNHOOKED_TOOLS`, with the pages and the day each was read).
`tests/test_doc_pages.py` fails when this table and the command differ: change the rows in the code, then paste the output of the command here.
