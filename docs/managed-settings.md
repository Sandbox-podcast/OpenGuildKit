# Managed settings: one deployment for every project of a workstation

For: an administrator who deploys the hooks by MDM on every workstation, for Claude Code, Codex and Gemini CLI.

`openguildkit host apply` writes the settings of one project, one repository at a time.
Claude Code, Codex and Gemini CLI also have a layer that the company manages, which wins over every other one: files that an MDM deploys on each workstation.
Two things follow for a security team.
A policy of the company can make the hooks of a project stop running (Claude Code's `allowManagedHooksOnly` runs only the hooks the organization deploys), and a repository that has no OpenGuildKit profile gets no hook at all.
`openguildkit host managed` produces the files for the managed layer, `host check` reads the Claude Code ones back, and a workstation policy says what the hook does in a repository with no profile.

## Produce the files

```bash
openguildkit host managed --host claude-code --os macos                 # prints the file; the way to deploy it goes to standard error
openguildkit host managed --host codex --os linux --output ./managed    # writes ./managed/codex/requirements.toml
openguildkit host managed --host claude-code --os windows --command 'C:\Program Files\OGK\openguildkit.exe' --block-on-failure
openguildkit host managed --host claude-code --os macos --allow allow.json   # also the allow list of host scan, as the locks of the host
```

The command needs no project and installs nothing: it prints the file, or writes it in the folder `--output` names, and says where each system expects it and which channel an MDM has.
Copy it with your own MDM.

| Host | The file holds | Deploy it at | MDM channel |
|---|---|---|---|
| `claude-code` | the two guard hooks, run with the command given, the deny rules of the approval commands, terminal emulators and pseudo-terminals, and `permissions.disableBypassPermissionsMode: "disable"` (`50-openguildkit.json`) | macOS `/Library/Application Support/ClaudeCode/managed-settings.d/`, Linux `/etc/claude-code/managed-settings.d/`, Windows `C:\Program Files\ClaudeCode\managed-settings.d\` | macOS: a configuration profile, domain `com.anthropic.claudecode`; Windows: the registry key `HKLM\SOFTWARE\Policies\ClaudeCode` |
| `codex` | the two guard hooks as managed hooks under `[hooks]`, and `[features] hooks = true`, which keeps a user from turning the hooks off (`requirements.toml`) | macOS and Linux `/etc/codex/`, Windows `%ProgramData%\OpenAI\Codex\` | macOS: domain `com.openai.codex`, key `requirements_toml_base64` |
| `gemini-cli` | the guard hooks and `hooksConfig.enabled: true`, the whole system settings file (`settings.json`) | macOS `/Library/Application Support/GeminiCli/`, Linux `/etc/gemini-cli/`, Windows `C:\ProgramData\gemini-cli\` | none read |

`--command` is the command the hooks run: give the full path where the PATH of the agent may not hold `openguildkit`. A path with a space is written between double quotes.
`--block-on-failure` writes Claude Code's `onFailure: block` on the edit hook. It is not the default: the file applies to every repository of the workstation, and a hook that cannot start would then refuse every edit, in projects that have nothing to do with OpenGuildKit.
The Gemini CLI file replaces the system file already there: merge it by hand.

### The allow list as the locks of the hosts

`--allow FILE` takes the [allow list of `host scan`](host-scan.md#the-allow-list) and writes it where the page of the host shows a form it maps to:

| Axis of the list | Claude Code | Codex | Gemini CLI |
|---|---|---|---|
| `models` | `availableModels`, the list as it is: a model outside it cannot be selected | not written: no managed key for models was read | not written: no key that restricts models was read |
| `mcp_servers` | `allowedMcpServers`, one `serverUrl` entry per address, when the list names only addresses; an empty list blocks every server users add | the approved list `[mcp_servers]` of `requirements.toml`, a table per server keyed by its `name`, with `identity = { url = ... }` for an address and `identity = { command = ... }` for `command:PROGRAM`, when every server has a name and none is a package; an empty list turns off every server | `mcp.allowed`, the names of the servers, when every server has a name and the list is not empty |
| `endpoints` | not written: no managed key for a provider address was read | not written | not written |

Codex and Gemini CLI allow a server by its name, so a server of the list may carry one:

```json
{"allow": {"mcp_servers": [{"server": "https://mcp.example.com/mcp", "name": "docs"}, {"server": "command:basecamp", "name": "basecamp"}]}}
```

The name is the one the projects give the server in their host settings (the key under `mcpServers` or `[mcp_servers]`), made of letters, digits, `-` and `_`, and two servers cannot share one.
`host scan` reads the `server` alone.
A list where a server has no name is not written for Codex and Gemini CLI, and neither is a Codex list with a package (`npm:`, `pypi:`, `docker:`): Codex matches such a server by its program and each of its arguments, which the list does not hold, and a partial list would turn off the servers it leaves out.
`mcp.allowed` of Gemini CLI matches a name only, and Gemini CLI runs the tools of a listed server without asking: its enterprise page advises defining each approved server under `mcpServers` of the same system file, which a user cannot override.
The list holds no command to write there, so add those definitions by hand.
What an empty `mcp.allowed` does is on no page: à vérifier, and not written.

A list that names a server by package or command (`npm:@playwright/mcp`, `command:basecamp`) leaves `allowedMcpServers` out: Claude Code matches a local server by its exact command line (`serverCommand`), which the list does not hold, and a list with only the addresses would block every other local server.
What is not written is said on standard error, or in the output with `--output`. Without `--allow`, the files are as above.
`host scan --allow FILE` still checks each project against the whole list.

### What was read

The paths, the channels and the key names come from these pages, read on 2026-11-28:

- Claude Code: https://code.claude.com/docs/en/managed-settings.md (the files, the folder `managed-settings.d/` next to `managed-settings.json` in the system folder of each system, the profile and the registry key) and https://code.claude.com/docs/en/settings-reference.md (`allowManagedHooksOnly`, `permissions.disableBypassPermissionsMode` and its value `"disable"`, `availableModels`, `allowedMcpServers` and its entries `serverName`, `serverCommand`, `serverUrl`).
- Codex: https://learn.chatgpt.com/docs/enterprise/managed-configuration.md (`requirements.toml`, `/etc/codex/` on Linux and macOS, the MDM key, the pin of `[features].hooks`, the approved list `mcp_servers`: a table per server name with an `identity` of `command` or `url`, a server enabled only when its name and its identity match, an empty list that turns off every server, no key for models or provider addresses) and https://developers.openai.com/codex/hooks.md (managed hooks under `[hooks]` of `requirements.toml`, `allow_managed_hooks_only`).
- Gemini CLI: https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/reference/configuration.md (the system settings file and its places, which overrides the other files; `hooks`, `hooksConfig.enabled` and `mcp.allowed` among the settings of every file; no setting that restricts models), https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/tools/mcp-server.md (`mcp.allowed`, a list of server names, the keys of `mcpServers`) and https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/cli/enterprise.md (`mcp.allowed` in the system file, the tool calls of a listed server approved without asking, a server defined in the system file that a user cannot override).

Not written, by choice:

- `allow_managed_hooks_only` of Codex and `allowManagedHooksOnly` of Claude Code: they stop every other hook of the workstation.
- `managed_dir` of the Codex hooks: it says where scripts are installed, and the guard hooks run the `openguildkit` command, not a script.
- `admin.secureModeEnabled` of Gemini CLI, which disallows YOLO mode: the page lists it under `admin`, and whether the system settings file sets it is à vérifier.

A key written with a wrong name or value could make a host ignore the file and leave the hooks off while everything looks deployed. That is why this command writes only what the pages say.
The Edit rules that `host apply` writes for the files of a project are not in the managed file: a path rule is relative to the settings source, and the hooks refuse those edits anyway.
In a Codex project where `host apply` wrote `.codex/hooks.json`, the guard runs twice, from the project and from the managed file, with the same answer.

## What `host check` reads back

On the workstation where it runs, `host check` reads the Claude Code managed settings: `managed-settings.json` and the files of `managed-settings.d/`, in the folder of the system (`/Library/Application Support/ClaudeCode`, `/etc/claude-code` or `C:\Program Files\ClaudeCode`).
A file that sets `allowManagedHooksOnly: true` stops the hooks of the project, so the control "The board is consulted before each change" reads `missing`, with the file named, unless a managed file runs `openguildkit guard` before requests and before edits (the file `host managed` writes). `host apply` cannot fix it: deploy the managed file, or remove the key.
A configuration profile or a registry key is not read, and neither are the managed files of Codex and Gemini CLI: à vérifier.
The check reads files on the machine it runs on; a CI runner has none.

## The workstation policy

An administrator may deploy one more file, which only OpenGuildKit reads: `/etc/openguildkit/config.json` (on macOS also `/Library/Application Support/OpenGuildKit/config.json`, on Windows `%ProgramData%\OpenGuildKit\config.json`). No variable moves it, so an agent that sets the environment of a command cannot point the policy elsewhere. It is a JSON object with these keys only:

| Key | Values | What it does |
|---|---|---|
| `no_profile` | `allow` (the default, and what happens without the file), `observe`, `refuse` | What the guard hook does in a folder with no `.openguildkit` folder above it. `allow` exits 0 without a word, as before. `observe` flags the edit and lets it through. `refuse` exits 2 with a reason, as `enforce` does. A project whose profile says `"guard": "off"` is left alone whatever this says. |
| `audit_log` | `true`, or the name of a file | Turns on the [audit log](audit-log.md) without a variable in each environment. |

A policy file that is not JSON, holds another key or another value is refused with its name: in a folder with no profile the hook then refuses the edit, because a policy that cannot be read is not one that allows. The hook runs the policy only when there is no profile to read, or when it says `off`.
