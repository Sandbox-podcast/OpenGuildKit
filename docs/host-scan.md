# Scan what an agent reads, and list what could act

An agent reads `AGENTS.md`, the agents, Skills and commands of `.claude/`, the rules of Cursor and the instructions of Copilot as orders, without questioning them. A character nobody sees, or a sentence that tells it to drop its rules, passes a human review. `openguildkit check` verifies that the instructions match the profile and `sensitive.py` looks for credentials; neither reads the rest of these files. And a repository can hold the files of agent tools that the guard does not cover, MCP servers that fetch the latest version of a package at every start, and settings that take every permission prompt away, without anyone seeing them. `openguildkit host scan` does both: it reads the files, and it lists these tools, servers and settings.

```bash
openguildkit host scan                 # a few lines: the tools, the servers, one line per code, the command for the rest
openguildkit host scan --json          # the whole inventory and every finding with its path, line and excerpt
openguildkit host scan --strict        # exit 1 on any finding, not only on an error
```

The command works offline and in read-only mode. It opens no network connection, starts no process, writes no file and runs nothing it reads. It needs no initialized project; with one, it reads the guard and the host from the profile.

## What it reads for content

| Path | Read for |
|---|---|
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `WARP.md`, `.cursorrules`, `.windsurfrules`, `.rules`, `.github/copilot-instructions.md` | `hidden-character`, `instruction-override`, `remote-execution` |
| `.claude/agents/`, `.claude/skills/`, `.claude/commands/`, `.cursor/rules/`, `.github/instructions/`, `.windsurf/rules/`, `.roo/`, `.kilocode/`, `.junie/`, `.clinerules` (a file or a folder) | the same three codes, every file under the folder |
| `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, `.gemini/settings.json`, `.codex/config.toml`, `.codex/hooks.json`, `.claude/settings.json`, `.claude/settings.local.json` | `remote-execution` only |

Only the files at these places are read: an `AGENTS.md` in a subfolder is not. The reading is bounded like the machine checks of the rule packs (`rule_checks.py`):

- a file larger than 1 MB is not read, and neither are the files past the 200th or past 20 MB in all;
- a symbolic link that leaves the project is not followed, and a link that stays in the project is read once, under the first name in alphabetical order (`CLAUDE.md` linked to `AGENTS.md` is `AGENTS.md`);
- `.git`, `node_modules`, `.venv` and `.openguildkit/tasks` are not read, and neither is a file that looks binary.

Each file left alone is listed in `scanned.skipped` of the JSON with the reason, and the text output counts them: a scan that skips a file says so. A settings or MCP file that is not valid JSON (comments and trailing commas are accepted, as in `.vscode/mcp.json`) or TOML is listed the same way.

## What it lists

### The agent tools of the project

A tool is present when one of its files is. These are the file names OpenGuildKit looks for; they are conventions of each tool, not checked against each vendor's current documentation, so a tool that moves its files is missed, and a folder of the same name that another tool wrote is taken for it. Only the file names of `claude-code` and `codex` come from the code of OpenGuildKit itself (`CLAUDE.md`, `.claude/settings.json`, `.mcp.json`, `.codex/config.toml`, `.codex/hooks.json`).

| Tool | Files that show it | Reads AGENTS.md, by the agents.md list |
|---|---|---|
| `aider` Aider | `.aider.conf.yml` | listed |
| `claude-code` Claude Code | `CLAUDE.md`, `.claude`, `.mcp.json` | not listed; reads `CLAUDE.md`, where OpenGuildKit writes an import of `AGENTS.md` |
| `cline` Cline | `.clinerules` | not documented as reading AGENTS.md |
| `codex` Codex | `.codex` | listed |
| `copilot` GitHub Copilot | `.github/copilot-instructions.md`, `.github/instructions` | listed, as "Coding agent" |
| `cursor` Cursor | `.cursor`, `.cursorrules` | listed |
| `gemini-cli` Gemini CLI | `GEMINI.md`, `.gemini` | listed |
| `goose` goose | `.goosehints` | listed |
| `junie` Junie | `.junie` | listed |
| `kilo` Kilo Code | `.kilocode` | listed |
| `opencode` opencode | `opencode.json`, `opencode.jsonc`, `.opencode` | listed |
| `roo` Roo Code | `.roo` | listed |
| `warp` Warp | `WARP.md` | listed |
| `windsurf` Windsurf | `.windsurf`, `.windsurfrules` | listed |
| `zed` Zed | `.rules`, `.zed` | listed |

**What "listed" rests on.** The one source for these statements is the compatibility list of [agents.md](https://agents.md) (repository agentsmd/agents.md, component `CompatibilitySection`), read on 2026-11-25. It names 23 tools: Codex, Amp, Jules, Cursor, Factory, RooCode, Aider, Gemini CLI, goose, Kilo Code, opencode, Zed, Warp, GitHub Copilot (entry "Coding agent"), VS Code, Ona, Devin, Windsurf, Augment Code, Junie, Phoenix, Semgrep and UiPath. A tool that is not on that list is shown as **not documented as reading AGENTS.md**: that says the list does not name it, not that it ignores the file. For ten tools of the list the table has no file name to look for (Amp, Jules, Factory, VS Code, Ona, Devin, Augment Code, Phoenix, Semgrep, UiPath), so the scan cannot show that they are used. The `--json` output carries the source, the day and the list under `source.agents_md`.

Since the managed block of `AGENTS.md` reaches every tool that reads the file, the tools marked "listed" receive the rules and the task workflow of OpenGuildKit; Claude Code receives them through the import that `init` writes in `CLAUDE.md`; Cline is not documented as receiving them.

**What OpenGuildKit covers for each tool.**

- `claude-code` and `codex`: what `host check` says about the hooks of the guard, for the guard of the profile. With `"guard": "off"` no hook runs (`host check` says nothing about hooks then). With `observe` or `enforce`, the status is the one of the control "The board is consulted before each change": `enforced` when the hooks are installed and can run, `missing` otherwise. `host apply` installs the hooks of the profile's host only: a project of host `claude-code` that also holds a `.codex` folder has no Codex hook, and the scan says so.
- every other tool: no hook blocks an edit made through it, and the CI check (`guard --ci`) is the only barrier.

A present tool whose hooks are not enforced is a `surface-uncovered` finding: a `note`, a `warning` when the profile says `"guard": "enforce"`. It is information, not an error: only `--strict` makes it fail the command.

### MCP servers

The scan reads `.mcp.json` (key `mcpServers`), `.cursor/mcp.json` (`mcpServers`), `.vscode/mcp.json` (`servers`), `.gemini/settings.json` (`mcpServers`) and `.codex/config.toml` (tables `mcp_servers.<name>`). For each server it shows the name, the file, the transport (`stdio`, `http`, `sse`, `remote` for an address with no declared type, or `unknown`), the launch (the command and its arguments, or the address) and whether the [tool registry](tools.md) knows it: by its npm or Python package, its Docker image, its address or its command line. It never shows the environment, the headers or any credential: the value of `-e NAME=value`, of an option such as `--token` or `--api-key`, a user name, a password or a query string in an address is replaced or left out.

- `mcp-unpinned` (warning): `npx`, `bunx`, `pnpm dlx`, `uvx` or `pipx run` with a package that has no version, the tag `latest` or any tag or range that is not one fixed version; `docker run` with an image that has no tag, the tag `latest` and no digest. A launch by any other command (`node server.js`) names no package to pin and is not judged.
- `mcp-insecure-transport` (error): an address that starts with `http://` and does not point at `localhost`, `127.0.0.1` or `[::1]`.

### Permissive settings

`permissive-setting` (warning): in `.claude/settings.json` or `.claude/settings.local.json`, `permissions.defaultMode` set to `bypassPermissions`, `"Bash"` or `"Bash(*)"` in `permissions.allow`, or `enableAllProjectMcpServers` set to `true`; in `.codex/config.toml`, `approval_policy = "never"` together with `sandbox_mode = "danger-full-access"`. The key names are the ones of the issue that asked for this command; they are not read from each tool's documentation.

## What the findings mean

Each finding has a `code`, a `level` (`error`, `warning` or `note`), a `message`, a `path` relative to the project and written with `/`, a `line` (or none), and, for the content codes, an `excerpt`. In the excerpt the control and invisible characters are written `<U+XXXX>`, never as the character, and a line that looks like a credential (the detector of `sensitive.py`) is replaced by `[redacted]`: a secret never appears in the output. A file with more than 25 findings of one code lists the first 25 and one more finding that counts the rest.

| Code | Level | What it means |
|---|---|---|
| `hidden-character` | error | The line holds a character a person does not see: a Unicode tag (U+E0000 to U+E007F), a bidirectional control (U+202A to U+202E, U+2066 to U+2069), a directional mark (U+200E, U+200F, U+061C), a zero width space (U+200B), a word joiner (U+2060), or a byte order mark (U+FEFF) that is not the first character of the file. |
| `hidden-character` | warning | The line holds a zero width non-joiner (U+200C) or joiner (U+200D) that is neither inside an emoji sequence nor between two letters of Arabic, Persian or an Indic script, which are written with them. |
| `instruction-override` | warning | The line asks the agent to ignore or forget the previous instructions or rules, to hide an action or a fact from the user, to act without informing the person, or tells it "you are now" a role (the same in French: "ignore les instructions précédentes", "ne le dis pas à l'utilisateur", "sans en informer la personne", "tu es maintenant un..."). The block that OpenGuildKit manages in `AGENTS.md` and `CLAUDE.md` is not read for this code; it is read for the other two. |
| `remote-execution` | warning | The line runs code as it arrives: `curl`, `wget`, `iwr` or `irm` piped into `sh`, `bash`, `zsh`, `python`, `pwsh` or `iex`; `base64 -d` piped into an interpreter; `eval "$(curl ...)"`; `powershell -enc`; `Invoke-Expression`. |
| `mcp-unpinned` | warning | An MCP server starts a package or an image without one fixed version (above). |
| `mcp-insecure-transport` | error | An MCP server is reached over `http://` outside the machine. |
| `permissive-setting` | warning | A setting hands the agent every shell command or takes away its prompts or its sandbox (above). |
| `surface-uncovered` | note, or warning with `"guard": "enforce"` | A tool is present and no hook of OpenGuildKit blocks an edit made through it (above). |

What is never a `hidden-character`: a no-break space (U+00A0), a narrow no-break space (U+202F), a thin space (U+2009), accents, curly quotes, a byte order mark at the start of a file, a zero width joiner in an emoji such as a family or a flag, and the three flag sequences of England, Scotland and Wales.

A `warning` is a line to read, not proof of an attack: "Never ignore the rules above" is a rule, and the matching skips a formula that follows a negation ("do not", "never", "ne jamais"). A sentence like "Do not tell the user about this" in a file that asks for it is flagged on purpose, whoever wrote it.

## Exit code and JSON

The exit code is 1 when a finding is an `error`, and with `--strict` when there is any finding, a note included; 0 otherwise. `--json` prints:

```json
{
  "surfaces": [
    {"id": "cursor", "name": "Cursor", "files": [".cursor"], "reads_agents_md": true, "agents_md": "listed",
     "agents_md_text": "reads AGENTS.md (agents.md list, read 2026-11-25)",
     "coverage": {"status": "none", "detail": "no hook blocks an edit; the CI check (guard --ci) is the only barrier"}}
  ],
  "mcp_servers": [
    {"name": "docs", "file": ".mcp.json", "host": "claude-code", "transport": "stdio",
     "launch": "npx -y some-docs-server", "pinned": false, "registry": null}
  ],
  "findings": [
    {"code": "mcp-unpinned", "level": "warning", "message": "MCP server \"docs\" runs the npm package some-docs-server with no version: ...",
     "path": ".mcp.json", "line": 10}
  ],
  "source": {"agents_md": {"url": "https://agents.md", "read": "2026-11-25", "tools": ["Codex", "..."]}},
  "scanned": {"files": 10, "skipped": []}
}
```

`agents_md` is `listed`, `import` or `not-documented`; `coverage.status` is `enforced`, `missing`, `off`, `none` or `unreadable`; `pinned` is `true`, `false`, or `null` when the launch names no package. The findings of both analyses are in one list, sorted by path, line and code.

## What it does not prove

- It blocks nothing. No hook of any agent runs it: a person runs it, or CI does. A clean scan says that these patterns are absent from these files, not that the files are safe; for any tool but Claude Code and Codex, no hook blocks an edit and the CI check (`guard --ci`) is the only barrier.
- It does not detect every injection. Matching is by a short list of words in English and French, in the order and the distance the list names; a sentence in another language, another wording, a text split over lines or an instruction hidden in an image passes. Hidden characters outside the list above (soft hyphen, variation selectors, invisible mathematical operators) are not flagged. A `bash <(curl ...)` or `sh -c "$(curl ...)"` is not detected as `remote-execution`.
- It reads files, not what an agent does with them. It does not check that a command a file asks for is safe, only that a line has this shape.
- It does not read what a person puts elsewhere: `README.md`, source code, the files of a subfolder, the user-level settings of an agent in the home folder, a Codex profile (`[profiles.*]`) or a setting that another tool reads from an environment variable.
- A settings file is read as text, line by line, for `remote-execution`: it does not read hooks as structured data.
- The inventory shows the files that exist, not which tool a person runs. A `.cursor` folder is present whether or not anyone uses Cursor, and a tool that leaves no file in the repository is not listed. The registry check recognises a server by what it runs: a server that the registry does not name, or that runs a fork, is shown as not in the registry, which is no verdict on it.
- It never checks a package, an image or an address on the network: "version not fixed" says the launch does not name one version, not that the latest version is unsafe.
