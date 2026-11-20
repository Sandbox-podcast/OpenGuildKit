"""Report and apply the project rules that a host agent can enforce itself.

OpenGuildKit cannot stop a host agent from using its tools. Some hosts can, through
their own project settings. This module writes those settings for the hosts it knows
and tells the requester which rules remain instructions or human checks.
"""

import json
import re
import tomllib
from pathlib import Path

from .storage import write_text

HOSTS = ("claude-code", "codex", "other")
APPROVAL_COMMANDS = (
    ("openguildkit", "task", "decide"),
    ("python", "-m", "openguildkit", "task", "decide"),
    ("python3", "-m", "openguildkit", "task", "decide"),
)
TERMINAL_EMULATORS = ("script", "expect", "unbuffer")
CLAUDE_RESEARCH_RULES = ("WebSearch", "WebFetch")
CLAUDE_APPROVAL_RULES = tuple(f"Bash({' '.join(command)}:*)" for command in APPROVAL_COMMANDS) + tuple(
    f"Bash({tool}:*)" for tool in TERMINAL_EMULATORS
)
CODEX_RULES_FILE = Path(".codex") / "rules" / "openguildkit.rules"
CODEX_CONFIG_FILE = Path(".codex") / "config.toml"
CLAUDE_SETTINGS_FILE = Path(".claude") / "settings.json"
CODEX_RULES_HEADER = "# Managed by OpenGuildKit: openguildkit host apply rewrites this file.\n"


def _claude_settings(root: Path) -> dict:
    path = root / CLAUDE_SETTINGS_FILE
    if not path.is_file():
        return {}
    try:
        settings = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(settings, dict):
        raise ValueError(f"{path} must hold a JSON object.")
    return settings


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
        raise ValueError(f"{path} is not valid TOML: {error}") from error


def _codex_rules() -> str:
    rules = [CODEX_RULES_HEADER]
    for command in APPROVAL_COMMANDS:
        pattern = ", ".join(json.dumps(part) for part in command)
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


def _control(control_id: str, title: str, status: str, detail: str) -> dict:
    return {"id": control_id, "title": title, "status": status, "detail": detail}


def host_controls(root: Path, profile: dict) -> list[dict]:
    """Say, for each project rule, whether the host enforces it, could but does not, or cannot."""
    host = profile.get("host", "other")
    local_only = profile.get("research", "local-only") == "local-only"
    controls = []
    research_title = "Public research stays off when the policy is local-only"
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
        missing = [rule for rule in CLAUDE_APPROVAL_RULES if rule not in denied]
        controls.append(_control(
            "approval", approval_title, "missing" if missing else "enforced",
            "Claude Code denies the approval command and terminal emulators"
            + (f"; missing: {', '.join(missing)}" if missing else ". Other ways to emulate a terminal stay possible."),
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
        rules_path = root / CODEX_RULES_FILE
        current = rules_path.read_text(encoding="utf-8") if rules_path.is_file() else ""
        controls.append(_control(
            "approval", approval_title, "enforced" if current == _codex_rules() else "missing",
            f"{CODEX_RULES_FILE.as_posix()} forbids the approval command and terminal emulators. "
            "Codex reads it only once the project is trusted.",
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
            raise ValueError(f"{path}: permissions must be a JSON object.")
        deny = permissions.setdefault("deny", [])
        if not isinstance(deny, list):
            raise ValueError(f"{path}: permissions.deny must be a list.")
        wanted = list(CLAUDE_APPROVAL_RULES) + (list(CLAUDE_RESEARCH_RULES) if local_only else [])
        deny.extend(rule for rule in wanted if rule not in deny)
        write_text(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
        written.append(CLAUDE_SETTINGS_FILE.as_posix())
    elif host == "codex":
        write_text(root / CODEX_RULES_FILE, _codex_rules())
        written.append(CODEX_RULES_FILE.as_posix())
        if local_only:
            path = root / CODEX_CONFIG_FILE
            config = _codex_config(root)
            current = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
            if "web_search" in config and config["web_search"] != "disabled":
                raise ValueError(f'{path} sets web_search = "{config["web_search"]}". Set it to "disabled" yourself.')
            sandbox = config.get("sandbox_workspace_write", {})
            if isinstance(sandbox, dict) and sandbox.get("network_access") is True:
                raise ValueError(f"{path} allows sandbox network access. Turn it off yourself.")
            if "web_search" not in config:
                # Top-level keys must come before the first table.
                table = re.search(r"(?m)^\s*\[", current)
                line = 'web_search = "disabled"  # Set by OpenGuildKit: research policy is local-only.\n'
                updated = current[:table.start()] + line + current[table.start():] if table else current + line
                write_text(path, updated)
                written.append(CODEX_CONFIG_FILE.as_posix())
    return written
