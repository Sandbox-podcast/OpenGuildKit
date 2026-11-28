"""Render, merge, sync and check the repository instructions: the managed block of AGENTS.md and its imports."""

import re
from pathlib import Path

from . import lazy_re
from .agent_workflow import AGENT_WORKFLOW, RULE_PACKS_NOTE
from .catalog import rule_check
from .patterns import pattern_selection
from .project import STATE_DIR, pattern_ids, rules_in_force, state_path
from .project_rules import (
    pack_scopes,
    profile_fingerprint,
    require_resolved_conflicts,
    resolved_profile,
    rule_conflicts,
)
from .rule_checks import describe_check
from .storage import write_json, write_text
from .wording import plural

BEGIN = "<!-- BEGIN OPENGUILDKIT -->"
END = "<!-- END OPENGUILDKIT -->"
# The layout of the managed block, written in its stamp. Raise it when a release changes the block without changing
# the profile: the stamp then differs, and check calls the block out of date instead of calling its lines hand edits.
INSTRUCTIONS_LAYOUT = 3
ALREADY_INITIALIZED = (
    "Project is already initialized. Change its profile with openguildkit profile (adopt, decline, add, remove, "
    "set); openguildkit profile --help lists them."
)
PROJECT_IGNORE = "tasks/\nshares/\nwork/\n.lock\n.*.tmp\n"


def _bullets(values: list[str]) -> list[str]:
    return ["- " + value.replace("\n", "\n  ") for value in values]


CHECK_VERIFICATION = "OpenGuildKit evaluates the check: task verify in the project, ci-check on a commit."


def rule_text(rule: dict) -> tuple[str, str]:
    """The rule's instruction and verification; a machine check fills in the text a rule leaves out."""
    check = rule_check(rule)
    if check is None:
        return rule["instruction"], rule["verification"]
    return (
        rule.get("instruction", describe_check(check)),
        rule.get("verification", CHECK_VERIFICATION),
    )


def profile_decision_lines(profile: dict, catalog: dict) -> list[str]:
    """The declined patterns and the patterns adopted by a command, with who, when and why when recorded."""
    lines = []
    for entry in profile.get("declined", []):
        if isinstance(entry, dict):
            lines.append(f"Declined `{entry['id']}` by {entry['by']} on {entry['on']}: {entry['reason']}. "
                         "It is not active; the person can adopt it again with openguildkit profile adopt.")
        else:
            lines.append(f"Declined `{entry}` before declines recorded who and why. It is not active.")
    for change in profile.get("changes", []):
        verb, _, target = change["change"].partition(" ")
        if verb == "adopt" and target in pattern_ids(profile):
            lines.append(f"Adopted `{target}` by {change['by']} on {change['on']}: {change['reason']}.")
    for entry in profile.get("declined_rules", []):
        lines.append(f"Declined rule `{entry['id']}` by {entry['by']} on {entry['on']}: {entry['reason']}. It is not "
                     "listed with its pack and no task is asked it; the person can restore it with openguildkit "
                     f"profile adopt rule {entry['id']}.")
    return lines


def render_instructions(profile: dict, catalog: dict) -> str:
    require_resolved_conflicts(profile, catalog)
    resolved = resolved_profile(profile, catalog)
    sector = catalog["sectors"][profile["sector"]]
    lines = [
        "## OpenGuildKit",
        "",
        f"Project: {profile['name']}",
        f"Sector: {sector['title']}",
        f"Stack: {', '.join(profile['stack']) or 'See the project files.'}",
        f"Research policy: `{profile['research']}`",
        *([f"Host agent: `{profile['host']}`"] if profile.get("host") else []),
        "",
        *_bullets(sector["context"]),
        "",
        *AGENT_WORKFLOW.strip().splitlines(),
    ]
    components = {component["id"]: component for component in profile.get("components", [])}

    def scope_text(scope: list[str] | None) -> str:
        names = [
            f"`{component_id}` ({components[component_id]['path']})" if components[component_id].get("path")
            else f"`{component_id}`"
            for component_id in scope or []
        ]
        return ", ".join(names)

    if components:
        lines.extend(["", "### Components", ""])
        for component in components.values():
            location = f" in `{component['path']}`" if component.get("path") else ""
            lines.append(f"- `{component['id']}`{location}: {', '.join(component['stack'])}")
    if profile.get("patterns"):
        lines.extend(["", "### Selected patterns", ""])
        for entry in profile["patterns"]:
            pattern_id, scope = pattern_selection(entry)
            pattern = catalog["patterns"][pattern_id]
            packs = ", ".join(f"`{pack_id}`" for pack_id in pattern["packs"])
            where = f" Applies to {scope_text(scope)}." if scope else ""
            lines.append(f"- {pattern['title']} (`{pattern_id}`) uses {packs}.{where}")
    decisions = profile_decision_lines(profile, catalog)
    if decisions:
        lines.extend(["", "### Profile decisions", "", *_bullets(decisions)])
    applied = [conflict for conflict in rule_conflicts(profile, catalog) if conflict["resolution"]]
    if applied:
        lines.extend(["", "### Rule decisions", ""])
        for conflict in applied:
            resolution = conflict["resolution"]
            kept = ", ".join(f"`{pack_id}`" for pack_id in resolution["keep"])
            dropped = [pack_id for pack_id in conflict["packs"] if pack_id not in resolution["keep"]]
            verb = "applies" if len(resolution["keep"]) == 1 else "apply"
            outcome = (
                f"{kept} {verb} instead of {', '.join(f'`{pack_id}`' for pack_id in dropped)}" if dropped
                else f"{kept} both apply"
            )
            lines.append(f"- {outcome}. Reason: {resolution['reason']}")
    if profile.get("approval", {}).get("mode") == "signed":
        lines.extend(["", "### Signed approvals", ""])
        lines.append(
            f"Approvals must be signed by {', '.join(profile['approval']['approvers'])} with a key listed in "
            f"`{profile['approval']['allowed_signers']}`."
        )
    if profile.get("separate_requester") is True:
        lines.extend(["", "### Requester and approver", ""])
        lines.append("Open each task with `--requested-by NAME`, the person who asked for the work; that person "
                     "cannot approve it, another person does.")
    if profile.get("waivers"):
        lines.extend(["", "### Waivers", ""])
        lines.append(
            f"Only {', '.join(profile['waivers']['allowed_by'])} can waive a blocker, "
            f"for up to {profile['waivers']['max_days']} days."
        )
    if profile.get("guard", "off") != "off":
        lines.extend(["", "### Board guard", ""])
        lines.append(
            "Every change goes through an approved task. "
            + ("Edits without one are refused." if profile["guard"] == "enforce" else "Edits without one are flagged.")
        )
    if profile.get("required_boards"):
        lines.extend(["", "### Required reviews", ""])
        lines.append(
            "Every consultation includes these boards: "
            + ", ".join(f"`{board_id}`" for board_id in profile["required_boards"]) + "."
        )
    for title, field in (("Team conventions", "conventions"), ("Project checks", "checks")):
        if profile[field]:
            lines.extend(["", f"### {title}", "", *_bullets(profile[field])])
    scopes = pack_scopes(profile, catalog) if components else {}
    lines.extend(["", "### Rule packs", "", *RULE_PACKS_NOTE.splitlines()])
    for pack_id in resolved["packs"]:
        pack = catalog["packs"][pack_id]
        lines.extend(["", f"#### {pack['title']} (`{pack_id}@{pack['version']}`)", ""])
        if scopes.get(pack_id):
            lines.append(f"Applies to {scope_text(scopes[pack_id])}.")
        if "policy_commit" in pack:
            lines.append(f"Policy commit: `{pack['policy_commit']}`")
        lines.append(", ".join(f"`{rule['id']}`" for rule in rules_in_force(pack, profile)["rules"]))
    stamp = f"{profile_fingerprint(profile, catalog)} layout {INSTRUCTIONS_LAYOUT}"
    lines.extend(["", f"<!-- openguildkit profile {stamp} -->"])
    return "\n".join(lines)


_MARKER_LINE = lazy_re.compile("(" + re.escape(BEGIN) + "|" + re.escape(END) + r")[ \t]*")
_IMPORT_LINE = lazy_re.compile(r"[ \t]*(@AGENTS\.md|@\./AGENTS\.md)[ \t]*")
_FENCE = lazy_re.compile(r" {0,3}(`{3,}|~{3,})")
BOM = "\ufeff"


def _scan_markers(text: str, line_pattern: re.Pattern = _MARKER_LINE) -> tuple[list[tuple[str, int, int]], int | None]:
    """Find the lines the pattern matches (the markers) outside fenced code blocks, and the line of a fence the
    text leaves open."""
    found, fence, opened, offset = [], None, None, 0
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        content = line.rstrip("\r\n")
        opening = _FENCE.match(content)
        if fence is None and opening:
            fence, opened = opening.group(1), number
        elif fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence) \
                    and not content[opening.end():].strip():
                fence = None
        else:
            match = line_pattern.fullmatch(content)
            if match:
                found.append((match.group(1), offset, offset + len(content)))
        offset += len(line)
    return found, opened if fence is not None else None


def _marker_positions(text: str) -> list[tuple[str, int, int]]:
    """Find the OpenGuildKit markers that stand on their own line outside fenced code blocks."""
    return _scan_markers(text)[0]


def managed_block_lines(text: str) -> tuple[int, int] | None:
    """The first and last line (counted from 1, markers included) of the block OpenGuildKit manages, or None when the
    text has no block or malformed markers."""
    matches = _marker_positions(text)
    if [kind for kind, _, _ in matches] != [BEGIN, END]:
        return None
    return text.count("\n", 0, matches[0][1]) + 1, text.count("\n", 0, matches[1][2]) + 1


def merged_instructions(current: str, generated: str, label: str = "AGENTS.md") -> str:
    """Replace the managed block in an instructions file, or append it, keeping the rest unchanged."""
    newline = "\r\n" if "\r\n" in current else "\n"
    if any(_MARKER_LINE.fullmatch(line.strip()) for line in generated.splitlines()):
        raise ValueError("Project instructions contain a reserved OpenGuildKit marker.")
    matches, open_fence = _scan_markers(current)
    block = newline.join([BEGIN, generated.replace("\n", newline), END])
    if not matches:
        if open_fence is not None:
            # Appending would put the rules inside the code block, and each sync would add another copy.
            raise ValueError(f"{label} ends inside an unclosed code block at line {open_fence}. Close it and retry.")
        separator = newline if current.endswith(newline) else newline * 2
        return current + (separator if current else "") + block + newline
    if [kind for kind, _, _ in matches] != [BEGIN, END]:
        raise ValueError(f"{label} has malformed OpenGuildKit markers. Repair the marked block and retry.")
    return current[:matches[0][1]] + block + current[matches[1][2]:]


_FINGERPRINT_LINE = lazy_re.compile(r"<!-- openguildkit profile [0-9a-f]{64}(?: layout \d+)? -->")


def hand_edits(current: str, generated: str) -> list[str]:
    """The lines a person changed in the managed block: lines it holds that the generated block lacks, when the
    block still carries the same profile fingerprint (otherwise the profile or catalog changed, not a person)."""
    matches = _marker_positions(current)
    if [kind for kind, _, _ in matches] != [BEGIN, END]:
        return []
    block = current[matches[0][2]:matches[1][1]].replace("\r\n", "\n")
    stamp = _FINGERPRINT_LINE.search(block)
    if stamp is None or stamp.group(0) not in generated:
        return []
    expected = set(generated.splitlines())
    return [line.strip() for line in block.splitlines() if line.strip() and line not in expected]


def _read_instructions(path: Path) -> tuple[str, bool]:
    """Read an instructions file and report whether it starts with a UTF-8 byte order mark."""
    if path.is_symlink():
        raise ValueError(f"Refusing a symbolic link as project instructions: {path}")
    if not path.exists():
        return "", False
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{path.name} is not UTF-8 (byte {error.start + 1}): convert it to UTF-8 and retry.") from error
    return (text[1:], True) if text.startswith(BOM) else (text, False)


def _instruction_text(path: Path) -> str:
    return _read_instructions(path)[0]


def _links_to_agents(root: Path, name: str = "CLAUDE.md") -> bool:
    """An instructions file (CLAUDE.md, GEMINI.md) that is a symbolic link to the project's AGENTS.md already carries the
    rules."""
    linked, agents = root / name, root / "AGENTS.md"
    if not linked.is_symlink():
        return False
    try:
        return linked.resolve(strict=True) == agents.resolve(strict=True) and not agents.is_symlink()
    except OSError:
        return False


def _claude_links_to_agents(root: Path) -> bool:
    return _links_to_agents(root)


def _import_instructions(current: str, label: str, line: str) -> str:
    """The file that imports AGENTS.md: as it is when a line of its own already does, else with the managed import."""
    standalone_import = bool(_scan_markers(current, _IMPORT_LINE)[0])
    if not _marker_positions(current) and standalone_import:
        return current
    return merged_instructions(current, line, label)


def _claude_instructions(current: str) -> str:
    return _import_instructions(current, "CLAUDE.md", "@AGENTS.md")


# Gemini CLI loads GEMINI.md, not AGENTS.md, unless its context.fileName setting says so; it imports a file with a
# relative path (https://geminicli.com/docs/cli/gemini-md/). Only a profile that names the host gets the file.
GEMINI_FILE = "GEMINI.md"


def _gemini_instructions(current: str) -> str:
    return _import_instructions(current, GEMINI_FILE, "@./AGENTS.md")


def _wants_gemini_file(root: Path, profile: dict) -> bool:
    return profile.get("host") == "gemini-cli" and not _links_to_agents(root, GEMINI_FILE)


def sync_instructions(root: Path, profile: dict, catalog: dict) -> list[str]:
    """Write the managed instructions; returns the lines a person had edited in the block, which it replaces."""
    state = state_path(root)
    instructions = root / "AGENTS.md"
    current, bom = _read_instructions(instructions)
    generated = render_instructions(profile, catalog)
    replaced = hand_edits(current, generated)
    updated = merged_instructions(current, generated)
    claude = root / "CLAUDE.md"
    linked = _claude_links_to_agents(root)
    if not linked:
        current_claude, claude_bom = _read_instructions(claude)
        updated_claude = _claude_instructions(current_claude)
    gemini = root / GEMINI_FILE
    if _wants_gemini_file(root, profile):
        current_gemini, gemini_bom = _read_instructions(gemini)
        updated_gemini = _gemini_instructions(current_gemini)
    ignore = state / ".gitignore"
    previous_ignore = _instruction_text(ignore)
    missing = [entry for entry in PROJECT_IGNORE.splitlines() if entry not in previous_ignore.splitlines()]
    if missing:
        separator = "\n" if previous_ignore and not previous_ignore.endswith("\n") else ""
        write_text(ignore, previous_ignore + separator + "\n".join(missing) + "\n")
    write_text(instructions, (BOM if bom else "") + updated)
    if not linked:
        write_text(claude, (BOM if claude_bom else "") + updated_claude)
    if _wants_gemini_file(root, profile):
        write_text(gemini, (BOM if gemini_bom else "") + updated_gemini)
    return replaced


def initialize(root: Path, state: Path, profile: dict, catalog: dict) -> None:
    path = state / "project.json"
    if path.exists():
        raise ValueError(ALREADY_INITIALIZED)
    sync_instructions(root, profile, catalog)
    write_json(path, profile)


class RuleError(ValueError):
    """A problem `check` reports under a rule of docs/sarif.md.

    `code` is the rule's stable code, None when the findings were already reported one by one; `files` are the files
    the problem concerns, relative to the project root. The message is the one the command prints.
    """

    def __init__(self, message: str, code: str | None, files: tuple[str, ...] | list[str] = ()):
        super().__init__(message)
        self.code = code
        self.files = tuple(files)


def _outdated(test) -> bool:
    try:
        return bool(test())
    except ValueError:
        return False  # A file that cannot be merged is reported by its own message, not listed here.


def _outdated_files(generated: str, current: str, claude: str, linked: bool, ignore: str,
                    gemini: str | None = None) -> list[str]:
    """The instructions files that no longer match the profile, for the finding that names them. gemini is the text of
    GEMINI.md when the profile's host is Gemini CLI, None for every other host."""
    checks = (
        ("AGENTS.md", lambda: current != merged_instructions(current, generated)),
        ("CLAUDE.md", lambda: not linked and claude != _claude_instructions(claude)),
        (GEMINI_FILE, lambda: gemini is not None and gemini != _gemini_instructions(gemini)),
        (f"{STATE_DIR}/.gitignore", lambda: not set(PROJECT_IGNORE.splitlines()).issubset(ignore.splitlines())),
    )
    return [name for name, test in checks if _outdated(test)]


def check_instructions(root: Path, profile: dict, catalog: dict) -> None:
    current = _instruction_text(root / "AGENTS.md")
    linked = _claude_links_to_agents(root)
    claude = "" if linked else _instruction_text(root / "CLAUDE.md")
    gemini = _instruction_text(root / GEMINI_FILE) if _wants_gemini_file(root, profile) else None
    ignore = _instruction_text(state_path(root) / ".gitignore")
    generated = render_instructions(profile, catalog)
    edited = hand_edits(current, generated)
    if edited:
        raise RuleError(
            f"The OpenGuildKit block of AGENTS.md was edited by hand ({plural(len(edited), 'line')}, first: {edited[0][:80]}). "
            "openguildkit sync replaces the block: move your own text outside the markers first.",
            "instructions-edited", ["AGENTS.md"],
        )
    if (
        current != merged_instructions(current, generated)
        or (not linked and claude != _claude_instructions(claude))
        or (gemini is not None and gemini != _gemini_instructions(gemini))
        or not set(PROJECT_IGNORE.splitlines()).issubset(ignore.splitlines())
    ):
        raise RuleError("OpenGuildKit instructions are out of date. Run openguildkit sync.", "instructions-drift",
                        _outdated_files(generated, current, claude, linked, ignore, gemini))
