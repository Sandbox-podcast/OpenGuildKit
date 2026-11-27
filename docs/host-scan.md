# Scan what an agent reads, and list what could act

An agent reads `AGENTS.md`, the agents, Skills and commands of `.claude/`, the rules of Cursor and the instructions of Copilot as orders, without questioning them. A character nobody sees, or a sentence that tells it to drop its rules, passes a human review. `openguildkit check` verifies that the instructions match the profile and `sensitive.py` looks for credentials; neither reads the rest of these files. And a repository can hold the files of agent tools that the guard does not cover, MCP servers that fetch the latest version of a package at every start, and settings that take every permission prompt away, without anyone seeing them. `openguildkit host scan` does both: it reads the files, and it lists these tools, servers and settings.

```bash
openguildkit host scan                 # a few lines: the tools, the servers, one line per code, the command for the rest
openguildkit host scan --json          # the whole inventory and every finding with its path, line and excerpt
openguildkit host scan --strict        # exit 1 on any finding, not only on an error
openguildkit host scan --allow allow.json   # an error for each MCP server, model or provider address the list does not name
```

The command works offline and in read-only mode. It opens no network connection, starts no process, writes no file and runs nothing it reads. It needs no initialized project; with one, it reads the guard and the host from the profile.

## What it reads for content

| Path | Read for |
|---|---|
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `WARP.md`, `.cursorrules`, `.windsurfrules`, `.rules`, `.github/copilot-instructions.md` | `hidden-character`, `instruction-override`, `remote-execution` |
| `.claude/agents/`, `.claude/skills/`, `.claude/commands/`, `.cursor/rules/`, `.github/instructions/`, `.windsurf/rules/`, `.roo/`, `.kilocode/`, `.junie/`, `.clinerules` (a file or a folder) | the same three codes, every file under the folder |
| `.goosehints`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.override.md`, and the folders `.opencode/`, `.claude/rules/`, `.agents/skills/`, `.gemini/commands/`, `.github/prompts/`, `.github/agents/`, `.cursor/commands/`, `.windsurf/workflows/` | the same three codes (the places the tool table below already knew, added by issue #523) |
| `AGENTS.md`, `CLAUDE.md` and `GEMINI.md` in any subfolder | the same three codes |
| `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, `.gemini/settings.json`, `.codex/config.toml`, `.codex/hooks.json`, `.claude/settings.json`, `.claude/settings.local.json` | `remote-execution` only |

Only the files at these places are read.
The subfolders are searched by a walk of the project that starts no process and follows no link, so a folder that Git ignores is searched too.
The walk stops after 5,000 folders and says so in `scanned.skipped`.
Whether each tool reads each of these places comes from that tool's own documentation, which was not re-read for issue #523: à vérifier.

The reading is bounded like the machine checks of the rule packs (`rule_checks.py`):

- a file larger than 1 MB is not read, and neither are the files past the 200th or past 20 MB in all;
- a symbolic link that leaves the project is not followed, and a link that stays in the project is read once, under the first name in alphabetical order (`CLAUDE.md` linked to `AGENTS.md` is `AGENTS.md`);
- `.git`, `node_modules`, `.venv` and `.openguildkit/tasks` are not read, and neither is a file that looks binary.

Each file left alone is listed in `scanned.skipped` of the JSON with the reason, and the text output counts them: a scan that skips a file says so. A settings or MCP file that is not valid JSON (comments and trailing commas are accepted, as in `.vscode/mcp.json`) or TOML is listed the same way.

## What it lists

### The agent tools of the project

A tool is present when one of its files is. These are the file names OpenGuildKit looks for; they are conventions of each tool, not checked against each vendor's current documentation, so a tool that moves its files is missed, and a folder of the same name that another tool wrote is taken for it. Only the file names of `claude-code`, `codex` and `gemini-cli` come from the code of OpenGuildKit itself (`CLAUDE.md`, `.claude/settings.json`, `.mcp.json`, `.codex/config.toml`, `.codex/hooks.json`, `GEMINI.md`, `.gemini/settings.json`).

| Tool | Files that show it | Reads AGENTS.md, by the agents.md list |
|---|---|---|
| `aider` Aider | `.aider.conf.yml` | listed |
| `claude-code` Claude Code | `CLAUDE.md`, `.claude`, `.mcp.json` | not listed; reads `CLAUDE.md`, where OpenGuildKit writes an import of `AGENTS.md` |
| `cline` Cline | `.clinerules` | not documented as reading AGENTS.md |
| `codex` Codex | `.codex` | listed |
| `copilot` GitHub Copilot | `.github/copilot-instructions.md`, `.github/instructions`, `.github/hooks` | listed, as "Coding agent" |
| `cursor` Cursor | `.cursor`, `.cursorrules` | listed |
| `gemini-cli` Gemini CLI | `GEMINI.md`, `.gemini` | listed (its default context file is `GEMINI.md`: OpenGuildKit writes an import of `AGENTS.md` there when the profile's host is `gemini-cli`) |
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

- `claude-code`, `codex` and `gemini-cli`: what `host check` says about the hooks of the guard, for the guard of the profile. With `"guard": "off"` no hook runs (`host check` says nothing about hooks then). With `observe` or `enforce`, the status is the one of the control "The board is consulted before each change": `enforced` when the hooks are installed and can run, `missing` otherwise. `host apply` installs the hooks of the profile's host only: a project of host `claude-code` that also holds a `.codex` or `.gemini` folder has no Codex or Gemini CLI hook, and the scan says so. The hooks of Gemini CLI are those of [its section](../integrations/README.md#gemini-cli), not seen in a live session.
- `cursor` and `copilot`: they document a hook that can refuse a tool before it runs, but their pages, read on 2026-11-26, give no path of the file an edit tool is about to change ([Cursor hooks](https://cursor.com/docs/agent/hooks); GitHub Copilot [hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference) and [CLI hooks reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference)), so OpenGuildKit installs no hook for them ([what was read](../integrations/README.md#hooks-of-other-tools-what-was-read-and-why-none-was-added)). Their line says `no edit blocked, guard --ci is the only barrier (hook docs read 2026-11-26)`; `--json` carries the pages and the day under `coverage.source`, and `host check` prints the same sentence as a rule `by instruction`.
- every other tool: no hook blocks an edit made through it, and the CI check (`guard --ci`) is the only barrier.

A present tool whose hooks are not enforced is a `surface-uncovered` finding: a `note`, a `warning` when the profile says `"guard": "enforce"`. It is information, not an error: only `--strict` makes it fail the command.

### MCP servers

The scan reads `.mcp.json` (key `mcpServers`), `.cursor/mcp.json` (`mcpServers`), `.vscode/mcp.json` (`servers`), `.gemini/settings.json` (`mcpServers`) and `.codex/config.toml` (tables `mcp_servers.<name>`). For each server it shows the name, the file, the transport (`stdio`, `http`, `sse`, `remote` for an address with no declared type, or `unknown`), the launch (the command and its arguments, or the address) and whether the [tool registry](tools.md) knows it: by its npm or Python package, its Docker image, its address or its command line. It never shows the environment, the headers or any credential: the value of `-e NAME=value`, of an option such as `--token` or `--api-key`, a user name, a password or a query string in an address is replaced or left out.

- `mcp-unpinned` (warning): `npx`, `bunx`, `pnpm dlx`, `uvx` or `pipx run` with a package that has no version, the tag `latest` or any tag or range that is not one fixed version; `docker run` with an image that has no tag, the tag `latest` and no digest. A launch by any other command (`node server.js`) names no package to pin and is not judged.
- `mcp-insecure-transport` (error): an address that starts with `http://` and does not point at `localhost`, `127.0.0.1` or `[::1]`.

### The allow list

`--allow FILE` reads a list that a person keeps, in a policy repository or in the project, and turns what it does not name into an error.
Without the option nothing changes: the output and the exit code of a project are those of a scan with no list, and the scan reads no other file than the ones above.
The file is a JSON object with three lists, alone or under the key `allow`, so that a future organization policy can hold it:

```json
{"allow": {
  "mcp_servers": ["npm:@playwright/mcp@1.2.3", "pypi:mailchimp-mcp", "docker:ghcr.io/github/github-mcp-server", "https://mcp.example.com/mcp", "command:basecamp"],
  "models": ["claude-sonnet-4-5"],
  "endpoints": ["https://gateway.company.example"]
}}
```

An axis that the file does not have is not restricted, and an empty list allows nothing.

- `mcp_servers`: a server that runs a package is named by `npm:PACKAGE`, `pypi:PACKAGE` or `docker:IMAGE`, which allows every version, or with a version (`npm:PACKAGE@1.2.3`, `pypi:PACKAGE==2.0`, `docker:IMAGE:1.0`), which allows that one only. A remote server is named by its address, without its query. A server that runs another command (`node server.js`) is named by `command:PROGRAM`, which allows every use of that program. `mcp-not-allowed` is an error with the name of the server, its file and its line.
- `models`: the `model` of `.claude/settings.json` and `.claude/settings.local.json`, and the `model` of `.codex/config.toml`, compared as written. `model-not-allowed` is an error.
- `endpoints`: `env.ANTHROPIC_BASE_URL` of the Claude Code settings, and the `base_url` of each `model_providers` table of `.codex/config.toml`. An address is allowed when the list names it or an address above it (`https://gateway.company.example` allows `https://gateway.company.example/v1`); the query and the case do not count. `endpoint-not-allowed` is an error that names the host and never the rest of the address.

The two settings findings name the key and the value that was refused (a model, a host) and carry no excerpt: no other value of an `env` section reaches the output. The key names read in `.codex/config.toml` (`model`, `model_providers.*.base_url`) and the absence of any key read in `.gemini/settings.json` are à vérifier: no page of either host was read for this command.
`host managed` does not yet write the allow list as the locks of the hosts (`allowedMcpServers` and `availableModels` of Claude Code, a list of `requirements.toml` for Codex, `admin.mcp.config` for Gemini CLI): the exact form of each was not read, and `tools apply` does not refuse a server outside the list.

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
| `mcp-not-allowed` | error | With `--allow`: an MCP server that the allow list does not name (above). |
| `model-not-allowed` | error | With `--allow`: a model that the allow list does not name. |
| `endpoint-not-allowed` | error | With `--allow`: a provider address that the allow list does not name. |
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

## SARIF

`openguildkit host scan --format sarif` prints the findings as a SARIF 2.1.0 document for code scanning, under the ten codes of the table above, one rule each. The document is the one [`check` and `guard --ci` write](sarif.md): the same bytes at every run, paths relative to the project, no folder of the machine, and a stable fingerprint per finding. The exit code is the one of the text form. It does not go with `--json`, and it is for `host scan` only. [The upload to GitHub](sarif.md#upload-to-github-code-scanning) is described there.

## What it does not prove

- It blocks nothing. No hook of any agent runs it: a person runs it, or CI does. A clean scan says that these patterns are absent from these files, not that the files are safe; for any tool but Claude Code, Codex and Gemini CLI, no hook blocks an edit and the CI check (`guard --ci`) is the only barrier.
- It does not detect every injection. Matching is by a short list of words in English and French, in the order and the distance the list names; a sentence in another language, another wording, a text split over lines or an instruction hidden in an image passes. Hidden characters outside the list above (soft hyphen, variation selectors, invisible mathematical operators) are not flagged. A `bash <(curl ...)` or `sh -c "$(curl ...)"` is not detected as `remote-execution`.
- It reads files, not what an agent does with them. It does not check that a command a file asks for is safe, only that a line has this shape.
- It does not read what a person puts elsewhere: `README.md`, source code, any subfolder file but `AGENTS.md`, `CLAUDE.md` and `GEMINI.md`, the user-level settings of an agent in the home folder, a Codex profile (`[profiles.*]`) or a setting that another tool reads from an environment variable.
- A settings file is read as text, line by line, for `remote-execution`: it does not read hooks as structured data.
- The inventory shows the files that exist, not which tool a person runs. A `.cursor` folder is present whether or not anyone uses Cursor, and a tool that leaves no file in the repository is not listed. The registry check recognises a server by what it runs: a server that the registry does not name, or that runs a fork, is shown as not in the registry, which is no verdict on it.
- It never checks a package, an image or an address on the network: "version not fixed" says the launch does not name one version, not that the latest version is unsafe.
