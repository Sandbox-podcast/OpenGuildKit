"""Report and apply the project rules that a host agent can enforce itself.

OpenGuildKit cannot stop a host agent from using its tools. Some hosts can, through
their own project settings. This module writes those settings for the hosts it knows
and tells the requester which rules remain instructions or human checks.
"""

import json
import re
import shutil
import tomllib
from pathlib import Path

from .storage import write_text

HOSTS = ("claude-code", "codex", "other")
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
# Files the guard relies on: the CLI writes them through its own commands. A leading / is relative
# to the settings source, the project root for .claude/settings.json; ./ would follow the current directory.
PROTECTED_PATHS = (
    ".openguildkit/tasks/**", ".openguildkit/decisions/**", ".openguildkit/project.json",
    ".openguildkit/catalog.lock.json", ".claude/settings.json", ".claude/settings.local.json",
)
CLAUDE_PROTECTED_RULES = tuple(f"Edit(/{path})" for path in PROTECTED_PATHS)
OUTDATED_PROTECTED_RULES = tuple(f"Edit(./{path})" for path in PROTECTED_PATHS)
CODEX_RULES_FILE = Path(".codex") / "rules" / "openguildkit.rules"
CODEX_CONFIG_FILE = Path(".codex") / "config.toml"
CLAUDE_SETTINGS_FILE = Path(".claude") / "settings.json"
CODEX_RULES_HEADER = "# Managed by OpenGuildKit: openguildkit host apply rewrites this file.\n"
CODEX_WEB_SEARCH_LINE = 'web_search = "disabled"  # Set by OpenGuildKit: research policy is local-only.'
CODEX_TOOLS_BEGIN = "# >>> OpenGuildKit tools"
_TOML_TABLE = re.compile(r"[ \t]*\[")


def _claude_settings(root: Path) -> dict:
    path = root / CLAUDE_SETTINGS_FILE
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
GUARD_PROMPT = "openguildkit guard --hook prompt"
GUARD_EDIT = "openguildkit guard --hook pre-edit"
EDIT_MATCHERS = {"claude-code": "Edit|Write|MultiEdit|NotebookEdit", "codex": "apply_patch|Edit|Write"}


def _guard_hooks(host: str) -> dict:
    return {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": GUARD_PROMPT}]}],
        "PreToolUse": [{"matcher": EDIT_MATCHERS[host], "hooks": [{"type": "command", "command": GUARD_EDIT}]}],
    }


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


def _edit_handlers(hooks: object) -> list[dict]:
    """The PreToolUse handlers that run the pre-edit guard."""
    groups = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
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


def _control(control_id: str, title: str, status: str, detail: str) -> dict:
    return {"id": control_id, "title": title, "status": status, "detail": detail}


def _board_control(root: Path, host: str, guard: str) -> dict:
    """Whether the guard hooks are installed, protect the files they rely on, and can run on this workstation."""
    title = "The board is consulted before each change"
    shell = " Shell commands (sed -i, echo > file) do not go through the hook."
    if host == "claude-code":
        settings = _claude_settings(root)
        missing = [rule for rule in CLAUDE_PROTECTED_RULES if rule not in _claude_denied(root)]
        hooks = settings.get("hooks", {})
        unblocked = guard == "enforce" and not _blocks_on_failure(hooks)
        present = _claude_hooks_present(hooks) and not missing and not unblocked
        detail = (f"Claude Code hooks in {CLAUDE_SETTINGS_FILE.as_posix()} run openguildkit guard on each request and "
                  "before file edits, and file edits to the task records, the profile and the settings are denied."
                  + (f" Missing: {', '.join(missing)}." if missing else "")
                  + (" The pre-edit hook lacks \"onFailure\": \"block\", so an edit goes through when the hook cannot start."
                     if unblocked else "") + shell)
    elif host == "codex":
        present = _claude_hooks_present(_codex_hooks(root).get("hooks", {}))
        detail = (f"{CODEX_HOOKS_FILE.as_posix()} runs openguildkit guard on each request and before patches. "
                  "Codex reads it only once the project is trusted and its hooks reviewed." + shell)
    else:
        return _control("board", title, "instruction",
                        "This host has no known hook: AGENTS.md tells the agent to open a task, and CI checks decisions.")
    if present and shutil.which("openguildkit") is None:
        return _control("board", title, "missing",
                        "The hooks call openguildkit, which is not on this workstation's PATH: the guard is not enforced "
                        "here. Install it on the PATH (for example with pipx) or activate its environment before starting the agent.")
    return _control("board", title, "enforced" if present else "missing", detail)


def approval_warning(profile: dict) -> str | None:
    """One line when the guard enforces but approvals are only sealed locally."""
    if profile.get("guard", "off") != "enforce" or (profile.get("approval") or {}).get("mode") == "signed":
        return None
    return ("OpenGuildKit: guard is enforce but approvals are not signed: a local seal only detects accidental edits, "
            "and an agent that can write files could forge one. Set \"approval\": {\"mode\": \"signed\", ...} "
            "(docs/workflow.md#signed-approvals).")


def host_controls(root: Path, profile: dict) -> list[dict]:
    """Say, for each project rule, whether the host enforces it, could but does not, or cannot."""
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
        missing = [rule for rule in CLAUDE_APPROVAL_RULES if rule not in denied]
        controls.append(_control(
            "approval", approval_title, "missing" if missing else "enforced",
            "Claude Code denies the approval, waiver and allow commands in every documented form, terminal emulators "
            "and Python pseudo-terminals"
            + (f"; missing: {', '.join(missing)}" if missing else ". A script file or a shell redirect can still get around them."),
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
            "approval", approval_title, "enforced" if current == _codex_rules() else "missing",
            f"{CODEX_RULES_FILE.as_posix()} forbids the approval, waiver and authorization commands and terminal emulators. "
            "Codex reads it only once the project is trusted; a script file or a Python pseudo-terminal can still get around it.",
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
    guard = profile.get("guard", "off")
    if guard != "off":
        controls.append(_board_control(root, host, guard))
    controls.append(_control(
        "external-actions", "External actions outside the authorized scope need a recorded decision", "human",
        "The agent asks the requester, who records the decision with openguildkit task authorize.",
    ))
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
        if profile.get("guard", "off") != "off":
            wanted += CLAUDE_PROTECTED_RULES
        deny[:] = [rule for rule in deny if rule not in OUTDATED_PROTECTED_RULES]
        deny.extend(rule for rule in wanted if rule not in deny)
        if not local_only:
            deny[:] = [rule for rule in deny if rule not in CLAUDE_RESEARCH_RULES]
        if profile.get("guard", "off") != "off":
            settings["hooks"] = _merge_hooks(settings.get("hooks"), host, profile.get("guard") == "enforce")
        write_text(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        written.append(CLAUDE_SETTINGS_FILE.as_posix())
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
    return written
