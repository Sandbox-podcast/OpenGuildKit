# Integrations

Any agent that reads `AGENTS.md` and runs shell commands can follow the OpenGuildKit workflow, because `init` writes it there. The files below make the flow smoother in two agents.

| File | What it does |
|---|---|
| `skills/openguildkit/SKILL.md` | Skill for Claude Code and Codex: setup questionnaire, task scoping, one pass per board, review, stop for the decision, handoff |
| `chaosfolk/README.md` | Optional ChaosFolk end-to-end replays: pinned version, `chaosfolk-e2e` pack, CI example and exit codes |
| `claude-code/agents/guild-board.md` | Claude Code subagent that reviews a task through one board and returns a JSON entry |

Both agents use the same `SKILL.md` format (a folder with a `SKILL.md` file and `name` and `description` in the front matter).

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
| External actions outside the authorized scope | Recorded decision with `openguildkit task authorize` | Same | Same |

`host check` reports each rule as enforced, missing (the host could enforce it but the setting is absent), instruction (the agent follows the instruction and a person checks) or human (a person decides). When a project declares a host, `openguildkit check` fails while a setting is missing. Codex reads project settings only once the project is trusted. Denying the documented commands does not stop an agent with a shell from emulating a terminal another way; teams that need a verifiable approver use the team approval described in the task workflow.

When a consultation runs under `local-only` and the host does not block research, the consultation request says so and tells the agent to ask before using any external source.

A person records each decision on an external action outside the approved scope:

```bash
openguildkit task authorize ID --action external-api --target api.example.com --allow --by "Camille Martin" --reason "Read the public status page"
```

`--allow` needs a terminal and the typed task ID; `--deny` works anywhere. The target is a host or tool name, never a URL with a query, an address or other private details. The decisions appear in the task record and in the handoff.

## Other agents

Point the agent at `AGENTS.md`, which already contains the workflow, or paste the "Task" section of `SKILL.md` into its project instructions.
