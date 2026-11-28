"""Writes the settings files an administrator deploys by MDM for the managed layer of Claude Code, Codex and Gemini CLI,
and reads back what keeps the hooks of a project from running.

`openguildkit host managed --host H --os S` prints the file of one host, or writes it into the folder it is given, and
says where each system expects it and which channel an MDM has. It installs nothing and writes nowhere else. With
--allow FILE, the allow list of `host scan` (allowlist.py) becomes the locks of the host where the page of the host
shows a form it maps to: the models and addresses of Claude Code, and the named servers of Codex and Gemini CLI. The facts about the hosts (paths, channels, key names) are those of the pages read on
2026-11-28 (PAGES_READ); what no page was read for is marked "à vérifier" and not written.

Entry: add_options, run, only_managed_hooks.
Tests: tests/test_managed_settings.py.
"""

import json
import sys
from pathlib import Path

from . import allowlist, hosts
from .doc_links import doc_link
from .errors import OgkError
from .storage import load_json, write_text
from .wording import plural

OS_NAMES = ("macos", "linux", "windows")
FRAGMENT = "50-openguildkit.json"
PAGES_READ = "2026-11-28"
TARGETS: dict[str, dict] = {
    "claude-code": {
        "file": FRAGMENT,
        "where": {"macos": "/Library/Application Support/ClaudeCode/managed-settings.d/",
                  "linux": "/etc/claude-code/managed-settings.d/",
                  "windows": "C:\\Program Files\\ClaudeCode\\managed-settings.d\\"},
        "channel": {"macos": "a configuration profile, domain com.anthropic.claudecode",
                    "windows": "the registry key HKLM\\SOFTWARE\\Policies\\ClaudeCode"},
        "pages": ("https://code.claude.com/docs/en/managed-settings.md",
                  "https://code.claude.com/docs/en/settings-reference.md"),
        "notes": (("permissions.disableBypassPermissionsMode is \"disable\": no one enters bypassPermissions mode, and "
                   "Claude Code rejects --dangerously-skip-permissions."),
                  ("The Edit rules on the protected files of a project are not written: the hooks refuse those edits, "
                   "and a path rule is relative to the settings source.")),
    },
    "codex": {
        "file": "requirements.toml",
        "where": {"macos": "/etc/codex/", "linux": "/etc/codex/", "windows": "%ProgramData%\\OpenAI\\Codex\\"},
        "channel": {"macos": "MDM, domain com.openai.codex, key requirements_toml_base64 (this file, base64 encoded)"},
        "pages": ("https://learn.chatgpt.com/docs/enterprise/managed-configuration.md",
                  "https://developers.openai.com/codex/hooks.md"),
        "notes": (("The guard hooks are managed hooks under [hooks], and [features] hooks = true keeps a user from "
                   "turning them off. allow_managed_hooks_only is not written: other hooks keep running. In a project "
                   "where host apply wrote .codex/hooks.json too, the guard runs twice, with the same answer."),),
    },
    "gemini-cli": {
        "file": "settings.json",
        "where": {"macos": "/Library/Application Support/GeminiCli/", "linux": "/etc/gemini-cli/",
                  "windows": "C:\\ProgramData\\gemini-cli\\"},
        "channel": {},
        "pages": ("https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/reference/configuration.md",
                  "https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/tools/mcp-server.md",
                  "https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/cli/enterprise.md"),
        "notes": (("This file is the whole system settings file: it replaces one already there, so merge by hand. It "
                   "overrides the other settings files of Gemini CLI, and its keys hooks and hooksConfig.enabled are "
                   "settings of every file ({gemini_page})."),),
    },
}
CLAUDE_FOLDERS = {"darwin": "/Library/Application Support/ClaudeCode", "win32": "C:\\Program Files\\ClaudeCode"}
# Where Claude Code reads its managed settings on this system: a test points it at a folder of its own.
CLAUDE_FOLDER = Path(CLAUDE_FOLDERS.get(sys.platform, "/etc/claude-code"))


def add_options(host) -> None:
    """The options of `host managed` and of `host scan --allow` on the host parser."""
    host.add_argument("--host", choices=hosts.HOOK_HOSTS, help="With managed: the host whose file to produce.")
    host.add_argument("--os", choices=OS_NAMES, help="With managed: the system it will be deployed on.")
    host.add_argument("--output", type=Path, help="With managed: a folder to write the file in (default: print it).")
    host.add_argument("--command", dest="hook_command", default="openguildkit",
                      help="With managed: the command the hooks run (default openguildkit; give a full path).")
    host.add_argument("--allow", type=Path, metavar="FILE", help="With scan: an allow list of MCP servers, models and "
                      "provider addresses; what it does not name is an error. With managed: the same list, written as "
                      "the locks of the host where its page shows how.")
    host.add_argument("--block-on-failure", action="store_true",
                      help="With managed and Claude Code: refuse an edit when the hook cannot start (onFailure block).")


def _quoted(command: str) -> str:
    return f'"{command}"' if any(char.isspace() for char in command) else command


def _codex_hooks(command: str) -> list[str]:
    """The guard hooks as the [hooks] tables of requirements.toml, in the shape of the Codex hooks page."""
    lines = []
    for event, groups in hosts.guard_hooks("codex", _quoted(command)).items():
        for group in groups:
            lines += ["", f"[[hooks.{event}]]"] + ([f"matcher = {json.dumps(group['matcher'])}"] if "matcher" in group else [])
            for handler in group["hooks"]:
                lines += ["", f"[[hooks.{event}.hooks]]",
                          *(f"{key} = {json.dumps(value)}" for key, value in handler.items())]
    return lines


def _unnamed(host: str, allow: dict, why: str) -> str | None:
    """Why the servers of the list are not written for a host that allows a server by its name, or None."""
    unnamed = allow["names"].count(None)
    if not unnamed:
        return None
    return (f"The allow list is not written for {host}: {plural(unnamed, 'server')} of the list {'has' if unnamed == 1 else 'have'} "
            f"no name, and {why}. Give each server a name, or check it with openguildkit host scan --allow FILE in each project.")


def _not_read(host: str, allow: dict) -> list[str]:
    axes = [label for axis, label in (("models", "models"), ("endpoints", "provider addresses")) if axis in allow]
    return [f"The {' and '.join(axes)} of the list are not written for {host}: no managed key for them was read."] if axes else []


def _codex_servers(allow: dict | None) -> tuple[list[str], list[str]]:
    """The approved list mcp_servers of requirements.toml: a table per server, keyed by its name, with its identity (an
    address, or the program a server runs), and what is not written, with why."""
    if allow is None:
        return [], []
    left = _not_read("codex", allow)
    if "mcp_servers" not in allow:
        return [], left
    why = _unnamed("codex", allow, "its page approves a server by its name and its identity")
    servers = allow["mcp_servers"]
    packages = [item for item in servers if not item.lower().startswith(("http://", "https://", "command:"))]
    if why is None and packages:
        why = (f"The allow list is not written for codex: {packages[0]} runs a package, and Codex matches such a server "
               "by its program and each of its arguments, which the list does not hold. Check it with openguildkit host "
               "scan --allow FILE in each project.")
    if why:
        return [], [why + " A partial list would turn off the other servers.", *left]
    lines = [] if servers else ["", "[mcp_servers]"]
    for item, name in zip(servers, allow["names"], strict=True):
        address = item.lower().startswith(("http://", "https://"))
        identity = f"url = {json.dumps(item)}" if address else f"command = {json.dumps(item.split(':', 1)[1])}"
        lines += ["", f"[mcp_servers.{name}]", f"identity = {{ {identity} }}"]
    return lines, left


def _gemini_servers(allow: dict | None) -> tuple[dict, list[str]]:
    """mcp.allowed of the Gemini CLI system settings: the names of the servers, and what is not written, with why."""
    if allow is None:
        return {}, []
    left = _not_read("gemini-cli", allow)
    if "mcp_servers" not in allow:
        return {}, left
    why = _unnamed("gemini-cli", allow, "mcp.allowed lists servers by name")
    if why is None and not allow["mcp_servers"]:
        why = "The allow list is not written for gemini-cli: no page says what an empty mcp.allowed does (à vérifier)."
    if why:
        return {}, [why, *left]
    return {"mcp": {"allowed": list(allow["names"])}}, [
        ("mcp.allowed matches a server by its name only, and Gemini CLI runs the tools of a listed server without "
         "asking: a user can define another server under an allowed name. Define each approved server under "
         "mcpServers in this same file, which a user cannot override (the enterprise page); the list holds no command "
         "to write there."), *left]


def _locks(host: str, allow: dict | None) -> tuple[dict, list[str]]:
    """The keys of the Claude Code file that the allow list becomes, and what is not written, with why."""
    if allow is None or host != "claude-code":
        return {}, []
    keys, left = {}, []
    if "models" in allow:
        keys["availableModels"] = allow["models"]
    if "mcp_servers" in allow:
        addresses = [item for item in allow["mcp_servers"] if item.lower().startswith(("http://", "https://"))]
        if len(addresses) == len(allow["mcp_servers"]):
            keys["allowedMcpServers"] = [{"serverUrl": item} for item in addresses]
        else:
            left.append("allowedMcpServers is not written: a server named by package or command needs its exact "
                        "command line (serverCommand), which the list does not hold, and a partial list would block "
                        "every other local server.")
    if "endpoints" in allow:
        left.append("The provider addresses of the list are not written: no managed key for them was read.")
    return keys, left


def _content(host: str, command: str, block: bool, allow: dict | None = None) -> tuple[str, list[str]]:
    locks, left = _locks(host, allow)
    if host == "codex":
        servers, left = _codex_servers(allow)
        return ("\n".join(["# Managed by OpenGuildKit: deploy it with your MDM (openguildkit host managed --host codex).",
                           "[features]", "hooks = true", *servers, *_codex_hooks(command)]) + "\n"), left
    if host == "claude-code":
        settings = {"hooks": hosts.guard_hooks(host, _quoted(command), block),
                    "permissions": {"deny": list(hosts.CLAUDE_APPROVAL_RULES), "disableBypassPermissionsMode": "disable"},
                    **locks}
    else:
        locks, left = _gemini_servers(allow)
        settings = {"hooks": hosts.guard_hooks(host, _quoted(command)), "hooksConfig": {"enabled": True}, **locks}
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n", left


def _guidance(host: str, system: str, shown_at: str | None, left: list[str]) -> list[str]:
    target = TARGETS[host]
    lines = [f"Deploy it at: {target['where'][system]}{target['file']}"]
    if system in target["channel"]:
        lines.append(f"MDM channel: {target['channel'][system]}")
    lines += [f"Read on {PAGES_READ}: {page}" for page in target["pages"]]
    readme = doc_link("integrations/README.md", "gemini-cli")
    lines += [f"Note: {note.format(gemini_page=readme)}" for note in [*target["notes"], *left]]
    return [*lines, "Nothing was installed" + (f": the file is at {shown_at}." if shown_at else ": copy it with your MDM.")]


def run(args) -> int:
    """host managed: print the file of one host, or write it in the folder --output names, and say how to deploy it."""
    if not args.host or not args.os:
        raise OgkError("OGK-CORE-005", "host managed needs --host (claude-code, codex or gemini-cli) and --os (macos, linux or windows).")
    if args.json:
        raise OgkError("OGK-CORE-006", "host managed prints the file as it is deployed, so --json is not an option of it.")
    if args.block_on_failure and args.host != "claude-code":
        raise OgkError("OGK-CORE-023", "--block-on-failure is the onFailure setting of a Claude Code hook: the other files have none.")
    allow = allowlist.load_allow(args.allow) if args.allow else None
    text, left = _content(args.host, args.hook_command, args.block_on_failure, allow)
    if args.output is None:
        print(text, end="")
        print("\n".join(_guidance(args.host, args.os, None, left)), file=sys.stderr)
        return 0
    path = args.output / args.host / TARGETS[args.host]["file"]
    write_text(path, text)
    print("\n".join([f"Wrote {path.as_posix()}", *_guidance(args.host, args.os, path.as_posix(), left)]))
    return 0


def _managed_files() -> list[tuple[Path, dict]]:
    """The managed settings of this workstation that Claude Code reads and that parse: managed-settings.json, then the
    files of managed-settings.d in name order."""
    found = []
    for path in [CLAUDE_FOLDER / "managed-settings.json", *sorted((CLAUDE_FOLDER / "managed-settings.d").glob("*.json"))]:
        try:
            data = load_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            found.append((path, data))
    return found


def _runs_guard(files: list[tuple[Path, dict]]) -> bool:
    commands = [handler.get("command") for _, data in files if isinstance(data.get("hooks"), dict)
                for groups in data["hooks"].values() if isinstance(groups, list)
                for group in groups if isinstance(group, dict) and isinstance(group.get("hooks"), list)
                for handler in group["hooks"] if isinstance(handler, dict)]
    ends = [command for command in commands if isinstance(command, str)]
    return any(item.endswith(" guard --hook prompt") for item in ends) and any(
        item.endswith(" guard --hook pre-edit") for item in ends)


def only_managed_hooks() -> tuple[str, bool] | None:
    """Claude Code runs only the hooks the organization deploys when a managed file says allowManagedHooksOnly: then
    the hooks of a project do not run. None without that key; else what host check says, and whether the managed hooks
    run openguildkit guard. A profile or a registry key is not read: à vérifier."""
    files = _managed_files()
    keyed = [path for path, data in files if data.get("allowManagedHooksOnly") is True]
    if not keyed:
        return None
    where = keyed[0].as_posix()
    if _runs_guard(files):
        text = (f"{where} sets allowManagedHooksOnly, so Claude Code runs only the hooks the organization deploys; "
                "they run openguildkit guard on each request and before file edits.")
        return text, True
    text = (f"{where} sets allowManagedHooksOnly: Claude Code runs only the hooks the organization deploys, and none "
            "of the managed files runs openguildkit guard, so the hooks of this project do not run. Deploy them with "
            "openguildkit host managed --host claude-code, or remove the key; host apply cannot fix this.")
    return text, False
