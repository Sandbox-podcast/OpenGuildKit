"""The `openguildkit profile` commands: change the project profile after setup, with who, when and why.

The guard forbids the agent to edit .openguildkit/project.json, so every change goes through these
commands. Each one validates the result like init, rewrites the instructions like sync and records the
change. What weakens a protection (see weakening_changes) is the person's decision: it needs an interactive terminal and a typed confirmation.
"""

import sys
from pathlib import Path

from .clock import today
from .hosts import HOSTS
from .lock import apply_lock, build_lock, read_lock, write_lock
from .patterns import pattern_selection, recommend_patterns, role_choices
from .project import (
    GUARD_MODES, declined_ids, load_profile, norm_reason, sync_instructions, unanswered_norms, validate_profile,
)
from .storage import project_lock, write_json
from .tasks import tasks_touched

LIST_FIELDS = {
    "pack": ("packs", "packs"), "role": ("roles", None), "tool": ("tools", None), "check": ("checks", None),
    "convention": ("conventions", None), "board": ("boards", "boards"),
}
SET_FIELDS = {
    "host": HOSTS, "guard": tuple(GUARD_MODES), "research": ("local-only", "public-sources"),
    "personal-data": ("yes", "no"), "people-decisions": ("yes", "no"), "sector": None,
}
GUARD_LEVEL = {"off": 0, "observe": 1, "enforce": 2}
# How much each host enforces by itself: Claude Code also denies edits to the profile and the task records,
# Codex runs the hooks and forbids the approval commands, another agent only reads the instructions.
HOST_LEVEL = {"other": 0, "codex": 1, "claude-code": 2}
PROTECTIVE_BOARDS = ("security", "legal")
AI_PACKS = ("llm-evaluations", "nist-ai-risk", "eu-ai-act")


def protective_packs(catalog: dict) -> set[str]:
    """Packs whose removal weakens a protection: those of a regulation, of a security method, or about AI."""
    packs = set(AI_PACKS) | {"secure-sdlc"}
    for pattern in catalog["patterns"].values():
        security_method = "security" in pattern["roles"] and not pattern.get("match", {}).get("stack")
        if pattern.get("kind") == "regulation" or security_method:
            packs.update(pattern["packs"])
    return packs & set(catalog["packs"])


def _packs_in_force(profile: dict, catalog: dict) -> set[str]:
    """The packs a profile lists or brings through its patterns, without resolving it: the page passes drafts."""
    packs = set(profile.get("packs", []))
    for entry in profile.get("patterns", []):
        if isinstance(entry, (str, dict)):
            packs.update(catalog["patterns"].get(pattern_selection(entry)[0], {}).get("packs", []))
    return packs


def _boards_in_force(profile: dict, catalog: dict) -> set[str]:
    """An empty board list lets every board advise."""
    return set(profile.get("boards") or catalog["boards"])


def add_parser(commands) -> None:
    profile = commands.add_parser(
        "profile", help="Change the project profile after setup: adopt or decline a pattern, add or remove a pack, "
                        "role, tool, check or board, set the host, guard or research policy.")
    actions = profile.add_subparsers(dest="profile_action", required=True)
    for name, text in (("adopt", "Adopt a pattern or regulation: it becomes active."),
                       ("decline", "Decline a pattern or regulation: it is not active and not proposed again.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("pattern", metavar="PATTERN", help="Pattern ID, from openguildkit recommend or patterns.")
    for name, text in (("add", "Add entries to a list of the profile."), ("remove", "Remove entries from a list.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("field", choices=sorted(LIST_FIELDS), help="The list to change.")
        command.add_argument("values", nargs="+", metavar="VALUE", help="IDs, tool names or check commands.")
    setter = actions.add_parser("set", help="Set the host, guard, research policy, sector or a setup answer.")
    setter.add_argument("field", choices=sorted(SET_FIELDS), help="The setting to change.")
    setter.add_argument("value", help="Its new value.")
    for command in actions.choices.values():
        command.add_argument("--by", required=True, help="The person who decides the change.")
        command.add_argument("--reason", required=True, help="Why, in one line; shown in AGENTS.md and preview.")


def weakening_changes(before: dict, after: dict, catalog: dict) -> list[tuple[str, list[str]]]:
    """What a new profile weakens, each with the profile command a person types for it at a terminal: a lower
    guard, public research, a regulation that stops being active, a regulation, security or AI pack removed, the
    security or legal board removed, personal data set to no, a host whose settings enforce less. The profile
    commands and the web page ask this."""
    person = ["--by", "NAME", "--reason", "WHY"]
    changes = []
    old_guard, new_guard = before.get("guard", "off"), after.get("guard", "off")
    if GUARD_LEVEL.get(new_guard, 0) < GUARD_LEVEL.get(old_guard, 0):
        changes.append((f"guard {old_guard} -> {new_guard}", ["profile", "set", "guard", str(new_guard), *person]))
    if after.get("research") == "public-sources" and before.get("research") != "public-sources":
        changes.append(("research public-sources", ["profile", "set", "research", "public-sources", *person]))

    def active(profile: dict) -> set:
        return {pattern_selection(entry)[0] for entry in profile.get("patterns", []) if isinstance(entry, (str, dict))}

    dropped = (active(before) - active(after)) | (set(declined_ids(after)) - set(declined_ids(before)))
    for pattern_id in sorted(item for item in dropped if isinstance(item, str)):
        if catalog["patterns"].get(pattern_id, {}).get("kind") == "regulation":
            changes.append((f"regulation {pattern_id} no longer active", ["profile", "decline", pattern_id, *person]))
    removed = (_packs_in_force(before, catalog) - _packs_in_force(after, catalog)) & protective_packs(catalog)
    # A pack that leaves with a regulation reported above is part of that change.
    removed -= {pack for pattern_id in dropped if isinstance(pattern_id, str)
                for pack in catalog["patterns"].get(pattern_id, {}).get("packs", [])}
    for pack_id in sorted(removed):
        changes.append((f"protective pack {pack_id} removed", ["profile", "remove", "pack", pack_id, *person]))
    if "boards" in after:
        for board in PROTECTIVE_BOARDS:
            if board in _boards_in_force(before, catalog) - _boards_in_force(after, catalog):
                changes.append((f"board {board} no longer advises", ["profile", "remove", "board", board, *person]))
    if before.get("personal_data") is not False and after.get("personal_data") is False:
        changes.append(("personal data set to no", ["profile", "set", "personal-data", "no", *person]))
    old_host, new_host = before.get("host", "other"), after.get("host", "other")
    if HOST_LEVEL.get(new_host, 0) < HOST_LEVEL.get(old_host, 0):
        changes.append((f"host {old_host} -> {new_host}, whose settings enforce less",
                        ["profile", "set", "host", str(new_host), *person]))
    return changes


def _adopt(profile: dict, pattern_id: str, catalog: dict) -> dict:
    if pattern_id not in catalog["patterns"]:
        raise ValueError(f"Unknown pattern: {pattern_id}. Run openguildkit patterns.")
    if pattern_id in {pattern_selection(entry)[0] for entry in profile.get("patterns", [])}:
        raise ValueError(f"{pattern_id} is already active. Nothing was written.")
    plan = recommend_patterns(catalog, profile.get("stack", []), profile["sector"], profile.get("roles", []),
                              profile.get("components"))
    scopes = {entry["id"]: entry.get("components") for entry in [*plan["matched"], *plan["suggested"]]}
    entry = {"id": pattern_id, "components": scopes[pattern_id]} if scopes.get(pattern_id) else pattern_id
    declined = [item for item in profile.get("declined", [])
                if (item.get("id") if isinstance(item, dict) else item) != pattern_id]
    return {**profile, "patterns": [*profile.get("patterns", []), entry], "declined": declined}


def _decline(profile: dict, pattern_id: str, catalog: dict, by: str, reason: str) -> dict:
    if pattern_id not in catalog["patterns"]:
        raise ValueError(f"Unknown pattern: {pattern_id}. Run openguildkit patterns.")
    if pattern_id in declined_ids(profile):
        raise ValueError(f"{pattern_id} is already declined. Nothing was written.")
    patterns = [entry for entry in profile.get("patterns", []) if pattern_selection(entry)[0] != pattern_id]
    decline = {"id": pattern_id, "by": by, "on": today().isoformat(), "reason": reason}
    return {**profile, "patterns": patterns, "declined": [*profile.get("declined", []), decline]}


def _change_list(profile: dict, field: str, values: list[str], add: bool, catalog: dict) -> dict:
    key, collection = LIST_FIELDS[field]
    known = catalog[collection] if collection else role_choices(catalog["patterns"]) if field == "role" else None
    current = list(profile.get(key, []))
    for value in values:
        if known is not None and value not in known:
            raise ValueError(f"Unknown {field}: {value}. Run openguildkit catalog or openguildkit patterns.")
        if add and value in current or not add and value not in current:
            state = "already in" if add else "not in"
            raise ValueError(f"{value} is {state} the profile's {key}. Nothing was written.")
        if add:
            current.append(value)
        else:
            current.remove(value)
    if field == "pack" and not add and "agent-workflow" in values:
        raise ValueError("agent-workflow is required by OpenGuildKit and cannot be removed.")
    return {**profile, key: current}


def _set(profile: dict, field: str, value: str, catalog: dict) -> dict:
    allowed = SET_FIELDS[field] or tuple(catalog["sectors"])
    if value not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}.")
    key = field.replace("-", "_")
    new = value == "yes" if field in ("personal-data", "people-decisions") else value
    if profile.get(key) == new:
        raise ValueError(f"{field} is already {value}. Nothing was written.")
    return {**profile, key: new}


def _changed(profile: dict, args, catalog: dict) -> tuple[dict, str, list[str]]:
    """The profile after the command, the change in a few words, and the protections it weakens."""
    action = args.profile_action
    if action == "adopt":
        updated, change = _adopt(profile, args.pattern, catalog), f"adopt {args.pattern}"
    elif action == "decline":
        updated = _decline(profile, args.pattern, catalog, args.by.strip(), args.reason.strip())
        change = f"decline {args.pattern}"
    elif action in ("add", "remove"):
        updated = _change_list(profile, args.field, args.values, action == "add", catalog)
        change = f"{action} {args.field} {', '.join(args.values)}"
    else:
        updated, change = _set(profile, args.field, args.value, catalog), f"set {args.field} {args.value}"
    return updated, change, [text for text, _ in weakening_changes(profile, updated, catalog)]


def _confirm(change: str, target: str, weakened: list[str]) -> None:
    """A change that weakens a protection is typed by the person at a terminal, never run by an agent."""
    what = "; ".join(weakened)
    if not sys.stdin.isatty():
        raise ValueError(f"'{change}' weakens a protection ({what}): it is the person's decision. Ask them to run the "
                         "same command at an interactive terminal. Nothing was written.")
    print(f"'{change}' weakens a protection of the project ({what}). Type {target} to confirm: ", end="",
          file=sys.stderr, flush=True)
    if input().strip() != target:
        raise ValueError("Profile change cancelled. Nothing was written.")


def run(args, root: Path, state: Path, installed_catalog, print_touched) -> int:
    """Apply one profile command, rewrite the instructions and the catalog lock, and say what follows."""
    with project_lock(state):
        live, bundled = installed_catalog(args, state)
        lock = read_lock(state)
        catalog = apply_lock(live, lock)
        profile = load_profile(state, catalog)
        updated, change, weakens = _changed(profile, args, catalog)
        if weakens:
            _confirm(change, getattr(args, "pattern", None) or getattr(args, "value", None) or " ".join(args.values),
                     weakens)
        record = {"change": change, "by": args.by, "on": today().isoformat(), "reason": args.reason}
        updated = validate_profile({**updated, "changes": [*profile.get("changes", []), record]}, catalog)
        sync_instructions(root, updated, catalog)
        write_json(state / "project.json", updated)
        write_lock(state, build_lock(updated, catalog, bundled, lock))
    print(f"Profile changed: {change}, by {record['by']} on {record['on']}. AGENTS.md is up to date.")
    for norm in unanswered_norms(updated, catalog, {}):
        pattern = catalog["patterns"][norm["id"]]
        print(f"  Norm {norm['id']} now concerns the project ({norm_reason(pattern)}) and is not active: ask the "
              f"person, then openguildkit profile adopt {norm['id']} or decline {norm['id']}, with --by and --reason.")
    if args.profile_action == "set" and args.field in ("host", "guard", "research"):
        print("  Run openguildkit host apply, then openguildkit host check, so the host settings follow.")
    touched = tasks_touched(state, updated, catalog)
    print_touched(touched)
    if not touched:
        print("No open task was consulted under the previous profile.")
    return 0
