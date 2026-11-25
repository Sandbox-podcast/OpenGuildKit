"""The `openguildkit profile` commands: change the project profile after setup, with who, when and why.

The guard forbids the agent to edit .openguildkit/project.json, so every change goes through these
commands, and the web page saves an edited profile through the same path (save_edited). Each change is
written under the project lock, validated like init, recorded in changes, and rewrites the instructions like
sync. What weakens a protection (see weakening_changes) is the person's decision: it needs an interactive
terminal and a typed confirmation. The approvals a change voids are named before anything is written.
"""

import sys
from pathlib import Path

from .clock import today
from .hosts import HOSTS
from .lock import apply_lock, build_lock, installed_catalog, read_lock, write_lock
from .patterns import pattern_selection, recommend_patterns, role_choices
from .project import (
    GUARD_MODES, declined_ids, load_profile, norm_reason, sync_instructions, unanswered_norms, validate_profile,
)
from .storage import project_lock, write_json
from .tasks import tasks_touched

LIST_FIELDS = {
    "pack": ("packs", "packs"), "role": ("roles", None), "tool": ("tools", None), "check": ("checks", None),
    "convention": ("conventions", None), "board": ("boards", "boards"),
    "required-board": ("required_boards", "boards"), "required-rule": ("required_rules", None),
}
SET_FIELDS = {
    "host": HOSTS, "guard": tuple(GUARD_MODES), "research": ("local-only", "public-sources"),
    "personal-data": ("yes", "no"), "people-decisions": ("yes", "no"), "sector": None,
    "approval": ("local", "signed"), "waivers": ("none", "allowed"), "ask-every-rule": ("yes", "no"),
}
# The options of profile set, each with the setting and value it belongs to.
SET_OPTIONS = {"signers": ("approval", "signed"), "approver": ("approval", "signed"),
               "allowed_by": ("waivers", "allowed"), "max_days": ("waivers", "allowed")}
# Lists whose entries a person adds for protection: removing one weakens it.
REQUIRED_LISTS = (("required_rules", "required-rule", "required rule"),
                  ("required_boards", "required-board", "required board"), ("checks", "check", "check command"))
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
    setter = actions.add_parser(
        "set", help="Set the host, guard, research policy, sector, approval mode, waiver policy, whether every rule "
                    "is asked, or a setup answer.")
    setter.add_argument("field", choices=sorted(SET_FIELDS), help="The setting to change.")
    setter.add_argument("value", help="Its new value.")
    setter.add_argument("--signers", metavar="PATH",
                        help="approval signed: the allowed signers file, a path inside the project.")
    setter.add_argument("--approver", action="append", metavar="NAME",
                        help="approval signed: a person whose signature approves a task; repeat for each.")
    setter.add_argument("--allowed-by", action="append", metavar="NAME",
                        help="waivers allowed: a person who may waive a blocker; repeat for each.")
    setter.add_argument("--max-days", type=int, metavar="DAYS",
                        help="waivers allowed: how long a waiver may last, 1 to 366 days.")
    for name, command in actions.choices.items():
        command.add_argument("--by", required=True, help="The person who decides the change.")
        # Only an adopted or declined pattern shows its reason in AGENTS.md and preview (profile_decision_lines).
        shown = " and shown in AGENTS.md and preview" if name in ("adopt", "decline") else ""
        command.add_argument("--reason", required=True, help="Why, in one line; recorded in the profile history "
                                                             f"(.openguildkit/project.json){shown}.")


def weakening_changes(before: dict, after: dict, catalog: dict) -> list[tuple[str, list[str]]]:
    """What a new profile weakens, each with the profile command a person types for it at a terminal: a lower
    guard, public research, a regulation that stops being active, a regulation, security or AI pack removed, the
    security or legal board removed, personal data set to no, a host whose settings enforce less, signed
    approvals turned off or on, an approver added or the signers file moved, waivers allowed or widened, a
    required rule, required board or check command removed, every rule no longer asked. The profile commands and
    the web page ask this."""
    person = ["--by", "NAME", "--reason", "WHY"]
    changes = [*_approval_changes(before, after, person), *_waiver_changes(before, after, person)]
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
    for key, field, label in REQUIRED_LISTS:
        kept = _texts(after.get(key))
        for value in _texts(before.get(key)):
            if value not in kept:
                changes.append((f"{label} {value} removed", ["profile", "remove", field, value, *person]))
    if before.get("ask_every_rule") is True and after.get("ask_every_rule") is not True:
        changes.append(("every rule no longer asked", ["profile", "set", "ask-every-rule", "no", *person]))
    return changes


def _texts(value) -> list[str]:
    """The entries of a list of a profile, or a draft's, keeping only text."""
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _signed(profile: dict) -> dict | None:
    """Who approves in a profile with signed approvals, or None when approvals are local."""
    approval = profile.get("approval")
    if not isinstance(approval, dict) or approval.get("mode") != "signed":
        return None
    return {"allowed_signers": str(approval.get("allowed_signers")), "approvers": _texts(approval.get("approvers"))}


def _approval_changes(before: dict, after: dict, person: list[str]) -> list[tuple[str, list[str]]]:
    """Signed approvals turned off, or a change of who signs: an approver added, the signers file moved, or
    signing turned on, since whoever writes that file then approves without a terminal."""
    old, new = _signed(before), _signed(after)
    if old == new:
        return []
    if new is None:
        return [("signed approvals turned off", ["profile", "set", "approval", "local", *person])]
    command = ["profile", "set", "approval", "signed", "--signers", new["allowed_signers"],
               *[word for name in new["approvers"] for word in ("--approver", name)], *person]
    if old is None:
        return [(f"signed approvals turned on: {', '.join(new['approvers'])} approve with a key listed in "
                 f"{new['allowed_signers']}", command)]
    changes = []
    added = [name for name in new["approvers"] if name not in old["approvers"]]
    if added:
        changes.append((f"approver {', '.join(added)} added", command))
    if new["allowed_signers"] != old["allowed_signers"]:
        changes.append((f"allowed signers moved from {old['allowed_signers']} to {new['allowed_signers']}", command))
    return changes


def _waiver_policy(profile: dict) -> tuple[list[str], int] | None:
    waivers = profile.get("waivers")
    if not isinstance(waivers, dict):
        return None
    days = waivers.get("max_days")
    return _texts(waivers.get("allowed_by")), days if type(days) is int else 0


def _waiver_changes(before: dict, after: dict, person: list[str]) -> list[tuple[str, list[str]]]:
    """Waivers allowed where none were, or allowed to more people or for longer."""
    old, new = _waiver_policy(before), _waiver_policy(after)
    if new is None or new == old:
        return []
    names, days = new
    command = ["profile", "set", "waivers", "allowed", *[word for name in names for word in ("--allowed-by", name)],
               "--max-days", str(days), *person]
    if old is None:
        return [(f"waivers allowed, by {', '.join(names)}, for up to {days} days", command)]
    wider = [f"{name} may waive" for name in names if name not in old[0]]
    if days > old[1]:
        wider.append(f"a waiver lasts up to {days} days instead of {old[1]}")
    return [(f"waivers widened: {'; '.join(wider)}", command)] if wider else []


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


def _setting(field: str, value: str, options: dict) -> tuple[str, object]:
    """The profile key a set command writes and its new value; None removes the key."""
    if field == "approval":
        if value == "local":
            return "approval", None
        if not options["signers"] or not options["approver"]:
            raise ValueError("profile set approval signed needs --signers PATH and at least one --approver NAME.")
        return "approval", {"mode": "signed", "allowed_signers": options["signers"], "approvers": options["approver"]}
    if field == "waivers":
        if value == "none":
            return "waivers", None
        if not options["allowed_by"] or options["max_days"] is None:
            raise ValueError("profile set waivers allowed needs at least one --allowed-by NAME and --max-days DAYS.")
        return "waivers", {"allowed_by": options["allowed_by"], "max_days": options["max_days"]}
    if field == "ask-every-rule":
        return "ask_every_rule", True if value == "yes" else None
    return field.replace("-", "_"), value == "yes" if field in ("personal-data", "people-decisions") else value


def _set(profile: dict, args, catalog: dict) -> dict:
    field, value = args.field, args.value
    allowed = SET_FIELDS[field] or tuple(catalog["sectors"])
    if value not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}.")
    options = {name: getattr(args, name, None) for name in SET_OPTIONS}
    for name, owner in SET_OPTIONS.items():
        if options[name] is not None and owner != (field, value):
            option = name.replace("_", "-")
            raise ValueError(f"--{option} belongs to profile set {' '.join(owner)}. Nothing was written.")
    key, new = _setting(field, value, options)
    if profile.get(key) == new:
        raise ValueError(f"{field} is already {value}. Nothing was written.")
    updated = {name: item for name, item in profile.items() if name != key}
    return updated if new is None else {**updated, key: new}


def _set_change(args) -> str:
    """The set command in a few words for the history, with who signs or who may waive."""
    change = f"set {args.field} {args.value}"
    if args.field == "approval" and args.value == "signed":
        return f"{change} (signers {args.signers}; approvers {', '.join(args.approver or [])})"
    if args.field == "waivers" and args.value == "allowed":
        return f"{change} (by {', '.join(args.allowed_by or [])}; up to {args.max_days} days)"
    return change


def _changed(profile: dict, args, catalog: dict) -> tuple[dict, str]:
    """The profile after the command and the change in a few words."""
    action = args.profile_action
    if action == "adopt":
        return _adopt(profile, args.pattern, catalog), f"adopt {args.pattern}"
    if action == "decline":
        updated = _decline(profile, args.pattern, catalog, args.by.strip(), args.reason.strip())
        return updated, f"decline {args.pattern}"
    if action in ("add", "remove"):
        updated = _change_list(profile, args.field, args.values, action == "add", catalog)
        return updated, f"{action} {args.field} {', '.join(args.values)}"
    return _set(profile, args, catalog), _set_change(args)


class Weakening(ValueError):
    """A change that weakens a protection, refused without a person at a terminal. `changes` holds each
    protection with the profile command a person types for it."""

    def __init__(self, message: str, changes: list[tuple[str, list[str]]]):
        super().__init__(message)
        self.changes = changes


class InvalidProfile(ValueError):
    """A profile edited in the page that cannot be used, or that rewrites the history of profile changes."""


def _voids(voided: list[str]) -> str:
    return f" It also voids the approval of {', '.join(voided)}." if voided else ""


def _confirm(change: str, target: str, weakened: list[tuple[str, list[str]]], voided: list[str]) -> None:
    """A change that weakens a protection is typed by the person at a terminal, never run by an agent."""
    what = "; ".join(text for text, _ in weakened)
    if not sys.stdin.isatty():
        raise Weakening(f"'{change}' weakens a protection ({what}): it is the person's decision. Ask them to run the "
                        f"same command at an interactive terminal.{_voids(voided)} Nothing was written.", weakened)
    print(f"'{change}' weakens a protection of the project ({what}).{_voids(voided)} Type {target} to confirm: ",
          end="", file=sys.stderr, flush=True)
    if input().strip() != target:
        raise ValueError("Profile change cancelled. Nothing was written.")


def voided_approvals(state: Path, profile: dict, catalog: dict) -> list[str]:
    """The approved tasks whose approval this profile voids, by the rule that decides whether an approval holds."""
    return [task["id"] for task in tasks_touched(state, profile, catalog) if task["status"] == "approved"]


def write_change(root: Path, state: Path, args, edit, by: str, reason: str, confirm) -> tuple[dict, dict, dict]:
    """Under the project lock: apply edit to the profile, name the approvals it voids, have the person confirm what
    it weakens, record who, when and why, then write the instructions, the profile and the catalog lock. args carries
    the central policy options of the command, or is None for the web page."""
    with project_lock(state):
        live, bundled = installed_catalog(args, state)
        lock = read_lock(state)
        catalog = apply_lock(live, lock)
        profile = load_profile(state, catalog)
        edited, change = edit(profile, catalog)
        updated = validate_profile(edited, catalog)
        weakened = weakening_changes(profile, updated, catalog)
        voided = voided_approvals(state, updated, catalog)
        if weakened:
            confirm(change, weakened, voided)
        elif voided:
            print(f"This change voids the approval of {', '.join(voided)}: each is consulted again before its work "
                  "goes on.", flush=True)
        record = {"change": change, "by": by, "on": today().isoformat(), "reason": reason}
        updated = validate_profile({**updated, "changes": [*profile.get("changes", []), record]}, catalog)
        sync_instructions(root, updated, catalog)
        write_json(state / "project.json", updated)
        write_lock(state, build_lock(updated, catalog, bundled, lock))
    return updated, updated["changes"][-1], catalog


def print_touched(tasks: list[dict], before: bool = False) -> None:
    """The tasks a change of rules touches, in the same words for update, update --apply, sync and profile changes."""
    if not tasks:
        return
    print("Tasks this change touches:" if before else "Tasks consulted under the previous rules:")
    for task in tasks:
        print(f"  {task['id']} ({task['status']}): {task['step']}.")


def report_change(state: Path, updated: dict, record: dict, catalog: dict, host_settings: bool) -> None:
    """What follows a change: the norms it brings, the host settings to apply, the tasks it touches."""
    print(f"Profile changed: {record['change']}, by {record['by']} on {record['on']}. AGENTS.md is up to date.")
    for norm in unanswered_norms(updated, catalog, {}):
        pattern = catalog["patterns"][norm["id"]]
        print(f"  Norm {norm['id']} now concerns the project ({norm_reason(pattern)}) and is not active: ask the "
              f"person, then openguildkit profile adopt {norm['id']} or decline {norm['id']}, with --by and --reason.")
    if host_settings:
        print("  Run openguildkit host apply, then openguildkit host check, so the host settings follow.")
    touched = tasks_touched(state, updated, catalog)
    print_touched(touched)
    if not touched:
        print("No open task was consulted under the previous profile.")


def run(args, root: Path, state: Path) -> int:
    """Apply one profile command, rewrite the instructions and the catalog lock, and say what follows."""
    target = getattr(args, "pattern", None) or getattr(args, "value", None) or " ".join(args.values)
    updated, record, catalog = write_change(
        root, state, args, lambda profile, catalog: _changed(profile, args, catalog),
        args.by, args.reason, lambda change, weakened, voided: _confirm(change, target, weakened, voided))
    host_settings = args.profile_action == "set" and args.field in ("host", "guard", "research")
    report_change(state, updated, record, catalog, host_settings)
    return 0


def save_edited(root: Path, state: Path, edited: dict, by: str, reason: str) -> None:
    """Save a whole profile edited in the web page by the same path as the commands. The page sends the history of
    changes as it is and the change is recorded after it; a change that weakens a protection is refused, with the
    profile command a person types for it."""
    changed: list[str] = []

    def edit(profile: dict, catalog: dict) -> tuple[dict, str]:
        try:
            candidate = validate_profile(edited, catalog)
        except ValueError as error:
            raise InvalidProfile(str(error)) from None
        # The history sent must be the saved one: the server adds the entry of this change itself. A page that
        # read the profile before another command changed it sends an older history and would undo that change.
        if candidate.get("changes", []) != profile.get("changes", []):
            raise InvalidProfile("The history of profile changes (changes) differs from the saved one: the profile "
                                 "changed since the page read it, or the page edited its history. Reload the profile "
                                 "and make the change again. Nothing was written.")
        fields = sorted(key for key in {*profile, *candidate} - {"changes"} if profile.get(key) != candidate.get(key))
        if not fields:
            raise ValueError("The profile is unchanged. Nothing was written.")
        changed.extend(fields)
        return candidate, f"edit {', '.join(fields)} from the web page"

    def refuse(change: str, weakened: list[tuple[str, list[str]]], voided: list[str]) -> None:
        what = "; ".join(text for text, _ in weakened)
        raise Weakening(f"{what}: this weakens a protection, which is the person's decision at an interactive "
                        f"terminal.{_voids(voided)} Nothing was written.", weakened)

    updated, record, catalog = write_change(root, state, None, edit, by, reason, refuse)
    report_change(state, updated, record, catalog, bool({"host", "guard", "research"} & set(changed)))
