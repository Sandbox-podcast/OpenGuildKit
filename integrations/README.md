# Integrations

Any agent that reads `AGENTS.md` and runs shell commands can follow the OpenGuildKit workflow, because `init` writes it there. The files below make the flow smoother in two agents.

| File | What it does |
|---|---|
| `skills/openguildkit/SKILL.md` | Skill for Claude Code and Codex: task scoping, one pass per board, review, stop for the decision, handoff; under 15 000 bytes, because it is read at every turn |
| `skills/openguildkit/references/*.md` | What only some sessions need, read when `SKILL.md` says so: the setup questionnaire, deliberation, closing a task, market dossiers, dependency alerts, Storybook, tools and MCP servers |
| `chaosfolk/README.md` | Optional ChaosFolk end-to-end replays: pinned version, `chaosfolk-e2e` pack, CI example and exit codes |
| `claude-code/agents/guild-board.md` | Claude Code subagent that reviews a task through one board and returns a JSON entry |
| `claude-code/agents/market-analyst.md` | Claude Code subagent that fills and refreshes a market dossier through `openguildkit market` commands, within the research policy |
| `claude-code/agents/dependency-watch.md` | Claude Code subagent that runs the project's scanners, imports their reports into the alert register and opens a task per new confirmed alert |
| `github/openguildkit-dependency-watch.yml`, `github/openguildkit-market-watch.yml` | Scheduled jobs: import a scanner report, open a task per new confirmed alert and propose the alert register in a pull request (the scanner runs in a read-only job; in guard mode `enforce` the pull request needs a review task's exported decision, and its checks wait for a maintainer's approval because the job's `GITHUB_TOKEN` opened it: [docs/alerts.md](../docs/alerts.md#the-pull-request-and-the-guard)); open an issue per competitor source due for review |

Both agents use the same `SKILL.md` format (a folder with a `SKILL.md` file and `name` and `description` in the front matter).

## Install from the package

`openguildkit integrations --host claude-code` or `--host codex` copies the skill (`SKILL.md` and its `references/` files) and subagent shipped with the installed version into the project (`--user` for your home folder). It keeps files you changed unless you pass `--force`. The copies below are the same files; a test keeps them identical to the packaged ones in `src/openguildkit/agent_files/`.

## Claude Code

Per project (shared with the team through git):

```bash
mkdir -p .claude/skills .claude/agents
cp -r path/to/OpenGuildKit/integrations/skills/openguildkit .claude/skills/
cp path/to/OpenGuildKit/integrations/claude-code/agents/*.md .claude/agents/
```

Or for every project: copy them to `~/.claude/skills/` and `~/.claude/agents/`.

## Codex

Per project (shared with the team through git):

```bash
mkdir -p .agents/skills
cp -r path/to/OpenGuildKit/integrations/skills/openguildkit .agents/skills/
```

Or for every project: copy it to `~/.agents/skills/`.

Codex spawns its own agents for the board passes; it does not need the `guild-board` file.

## What the host enforces

OpenGuildKit cannot stop an agent from using its tools. Some hosts can, through their own project settings. Set `"host": "claude-code"` or `"host": "codex"` in `.openguildkit/project.json`, then:

```bash
openguildkit host check
openguildkit host apply
```

| Rule | Claude Code | Codex | Other hosts |
|---|---|---|---|
| No public research when the policy is `local-only` | `.claude/settings.json` denies `WebSearch` and `WebFetch` | `.codex/config.toml` sets `web_search = "disabled"` and leaves sandbox network access off | Instruction only |
| Public research stays available when the policy is `public-sources` | `host apply` removes the `WebSearch` and `WebFetch` denies | `host apply` removes the `web_search` line it wrote; a line the team wrote is reported for the team to remove | Instruction only |
| The agent cannot run the approval command (`partial`: a script file gets around it) | `.claude/settings.json` denies `task decide`, `task waive` and `task authorize ... --allow` in every documented form (`openguildkit`, `python -m openguildkit`, a virtual environment path, `--project` before the subcommand), the `script`, `expect`, `unbuffer`, `tmux` and `screen` terminal emulators and Python pseudo-terminals (`import pty`, `pexpect`), and, with signed approvals, file edits to the allowed signers file | `.codex/rules/openguildkit.rules` forbids `task decide`, `task waive` and `task authorize` from `openguildkit` and `python -m openguildkit`, also after `--project .`, and the same terminal emulators | Typed confirmation only |
| The board before every change (`"guard": "observe"` or `"enforce"`) | Hooks in `.claude/settings.json` run `openguildkit guard` on each request and before `Edit`, `Write`, `MultiEdit` and `NotebookEdit`; `Edit(/...)` deny rules keep those tools away from `.openguildkit/tasks/`, `.openguildkit/decisions/`, `.openguildkit/project.json`, the catalog lock, the project catalog (`.openguildkit/catalog/`), the alert register (`.openguildkit/alerts.json`) and the Claude Code settings; in `enforce` the pre-edit hook carries `"onFailure": "block"` and the settings say `"disableAllHooks": false` | `.codex/hooks.json` runs it on each request and before `apply_patch` | AGENTS.md instruction and the CI check |
| External actions outside the authorized scope | Recorded decision with `openguildkit task authorize` | Same | Same |

`host check` reports each rule as enforced, partial (the setting is in place and the detail says what still gets around it), missing (the host could enforce it but the setting is absent), by instruction (the agent follows the instruction and a person checks) or by a person (a person decides); `--json` gives the statuses `enforced`, `partial`, `missing`, `instruction` and `human`. The rule that keeps the agent from approving is `partial` at best: deny rules match a command line, and a script file that runs the command or opens a pseudo-terminal gets around them. `host check` exits with code 1 while a setting is missing, and with 0 when nothing is missing, even if some rules stay with the instructions or with a person: no setting of the host can enforce those. `openguildkit check` fails too while a setting is missing. Codex reads project settings only once the project is trusted. `host apply` adds its `web_search` line as a top-level key outside the `openguildkit tools` block and refuses to write when the result would not read back as `web_search = "disabled"`. Deny rules match the command line only: they are friction, not a security boundary. See [what the hosts document](#what-the-host-documentation-says) for what they miss. A local approval seal only detects accidental edits, so with `"guard": "enforce"` `host check` and `check` print a one-line warning until the project requires [signed approvals](../docs/workflow.md#signed-approvals), the only approval that resists an agent that can write files.

The hooks call `openguildkit` by name. When that command is not on the PATH of the workstation running `host check` (a virtual environment that is not activated, for example), the board control reads `missing`. In `enforce`, `host apply` writes `"onFailure": "block"` on the Claude Code pre-edit hook, so a hook that cannot start refuses the edit instead of letting it through; this needs Claude Code 2.1.295 or later, and `host check` reports the hook as `missing` without it. In `observe` the key is not written. In `enforce`, `host apply` also writes `"disableAllHooks": false` in `.claude/settings.json`: Claude Code honours `"disableAllHooks": true` from a user's own settings unless the project says `false`, and `host check` reports the board as `missing` without it. Codex has no such setting: install OpenGuildKit on the PATH (with `pipx`, for example) or start the agent from the activated environment.

### What the host documentation says

Read on 2026-11-21 in the [Claude Code permissions](https://code.claude.com/docs/en/permissions) and [hooks](https://code.claude.com/docs/en/hooks) pages and the Codex [rules](https://learn.chatgpt.com/docs/agent-configuration/rules) and [hooks](https://learn.chatgpt.com/docs/hooks) pages:

- Claude Code path rules: `./path` and a bare path follow the current directory, `/path` is relative to the settings source (the project root for `.claude/settings.json`), `//path` is absolute, and `**` is supported. OpenGuildKit writes the `/` form; `host check` accepts only that form and `host apply` replaces the `./` form an earlier version wrote.
- Claude Code `Edit` rules apply to every built-in tool that edits files and to shell redirections (`>`, `>>`, `tee`, `sed`), but not to a script that writes the file.
- Claude Code hooks: only exit code 2 blocks. Exit 1 and a hook that cannot start (command not found) are non-blocking errors, unless the hook carries `"onFailure": "block"` (Claude Code 2.1.295 and later).
- Claude Code `Bash` rules accept `*` at any position, and `Bash(*openguildkit* task decide*)` matches each subcommand of a compound line. The documentation says such rules cover the invocation Claude usually produces and are not a security boundary: `sh -c '...'`, an absolute path to the program or `env PROGRAM` are not stopped.
- Codex `prefix_rule` accepts a list of alternatives at one position. A rule is an exact prefix from the first word, so `--project /some/other/path` is not matched. A compound `bash -lc` line is split into commands only when it is plain words joined by `&&`, `||`, `;` or `|`; a redirect or `$(...)` prevents the split.
- Codex reads `.codex/hooks.json` in a trusted project. The edit tool reports `tool_name: "apply_patch"` with the patch in `tool_input.command`, and exit code 2 blocks.

Checked without a host: `tests/test_written_host_controls.py` runs the hooks `host apply` writes through the shell, with the input each host documents, and matches every rule it writes with the syntax above. Not verified in a live host session yet: that both hosts load these settings and apply them as documented. The [host validation scenario](../examples/host-validation/README.md#the-controls-that-host-apply-writes) gives the steps of that session, and says why Codex was not run.

When a consultation runs under `local-only` and the host does not block research, the consultation request says so and tells the agent to ask before using any external source.

A person records each decision on an external action outside the approved scope:

```bash
openguildkit task authorize ID --action external-api --target api.example.com --allow --by CM --reason "Read the public status page"
```

`--allow` needs a terminal and the typed task ID; `--deny` works anywhere. The target is a host or tool name, never a URL with a query, an address or other private details. The decisions appear in the task record and in the handoff.

## The board before every change

`openguildkit init` writes `"guard": "observe"` for a new project unless the person chooses another mode; a profile without `guard` (projects created before) stays `off`. With `"guard": "observe"` or `"guard": "enforce"` in the profile, `openguildkit host apply` installs hooks that run `openguildkit guard`:

- on each request, the agent receives a reminder: either the approved tasks in progress, or the instruction to open a task and consult the boards before changing files;
- before a file edit inside the project, when no approved task covers the work, `enforce` refuses the edit (exit code 2, "Edit refused") and `observe` lets it through with a warning for the agent ("Edit flagged, not blocked"). The word "refused" appears only when the edit is refused. When a task covers it, the agent is told which one, with its brief, and an approval older than 14 days is flagged so the agent asks the person whether it still applies.
- an approval covers the work, not a list of files: while one task is approved, every edit in the project counts as covered, `README.md` or an unrelated module included, and the hook tells the agent that the guard does not compare the files with the task's scope. A task records the kind of work and the affected areas, not paths, so the guard has nothing it could compare without false refusals. At review, the person compares the files of the change with the approved brief and sends anything outside it back to a new task.
- edits to the files the CLI writes through its own commands and the guard relies on are refused in `enforce`, even under an approved task: `.openguildkit/tasks/`, `.openguildkit/decisions/`, `.openguildkit/project.json`, `.openguildkit/catalog.lock.json`, `.claude/settings.json`, `.claude/settings.local.json` and the `.codex/` settings. So is the allowed signers file of a project with signed approvals, wherever the profile puts it: only the person changes who may approve.
- the project catalog (`.openguildkit/catalog/`) and the alert register (`.openguildkit/alerts.json`) are work like any other file: an approved task must cover an edit to them, since they change what the boards review and what blocks an approval. Other files under `.openguildkit/` and files outside the project stay allowed. Codex patches are checked on every `Update`, `Add`, `Delete` and `Move to` line.
- in `enforce`, a hook that cannot decide refuses the edit with a one-line reason: an unreadable profile, an input that names no file, or any error. `observe` reports the same reason and lets the edit through. When the profile itself cannot be read, the guard cannot know its mode: it refuses the edit as in `enforce` and says so. A broken task record covers nothing and does not stop the hook.
- writes through the shell (`sed -i`, `echo > file`, a script) do not go through the hook. In Claude Code the `Edit(/...)` deny rules still cover redirections, `tee` and `sed` on the protected files, not a script. The CI check below is the backstop for the rest.

`openguildkit guard` without options prints the same answer for a person, including that coverage is not tied to files; `--json` lists each covering task with its approval date and a `stale` flag. In CI, export the decision of the approved task with `openguildkit task export ID` once the work is committed: it writes `.openguildkit/decisions/ID.json` with the brief, the verdict of each board, the sealed approval and the approval payload the seal covers (and the signature when there is one), the blockers and how they were cleared, and the files Git tracks that changed since the approved revision, without evidence or internal notes. Commit it with the change. [`github/openguildkit-guard.yml`](github/openguildkit-guard.yml) runs `openguildkit guard --ci --base BASE`, which:

- reads the guard mode, the profile, the catalog lock and the allowed signers from the base revision, so a pull request that sets `"guard": "observe"` or swaps the signers is still judged by the base rules;
- counts every changed file as work, `.openguildkit/project.json` and the catalog lock included, except the decision records themselves, and requires each one in the `files` of a valid record the pull request brings: a record copied into another change does not cover it, and the check names the files no record lists;
- recomputes each record's seal from its payload, checks that the payload names the record's task and the base rules, and verifies the signature when the base profile requires signed approvals;
- refuses a record whose task already had another approval on the base revision: new work needs a new task. A record of the same approval (same seal, same consultation) passes, so the record that adds the completion can come in a pull request of its own; it covers only the files its base version listed;
- with local approvals on the base revision, says that the records cannot be verified: whoever can write a record can recompute its seal. `guard --ci --require-signed` fails the check until the base revision requires [signed approvals](../docs/workflow.md#signed-approvals);
- names a changed workflow file that runs the check (see [Protect the check](#protect-the-check));
- refuses a record placed anywhere but directly in `.openguildkit/decisions/`, where `task export` writes it, and reads the base revision's records at any depth below that folder, so a record merged in a subfolder still binds its approval;
- refuses a new approval whose approved revision is not in the history of the pull request (an approval given on an abandoned branch and copied into another change), with the message `task list` gives;
- refuses a record that carries the withdrawal of its approval (`task revoke`, then `task export`), and a copy of that approval made before the withdrawal once the withdrawn record is on the base revision;
- names the task whose decision covers the change with the record it read, and reports a record it cannot read, or that `task export` could not have written, as a problem of the check: it fails in `enforce` and is flagged, not blocking, in `observe`, like any other problem.

The list of files is written after the approval and sealed by nobody, not even by a signature: it stops a record from being reused as it is, and the reviewer compares it with the diff of the pull request.

The pull request that adds the profile runs on a base revision without one: the check reports mode `off` and enforces nothing, which is expected, and says which mode the next pull requests get once the profile is merged (the `"guard"` value of the change).

A change that is not covered is reported, and fails in `enforce` mode; in `observe` the report says it is flagged, not blocking, and the check passes. To change the profile itself, have the task approved before editing `.openguildkit/project.json`, then export its decision: it carries the base rules the CI check compares with.

### Protect the check

The template runs on `pull_request`, and GitHub runs the copy of the workflow file that the pull request carries: a pull request that edits `.github/workflows/openguildkit-guard.yml` can drop the step that judges it. `guard --ci` names a changed workflow file that runs `openguildkit guard --ci` (on the base revision or in the change), but an edited copy may never run it. Keep pull requests from changing the check:

- list `.github/workflows/` in `.github/CODEOWNERS`, with the allowed signers file of a project with signed approvals, and require a review from the code owners in the branch protection or ruleset of the default branch;
- or require the workflow itself from the default branch: an organization or enterprise ruleset with the rule "Require workflows to pass before merging", naming this workflow file, runs that copy whatever the pull request contains. The rule exists only at those levels, and the workflow must run on `pull_request` (and `merge_group` with a merge queue); see GitHub's [available rules for rulesets](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) (read on 2026-11-22).

## Try the hooks by hand

Each host sends the hook a JSON object on standard input; the guard reads `tool_input` before an edit and nothing from a request. The examples below hold the fields the guard reads (the hosts add others, such as the session and the working folder, which it ignores) and are tested against the guard. Run them from the project folder. Write the JSON on one line and pass it with `printf '%s'` or a file: `echo` can turn the `\n` of a patch into real line breaks, and the input is then no longer JSON.

### Claude Code

```sh
printf '%s' '{"hook_event_name":"UserPromptSubmit","prompt":"Add a status page"}' | openguildkit guard --hook prompt
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"app.py","old_string":"a","new_string":"b"}}' | openguildkit guard --hook pre-edit
```

```powershell
'{"hook_event_name":"UserPromptSubmit","prompt":"Add a status page"}' | openguildkit guard --hook prompt
'{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"app.py","old_string":"a","new_string":"b"}}' | openguildkit guard --hook pre-edit
```

### Codex

```sh
printf '%s' '{"hook_event_name":"UserPromptSubmit","prompt":"Add a status page"}' | openguildkit guard --hook prompt
printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"apply_patch","tool_input":{"command":"*** Begin Patch\n*** Update File: app.py\n@@\n-a\n+b\n*** End Patch\n"}}' | openguildkit guard --hook pre-edit
```

```powershell
'{"hook_event_name":"UserPromptSubmit","prompt":"Add a status page"}' | openguildkit guard --hook prompt
'{"hook_event_name":"PreToolUse","tool_name":"apply_patch","tool_input":{"command":"*** Begin Patch\n*** Update File: app.py\n@@\n-a\n+b\n*** End Patch\n"}}' | openguildkit guard --hook pre-edit
```

### Other hosts

They run no hook (see [Other agents](#other-agents)). To test the guard for such a host, use the Claude Code examples: the guard reads the same `tool_input.file_path`.

The answer depends on the mode and on the tasks. Without an approved task, the prompt example prints a reminder as `additionalContext` and exits with 0; the edit example exits with 2 and prints `Edit refused for: app.py` on standard error in `enforce`, and in `observe` prints `Edit flagged, not blocked` as `additionalContext` and exits with 0. With `"guard": "off"` both print nothing. To keep the input in a file instead, save the JSON as `hook-input.json` and run `openguildkit guard --hook pre-edit < hook-input.json`, or `Get-Content -Raw hook-input.json | openguildkit guard --hook pre-edit` in PowerShell.

## Scan what an agent reads

`openguildkit host scan` reads the instruction files and agent settings of the project (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, the agents, Skills and commands of `.claude/`, the rules of Cursor, Windsurf, Roo Code, Kilo Code and Junie, the instructions of Copilot, the MCP configurations) and reports hidden characters, phrases that tell an agent to drop its rules and downloads piped into an interpreter. It runs offline, changes nothing and blocks nothing: no hook of any host runs it, so a person or CI does. [What each code means, and what the scan does not prove](../docs/host-scan.md).

## Validate a host

The [host validation scenario](../examples/host-validation/) checks that an agent runs the whole flow: board passes, a disagreement, insufficient evidence, the person's decision and the results. Its CLI rehearsal runs in CI; reports from real hosts sit next to it, with what each shows for issue #23, and the steps of a live session that checks the hooks and deny rules `host apply` writes.

## Other agents

`openguildkit init` records `"host": "other"` unless the person chooses Claude Code or Codex. For any other agent:

1. `openguildkit integrations --host other` writes the skill to `.agents/skills/openguildkit/SKILL.md`, the folder of the Agent Skills format. If the agent reads its skills or instructions from another folder, copy the whole folder there (`SKILL.md` and `references/`), or point the agent at `AGENTS.md`, which carries the same workflow.
2. OpenGuildKit writes no settings for this agent. `host apply` says so, writes nothing and exits with 1; `host check` lists the rules left to the instructions (`by instruction`) or to a person (`by a person`) and exits with 0. The board guard has no hook: the AGENTS.md instruction and the CI check (`guard --ci`) are the controls.
3. `tools apply` and `tools remove` write MCP settings for Claude Code or Codex only: add `--host claude-code` or `--host codex` to write them for one of these agents. For another agent, run `openguildkit tools plan ID`: with the host `other` it prints each server as an `mcpServers` entry, the format most MCP clients read, to copy into that agent's settings.
4. To move to Claude Code or Codex later, run `openguildkit profile set host claude-code --by NAME --reason WHY` (or `codex`), then `openguildkit host apply`.

`init` also writes `CLAUDE.md`, one line that imports `AGENTS.md` for Claude Code, whatever the host; delete it if nobody uses Claude Code.
