# Integrations

Any agent that reads `AGENTS.md` and runs shell commands can follow the OpenGuildKit workflow, because `init` writes it there. The files below make the flow smoother in two agents.

| File | What it does |
|---|---|
| `skills/openguildkit/SKILL.md` | Skill for Claude Code and Codex: setup questionnaire, task scoping, one pass per board, review, stop for the decision, handoff |
| `chaosfolk/README.md` | Optional ChaosFolk end-to-end replays: pinned version, `chaosfolk-e2e` pack, CI example and exit codes |
| `claude-code/agents/guild-board.md` | Claude Code subagent that reviews a task through one board and returns a JSON entry |
| `claude-code/agents/market-analyst.md` | Claude Code subagent that fills and refreshes a market dossier through `openguildkit market` commands, within the research policy |
| `claude-code/agents/dependency-watch.md` | Claude Code subagent that runs the project's scanners, imports their reports into the alert register and opens a task per new confirmed alert |
| `github/openguildkit-dependency-watch.yml`, `github/openguildkit-market-watch.yml` | Scheduled jobs: import a scanner report and open an issue per new confirmed alert; open an issue per competitor source due for review |

Both agents use the same `SKILL.md` format (a folder with a `SKILL.md` file and `name` and `description` in the front matter).

## Install from the package

`openguildkit integrations --host claude-code` or `--host codex` copies the skill and subagent shipped with the installed version into the project (`--user` for your home folder). It keeps files you changed unless you pass `--force`. The copies below are the same files; a test keeps them identical to the packaged ones in `src/openguildkit/agent_files/`.

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
| The agent cannot run the approval command | `.claude/settings.json` denies `task decide`, `task waive` and `task authorize ... --allow` in every documented form (`openguildkit`, `python -m openguildkit`, a virtual environment path, `--project` before the subcommand), the `script`, `expect`, `unbuffer`, `tmux` and `screen` terminal emulators and Python pseudo-terminals (`import pty`, `pexpect`) | `.codex/rules/openguildkit.rules` forbids `task decide`, `task waive` and `task authorize` from `openguildkit` and `python -m openguildkit`, also after `--project .`, and the same terminal emulators | Typed confirmation only |
| The board before every change (`"guard": "observe"` or `"enforce"`) | Hooks in `.claude/settings.json` run `openguildkit guard` on each request and before `Edit`, `Write`, `MultiEdit` and `NotebookEdit`; `Edit(/...)` deny rules keep those tools away from `.openguildkit/tasks/`, `.openguildkit/decisions/`, `.openguildkit/project.json`, the catalog lock and the Claude Code settings; in `enforce` the pre-edit hook carries `"onFailure": "block"` | `.codex/hooks.json` runs it on each request and before `apply_patch` | AGENTS.md instruction and the CI check |
| External actions outside the authorized scope | Recorded decision with `openguildkit task authorize` | Same | Same |

`host check` reports each rule as enforced, missing (the host could enforce it but the setting is absent), instruction (the agent follows the instruction and a person checks) or human (a person decides). When a project declares a host, `openguildkit check` fails while a setting is missing. Codex reads project settings only once the project is trusted. `host apply` adds its `web_search` line as a top-level key outside the `openguildkit tools` block and refuses to write when the result would not read back as `web_search = "disabled"`. Deny rules match the command line only: they are friction, not a security boundary. See [what the hosts document](#what-the-host-documentation-says) for what they miss. A local approval seal only detects accidental edits, so with `"guard": "enforce"` `host check` and `check` print a one-line warning until the project requires [signed approvals](../docs/workflow.md#signed-approvals), the only approval that resists an agent that can write files.

The hooks call `openguildkit` by name. When that command is not on the PATH of the workstation running `host check` (a virtual environment that is not activated, for example), the board control reads `missing`. In `enforce`, `host apply` writes `"onFailure": "block"` on the Claude Code pre-edit hook, so a hook that cannot start refuses the edit instead of letting it through; this needs Claude Code 2.1.295 or later, and `host check` reports the hook as `missing` without it. In `observe` the key is not written. Codex has no such setting: install OpenGuildKit on the PATH (with `pipx`, for example) or start the agent from the activated environment.

### What the host documentation says

Read on 2026-11-21 in the [Claude Code permissions](https://code.claude.com/docs/en/permissions) and [hooks](https://code.claude.com/docs/en/hooks) pages and the Codex [rules](https://learn.chatgpt.com/docs/agent-configuration/rules) and [hooks](https://learn.chatgpt.com/docs/hooks) pages:

- Claude Code path rules: `./path` and a bare path follow the current directory, `/path` is relative to the settings source (the project root for `.claude/settings.json`), `//path` is absolute, and `**` is supported. OpenGuildKit writes the `/` form; `host check` accepts only that form and `host apply` replaces the `./` form an earlier version wrote.
- Claude Code `Edit` rules apply to every built-in tool that edits files and to shell redirections (`>`, `>>`, `tee`, `sed`), but not to a script that writes the file.
- Claude Code hooks: only exit code 2 blocks. Exit 1 and a hook that cannot start (command not found) are non-blocking errors, unless the hook carries `"onFailure": "block"` (Claude Code 2.1.295 and later).
- Claude Code `Bash` rules accept `*` at any position, and `Bash(*openguildkit* task decide*)` matches each subcommand of a compound line. The documentation says such rules cover the invocation Claude usually produces and are not a security boundary: `sh -c '...'`, an absolute path to the program or `env PROGRAM` are not stopped.
- Codex `prefix_rule` accepts a list of alternatives at one position. A rule is an exact prefix from the first word, so `--project /some/other/path` is not matched. A compound `bash -lc` line is split into commands only when it is plain words joined by `&&`, `||`, `;` or `|`; a redirect or `$(...)` prevents the split.
- Codex reads `.codex/hooks.json` in a trusted project. The edit tool reports `tool_name: "apply_patch"` with the patch in `tool_input.command`, and exit code 2 blocks.

Not verified in a live host session: that both hosts apply these settings as documented to the rules OpenGuildKit writes.

When a consultation runs under `local-only` and the host does not block research, the consultation request says so and tells the agent to ask before using any external source.

A person records each decision on an external action outside the approved scope:

```bash
openguildkit task authorize ID --action external-api --target api.example.com --allow --by "Camille Martin" --reason "Read the public status page"
```

`--allow` needs a terminal and the typed task ID; `--deny` works anywhere. The target is a host or tool name, never a URL with a query, an address or other private details. The decisions appear in the task record and in the handoff.

## The board before every change

With `"guard": "observe"` or `"guard": "enforce"` in the profile, `openguildkit host apply` installs hooks that run `openguildkit guard`:

- on each request, the agent receives a reminder: either the approved tasks in progress, or the instruction to open a task and consult the boards before changing files;
- before a file edit inside the project, `observe` adds a warning for the agent and `enforce` refuses the edit when no approved task covers the work. When a task covers it, the agent is told which one, with its brief, and an approval older than 14 days is flagged so the agent asks the person whether it still applies. One approved task covers every file: the guard does not check that an edit stays inside the task's scope.
- edits to the files the CLI writes through its own commands and the guard relies on are refused in `enforce`, even under an approved task: `.openguildkit/tasks/`, `.openguildkit/decisions/`, `.openguildkit/project.json`, `.openguildkit/catalog.lock.json`, `.claude/settings.json`, `.claude/settings.local.json` and the `.codex/` settings. Other files under `.openguildkit/` and files outside the project stay allowed. Codex patches are checked on every `Update`, `Add`, `Delete` and `Move to` line.
- in `enforce`, a hook that cannot decide refuses the edit with a one-line reason: an unreadable profile, an input that names no file, or any error. `observe` reports the same reason and lets the edit through. A broken task record covers nothing and does not stop the hook.
- writes through the shell (`sed -i`, `echo > file`, a script) do not go through the hook. In Claude Code the `Edit(/...)` deny rules still cover redirections, `tee` and `sed` on the protected files, not a script. The CI check below is the backstop for the rest.

`openguildkit guard` without options prints the same answer for a person; `--json` lists each covering task with its approval date and a `stale` flag. In CI, export the decision of the approved task with `openguildkit task export ID`: it writes `.openguildkit/decisions/ID.json` with the brief, the verdict of each board, the sealed approval and the approval payload the seal covers (and the signature when there is one), without evidence or internal notes. Commit it with the change. [`github/openguildkit-guard.yml`](github/openguildkit-guard.yml) runs `openguildkit guard --ci --base BASE`, which:

- reads the guard mode, the profile, the catalog lock and the allowed signers from the base revision, so a pull request that sets `"guard": "observe"` or swaps the signers is still judged by the base rules;
- counts every changed file as work, `.openguildkit/project.json` and the catalog lock included, except the decision records themselves;
- recomputes each record's seal from its payload, checks that the payload names the record's task and the base rules, and verifies the signature when the base profile requires signed approvals;
- refuses a record whose task already had a decision on the base revision: new work needs a new task;
- names the task whose decision covers the change, and reports a malformed record as an `OpenGuildKit:` error with exit code 1.

A change that is not covered is reported, and fails in `enforce` mode. To change the profile itself, have the task approved before editing `.openguildkit/project.json`, then export its decision: it carries the base rules the CI check compares with.

## Validate a host

The [host validation scenario](../examples/host-validation/) checks that an agent runs the whole flow: board passes, a disagreement, insufficient evidence, the person's decision and the results. Its CLI rehearsal runs in CI; reports from real hosts sit next to it.

## Other agents

Point the agent at `AGENTS.md`, which already contains the workflow, or paste the "Task" section of `SKILL.md` into its project instructions.
