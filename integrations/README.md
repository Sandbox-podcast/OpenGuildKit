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

`openguildkit integrations --host claude-code`, `--host codex` or `--host gemini-cli` copies the skill (`SKILL.md` and its `references/` files) and subagent shipped with the installed version into the project (`--user` for your home folder). It keeps files you changed unless you pass `--force`. The copies below are the same files; a test keeps them identical to the packaged ones in `src/openguildkit/agent_files/`.

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

OpenGuildKit cannot stop an agent from using its tools. Some hosts can, through their own project settings. Set `"host": "claude-code"`, `"host": "codex"` or `"host": "gemini-cli"` in `.openguildkit/project.json`, then:

```bash
openguildkit host check
openguildkit host apply
```

| Rule | Claude Code | Codex | Gemini CLI | Other hosts |
|---|---|---|---|---|
| No public research when the policy is `local-only` | `.claude/settings.json` denies `WebSearch` and `WebFetch` | `.codex/config.toml` sets `web_search = "disabled"` and leaves sandbox network access off | Instruction only | Instruction only |
| Public research stays available when the policy is `public-sources` | `host apply` removes the `WebSearch` and `WebFetch` denies | `host apply` removes the `web_search` line it wrote; a line the team wrote is reported for the team to remove | Instruction only | Instruction only |
| The agent cannot run the approval command (`partial`: a script file gets around it) | `.claude/settings.json` denies `task decide`, `task waive` and `task authorize ... --allow` in every documented form (`openguildkit`, `python -m openguildkit`, a virtual environment path, `--project` before the subcommand), the `script`, `expect`, `unbuffer`, `tmux` and `screen` terminal emulators and Python pseudo-terminals (`import pty`, `pexpect`), and, with signed approvals, file edits to the allowed signers file | `.codex/rules/openguildkit.rules` forbids `task decide`, `task waive` and `task authorize` from `openguildkit` and `python -m openguildkit`, also after `--project .`, and the same terminal emulators | Typed confirmation only | Typed confirmation only |
| The board before every change (`"guard": "observe"` or `"enforce"`) | Hooks in `.claude/settings.json` run `openguildkit guard` on each request and before `Edit`, `Write`, `MultiEdit` and `NotebookEdit`; `Edit(/...)` deny rules keep those tools away from `.openguildkit/tasks/`, `.openguildkit/decisions/`, `.openguildkit/project.json`, the catalog lock, the project catalog (`.openguildkit/catalog/`), the alert register (`.openguildkit/alerts.json`) and the Claude Code settings; in `enforce` the pre-edit hook carries `"onFailure": "block"` and the settings say `"disableAllHooks": false` | `.codex/hooks.json` runs it on each request and before `apply_patch` | Hooks in `.gemini/settings.json`: `BeforeAgent` on each request and `BeforeTool` before `write_file` and `replace` only ([Gemini CLI](#gemini-cli)) | AGENTS.md instruction and the CI check |
| External actions outside the authorized scope | Recorded decision with `openguildkit task authorize` | Same | Same | Same |
| Version checked | 2.1.295 or later for `onFailure` ([hooks](https://code.claude.com/docs/en/hooks), read 2026-11-21); 2.1.328 connected to the MCP mocks ([what was verified](../docs/tools.md#what-was-verified), 2026-11-21) | 0.171 wrote the MCP format `tools apply` follows ([what was verified](../docs/tools.md#what-was-verified), 2026-11-21); no session ran the hooks | None: no session ran, and the pages read on 2026-11-25 name no version (to verify) | Not applicable |

When the repository also holds the files of Cursor (`.cursor`, `.cursorrules`) or GitHub Copilot (`.github/copilot-instructions.md`, `.github/instructions`, `.github/hooks`), `host check` adds one rule for each, `by instruction` (`tool-cursor`, `tool-copilot` in `--json`, with the files and the pages read): the tool reads the AGENTS.md instructions, no hook blocks an edit made through it, and `guard --ci` is the only barrier. It does not change the exit code, whatever the host of the profile, and a task consultation does not record it. [Why neither is a host](#hooks-of-other-tools-what-was-read-and-why-none-was-added).

Gemini CLI (`"host": "gemini-cli"`) is the third host with hooks, and the only rule it enforces is the last-but-one row: the board before every change, through hooks in `.gemini/settings.json` (see [Gemini CLI](#gemini-cli)). For the other rows it behaves as the column "Other hosts": research and approval stay instructions, and `host check` says so.

`host check` reports each rule as enforced, partial (the setting is in place and the detail says what still gets around it), missing (the host could enforce it but the setting is absent), by instruction (the agent follows the instruction and a person checks) or by a person (a person decides); `--json` gives the statuses `enforced`, `partial`, `missing`, `instruction` and `human`. The rule that keeps the agent from approving is `partial` at best: deny rules match a command line, and a script file that runs the command or opens a pseudo-terminal gets around them. `host check` exits with code 1 while a setting is missing, and with 0 when nothing is missing, even if some rules stay with the instructions or with a person: no setting of the host can enforce those. `openguildkit check` fails too while a setting is missing. Codex reads project settings only once the project is trusted. `host apply` adds its `web_search` line as a top-level key outside the `openguildkit tools` block and refuses to write when the result would not read back as `web_search = "disabled"`. Deny rules match the command line only: they are friction, not a security boundary. See [what the hosts document](#what-the-host-documentation-says) for what they miss. A local approval seal only detects accidental edits, so with `"guard": "enforce"` `host check` and `check` print a one-line warning until the project requires [signed approvals](../docs/workflow.md#signed-approvals), the only approval that resists an agent that can write files.

The hooks call `openguildkit` by name. When that command is not on the PATH of the workstation running `host check` (a virtual environment that is not activated, for example), the board control reads `missing`. In `enforce`, `host apply` writes `"onFailure": "block"` on the Claude Code pre-edit hook, so a hook that cannot start refuses the edit instead of letting it through; this needs Claude Code 2.1.295 or later, and `host check` reports the hook as `missing` without it. In `observe` the key is not written. In `enforce`, `host apply` also writes `"disableAllHooks": false` in `.claude/settings.json`: Claude Code honours `"disableAllHooks": true` from a user's own settings unless the project says `false`, and `host check` reports the board as `missing` without it. Codex and Gemini CLI have no such setting: install OpenGuildKit on the PATH (with `pipx`, for example) or start the agent from the activated environment.

### Paths the team closes to the agent

A team can say that a folder (customer exports, secrets, scoring models) is closed to the agent. A person writes it in `.openguildkit/project.json`; no `profile set` command writes it yet:

```json
"restricted_paths": [{"paths": ["data/customers/**", "secrets/**"], "class": "restricted", "boards": ["security", "legal"]}]
```

`paths` are project paths, without a leading `/` or `..` and without parentheses. `class` and `boards` are kept for the decision a later change will make and nothing reads them yet. The setting is read when the host acts, so it leaves standing approvals standing, as the guard and the host do.

| Host | What `host apply` and `host check` do |
|---|---|
| Claude Code | `host apply` adds `Read(/PATH)` and `Edit(/PATH)` to `permissions.deny` of `.claude/settings.json` for each path, and keeps the rules of the team; `host check` reports `restricted-paths` as `enforced` or `missing`. Those rules apply to its file tools: a shell command (`cat`, `sed`, a script) is not covered by them (à vérifier: the permissions page was not read again for this). |
| Codex | Nothing: no setting of Codex that refuses a read of a path was read (à vérifier). `host check` says so, as a rule `by instruction`. |
| Gemini CLI | Nothing: no setting of Gemini CLI that refuses a read of a path was read (à vérifier). `host check` says so, as a rule `by instruction`. |
| Other hosts | Nothing. |

Not done yet, though issue #519 asks for it: `profile set restricted-paths` with its history and its confirmation at a terminal, the `pre-edit` hook that refuses an edit on a restricted path even under an approved task, and the removal of the rules `host apply` wrote when a path leaves the setting.
A rule it wrote cannot be told from the same rule the team wrote, so `host apply` removes none: delete the stale rule by hand. How `host apply` should recognise its own rules is an open question of that issue.
OpenGuildKit does not write the paths into `AGENTS.md` either, so an agent of Codex or Gemini CLI is not told about them.

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
- edits to the files the CLI writes through its own commands and the guard relies on are refused in `enforce`, even under an approved task: `.openguildkit/tasks/`, `.openguildkit/decisions/`, `.openguildkit/project.json`, `.openguildkit/catalog.lock.json`, `.claude/settings.json`, `.claude/settings.local.json` and the `.codex/` settings, and `.gemini/settings.json` when the profile's host is `gemini-cli`. So is the allowed signers file of a project with signed approvals, wherever the profile puts it: only the person changes who may approve.
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

They run no hook (see [Other agents](#other-agents)). To test the guard for such a host, use the Claude Code examples: the guard reads the same `tool_input.file_path`. Gemini CLI has its own examples, under [Gemini CLI](#try-the-hooks-of-gemini-cli-by-hand).

The answer depends on the mode and on the tasks. Without an approved task, the prompt example prints a reminder as `additionalContext` and exits with 0; the edit example exits with 2 and prints `Edit refused for: app.py` on standard error in `enforce`, and in `observe` prints `Edit flagged, not blocked` as `additionalContext` and exits with 0. With `"guard": "off"` both print nothing. To keep the input in a file instead, save the JSON as `hook-input.json` and run `openguildkit guard --hook pre-edit < hook-input.json`, or `Get-Content -Raw hook-input.json | openguildkit guard --hook pre-edit` in PowerShell.

## Gemini CLI

Gemini CLI is the third host whose hooks `host apply` writes. With `"host": "gemini-cli"` and a guard other than `off` in the profile:

```bash
openguildkit host apply
openguildkit host check
```

### What it receives and what it blocks

- `host apply` declares two hooks in `.gemini/settings.json`, the project settings file, and keeps every other key of the file: a hook on `BeforeAgent` (each request) named `openguildkit-prompt`, which runs `openguildkit guard --hook prompt`, and a hook on `BeforeTool` named `openguildkit-guard`, with the matcher `write_file|replace`, which runs `openguildkit guard --hook pre-edit`. Running it again changes nothing. A group of the person's that already runs the guard is not doubled.
- `host apply` removes the two guard hooks from `hooksConfig.disabled` when the person had listed them. In `enforce` it also writes `"hooksConfig": {"enabled": true}`, since Gemini CLI lets a project setting win over a user setting and `"enabled": false` turns every hook off; `observe` leaves that key alone.
- Before a `write_file` or a `replace`, `enforce` refuses the edit with exit code 2 and the reason on standard error, which Gemini CLI sends to the agent as the reason of the block, and `observe` lets it through. In `observe` the flag goes to the person as a `systemMessage`: Gemini CLI documents `additionalContext` for `BeforeAgent` only, and no field that tells the agent something from a `BeforeTool` hook that lets the edit through. The request hook answers with `additionalContext` under `"hookEventName": "BeforeAgent"`: the approved tasks in progress, or the instruction to open a task. When an approved task covers the edit, the hook prints nothing.
- The files the guard relies on are refused in `enforce` as for the other hosts, and `.gemini/settings.json` joins them when the profile names this host: only `host apply` and the person change what the hooks run. A project of another host may still edit that file as any work.
- `init` and `sync` write `GEMINI.md`, one line that imports `AGENTS.md` (`@./AGENTS.md`), when the profile's host is `gemini-cli`, as they write `CLAUDE.md` for Claude Code: Gemini CLI loads `GEMINI.md` unless its `context.fileName` setting says otherwise, and imports another file with a relative `@` path. A file of yours keeps its text, a symbolic link to `AGENTS.md` is left alone, and `check` reports the file as out of date until `sync` has written the import. If your `context.fileName` also lists `AGENTS.md`, the rules may be read twice.
- `integrations --host gemini-cli` installs the skill in `.agents/skills/openguildkit/`, the alias of its workspace skills folder that Gemini CLI reads.
- `host check` reports the board control as enforced once the hooks stand under the right events with a matcher that fires for both tools, the project does not switch them off and the command is on the PATH. It says what the hooks leave open and that the host was not seen in a session.

### What it does not block

- Anything that does not go through `write_file` or `replace`: `run_shell_command` (`sed -i`, `echo > file`, a script) and a tool of an MCP server that writes files. The tool reference lists `replace` and `write_file` as its two file-editing tools. The CI check (`guard --ci`) is the backstop.
- An edit when the hook cannot start (the command is not on the PATH of the person who runs Gemini CLI) or exits with a code other than 0 and 2: the documentation calls those a warning and lets the action proceed, and Claude Code's `onFailure` has no equivalent. A hook that fails inside `openguildkit` exits with 2 and refuses in `enforce`. What a timeout does is not documented.
- A folder Gemini CLI does not trust, when its Trusted Folders feature (off by default) is on: the project's `.gemini/settings.json` is then not loaded. Gemini CLI treats a new or changed project hook as untrusted and warns the person before it runs; the page does not say whether it runs before the person accepts. The system settings file overrides every other: an administrator can turn hooks off there, and nothing here can tell.
- A session where hooks do not run: the pages say nothing about non-interactive mode, an IDE or a GitHub Action, so this is not established either way.
- The research and approval rules: `host check` lists them as instructions, since no setting of Gemini CLI that enforces them was read.

### What the Gemini CLI documentation says

These pages were read on 2026-11-25, and every statement above about the host rests on them; the "last updated" date is the one each page shows.

- [Hooks](https://geminicli.com/docs/hooks/) (last updated 2026-04-13): hooks are configured in `settings.json`, in the project (`.gemini/settings.json`), user (`~/.gemini/settings.json`) or system file or by an extension; an event lists groups with a `matcher`, a regular expression for tool events, and `hooks` entries of type `command` with an optional `name` and a `timeout` in milliseconds (60 000 by default); exit code 0 reads standard output as JSON, 2 blocks the action and uses standard error as the reason, any other code is a warning that lets the interaction proceed; Gemini CLI fingerprints project hooks and treats a changed one as new and untrusted, with a warning before it runs.
- [Hooks reference](https://geminicli.com/docs/hooks/reference/) (2026-04-10): the common input fields (`session_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`); `BeforeTool` adds `tool_name` and `tool_input`, `BeforeAgent` adds `prompt`; `BeforeTool` is refused by `"decision": "deny"` with a `reason`, or by exit code 2; `systemMessage` is shown to the person; `additionalContext` of `hookSpecificOutput` is documented for `BeforeAgent`.
- [Hooks best practices](https://geminicli.com/docs/hooks/best-practices/) (2026-04-10): the one JSON input of a `BeforeTool` hook the pages show, for `write_file` with `file_path` and `content`, which the tests use as it stands. The inputs for `replace` and `BeforeAgent` are composed from the field lists of the reference pages, and the tests say so.
- [Tools reference](https://geminicli.com/docs/reference/tools/) (2026-09-01): `write_file` takes `file_path` and `content`; `replace` takes `file_path`, `old_string`, `new_string`, `instruction` and `allow_multiple`; `run_shell_command` runs shell commands.
- [Configuration reference](https://geminicli.com/docs/reference/configuration/) (2026-10-15): a project setting overrides a user setting and the system settings file overrides all others; `hooksConfig.enabled` (true by default) turns the hooks system off when false, and `hooksConfig.disabled` lists hook names that do not run.
- [Context files](https://geminicli.com/docs/cli/gemini-md/) (2026-06-18): `GEMINI.md` is the default name, a file is imported with `@` and a relative path, and `context.fileName` names other files, such as `AGENTS.md`. [Skills](https://geminicli.com/docs/cli/skills/) (2026-04-30): workspace skills are read from `.gemini/skills/` and from its alias `.agents/skills/`. [Trusted folders](https://geminicli.com/docs/cli/trusted-folders/) (2026-04-23).
- The hooks pages carry a banner saying that, for the unpaid tier and Google One users, Gemini CLI was replaced by Antigravity CLI on 2026-06-18. Antigravity CLI is not covered here: its documentation was not read.

Checked without Gemini CLI: `tests/test_gemini_host.py` runs the documented input through `guard --hook`, runs the hook commands that `host apply` wrote through the shell, and checks `host apply`, `host check` and `host scan` before and after. Not verified: that Gemini CLI loads these settings, runs these hooks and refuses on exit code 2 as its pages say. The hook is not seen in a live session of Gemini CLI, and neither is `GEMINI.md`. The [host validation scenario](../examples/host-validation/README.md#the-controls-that-host-apply-writes) gives the steps for Claude Code and Codex; a Gemini CLI session would follow the same steps with `"host": "gemini-cli"`.

### Try the hooks of Gemini CLI by hand

The first input is the one of the documentation, reduced to the fields the guard reads; the other two are composed from its field lists. Run them from the project folder, with the same care for quotes as above.

```sh
printf '%s' '{"hook_event_name":"BeforeAgent","prompt":"Add a status page"}' | openguildkit guard --hook prompt
printf '%s' '{"hook_event_name":"BeforeTool","tool_name":"write_file","tool_input":{"file_path":"app.py","content":"b"}}' | openguildkit guard --hook pre-edit
printf '%s' '{"hook_event_name":"BeforeTool","tool_name":"replace","tool_input":{"file_path":"app.py","old_string":"a","new_string":"b","instruction":"Rename a"}}' | openguildkit guard --hook pre-edit
```

```powershell
'{"hook_event_name":"BeforeAgent","prompt":"Add a status page"}' | openguildkit guard --hook prompt
'{"hook_event_name":"BeforeTool","tool_name":"write_file","tool_input":{"file_path":"app.py","content":"b"}}' | openguildkit guard --hook pre-edit
'{"hook_event_name":"BeforeTool","tool_name":"replace","tool_input":{"file_path":"app.py","old_string":"a","new_string":"b","instruction":"Rename a"}}' | openguildkit guard --hook pre-edit
```

Without an approved task, the first prints the reminder as `additionalContext` under `BeforeAgent` and exits with 0; each edit exits with 2 and prints `Edit refused for: app.py` on standard error in `enforce`, and in `observe` prints `Edit flagged, not blocked` as a `systemMessage` and exits with 0.

## Managed settings: one deployment for every project

`openguildkit host apply` writes the settings of one project. Each of the three hosts also reads a layer that the company manages and that wins over the others, which an MDM deploys. `openguildkit host managed --host claude-code|codex|gemini-cli --os macos|linux|windows` prints the file for that layer, or writes it in a folder you give it, and installs nothing;
[the page](../docs/managed-settings.md) says what each file holds, where each system expects it and what is left to verify.

The pages behind it were read on 2026-11-26 by the audit of issue #453 and not read again when the command was written:

- Claude Code, [Managed settings](https://code.claude.com/docs/en/managed-settings.md): the files `managed-settings.json` and the folder `managed-settings.d/`, the macOS profile `com.anthropic.claudecode`, the registry key `HKLM\SOFTWARE\Policies\ClaudeCode`; and [Settings reference](https://code.claude.com/docs/en/settings-reference.md):
  `allowManagedHooksOnly`, "Run only the hooks your organization deploys". With it, the hooks of a project do not run, and `host check` says so.
- Codex, [Managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration.md): `requirements.toml` at `/etc/codex/` and `%ProgramData%\OpenAI\Codex\`, the MDM key `com.openai.codex:requirements_toml_base64`, and the pin of `[features].hooks = true` that keeps the hooks on. The key names of managed hooks and rules were not read: à vérifier.
- Gemini CLI, [Configuration](https://geminicli.com/docs/reference/configuration/): the system settings file at `/etc/gemini-cli/settings.json`, `/Library/Application Support/GeminiCli/settings.json` and `C:\ProgramData\gemini-cli\settings.json`, which overrides the other files.

## Hooks of other tools: what was read and why none was added

An issue asked for the hosts whose official documentation describes a hook that runs before a file edit and can refuse it. A host is added only when the documentation shows the input of that hook for an edit: the guard needs the path of the file to protect the task records and the profile, and a guard that guesses the key would either refuse every edit in `enforce` or let a protected file through. These pages were first read on 2026-11-25; the pages of Cursor and GitHub Copilot were read again on 2026-11-26 (issue #430), with the same answer. No live session of any of these tools was run.

- **Cursor**, [Hooks](https://cursor.com/docs/agent/hooks) (no date on the page; read 2026-11-26): `.cursor/hooks.json` with `"version": 1`, in the project root; `preToolUse` is "called before any tool execution" and takes a `matcher` whose documented values are `Shell`, `Read`, `Write`, `Grep`, `Delete`, `Task` and `MCP:<tool_name>` (no `Edit`); exit code 2 or `"permission": "deny"` refuses. Its input is `tool_name`, `tool_input`, `tool_use_id`, `cwd` and model fields, and the one example is a `Shell` call (`tool_input` holds `command` and `working_directory`); every other `tool_input` shown is a shell command, and no example script reads the input of a `Write`. A file path is documented only at the top level of `beforeReadFile`, `afterFileEdit`, `beforeTabFileRead` and `afterTabFileEdit`; `afterFileEdit` runs after the edit and has no output that refuses. On 2026-11-25 the page on [third-party hooks](https://cursor.com/docs/reference/third-party-hooks) said Cursor also loads the hooks of `.claude/settings.json` (a setting on by default), without saying what input they then receive (not read again). Cursor reads `AGENTS.md` ([rules](https://cursor.com/docs/rules), read 2026-11-25).
- **GitHub Copilot**, [Hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference) and [Copilot CLI hooks reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference) (no date on the pages; read 2026-11-26), with [Using hooks with Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks), [Using hooks with the cloud agent](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/use-hooks) and VS Code's [Agent hooks](https://code.visualstudio.com/docs/agent-customization/hooks), read the same day: `.github/hooks/*.json` with `"version": 1`, the only source of the cloud agent; a `preToolUse` hook refuses by exit code 2, any other failure, or `"permissionDecision": "deny"`, and a timeout lets the tool run. Its input is `sessionId`, `timestamp`, `cwd`, `toolName` and `toolArgs` (typed `unknown`), or, for the event spelled `PreToolUse`, `tool_name` and `tool_input` ("parsed from JSON string when possible", also `unknown`). The tools `edit` and `create` are named in the matcher table, without their arguments; the one input shown is a `bash` call whose `toolArgs` is a JSON string (`"{\"command\":\"ls\"}"`), and no page shows the arguments of an edit. VS Code's page says neither format guarantees the tool arguments of its older hooks.
- **Devin CLI** (Windsurf's own documentation now describes Devin Local and sends to the Devin CLI pages for hooks), [Hooks](https://docs.devin.ai/cli/extensibility/hooks/overview) and [lifecycle hooks](https://docs.devin.ai/cli/extensibility/hooks/lifecycle-hooks): `.devin/hooks.v1.json`, a `PreToolUse` hook with a matcher on tools such as `edit`, `write` and `apply_patch`, exit code 2 or `"decision": "block"` refuses, any other failure does not. The one input shown is an `exec` call. Not added either.
- Cline's page on hooks points to a page on SDK plugins, which was not read. Kilo Code, Roo Code, opencode, Junie, Warp, goose, Zed and Aider were not examined.

These tools keep the status of `host scan`: they read the instructions and nothing blocks an edit but the CI check. When a page of one of them shows the input of its edit tool, adding it follows the Gemini CLI model: an entry of `HOSTS`, the hook declaration in `hosts.py`, the paths in `guard.py`, a test that feeds the hook the documented input.

## Scan what an agent reads

`openguildkit host scan` reads the instruction files and agent settings of the project (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, the agents, Skills and commands of `.claude/`, the rules of Cursor, Windsurf, Roo Code, Kilo Code and Junie, the instructions of Copilot, the MCP configurations) and reports hidden characters, phrases that tell an agent to drop its rules and downloads piped into an interpreter. It also lists the agent tools the repository shows, its MCP servers (launch, presence in the tool registry, version not fixed, `http://` address) and its permissive settings. It runs offline, changes nothing and blocks nothing: no hook of any host runs it, so a person or CI does. [What each code means, and what the scan does not prove](../docs/host-scan.md).

What each tool receives from OpenGuildKit, and what blocks an edit:

| Tool | Receives | What blocks an edit |
|---|---|---|
| Claude Code | `AGENTS.md` through the import in `CLAUDE.md`; the settings and hooks `host apply` writes when the profile's host is `claude-code` | Its hooks, once `host check` reports the board control as enforced; then `guard --ci` |
| Codex | `AGENTS.md` (Codex is on the agents.md list); the rules, hooks and config `host apply` writes when the profile's host is `codex` | Its hooks, same condition; then `guard --ci` |
| Gemini CLI | `GEMINI.md`, where OpenGuildKit writes an import of `AGENTS.md` when the profile's host is `gemini-cli` (the [agents.md list](https://agents.md) names Gemini CLI too, read on 2026-11-25; its default context file is `GEMINI.md`); the hooks `host apply` writes when the profile's host is `gemini-cli` | Its hooks, once `host check` reports the board control as enforced; then `guard --ci` |
| Cursor, GitHub Copilot, Windsurf, Roo Code, Kilo Code, Junie, Aider, Zed, opencode, Warp, goose | `AGENTS.md`, since the [agents.md list](https://agents.md) names them (read on 2026-11-25) | No hook blocks an edit: the CI check (`guard --ci`) is the only barrier. Cursor and GitHub Copilot document a hook that can refuse a tool, but no page read on 2026-11-26 shows the arguments of their edit tools ([Cursor](https://cursor.com/docs/agent/hooks), [GitHub Copilot](https://docs.github.com/en/copilot/reference/hooks-reference), [Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference)); `host check` and `host scan` say so in one line when their files are present: [see why none was added](#hooks-of-other-tools-what-was-read-and-why-none-was-added) |
| Cline, and any tool absent from the list | Not documented as reading `AGENTS.md` | No hook blocks an edit: the CI check (`guard --ci`) is the only barrier |

`host apply` writes hooks for the host the profile names, and for no other tool. With `"guard": "enforce"`, `host scan` raises each tool that is present and not covered from a note to a warning.

## Validate a host

The [host validation scenario](../examples/host-validation/) checks that an agent runs the whole flow: board passes, a disagreement, insufficient evidence, the person's decision and the results. Its CLI rehearsal runs in CI; reports from real hosts sit next to it, with what each shows for issue #23, and the steps of a live session that checks the hooks and deny rules `host apply` writes.

## Other agents

`openguildkit init` records `"host": "other"` unless the person chooses Claude Code, Codex or Gemini CLI. For any other agent:

1. `openguildkit integrations --host other` writes the skill to `.agents/skills/openguildkit/SKILL.md`, the folder of the Agent Skills format. If the agent reads its skills or instructions from another folder, copy the whole folder there (`SKILL.md` and `references/`), or point the agent at `AGENTS.md`, which carries the same workflow.
2. OpenGuildKit writes no settings for this agent. `host apply` says so, writes nothing and exits with 1; `host check` lists the rules left to the instructions (`by instruction`) or to a person (`by a person`) and exits with 0. The board guard has no hook: the AGENTS.md instruction and the CI check (`guard --ci`) are the controls.
3. `tools apply` and `tools remove` write MCP settings for Claude Code or Codex only: add `--host claude-code` or `--host codex` to write them for one of these agents. For another agent, run `openguildkit tools plan ID`: with the host `other` it prints each server as an `mcpServers` entry, the format most MCP clients read, to copy into that agent's settings.
4. To move to Claude Code, Codex or Gemini CLI later, run `openguildkit profile set host claude-code --by INITIALS --reason WHY` (or `codex`, or `gemini-cli`), then `openguildkit host apply`.

`init` also writes `CLAUDE.md`, one line that imports `AGENTS.md` for Claude Code, whatever the host; delete it if nobody uses Claude Code.
