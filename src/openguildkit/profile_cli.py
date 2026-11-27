"""The `openguildkit profile` commands: change the project profile after setup, with who, when and why.

The guard forbids the agent to edit .openguildkit/project.json, so every change goes through these
commands, and the web page saves an edited profile through the same path (save_edited). Each change is
written under the project lock, validated like init, recorded in changes, and rewrites the instructions like
sync. What weakens a protection (see weakening_changes) is the person's decision: it needs an interactive
terminal and a typed confirmation. The approvals a change voids are named before anything is written.
"""

import difflib
import sys
from argparse import Namespace
from pathlib import Path

from . import incident, light_lane, requester
from .clock import today
from .hosts import HOSTS
from .lock import apply_lock, build_lock, installed_catalog, project_catalog, read_lock, write_lock
from .patterns import pattern_selection, recommend_patterns, role_choices
from .project import (
    DEFAULT_GUARD, GUARD_MODES, declined_ids, declined_rule_ids, is_norm, load_profile, norm_reason, resolved_profile,
    rules_in_force, sync_instructions, unanswered_norms, validate_profile,
)
from .sensitive import redact_credentials
from .shell import shell_word
from .storage import print_json, project_lock, write_json
from .tasks import tasks_touched
from .terminal import interactive

LIST_FIELDS = {
    "pack": ("packs", "packs"), "role": ("roles", None), "tool": ("tools", None), "check": ("checks", None),
    "convention": ("conventions", None), "board": ("boards", "boards"),
    "required-board": ("required_boards", "boards"), "required-rule": ("required_rules", None),
}
SET_FIELDS = {
    "host": HOSTS, "guard": tuple(GUARD_MODES), "research": ("local-only", "public-sources"),
    "personal-data": ("yes", "no"), "people-decisions": ("yes", "no"), "sector": None,
    "approval": ("local", "signed"), "waivers": ("none", "allowed"), "ask-every-rule": ("yes", "no"),
    "light-paths": None,  # Paths, not a choice: set apart in _set.
    "separate-requester": ("on", "off"),
    "freeze": ("on", "off"),
    "max-approval-age": None,  # A number of days, or none: set apart in _set.
}
# Settings whose value is not one of a short list.
FREE_VALUES = ("light-paths", "max-approval-age")
# The options of profile set, each with the setting and value it belongs to.
SET_OPTIONS = {"signers": ("approval", "signed"), "approver": ("approval", "signed"),
               "allowed_by": ("waivers", "allowed"), "max_days": ("waivers", "allowed")}
# Lists whose entries a person adds for protection: removing one weakens it.
REQUIRED_LISTS = (("required_rules", "required-rule", "required rule"),
                  ("required_boards", "required-board", "required board"), ("checks", "check", "check command"))
GUARD_LEVEL = {"off": 0, "observe": 1, "enforce": 2}
# How much each host enforces by itself: Claude Code also denies edits to the profile and the task records,
# Codex runs the hooks and forbids the approval commands, Gemini CLI runs the hooks and nothing else, another agent
# only reads the instructions.
HOST_LEVEL = {"other": 0, "gemini-cli": 1, "codex": 2, "claude-code": 3}
PROTECTIVE_BOARDS = ("security", "legal")
AI_PACKS = ("llm-evaluations", "nist-ai-risk", "eu-ai-act")
# profile decline rule PACK/RULE and profile adopt rule PACK/RULE set one rule aside and restore it (RFC #447).
RULE_WORD = "rule"


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
    for name, text in (("adopt", "Adopt a pattern or regulation: it becomes active. adopt rule PACK/RULE restores a "
                                 "declined rule."),
                       ("decline", "Decline a pattern or regulation: it is not active and not proposed again. decline "
                                   "rule PACK/RULE sets one rule aside: no task is asked it.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("pattern", metavar="PATTERN", help="Pattern ID, from openguildkit recommend or patterns; "
                                                                "or the word rule, followed by PACK/RULE.")
        command.add_argument("rule", nargs="?", metavar="PACK/RULE",
                             help="After the word rule: one rule, as AGENTS.md lists it under its pack.")
    for name, text in (("add", "Add entries to a list of the profile."), ("remove", "Remove entries from a list.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("field", choices=sorted(LIST_FIELDS), help="The list to change.")
        command.add_argument("values", nargs="+", metavar="VALUE", help="IDs, tool names or check commands.")
    setter = actions.add_parser(
        "set", help="Set the host, guard, research policy, sector, approval mode, waiver policy, whether every rule "
                    "is asked, the paths of the short lane, whether the requester of a task may approve it, the "
                    "freeze of the project, the longest age of an approval, or a setup answer.")
    setter.add_argument("field", choices=sorted(SET_FIELDS), help="The setting to change.")
    setter.add_argument("value", help="Its new value (light-paths: a folder or file glob such as 'docs/**', or none).")
    setter.add_argument("more", nargs="*", metavar="PATH", help="light-paths: more paths.")
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
    # Reading only: no --by or --reason, since nothing is written.
    actions.add_parser("export", help="Print the setup answers that give another repository this profile's patterns, "
                                      "packs, boards and settings, for openguildkit init --answers FILE there.")


def weakening_changes(before: dict, after: dict, catalog: dict) -> list[tuple[str, list[str]]]:
    """What a new profile weakens, each with the profile command a person types for it at a terminal: a lower
    guard, public research, a regulation that stops being active, a regulation, security or AI pack removed, the
    security or legal board removed, personal data set to no, a host whose settings enforce less, signed
    approvals turned off or on, an approver added or the signers file moved, waivers allowed or widened, a
    required rule, required board or check command removed, every rule no longer asked, a path added to the short
    lane, the separation of the requester and the approver turned on or off, a freeze lifted, the limit on the age of an
    approval raised or removed. The profile commands and the web page ask this."""
    person = ["--by", "NAME", "--reason", "WHY"]
    changes = [*_approval_changes(before, after, person), *_waiver_changes(before, after, person),
               *_light_changes(before, after, person), *_requester_changes(before, after, person),
               *_incident_changes(before, after, person)]
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
    already = set(declined_rule_ids(before))
    for rule in declined_rule_ids(after):
        if rule not in already:
            changes.append((f"rule {rule} declined", ["profile", "decline", RULE_WORD, rule, *person]))
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


def _light_changes(before: dict, after: dict, person: list[str]) -> list[tuple[str, list[str]]]:
    """A path added to the short lane: a task there is reviewed by one board and without questions, so adding a path
    lowers the rigor of that part of the project. Fewer paths, or none, is stricter and asks nothing."""
    old, new = _texts(before.get("light_paths")), _texts(after.get("light_paths"))
    added = [path for path in new if path not in old]
    if not added:
        return []
    what = f"short lane widened: {', '.join(added)} added" if old else f"short lane turned on for {', '.join(added)}"
    return [(what, ["profile", "set", "light-paths", *new, *person])]


def _requester_changes(before: dict, after: dict, person: list[str]) -> list[tuple[str, list[str]]]:
    """The separation of the requester and the approver turned on or off. Either way it changes who may approve, so
    only a person turns it, at a terminal, as for signed approvals."""
    old, new = requester.active(before), requester.active(after)
    if old == new:
        return []
    if new:
        return [("requester separation turned on: task new needs --requested-by and the requester cannot approve",
                 ["profile", "set", "separate-requester", "on", *person])]
    return [("requester separation turned off: the requester of a task may approve it",
             ["profile", "set", "separate-requester", "off", *person])]


def _incident_changes(before: dict, after: dict, person: list[str]) -> list[tuple[str, list[str]]]:
    """A freeze lifted, or the limit on the age of an approval raised or removed (incident.py). Freezing and a shorter
    limit only restrict, so they ask nothing."""
    changes = []
    if incident.frozen(before) and not incident.frozen(after):
        changes.append(("freeze lifted: agents may edit again", ["profile", "set", "freeze", "off", *person]))
    old, new = incident.max_age_days(before), incident.max_age_days(after)
    if old is not None and (new is None or new > old):
        what = "removed" if new is None else f"raised from {old} to {new} days"
        changes.append((f"approval age limit {what}: approvals cover work for longer",
                        ["profile", "set", "max-approval-age", "none" if new is None else str(new), *person]))
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


def _known_rule(value: str, catalog: dict) -> str:
    """PACK/RULE as the catalog has it, from PACK/RULE or rule:PACK/RULE (the ID task checks prints)."""
    rule = value.strip().removeprefix("rule:")
    if "/" not in rule:
        raise ValueError(f"Name one rule as PACK/RULE, such as python/follow-python-style: {value} is not. AGENTS.md "
                         "lists the rules in force under their pack. Nothing was written.")
    names = [f"{pack_id}/{item['id']}" for pack_id, pack in catalog["packs"].items() for item in pack["rules"]]
    if rule not in names:
        close = difflib.get_close_matches(rule, names, n=1)
        hint = f" Did you mean {close[0]}?" if close else " AGENTS.md lists the rules in force under their pack."
        raise ValueError(f"Unknown rule {rule}.{hint} Nothing was written.")
    return rule


def _decline_rule(profile: dict, value: str, catalog: dict, by: str, reason: str) -> dict:
    """One rule set aside with who, when and why: a rule in force, neither required nor the last of its pack."""
    rule = _known_rule(value, catalog)
    pack_id, _, rule_id = rule.partition("/")
    if pack_id == "agent-workflow":
        raise ValueError("agent-workflow is required by OpenGuildKit: its rules cannot be declined. Nothing was written.")
    if rule in declined_rule_ids(profile):
        raise ValueError(f"Rule {rule} is already declined. Nothing was written.")
    if pack_id not in resolved_profile(profile, catalog)["packs"]:
        raise ValueError(f"Rule {rule} is not in force: its pack {pack_id} is not active in this profile, so no task "
                         "is asked it. Nothing was written.")
    required = [item for item in profile.get("required_rules", []) if item in (pack_id, rule)]
    if required:
        raise ValueError(f"Rule {rule} is required by the profile (required_rules lists {required[0]}): remove it from "
                         f"the required rules first, at a terminal: openguildkit profile remove required-rule "
                         f"{required[0]} --by NAME --reason WHY. Nothing was written.")
    if [item["id"] for item in rules_in_force(catalog["packs"][pack_id], profile)["rules"]] == [rule_id]:
        raise ValueError(f"{rule_id} is the last rule of pack {pack_id} in force: remove the pack (openguildkit profile "
                         f"remove pack {pack_id}) or decline the pattern that brings it, rather than each of its rules. "
                         "Nothing was written.")
    entry = {"id": rule, "by": by, "on": today().isoformat(), "reason": reason}
    return {**profile, "declined_rules": [*profile.get("declined_rules", []), entry]}


def _adopt_rule(profile: dict, value: str) -> dict:
    """A declined rule asked again; a rule the catalog no longer has can be restored too, to clear its entry."""
    rule = value.strip().removeprefix("rule:")
    if rule not in declined_rule_ids(profile):
        declined = ", ".join(declined_rule_ids(profile)) or "none"
        raise ValueError(f"Rule {rule} is not declined (declined rules: {declined}). Nothing was written.")
    kept = [entry for entry in profile["declined_rules"] if entry["id"] != rule]
    updated = {key: value for key, value in profile.items() if key != "declined_rules"}
    return {**updated, "declined_rules": kept} if kept else updated


def _rule_argument(args) -> str | None:
    """The PACK/RULE of profile adopt rule or decline rule, None for a pattern, or why the words do not fit."""
    rule = getattr(args, "rule", None)
    if args.pattern != RULE_WORD:
        if rule is not None:
            raise ValueError(f"profile {args.profile_action} takes one PATTERN, or the word rule and PACK/RULE: "
                             f"openguildkit profile {args.profile_action} rule {rule}. Nothing was written.")
        return None
    if rule is None:
        raise ValueError(f"profile {args.profile_action} rule needs PACK/RULE, such as openguildkit profile "
                         f"{args.profile_action} rule python/follow-python-style --by NAME --reason WHY.")
    return rule


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
        kept = {key: item for key, item in options["approval"].items() if key == "max_age_days"}  # Set by its own command.
        if value == "local":
            return "approval", {"mode": "local", **kept} if kept else None
        if not options["signers"] or not options["approver"]:
            raise ValueError("profile set approval signed needs --signers PATH and at least one --approver NAME.")
        return "approval", {"mode": "signed", "allowed_signers": options["signers"], "approvers": options["approver"],
                            **kept}
    if field == "freeze":
        return "frozen", {"by": options["by"], "on": today().isoformat(), "reason": options["reason"]} \
            if value == "on" else None
    if field == "max-approval-age":
        approval = options["approval"]
        if value == "none":
            rest = {key: item for key, item in approval.items() if key != "max_age_days"}
            return "approval", rest if len(rest) > 1 else None
        if not value.isdigit() or not 1 <= int(value) <= 366:
            raise ValueError("profile set max-approval-age takes a whole number of days, 1 to 366, or none. Nothing "
                             "was written.")
        return "approval", {**approval, "max_age_days": int(value)}
    if field == "waivers":
        if value == "none":
            return "waivers", None
        if not options["allowed_by"] or options["max_days"] is None:
            raise ValueError("profile set waivers allowed needs at least one --allowed-by NAME and --max-days DAYS.")
        return "waivers", {"allowed_by": options["allowed_by"], "max_days": options["max_days"]}
    if field == "ask-every-rule":
        return "ask_every_rule", True if value == "yes" else None
    if field == "separate-requester":
        return requester.FIELD, True if value == "on" else None
    if field == "light-paths":
        if value == "none":
            if options["paths"][1:]:
                raise ValueError("profile set light-paths none takes no other path. Nothing was written.")
            return "light_paths", None
        return "light_paths", light_lane.normalize_entries(options["paths"], "light-paths")
    return field.replace("-", "_"), value == "yes" if field in ("personal-data", "people-decisions") else value


def _set(profile: dict, args, catalog: dict) -> dict:
    field, value = args.field, args.value
    if field not in FREE_VALUES:
        allowed = SET_FIELDS[field] or tuple(catalog["sectors"])
        if value not in allowed:
            raise ValueError(f"{field} must be one of {', '.join(allowed)}.")
        if args.more:
            raise ValueError(f"profile set {field} takes one value, not {len(args.more) + 1}. Nothing was written.")
    options = {name: getattr(args, name, None) for name in SET_OPTIONS}
    options["paths"] = [value, *args.more]
    options.update(approval=profile.get("approval") or {"mode": "local"}, by=args.by.strip(), reason=args.reason.strip())
    for name, owner in SET_OPTIONS.items():
        if options[name] is not None and owner != (field, value):
            option = name.replace("_", "-")
            raise ValueError(f"--{option} belongs to profile set {' '.join(owner)}. Nothing was written.")
    key, new = _setting(field, value, options)
    if field == "freeze" and new is not None and profile.get(key):
        raise ValueError(f"The project is already frozen by {profile[key]['by']} since {profile[key]['on']}. Nothing "
                         "was written.")
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
    if args.field == "light-paths" and args.value != "none":
        return f"set light-paths {', '.join(light_lane.normalize_entries([args.value, *args.more], 'light-paths'))}"
    return change


def _changed(profile: dict, args, catalog: dict) -> tuple[dict, str]:
    """The profile after the command and the change in a few words."""
    action = args.profile_action
    rule = _rule_argument(args) if action in ("adopt", "decline") else None
    if rule is not None and action == "decline":
        updated = _decline_rule(profile, rule, catalog, args.by.strip(), args.reason.strip())
        return updated, f"decline rule {_known_rule(rule, catalog)}"
    if rule is not None:
        return _adopt_rule(profile, rule), f"adopt rule {rule.strip().removeprefix('rule:')}"
    if action == "adopt":
        return _adopt(profile, args.pattern, catalog), f"adopt {args.pattern}"
    if action == "decline":
        updated = _decline(profile, args.pattern, catalog, args.by.strip(), args.reason.strip())
        return updated, f"decline {args.pattern}"
    if action in ("add", "remove"):
        updated = _change_list(profile, args.field, args.values, action == "add", catalog)
        return updated, f"{action} {args.field} {', '.join(args.values)}"
    return _set(profile, args, catalog), _set_change(args)


def check_proposal(profile: dict, catalog: dict, action: str, field: str | None, value: str) -> tuple[dict, list[str]]:
    """The profile a command would write and what it weakens, or the ValueError the command would raise.

    action is add, remove or decline: field names the list for add and remove and is None for decline, whose value is a
    pattern, or "rule" for decline rule, whose value is PACK/RULE. Nothing is written and the profile given is left as it is: the retrospective proposes only a command that
    this accepts, and the confirmation at a terminal that a weakening needs (write_change) is still the person's.
    """
    rule = field == RULE_WORD
    args = Namespace(profile_action=action, pattern=RULE_WORD if rule else value, rule=value if rule else None,
                     field=field, values=[value], by="NAME", reason="WHY")
    edited, _ = _changed(profile, args, catalog)
    updated = validate_profile(edited, catalog)
    return updated, [text for text, _ in weakening_changes(profile, updated, catalog)]


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
    if not interactive():
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


def _target(args) -> str:
    """What the person types to confirm a change that weakens a protection: the pattern, the values given."""
    if args.profile_action in ("adopt", "decline"):
        rule = _rule_argument(args)
        return args.pattern if rule is None else rule.strip().removeprefix("rule:")
    return " ".join([args.value, *args.more] if args.profile_action == "set" else args.values)


# What profile export never carries, whatever the profile holds: in the words of its last line.
LEFT_ASIDE = ("the project name", "the history of changes", "people's names", "the signers file",
              "component paths", "check commands", "the host's tool connections")
PERSON = "--by NAME --reason WHY"


def _yes_no(value: object) -> str:
    """A saved yes or no as init --answers reads it; unsure when the profile never answered."""
    return "unsure" if value is None else "yes" if value else "no"


def export_answers(profile: dict, catalog: dict) -> tuple[dict, list[str]]:
    """The init --answers file that sets up another repository with this profile's rules, and what the person types
    there for each setting that is left out because it names someone or lowers a protection.

    Carried: sector, stack, roles, the answers on personal data, the patterns and packs as they are, the boards,
    required boards and rules, the host and guard when they do not lower the default, the research policy when it is
    local, the conventions and the pack resolutions, without credentials. A declined norm comes back as yes: declining
    it again is the person's decision, recorded with their name.
    """
    answers: dict = {"sector": profile["sector"], "stack": profile["stack"]}
    if profile.get("roles"):
        answers["roles"] = profile["roles"]
    answers["personal_data"] = _yes_no(profile.get("personal_data"))
    if "people_decisions" in profile:
        answers["people_decisions"] = _yes_no(profile["people_decisions"])
    declined_norms = [pattern_id for pattern_id in declined_ids(profile)
                      if is_norm(catalog["patterns"].get(pattern_id, {}))]
    if declined_norms:
        answers["norms"] = dict.fromkeys(declined_norms, "yes")
    # Component scopes name this repository's folders: each pattern applies to the whole new project.
    answers["patterns"] = list(dict.fromkeys(pattern_selection(entry)[0] for entry in profile.get("patterns", [])))
    answers.update(packs=profile["packs"], replace_default_packs=True, boards=profile["boards"])
    for key in ("required_boards", "required_rules"):
        if profile.get(key):
            answers[key] = profile[key]
    if profile.get("ask_every_rule"):
        answers["ask_every_rule"] = True
    if profile.get("tools"):
        answers["tools"] = profile["tools"]
    commands = "; ".join(f"openguildkit profile decline {norm} {PERSON}" for norm in declined_norms)
    steps = [f"Declined norms come back active: {', '.join(declined_norms)}. The person declines each again at a "
             f"terminal there: {commands}."] if declined_norms else []
    declined_rules = declined_rule_ids(profile)
    if declined_rules:
        commands = "; ".join(f"openguildkit profile decline rule {rule} {PERSON}" for rule in declined_rules)
        steps.append(f"Declined rules come back in force: {', '.join(declined_rules)}. The person declines each again "
                     f"at a terminal there: {commands}.")
    if profile.get("host", "other") != "other":
        answers["host"] = profile["host"]
    guard = profile.get("guard", "off")
    if GUARD_LEVEL.get(guard, 0) >= GUARD_LEVEL[DEFAULT_GUARD]:
        answers["guard"] = guard
    else:
        steps.append(f"guard {guard} is not carried: the new project starts at {DEFAULT_GUARD}. To lower it, the "
                     f"person runs openguildkit profile set guard {guard} {PERSON} at a terminal there.")
    if profile.get("research") == "public-sources":
        steps.append("Public research is not carried: the person runs openguildkit profile set research "
                     f"public-sources {PERSON} at a terminal there.")
    else:
        answers["research"] = "local-only"
    answers["conventions"] = [redact_credentials(text) for text in profile.get("conventions", [])]
    if profile.get("resolutions"):
        answers["resolutions"] = [{**item, "reason": redact_credentials(item["reason"])}
                                  for item in profile["resolutions"]]
    if _signed(profile):
        steps.append("Signed approvals are not carried: the person runs openguildkit profile set approval signed "
                     f"--signers PATH --approver NAME {PERSON} at a terminal there.")
    if _waiver_policy(profile):
        steps.append("Waivers are not carried: the person runs openguildkit profile set waivers allowed --allowed-by "
                     f"NAME --max-days DAYS {PERSON} at a terminal there.")
    if incident.max_age_days(profile):
        steps.append("The limit on the age of an approval is not carried: the person runs openguildkit profile set "
                     f"max-approval-age DAYS {PERSON} at a terminal there.")
    if requester.active(profile):
        steps.append("Requester separation is not carried: the person runs openguildkit profile set separate-requester "
                     f"on {PERSON} at a terminal there.")
    if profile.get("light_paths"):
        steps.append("The short lane is not carried: the person runs openguildkit profile set light-paths GLOB "
                     f"{PERSON} at a terminal there.")
    return answers, _organization_steps(catalog) + steps


def _organization_steps(catalog: dict) -> list[str]:
    """What profile export says of the organization catalog (RFC #446): it is pinned in the lock, not the answers."""
    organization = catalog.get("organization")
    if organization is None:
        return []
    steps = [f"The organization catalog is not carried: before init there, the person runs openguildkit org-catalog "
             f"set --repo PATH --commit {organization['commit']} {PERSON} at a terminal, PATH being their copy."]
    if organization["replaced"]:
        steps.append(f"This project's own records that replace organization records stay here: "
                     f"{', '.join(organization['replaced'])}.")
    return steps


def export(args, state: Path) -> int:
    """Print the setup answers on standard output, and on standard error what stays behind and what follows."""
    catalog = project_catalog(args, state)
    profile = load_profile(state, catalog)
    answers, steps = export_answers(profile, catalog)
    print_json(answers)
    print(f"Left aside: {', '.join(LEFT_ASIDE)}.", file=sys.stderr)
    for step in steps:
        print(step, file=sys.stderr)
    print("Next: in the other repository, openguildkit init --answers answers.json, with this output saved as "
          "answers.json (openguildkit profile export > answers.json).", file=sys.stderr)
    return 0


def run(args, root: Path, state: Path) -> int:
    """Apply one profile command, rewrite the instructions and the catalog lock, and say what follows."""
    if args.profile_action == "export":
        return export(args, state)
    target = _target(args)
    updated, record, catalog = write_change(
        root, state, args, lambda profile, catalog: _changed(profile, args, catalog),
        args.by, args.reason, lambda change, weakened, voided: _confirm(change, target, weakened, voided))
    host_settings = args.profile_action == "set" and args.field in ("host", "guard", "research", "approval")
    report_change(state, updated, record, catalog, host_settings)
    rule = _rule_argument(args) if args.profile_action in ("adopt", "decline") else None
    if rule is not None:
        name = record["change"].split(" ", 2)[2]
        print(f"Tasks consulted from now on are not asked {name}; to restore it: openguildkit profile adopt rule "
              f"{name} --by NAME --reason WHY." if args.profile_action == "decline" else
              f"Rule {name} is asked again of the tasks it concerns, from their next consultation.")
    if updated.get("light_paths") and args.profile_action == "set" and args.field == "light-paths":
        print(f'Short lane: openguildkit task new "BRIEF" --id ID --lane light --paths '
              f'{shell_word(updated["light_paths"][0])} (docs/workflow.md, "Short lane").')
    if args.profile_action == "set" and args.field == "freeze" and incident.frozen(updated) \
            and updated.get("guard", "off") == "off":
        print("Note: the guard is off, so the freeze stops nothing until it is on: openguildkit profile set guard "
              "enforce --by NAME --reason WHY.")
    if requester.active(updated) and args.profile_action == "set" and args.field == "separate-requester":
        print(f'Requester and approver: openguildkit task new "BRIEF" --requested-by NAME; another person approves the '
              f"task ({requester.SECTION}).")
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
    report_change(state, updated, record, catalog, bool({"host", "guard", "research", "approval"} & set(changed)))
