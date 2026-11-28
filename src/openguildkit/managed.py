"""Managed settings: the files an administrator deploys by MDM so that the guard hooks run in every project of a
workstation, and what `host check` reads back of them.

`openguildkit host managed --host H --os S` prints the file of one host, or writes it into the folder it is given, and
says where each system expects it and which channel an MDM has. It installs nothing and writes nowhere else. The
facts about the hosts (paths, channels, key names) are those of the pages the audit of issue #453 read on 2026-11-26;
they were not read again when this module was written, and what no page was read for is marked "à vérifier".

Entry: add_options, run, only_managed_hooks.
Tests: tests/test_managed_settings.py.
"""

import json
import sys
from pathlib import Path

from . import hosts
from .doc_links import doc_link
from .storage import load_json, write_text

OS_NAMES = ("macos", "linux", "windows")
FRAGMENT = "50-openguildkit.json"
AUDIT_READ = "2026-11-26"
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
        "notes": (("The folder managed-settings.d/ sits next to managed-settings.json: the page names it, and where it "
                   "stands on Linux and Windows is à vérifier."),
                  ("Not written, value or form not read (à vérifier): permissions.disableBypassPermissionsMode, "
                   "allowedMcpServers, availableModels. The Edit rules on the protected files of a project are not "
                   "written either: the hooks refuse those edits, and a path rule is relative to the settings source.")),
    },
    "codex": {
        "file": "requirements.toml",
        "where": {"macos": "/etc/codex/", "linux": "/etc/codex/", "windows": "%ProgramData%\\OpenAI\\Codex\\"},
        "channel": {"macos": "MDM, domain com.openai.codex, key requirements_toml_base64 (this file, base64 encoded)"},
        "pages": ("https://learn.chatgpt.com/docs/enterprise/managed-configuration.md",),
        "notes": (("Only [features] hooks = true is written: it keeps a user from turning the hooks off. The key names of "
                   "managed hooks and of forbidden rules in requirements.toml, and the macOS place of the file, are "
                   "à vérifier (the reference of requirements.toml was not read). The hooks come from the project's "
                   ".codex/hooks.json (host apply)."),),
    },
    "gemini-cli": {
        "file": "settings.json",
        "where": {"macos": "/Library/Application Support/GeminiCli/", "linux": "/etc/gemini-cli/",
                  "windows": "C:\\ProgramData\\gemini-cli\\"},
        "channel": {},
        "pages": ("https://geminicli.com/docs/reference/configuration/",),
        "notes": (("This file is the whole system settings file: it replaces one already there, so merge by hand. Its "
                   "keys hooks and hooksConfig.enabled are those of the project file ({gemini_page}); that the "
                   "system file reads them the same way is à vérifier. It overrides the other settings files of "
                   "Gemini CLI."),),
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
                      "provider addresses; what it does not name is an error.")
    host.add_argument("--block-on-failure", action="store_true",
                      help="With managed and Claude Code: refuse an edit when the hook cannot start (onFailure block).")


def _quoted(command: str) -> str:
    return f'"{command}"' if any(char.isspace() for char in command) else command


def _content(host: str, command: str, block: bool) -> str:
    if host == "codex":
        return ("# Managed by OpenGuildKit: deploy it with your MDM (openguildkit host managed --host codex).\n"
                "[features]\nhooks = true\n")
    if host == "claude-code":
        settings = {"hooks": hosts.guard_hooks(host, _quoted(command), block),
                    "permissions": {"deny": list(hosts.CLAUDE_APPROVAL_RULES)}}
    else:
        settings = {"hooks": hosts.guard_hooks(host, _quoted(command)), "hooksConfig": {"enabled": True}}
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def _guidance(host: str, system: str, shown_at: str | None) -> list[str]:
    target = TARGETS[host]
    lines = [f"Deploy it at: {target['where'][system]}{target['file']}"]
    if system in target["channel"]:
        lines.append(f"MDM channel: {target['channel'][system]}")
    lines += [f"Read on {AUDIT_READ} by the audit of issue #453, not read again: {page}" for page in target["pages"]]
    readme = doc_link("integrations/README.md", "gemini-cli")
    lines += [f"Note: {note.format(gemini_page=readme)}" for note in target["notes"]]
    return [*lines, "Nothing was installed" + (f": the file is at {shown_at}." if shown_at else ": copy it with your MDM.")]


def run(args) -> int:
    """host managed: print the file of one host, or write it in the folder --output names, and say how to deploy it."""
    if not args.host or not args.os:
        raise ValueError("host managed needs --host (claude-code, codex or gemini-cli) and --os (macos, linux or windows).")
    if args.json:
        raise ValueError("host managed prints the file as it is deployed, so --json is not an option of it.")
    if args.block_on_failure and args.host != "claude-code":
        raise ValueError("--block-on-failure is the onFailure setting of a Claude Code hook: the other files have none.")
    if args.hook_command != "openguildkit" and args.host == "codex":
        raise ValueError("--command names the command of the hooks: the Codex file holds none.")
    text = _content(args.host, args.hook_command, args.block_on_failure)
    if args.output is None:
        print(text, end="")
        print("\n".join(_guidance(args.host, args.os, None)), file=sys.stderr)
        return 0
    path = args.output / args.host / TARGETS[args.host]["file"]
    write_text(path, text)
    print("\n".join([f"Wrote {path.as_posix()}", *_guidance(args.host, args.os, path.as_posix())]))
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
