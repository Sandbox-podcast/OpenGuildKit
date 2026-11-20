# Integrations

Any agent that reads `AGENTS.md` and runs shell commands can follow the OpenGuildKit workflow, because `init` writes it there. The files below make the flow smoother in two agents.

| File | What it does |
|---|---|
| `skills/openguildkit/SKILL.md` | Skill for Claude Code and Codex: setup questionnaire, task scoping, one pass per board, review, stop for the decision, handoff |
| `chaosfolk/README.md` | Optional ChaosFolk end-to-end replays: pinned version, `chaosfolk-e2e` pack, CI example and exit codes |
| `claude-code/agents/guild-board.md` | Claude Code subagent that reviews a task through one board and returns a JSON entry |

Both agents use the same `SKILL.md` format (a folder with a `SKILL.md` file and `name` and `description` in the front matter).

## Install from the package

`openguildkit integrations --host claude-code` or `--host codex` copies the skill and subagent shipped with the installed version into the project (`--user` for your home folder). It keeps files you changed unless you pass `--force`. The copies below are the same files; a test keeps them identical to the packaged ones in `src/openguildkit/agent_files/`.

## Claude Code

Per project (shared with the team through git):

```bash
mkdir -p .claude/skills .claude/agents
cp -r path/to/OpenGuildKit/integrations/skills/openguildkit .claude/skills/
cp path/to/OpenGuildKit/integrations/claude-code/agents/guild-board.md .claude/agents/
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
| The agent cannot run the approval command | `.claude/settings.json` denies `openguildkit task decide` and the `script`, `expect` and `unbuffer` terminal emulators | `.codex/rules/openguildkit.rules` forbids the same commands | Typed confirmation only |
| The board before every change (`"guard": "observe"` or `"enforce"`) | Hooks in `.claude/settings.json` run `openguildkit guard` on each request and before `Edit`, `Write`, `MultiEdit` and `NotebookEdit` | `.codex/hooks.json` runs it on each request and before `apply_patch` | AGENTS.md instruction and the CI check |
| External actions outside the authorized scope | Recorded decision with `openguildkit task authorize` | Same | Same |

`host check` reports each rule as enforced, missing (the host could enforce it but the setting is absent), instruction (the agent follows the instruction and a person checks) or human (a person decides). When a project declares a host, `openguildkit check` fails while a setting is missing. Codex reads project settings only once the project is trusted. Denying the documented commands does not stop an agent with a shell from emulating a terminal another way; teams that need a verifiable approver use the team approval described in the task workflow.

When a consultation runs under `local-only` and the host does not block research, the consultation request says so and tells the agent to ask before using any external source.

A person records each decision on an external action outside the approved scope:

```bash
openguildkit task authorize ID --action external-api --target api.example.com --allow --by "Camille Martin" --reason "Read the public status page"
```

`--allow` needs a terminal and the typed task ID; `--deny` works anywhere. The target is a host or tool name, never a URL with a query, an address or other private details. The decisions appear in the task record and in the handoff.

## The board before every change

With `"guard": "observe"` or `"guard": "enforce"` in the profile, `openguildkit host apply` installs hooks that run `openguildkit guard`:

- on each request, the agent receives a reminder: either the approved tasks in progress, or the instruction to open a task and consult the boards before changing files;
- before a file edit inside the project, `observe` adds a warning for the agent and `enforce` refuses the edit when no approved task covers the work. Edits to `.openguildkit/` and to files outside the project stay allowed.

`openguildkit guard` without options prints the same answer for a person. In CI, export the decision of the approved task with `openguildkit task export ID`: it writes `.openguildkit/decisions/ID.json` with the brief, the verdict of each board and the sealed approval, without evidence or internal notes. Commit it with the change. [`github/openguildkit-guard.yml`](github/openguildkit-guard.yml) runs `openguildkit guard --ci --base BASE`: a pull request that changes the project without a decision approved under the current rules is reported, and fails in `enforce` mode.

## Other agents

Point the agent at `AGENTS.md`, which already contains the workflow, or paste the "Task" section of `SKILL.md` into its project instructions.
