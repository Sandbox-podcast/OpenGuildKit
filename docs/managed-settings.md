# Managed settings: one deployment for every project of a workstation

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
```

The command needs no project and installs nothing: it prints the file, or writes it in the folder `--output` names, and says where each system expects it and which channel an MDM has.
Copy it with your own MDM.

| Host | The file holds | Deploy it at | MDM channel |
|---|---|---|---|
| `claude-code` | the two guard hooks, run with the command given, and the deny rules of the approval commands, terminal emulators and pseudo-terminals (`50-openguildkit.json`) | macOS `/Library/Application Support/ClaudeCode/managed-settings.d/`, Linux `/etc/claude-code/managed-settings.d/`, Windows `C:\Program Files\ClaudeCode\managed-settings.d\` | macOS: a configuration profile, domain `com.anthropic.claudecode`; Windows: the registry key `HKLM\SOFTWARE\Policies\ClaudeCode` |
| `codex` | `[features] hooks = true`, which keeps a user from turning the hooks off (`requirements.toml`) | macOS and Linux `/etc/codex/`, Windows `%ProgramData%\OpenAI\Codex\` | macOS: domain `com.openai.codex`, key `requirements_toml_base64` |
| `gemini-cli` | the guard hooks and `hooksConfig.enabled: true`, the whole system settings file (`settings.json`) | macOS `/Library/Application Support/GeminiCli/`, Linux `/etc/gemini-cli/`, Windows `C:\ProgramData\gemini-cli\` | none read |

`--command` is the command the hooks run: give the full path where the PATH of the agent may not hold `openguildkit`. A path with a space is written between double quotes.
`--block-on-failure` writes Claude Code's `onFailure: block` on the edit hook. It is not the default: the file applies to every repository of the workstation, and a hook that cannot start would then refuse every edit, in projects that have nothing to do with OpenGuildKit.
The Gemini CLI file replaces the system file already there: merge it by hand.

### What was read, and what was not

The paths, the channels and the key names come from pages that the audit of issue #453 read on 2026-11-26 and that were not read again when the command was written:

- Claude Code: https://code.claude.com/docs/en/managed-settings.md (the files, the folder `managed-settings.d/`, the profile and the registry key) and https://code.claude.com/docs/en/settings-reference.md (`allowManagedHooksOnly`).
- Codex: https://learn.chatgpt.com/docs/enterprise/managed-configuration.md (`requirements.toml`, its places, the MDM key, the pin of `[features].hooks`).
- Gemini CLI: https://geminicli.com/docs/reference/configuration/ (the system settings file and its places; it overrides the other files).

À vérifier, because no page was read for it:

- where `managed-settings.d/` stands on Linux and Windows (the page names the folder, the places above put it next to `managed-settings.json`);
- the value of `permissions.disableBypassPermissionsMode`, and the form of `allowedMcpServers` and `availableModels`: none is written;
- the key names of managed hooks and of `forbidden` rules in the `requirements.toml` of Codex: only `[features] hooks = true` is written, and the hooks of Codex come from `.codex/hooks.json` (`host apply`);
- that the Gemini CLI system file reads `hooks` and `hooksConfig` as the project file does;
- that the Codex file goes in `/etc/codex/` on macOS too.

A key written with a wrong name or value could make a host ignore the file and leave the hooks off while everything looks deployed. That is why this command writes only what the pages say.
The Edit rules that `host apply` writes for the files of a project are not in the managed file: a path rule is relative to the settings source, and the hooks refuse those edits anyway.

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
