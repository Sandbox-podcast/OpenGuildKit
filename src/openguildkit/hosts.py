"""Report and apply the project rules that a host agent can enforce itself.

OpenGuildKit cannot stop a host agent from using its tools. Some hosts can, through
their own project settings. This module writes those settings for the hosts it knows
and tells the requester which rules remain instructions or human checks.
"""

import json
import os
import re
import shutil
import tomllib
from pathlib import Path

from . import audit_log
from .doc_links import doc_link
from .storage import write_text

HOSTS = ("claude-code", "codex", "gemini-cli", "other")
# The hosts whose hooks `host apply` writes and `host check` reports.
HOOK_HOSTS = ("claude-code", "codex", "gemini-cli")
# Agent tools with a hook that can refuse a tool, whose pages, read on the day given, document no path of the file an
# edit tool is about to change in the input of that hook (integrations/README.md, "Hooks of other tools"). The guard
# needs that path, so they are not hosts: host check and host scan say what is left when their files are present.
UNHOOKED_TOOLS = {
    "cursor": {"name": "Cursor", "files": (".cursor", ".cursorrules"),
               "pages": ("https://cursor.com/docs/agent/hooks",), "read": "2026-11-26"},
    "copilot": {"name": "GitHub Copilot",
                "files": (".github/copilot-instructions.md", ".github/instructions", ".github/hooks"),
                "pages": ("https://docs.github.com/en/copilot/reference/hooks-reference",
                          "https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference"),
                "read": "2026-11-26"},
}


def unhooked_detail(tool_id: str) -> str:
    """The sentence host check and host scan print for a tool of UNHOOKED_TOOLS."""
    tool = UNHOOKED_TOOLS[tool_id]
    return (f"{tool['name']} reads the AGENTS.md instructions, but no hook blocks an edit made through it: guard --ci is the "
            f"only barrier (its hook pages, read {tool['read']}, give no edited file path: {', '.join(tool['pages'])}).")


def unhooked_source(tool_id: str) -> dict:
    tool = UNHOOKED_TOOLS[tool_id]
    return {"pages": list(tool["pages"]), "read": tool["read"]}
LAUNCHERS = (("openguildkit",), ("python", "-m", "openguildkit"), ("python3", "-m", "openguildkit"), ("py", "-m", "openguildkit"))
# Approving a task and withdrawing an approval (task revoke) are the person's acts at a terminal.
APPROVAL_COMMANDS = tuple((*launcher, "task", action) for action in ("decide", "revoke") for launcher in LAUNCHERS[:3])
TERMINAL_EMULATORS = ("script", "expect", "unbuffer", "tmux", "screen")
CLAUDE_RESEARCH_RULES = ("WebSearch", "WebFetch")
# Wildcards match every launcher (a venv path, python -m) and --project before the subcommand.
CLAUDE_APPROVAL_PATTERNS = (
    "*openguildkit* task decide*", "*openguildkit* task waive*", "*openguildkit* task authorize *--allow*",
    "*openguildkit* task revoke*",
    "*import pty*", "*pty.spawn*", "*pty.fork*", "*openpty*", "*pexpect*", "*ptyprocess*",
)
CLAUDE_APPROVAL_RULES = (
    tuple(f"Bash({' '.join(command)}:*)" for command in APPROVAL_COMMANDS)
    + tuple(f"Bash({tool}:*)" for tool in TERMINAL_EMULATORS)
    + tuple(f"Bash({pattern})" for pattern in CLAUDE_APPROVAL_PATTERNS)
)
# Files the guard relies on: the CLI writes most of them through its own commands, and the project catalog and the
# alert register change what the boards review and what blocks an approval. A leading / is relative to the settings
# source, the project root for .claude/settings.json; ./ would follow the current directory.
PROTECTED_PATHS = (
    ".openguildkit/tasks/**", ".openguildkit/decisions/**", ".openguildkit/project.json",
    ".openguildkit/catalog.lock.json", ".claude/settings.json", ".claude/settings.local.json",
    ".openguildkit/alerts.json", ".openguildkit/catalog/**",
)
CLAUDE_PROTECTED_RULES = tuple(f"Edit(/{path})" for path in PROTECTED_PATHS)
OUTDATED_PROTECTED_RULES = tuple(f"Edit(./{path})" for path in PROTECTED_PATHS)


def restricted_paths(profile: dict) -> list[str]:
    """The path patterns that `restricted_paths` of .openguildkit/project.json closes to the agent; none when it is
    absent. Refused, with the file named, when it is not a list of {"paths": [project paths]} (a "class" text and a list
    of "boards" may come with each): a path is relative to the project, without .. and without parentheses."""
    entries = profile.get("restricted_paths")
    if entries is None:
        return []
    shape = ('restricted_paths in .openguildkit/project.json must be a list of objects such as {"paths": '
             '["data/customers/**"], "class": "restricted", "boards": ["security"]}: paths are project paths without a '
             'leading / or .., and without parentheses.')
    paths = []
    for entry in entries if isinstance(entries, list) else [None]:
        listed = entry.get("paths") if isinstance(entry, dict) else None
        if (not isinstance(entry, dict) or set(entry) - {"paths", "class", "boards"} or not isinstance(listed, list)
                or not listed or any(not isinstance(item, str) or not item.strip() or item.startswith(("/", "\\"))
                                     or ".." in item.split("/") or any(char in item for char in "()\r\n")
                                     for item in listed)
                or not isinstance(entry.get("class", ""), str)
                or (not isinstance(entry.get("boards", []), list)
                    or any(not isinstance(item, str) for item in entry.get("boards", [])))):
            raise ValueError(shape)
        paths += [item.strip() for item in listed]
    return list(dict.fromkeys(paths))


def restricted_rules(profile: dict) -> list[str]:
    """The Claude Code rules for those paths: its file tools may neither read nor edit them."""
    return [f"{tool}(/{path})" for path in restricted_paths(profile) for tool in ("Read", "Edit")]


def signers_rule(profile: dict) -> str | None:
    """The deny rule that keeps Claude Code's file tools away from the allowed signers file of a signed project."""
    approval = profile.get("approval") or {}
    if approval.get("mode") != "signed" or not isinstance(approval.get("allowed_signers"), str):
        return None
    return f"Edit(/{Path(approval['allowed_signers']).as_posix()})"
CODEX_RULES_FILE = Path(".codex") / "rules" / "openguildkit.rules"
CODEX_CONFIG_FILE = Path(".codex") / "config.toml"
CLAUDE_SETTINGS_FILE = Path(".claude") / "settings.json"
CODEX_RULES_HEADER = "# Managed by OpenGuildKit: openguildkit host apply rewrites this file.\n"
CODEX_WEB_SEARCH_LINE = 'web_search = "disabled"  # Set by OpenGuildKit: research policy is local-only.'
CODEX_TOOLS_BEGIN = "# >>> OpenGuildKit tools"
_TOML_TABLE = re.compile(r"[ \t]*\[")


def _read_settings(path: Path) -> dict:
    """A settings file whose hooks the host reads: refused with its name when it is not a JSON object with readable hooks."""
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        raise ValueError(f"{path.as_posix()} is not valid JSON: {error}") from error
    if not isinstance(settings, dict):
        raise ValueError(f"{path.as_posix()} must hold a JSON object.")
    _check_hook_groups(settings.get("hooks"), path)
    return settings


def _claude_settings(root: Path) -> dict:
    return _read_settings(root / CLAUDE_SETTINGS_FILE)


def _codex_hooks(root: Path) -> dict:
    """The Codex hooks file, refused with its name when it is not a JSON object the hooks can be read from."""
    path = root / CODEX_HOOKS_FILE
    if not path.is_file():
        return {}
    try:
        current = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        raise ValueError(f"{path.as_posix()} is not valid JSON: {error}") from error
    if not isinstance(current, dict):
        raise ValueError(f"{path.as_posix()} must hold a JSON object.")
    _check_hook_groups(current.get("hooks"), path)
    return current


def _check_hook_groups(hooks: object, path: Path) -> None:
    """Each hook group lists its handlers: the host could not run a group whose hooks are not a list."""
    for event, groups in hooks.items() if isinstance(hooks, dict) else ():
        for index, group in enumerate(groups if isinstance(groups, list) else []):
            if isinstance(group, dict) and not isinstance(group.get("hooks", []), list):
                raise ValueError(f"{path.as_posix()}: hooks.{event}[{index}].hooks must be a list of handlers. "
                                 "Fix or remove it, then run openguildkit host apply.")


def _claude_denied(root: Path) -> set[str]:
    permissions = _claude_settings(root).get("permissions", {})
    deny = permissions.get("deny", []) if isinstance(permissions, dict) else []
    return {rule for rule in deny if isinstance(rule, str)}


def _codex_config(root: Path) -> dict:
    path = root / CODEX_CONFIG_FILE
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path.as_posix()} is not valid TOML: {error}") from error


def _top_level_positions(text: str) -> list[int]:
    """Where a top-level key may go: before a table header or the tools block, at the end, then at the start.

    A line that looks like a header can sit inside a multi-line string, so each place is checked by parsing.
    """
    positions, offset = [], 0
    for line in text.splitlines(keepends=True):
        if _TOML_TABLE.match(line) or line.startswith(CODEX_TOOLS_BEGIN):
            positions.append(offset)
        offset += len(line)
    return [*positions, len(text), 0]


def _parses_as(text: str, expected: dict) -> bool:
    try:
        return tomllib.loads(text) == expected
    except tomllib.TOMLDecodeError:
        return False


def _codex_disable_web_search(path: Path, current: str, config: dict) -> str:
    """Add the OpenGuildKit web_search line as a top-level key, or refuse when no place parses as intended."""
    newline = "\r\n" if "\r\n" in current else "\n"
    text = current if not current or current.endswith("\n") else current + newline
    expected = {**config, "web_search": "disabled"}
    for position in _top_level_positions(text):
        updated = text[:position] + CODEX_WEB_SEARCH_LINE + newline + text[position:]
        if _parses_as(updated, expected):
            return updated
    raise ValueError(f'Could not add web_search = "disabled" to {path.as_posix()} safely. Add it at the top of the file yourself.')


def _codex_lift_web_search(path: Path, current: str, config: dict) -> str | None:
    """Remove the web_search line OpenGuildKit wrote, or return None when the file has none."""
    lines = current.splitlines(keepends=True)
    kept = [line for line in lines if line.strip() != CODEX_WEB_SEARCH_LINE]
    if len(kept) == len(lines):
        return None
    updated = "".join(kept)
    if not _parses_as(updated, {key: value for key, value in config.items() if key != "web_search"}):
        raise ValueError(f"Could not remove the OpenGuildKit web_search line from {path.as_posix()} safely. Remove it yourself.")
    return updated


def _codex_rules() -> str:
    rules = [CODEX_RULES_HEADER]
    for launcher in LAUNCHERS:
        for project in ((), ("--project", [".", "./"])):
            actions = ["decide", "waive", "authorize", "revoke"]
            pattern = ", ".join(json.dumps(part) for part in (*launcher, *project, "task", actions))
            rules.append(
                f"prefix_rule(pattern = [{pattern}], decision = \"forbidden\", "
                "justification = \"A person approves OpenGuildKit tasks in their own terminal.\")\n"
            )
    for tool in TERMINAL_EMULATORS:
        rules.append(
            f"prefix_rule(pattern = [{json.dumps(tool)}], decision = \"forbidden\", "
            "justification = \"Emulating a terminal could answer the OpenGuildKit approval prompt.\")\n"
        )
    return "".join(rules)


CODEX_HOOKS_FILE = Path(".codex") / "hooks.json"
GEMINI_SETTINGS_FILE = Path(".gemini") / "settings.json"
GUARD_PROMPT = "openguildkit guard --hook prompt"
GUARD_EDIT = "openguildkit guard --hook pre-edit"
EDIT_MATCHERS = {"claude-code": "Edit|Write|MultiEdit|NotebookEdit", "codex": "apply_patch|Edit|Write",
                 "gemini-cli": "write_file|replace"}
# Gemini CLI names its hooks, so that /hooks and hooksConfig.disabled can address them (integrations/README.md,
# "Gemini CLI", says what its documentation shows).
GEMINI_HOOK_NAMES = {GUARD_PROMPT: "openguildkit-prompt", GUARD_EDIT: "openguildkit-guard"}
GEMINI_EDIT_TOOLS = ("write_file", "replace")


def _guard_hooks(host: str) -> dict:
    if host == "gemini-cli":
        def handler(command: str) -> dict:
            return {"name": GEMINI_HOOK_NAMES[command], "type": "command", "command": command}

        return {
            "BeforeAgent": [{"matcher": "*", "hooks": [handler(GUARD_PROMPT)]}],
            "BeforeTool": [{"matcher": EDIT_MATCHERS[host], "hooks": [handler(GUARD_EDIT)]}],
        }
    return {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": GUARD_PROMPT}]}],
        "PreToolUse": [{"matcher": EDIT_MATCHERS[host], "hooks": [{"type": "command", "command": GUARD_EDIT}]}],
    }


def guard_hooks(host: str, command: str = "openguildkit", block_on_failure: bool = False) -> dict:
    """The two guard hooks of a host, running `command` instead of the name on the PATH (a managed file gives its full
    path). block_on_failure adds Claude Code's onFailure: block to the edit hook."""
    hooks = json.loads(json.dumps(_guard_hooks(host)))
    for groups in hooks.values():
        for group in groups:
            for handler in group["hooks"]:
                edit = handler["command"] == GUARD_EDIT
                handler["command"] = command + handler["command"].removeprefix("openguildkit")
                if edit and block_on_failure and host == "claude-code":
                    handler["onFailure"] = "block"
    return hooks


def _claude_hooks_present(hooks: object) -> bool:
    if not isinstance(hooks, dict):
        return False
    commands = {
        handler.get("command")
        for groups in hooks.values() if isinstance(groups, list)
        for group in groups if isinstance(group, dict)
        for handler in group.get("hooks", []) if isinstance(handler, dict)
    }
    return {GUARD_PROMPT, GUARD_EDIT} <= commands


def _edit_handlers(hooks: object, event: str = "PreToolUse") -> list[dict]:
    """The handlers of an event (PreToolUse, or BeforeTool for Gemini CLI) that run the pre-edit guard."""
    groups = hooks.get(event) if isinstance(hooks, dict) else None
    return [
        handler for group in (groups if isinstance(groups, list) else []) if isinstance(group, dict)
        for handler in group.get("hooks", []) if isinstance(handler, dict) and handler.get("command") == GUARD_EDIT
    ]


def _blocks_on_failure(hooks: object) -> bool:
    """Claude Code lets an edit through when a hook cannot start, unless the hook says onFailure: block."""
    handlers = _edit_handlers(hooks)
    return bool(handlers) and all(handler.get("onFailure") == "block" for handler in handlers)


def _merge_hooks(current: object, host: str, block_on_failure: bool = False) -> dict:
    hooks = dict(current) if isinstance(current, dict) else {}
    for event, groups in _guard_hooks(host).items():
        existing = hooks.get(event) if isinstance(hooks.get(event), list) else []
        if not any(handler.get("command") in (GUARD_PROMPT, GUARD_EDIT)
                   for group in existing if isinstance(group, dict)
                   for handler in group.get("hooks", []) if isinstance(handler, dict)):
            existing = [*existing, *groups]
        hooks[event] = existing
    if host == "claude-code":
        for handler in _edit_handlers(hooks):
            if block_on_failure:
                handler["onFailure"] = "block"
            else:
                handler.pop("onFailure", None)
    return hooks


def _matches_every_edit_tool(matcher: object) -> bool:
    """Whether a Gemini CLI matcher fires for write_file and for replace: an empty matcher or * fires for every tool,
    any other value is a regular expression (https://geminicli.com/docs/hooks/, "Matchers")."""
    if not isinstance(matcher, str):
        return matcher is None
    try:
        return matcher.strip() in ("", "*") or all(re.search(matcher, tool) for tool in GEMINI_EDIT_TOOLS)
    except re.error:
        return False


def _gemini_hooks_present(hooks: object) -> bool:
    """Both guard hooks stand under the events Gemini CLI fires, and the edit hook fires for write_file and replace."""
    if not isinstance(hooks, dict):
        return False

    def groups(event: str, command: str) -> list[dict]:
        return [group for group in (hooks.get(event) if isinstance(hooks.get(event), list) else [])
                if isinstance(group, dict) and any(isinstance(handler, dict) and handler.get("command") == command
                                                   for handler in group.get("hooks", []))]

    return bool(groups("BeforeAgent", GUARD_PROMPT)) and any(
        _matches_every_edit_tool(group.get("matcher")) for group in groups("BeforeTool", GUARD_EDIT))


def _gemini_hooks_config(settings: dict, path: Path) -> dict:
    config = settings.get("hooksConfig", {})
    if not isinstance(config, dict):
        raise ValueError(f"{path.as_posix()}: hooksConfig must be a JSON object. Fix or remove it, then run openguildkit host apply.")
    return config


def _gemini_switched_off(settings: dict, guard: str) -> bool:
    """The project turns the hooks off (hooksConfig.enabled false), or, in enforce, leaves a user setting free to: the
    project's own setting wins over the user's, so enforce asks for it explicitly."""
    enabled = _gemini_hooks_config(settings, GEMINI_SETTINGS_FILE).get("enabled")
    return enabled is False or (guard == "enforce" and enabled is not True)


def _gemini_disabled(settings: dict) -> bool:
    """A hook of the guard that hooksConfig.disabled lists, by its name or its command."""
    listed = _gemini_hooks_config(settings, GEMINI_SETTINGS_FILE).get("disabled")
    return isinstance(listed, list) and any(item in listed for pair in GEMINI_HOOK_NAMES.items() for item in pair)


def _apply_gemini(root: Path, profile: dict) -> list[str]:
    """Declare the guard hooks in .gemini/settings.json and leave every other key of the file as it is."""
    path = root / GEMINI_SETTINGS_FILE
    settings = _read_settings(path)
    config = _gemini_hooks_config(settings, path)
    settings["hooks"] = _merge_hooks(settings.get("hooks"), "gemini-cli")
    if profile.get("guard") == "enforce":
        # A user setting "hooksConfig": {"enabled": false} turns every hook off unless the project says true.
        config["enabled"] = True
    if isinstance(config.get("disabled"), list):
        config["disabled"] = [item for item in config["disabled"]
                              if not any(item in pair for pair in GEMINI_HOOK_NAMES.items())]
    if config:
        settings["hooksConfig"] = config
    write_text(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    return [GEMINI_SETTINGS_FILE.as_posix()]


def _gemini_board(root: Path, guard: str, shell: str) -> tuple[bool, str]:
    """Whether the guard hooks of Gemini CLI are in place, and what host check says about them."""
    settings = _read_settings(root / GEMINI_SETTINGS_FILE)
    off, disabled = _gemini_switched_off(settings, guard), _gemini_disabled(settings)
    present = _gemini_hooks_present(settings.get("hooks")) and not off and not disabled
    detail = (
        f"{GEMINI_SETTINGS_FILE.as_posix()} runs openguildkit guard on each request (BeforeAgent) and before write_file "
        "and replace (BeforeTool). When its Trusted Folders feature is on, Gemini CLI loads project settings only in a "
        "trusted folder, and it treats a new or changed project hook as untrusted, warning before it runs. Only exit "
        "code 2 blocks: an edit goes through when the hook cannot start or exits with another code. Not seen in a live "
        "Gemini CLI session yet."
        + (' The settings lack "hooksConfig": {"enabled": true}, so a user setting can turn the hooks off.' if off else "")
        + (" A hook of the guard is listed in hooksConfig.disabled." if disabled else "") + shell)
    return present, detail


# What host check, host apply, check and the page say when the only thing missing is the command on the PATH:
# host apply cannot fix it, so none of them sends back to host apply.
OFF_PATH = ("openguildkit is not on this workstation's PATH, so the hooks of the host cannot run it: the board is not "
            "consulted here. Install it with pipx install or uv tool install, or activate its environment before "
            "starting the agent; host apply cannot fix this.")


def _control(control_id: str, title: str, status: str, detail: str, cause: str | None = None) -> dict:
    control = {"id": control_id, "title": title, "status": status, "detail": detail}
    if cause:
        control["cause"] = cause
    return control


def _board_control(root: Path, host: str, guard: str) -> dict:
    """Whether the guard hooks are installed, protect the files they rely on, and can run on this workstation."""
    title = "The board is consulted before each change"
    shell = " Shell commands (sed -i, echo > file) do not go through the hook."
    only = None
    if host == "claude-code":
        settings = _claude_settings(root)
        missing = [rule for rule in CLAUDE_PROTECTED_RULES if rule not in _claude_denied(root)]
        hooks = settings.get("hooks", {})
        unblocked = guard == "enforce" and not _blocks_on_failure(hooks)
        switchable = guard == "enforce" and settings.get("disableAllHooks") is not False
        present = _claude_hooks_present(hooks) and not missing and not unblocked and not switchable
        detail = (f"Claude Code hooks in {CLAUDE_SETTINGS_FILE.as_posix()} run openguildkit guard on each request and "
                  "before file edits, and file edits to the task records, the profile, the project catalog, the alert "
                  "register and the settings are denied."
                  + (f" Missing: {', '.join(missing)}." if missing else "")
                  + (" The pre-edit hook lacks \"onFailure\": \"block\", so an edit goes through when the hook cannot start."
                     if unblocked else "")
                  + (" The settings lack \"disableAllHooks\": false, so a user setting can turn the hooks off."
                     if switchable else "") + shell)
        from .managed import only_managed_hooks  # Here, not on top: managed.py imports this module.

        only = only_managed_hooks()
        if only:  # allowManagedHooksOnly: the hooks of the project do not run, only the managed ones do.
            present, detail = only[1], only[0] + shell
    elif host == "codex":
        present = _claude_hooks_present(_codex_hooks(root).get("hooks", {}))
        detail = (f"{CODEX_HOOKS_FILE.as_posix()} runs openguildkit guard on each request and before patches. "
                  "Codex reads it only once the project is trusted and its hooks reviewed." + shell)
    elif host == "gemini-cli":
        present, detail = _gemini_board(root, guard, shell)
    else:
        return _control("board", title, "instruction",
                        "This host has no known hook: AGENTS.md tells the agent to open a task, and CI checks decisions.")
    if present and not only and shutil.which("openguildkit") is None:
        return _control("board", title, "missing", f"The hooks are installed, but {OFF_PATH}", cause="path")
    return _control("board", title, "enforced" if present else "missing", detail)


def board_control(root: Path, host: str, guard: str) -> dict:
    """What host check says about the guard hooks of one host, whichever host the profile names."""
    return _board_control(root, host, guard)


def approval_warning(profile: dict) -> str | None:
    """One line when the guard enforces but approvals are only sealed locally."""
    if profile.get("guard", "off") != "enforce" or (profile.get("approval") or {}).get("mode") == "signed":
        return None
    return ("OpenGuildKit: guard is enforce but approvals are not signed: a local seal only detects accidental edits, "
            "and an agent that can write files could forge one. A person requires signed approvals at their terminal: "
            "openguildkit profile set approval signed --signers PATH --approver NAME --by INITIALS --reason WHY "
            f"({doc_link('docs/workflow.md', 'signed-approvals')}).")


def host_controls(root: Path, profile: dict, other_tools: bool = True) -> list[dict]:
    """Say, for each project rule, whether the host enforces it, could but does not, or cannot. With other_tools, also
    one line for each tool of UNHOOKED_TOOLS whose files the project holds (host check; a consultation leaves them)."""
    host = profile.get("host", "other")
    local_only = profile.get("research", "local-only") == "local-only"
    controls = []
    research_title = "Public research stays off when the policy is local-only"
    public_title = "Public research stays available when the policy is public-sources"
    approval_title = "The agent cannot run the approval command"
    if host == "claude-code":
        denied = _claude_denied(root)
        if local_only:
            missing = [rule for rule in CLAUDE_RESEARCH_RULES if rule not in denied]
            controls.append(_control(
                "research", research_title, "missing" if missing else "enforced",
                f"Claude Code denies {', '.join(CLAUDE_RESEARCH_RULES)} in {CLAUDE_SETTINGS_FILE.as_posix()}"
                + (f"; missing: {', '.join(missing)}" if missing else "."),
            ))
        else:
            left = [rule for rule in CLAUDE_RESEARCH_RULES if rule in denied]
            controls.append(_control(
                "research", public_title, "missing" if left else "enforced",
                f"{CLAUDE_SETTINGS_FILE.as_posix()} "
                + (f"still denies {', '.join(left)}." if left else f"does not deny {' or '.join(CLAUDE_RESEARCH_RULES)}."),
            ))
        signers = signers_rule(profile)
        missing = [rule for rule in (*CLAUDE_APPROVAL_RULES, *([signers] if signers else [])) if rule not in denied]
        controls.append(_control(
            "approval", approval_title, "missing" if missing else "partial",
            "Claude Code denies the approval, waiver and allow commands in every documented form, terminal emulators "
            "and Python pseudo-terminals" + (", and file edits to the allowed signers file" if signers else "")
            + (f"; missing: {', '.join(missing)}" if missing else ". Partial: a script file or a shell redirect can "
               "still get around them."),
        ))
    elif host == "codex":
        config = _codex_config(root)
        if local_only:
            sandbox = config.get("sandbox_workspace_write", {})
            enforced = config.get("web_search") == "disabled" and not (
                isinstance(sandbox, dict) and sandbox.get("network_access") is True
            )
            controls.append(_control(
                "research", research_title, "enforced" if enforced else "missing",
                f'{CODEX_CONFIG_FILE.as_posix()} sets web_search = "disabled" and keeps sandbox network access off. '
                "Codex reads it only once the project is trusted.",
            ))
        else:
            disabled = config.get("web_search") == "disabled"
            controls.append(_control(
                "research", public_title, "missing" if disabled else "enforced",
                f'{CODEX_CONFIG_FILE.as_posix()} '
                + ('still sets web_search = "disabled".' if disabled else 'does not set web_search = "disabled".'),
            ))
        rules_path = root / CODEX_RULES_FILE
        current = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else ""
        controls.append(_control(
            "approval", approval_title, "partial" if current == _codex_rules() else "missing",
            f"{CODEX_RULES_FILE.as_posix()} forbids the approval, waiver and authorization commands and terminal emulators. "
            "Codex reads it only once the project is trusted. Partial: a script file or a Python pseudo-terminal can "
            "still get around it.",
        ))
    else:
        if local_only:
            controls.append(_control(
                "research", research_title, "instruction",
                "This host has no known setting for it: the agent follows the instruction and a person checks.",
            ))
        controls.append(_control(
            "approval", approval_title, "instruction",
            "The approval asks for a typed confirmation at a terminal. A person keeps the command for themself.",
        ))
    paths = restricted_paths(profile)
    if paths and host == "claude-code":
        missing = [rule for rule in restricted_rules(profile) if rule not in _claude_denied(root)]
        controls.append(_control(
            "restricted-paths", "Paths the team closes to the agent are denied to its file tools",
            "missing" if missing else "enforced",
            f"{CLAUDE_SETTINGS_FILE.as_posix()} denies Read and Edit on {', '.join(paths)}"
            + (f"; missing: {', '.join(missing)}" if missing else ".")
            + " Those rules apply to Claude Code's file tools: a shell command (cat, sed, a script) is not covered by "
              "them (à vérifier: the permissions page was not read again for this check)."))
    elif paths:
        controls.append(_control(
            "restricted-paths", "Paths the team closes to the agent are denied to its file tools", "instruction",
            f"Nothing enforces {', '.join(paths)} for the host {host}: no setting of this host that refuses a read was "
            "read (à vérifier), and OpenGuildKit does not write these paths into AGENTS.md yet, so name them in your own "
            "instructions. The CI check (guard --ci) is the only barrier."))
    guard = profile.get("guard", "off")
    if guard != "off":
        controls.append(_board_control(root, host, guard))
    controls.append(_control(
        "external-actions", "External actions outside the authorized scope need a recorded decision", "human",
        "The agent asks the requester, who records the decision with openguildkit task authorize.",
    ))
    for tool_id, tool in UNHOOKED_TOOLS.items() if other_tools else ():
        files = [path for path in tool["files"] if os.path.lexists(root / path)]
        if files:
            control = _control(f"tool-{tool_id}", f"{tool['name']} edits are not blocked ({', '.join(files)} present)",
                               "instruction", unhooked_detail(tool_id))
            controls.append({**control, "files": files, "source": unhooked_source(tool_id)})
    return controls


def apply_host_settings(root: Path, profile: dict) -> list[str]:
    """Write the host settings that enforce the project's rules. Returns the files written."""
    host = profile.get("host", "other")
    local_only = profile.get("research", "local-only") == "local-only"
    written = []
    if host == "claude-code":
        path = root / CLAUDE_SETTINGS_FILE
        settings = _claude_settings(root)
        permissions = settings.setdefault("permissions", {})
        if not isinstance(permissions, dict):
            raise ValueError(f"{path.as_posix()}: permissions must be a JSON object.")
        deny = permissions.setdefault("deny", [])
        if not isinstance(deny, list):
            raise ValueError(f"{path.as_posix()}: permissions.deny must be a list.")
        wanted = list(CLAUDE_APPROVAL_RULES) + (list(CLAUDE_RESEARCH_RULES) if local_only else [])
        if signers_rule(profile):
            wanted.append(signers_rule(profile))
        if profile.get("guard", "off") != "off":
            wanted += CLAUDE_PROTECTED_RULES
        wanted += restricted_rules(profile)
        deny[:] = [rule for rule in deny if rule not in OUTDATED_PROTECTED_RULES]
        deny.extend(rule for rule in wanted if rule not in deny)
        if not local_only:
            deny[:] = [rule for rule in deny if rule not in CLAUDE_RESEARCH_RULES]
        if profile.get("guard", "off") != "off":
            settings["hooks"] = _merge_hooks(settings.get("hooks"), host, profile.get("guard") == "enforce")
        if profile.get("guard") == "enforce":
            # A user setting "disableAllHooks": true turns every hook off unless the project says false.
            settings["disableAllHooks"] = False
        write_text(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        written.append(CLAUDE_SETTINGS_FILE.as_posix())
    elif host == "gemini-cli":
        if profile.get("guard", "off") != "off":
            written += _apply_gemini(root, profile)
    elif host == "codex":
        write_text(root / CODEX_RULES_FILE, _codex_rules())
        written.append(CODEX_RULES_FILE.as_posix())
        if profile.get("guard", "off") != "off":
            hooks_path = root / CODEX_HOOKS_FILE
            current = _codex_hooks(root)
            current["hooks"] = _merge_hooks(current.get("hooks"), host)
            write_text(hooks_path, json.dumps(current, indent=2, ensure_ascii=False) + "\n")
            written.append(CODEX_HOOKS_FILE.as_posix())
        path = root / CODEX_CONFIG_FILE
        config = _codex_config(root)
        current = path.read_bytes().decode("utf-8-sig") if path.is_file() else ""
        if local_only:
            if "web_search" in config and config["web_search"] != "disabled":
                raise ValueError(f'{path.as_posix()} sets web_search = "{config["web_search"]}". Set it to "disabled" yourself.')
            sandbox = config.get("sandbox_workspace_write", {})
            if isinstance(sandbox, dict) and sandbox.get("network_access") is True:
                raise ValueError(f"{path.as_posix()} allows sandbox network access. Turn it off yourself.")
            if "web_search" not in config:
                write_text(path, _codex_disable_web_search(path, current, config))
                written.append(CODEX_CONFIG_FILE.as_posix())
        elif config.get("web_search") == "disabled":
            updated = _codex_lift_web_search(path, current, config)
            if updated is None:
                raise ValueError(
                    f'{path.as_posix()} sets web_search = "disabled" but the research policy is public-sources. '
                    "Remove it yourself, or set research to local-only."
                )
            write_text(path, updated)
            written.append(CODEX_CONFIG_FILE.as_posix())
    if written:
        audit_log.record(root, "host.applied", host=host, paths=written)
    return written
