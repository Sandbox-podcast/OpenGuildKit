"""What each `profile` command writes into the profile: packs and rules adopted or declined, lists, settings and their
values.

Entry: lifted_paths, rule_argument, changed_profile, LIST_FIELDS, SET_FIELDS, RULE_WORD
Tests: tests/test_profile_reference.py
"""

import difflib
from collections.abc import Mapping
from typing import Any

from . import requester, short_lane
from .clock import today
from .errors import OgkError
from .hosts import HOSTS, LIFTED
from .patterns import pattern_selection, recommend_patterns, role_choices
from .project import declined_ids, declined_rule_ids, restricted_paths, rules_in_force
from .project_rules import resolved_profile
from .project_setup import GUARD_MODES
from .records import Catalog, Profile, as_dict
from .shell import shell_word
from .tool_registry import load_tools
from .tools import match_tools

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
    "approver-roles": None,  # A board and the people of its role, or none: set apart in _set.
    "restricted-paths": None,  # Paths closed to the agents, or none: set apart in _set.
}


# Settings whose value is not one of a short list.
FREE_VALUES = ("light-paths", "max-approval-age", "approver-roles", "restricted-paths")


# The options of profile set, each with the setting and value it belongs to.
SET_OPTIONS = {"signers": ("approval", "signed"), "approver": ("approval", "signed"),
               "allowed_by": ("waivers", "allowed"), "max_days": ("waivers", "allowed")}


# profile decline rule PACK/RULE and profile adopt rule PACK/RULE set one rule aside and restore it (RFC #447).
RULE_WORD = "rule"


def lifted_paths(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    now = set(restricted_paths(after))
    return [path for path in restricted_paths(before) if path not in now]


def _adopt(profile: Profile, pattern_id: str, catalog: Catalog) -> dict:
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


def _decline(profile: Profile, pattern_id: str, catalog: Catalog, by: str, reason: str) -> dict:
    if pattern_id not in catalog["patterns"]:
        raise OgkError("OGK-PROFILE-001", f"Unknown pattern: {pattern_id}. Run openguildkit patterns.")
    if pattern_id in declined_ids(profile):
        raise ValueError(f"{pattern_id} is already declined. Nothing was written.")
    patterns = [entry for entry in profile.get("patterns", []) if pattern_selection(entry)[0] != pattern_id]
    decline = {"id": pattern_id, "by": by, "on": today().isoformat(), "reason": reason}
    return {**profile, "patterns": patterns, "declined": [*profile.get("declined", []), decline]}


def _known_rule(value: str, catalog: Catalog) -> str:
    """PACK/RULE as the catalog has it, from PACK/RULE or rule:PACK/RULE (the ID task checks prints)."""
    rule = value.strip().removeprefix("rule:")
    if "/" not in rule:
        raise OgkError("OGK-PROFILE-002", f"Name one rule as PACK/RULE, such as python/follow-python-style: {value} is not. AGENTS.md "
                         "lists the rules in force under their pack. Nothing was written.")
    names = [f"{pack_id}/{item['id']}" for pack_id, pack in catalog["packs"].items() for item in pack["rules"]]
    if rule not in names:
        close = difflib.get_close_matches(rule, names, n=1)
        hint = f" Did you mean {close[0]}?" if close else " AGENTS.md lists the rules in force under their pack."
        raise OgkError("OGK-PROFILE-003", f"Unknown rule {rule}.{hint} Nothing was written.")
    return rule


def _decline_rule(profile: Profile, value: str, catalog: Catalog, by: str, reason: str) -> dict:
    """One rule set aside with who, when and why: a rule in force, neither required nor the last of its pack."""
    rule = _known_rule(value, catalog)
    pack_id, _, rule_id = rule.partition("/")
    if pack_id == "agent-workflow":
        raise OgkError("OGK-PROFILE-004", "agent-workflow is required by OpenGuildKit: its rules cannot be declined. Nothing was written.")
    if rule in declined_rule_ids(profile):
        raise OgkError("OGK-PROFILE-005", f"Rule {rule} is already declined. Nothing was written.")
    if pack_id not in resolved_profile(profile, catalog)["packs"]:
        raise OgkError("OGK-PROFILE-006", f"Rule {rule} is not in force: its pack {pack_id} is not active in this profile, so no task "
                         "is asked it. Nothing was written.")
    required = [item for item in profile.get("required_rules", []) if item in (pack_id, rule)]
    if required:
        raise OgkError("OGK-PROFILE-007", f"Rule {rule} is required by the profile (required_rules lists {required[0]}): remove it from "
                         f"the required rules first, at a terminal: openguildkit profile remove required-rule "
                         f"{required[0]} --by INITIALS --reason WHY. Nothing was written.")
    if [item["id"] for item in rules_in_force(catalog["packs"][pack_id], profile)["rules"]] == [rule_id]:
        raise OgkError("OGK-PROFILE-008", f"{rule_id} is the last rule of pack {pack_id} in force: remove the pack (openguildkit profile "
                         f"remove pack {pack_id}) or decline the pattern that brings it, rather than each of its rules. "
                         "Nothing was written.")
    entry = {"id": rule, "by": by, "on": today().isoformat(), "reason": reason}
    return {**profile, "declined_rules": [*profile.get("declined_rules", []), entry]}


def _adopt_rule(profile: Profile, value: str) -> dict:
    """A declined rule asked again; a rule the catalog no longer has can be restored too, to clear its entry."""
    rule = value.strip().removeprefix("rule:")
    if rule not in declined_rule_ids(profile):
        declined = ", ".join(declined_rule_ids(profile)) or "none"
        raise OgkError("OGK-PROFILE-009", f"Rule {rule} is not declined (declined rules: {declined}). Nothing was written.")
    kept = [entry for entry in profile["declined_rules"] if entry["id"] != rule]
    updated = {key: value for key, value in profile.items() if key != "declined_rules"}
    return {**updated, "declined_rules": kept} if kept else updated


def rule_argument(args) -> str | None:
    """The PACK/RULE of profile adopt rule or decline rule, None for a pattern, or why the words do not fit."""
    rule = getattr(args, "rule", None)
    if args.pattern != RULE_WORD:
        if rule is not None:
            raise ValueError(f"profile {args.profile_action} takes one PATTERN, or the word rule and PACK/RULE: "
                             f"openguildkit profile {args.profile_action} rule {rule}. Nothing was written.")
        return None
    if rule is None:
        raise ValueError(f"profile {args.profile_action} rule needs PACK/RULE, such as openguildkit profile "
                         f"{args.profile_action} rule python/follow-python-style --by INITIALS --reason WHY.")
    return rule


def _change_tools(current: list[str], values: list[str], add: bool) -> list[str]:
    """The profile's tools after profile add or remove tool: a tool of the registry is found under any of its
    spellings and written as its title, as features enable and disable do; any other name is kept as typed."""
    tools = load_tools()
    for value in values:
        tool_id = next(iter(match_tools([value], tools)[0]), None)
        names = [name for name in current if name == value or tool_id and match_tools([name], tools)[0] == [tool_id]]
        if add and names or not add and not names:
            raise OgkError("OGK-PROFILE-010", f"{value} is {'already in' if add else 'not in'} the profile's tools. Nothing was written.")
        if add:
            current = [*current, tools[tool_id]["title"] if tool_id else value]
        else:
            current = [name for name in current if name not in names]
    return current


def _change_list(profile: Profile, field: str, values: list[str], add: bool, catalog: Catalog) -> dict:
    key, collection = LIST_FIELDS[field]
    if field == "tool":
        return {**profile, key: _change_tools(list(as_dict(profile).get(key, [])), values, add)}
    known = catalog[collection] if collection else role_choices(catalog["patterns"]) if field == "role" else None
    current = list(as_dict(profile).get(key, []))
    for value in values:
        if known is not None and value not in known:
            raise OgkError("OGK-PROFILE-011", f"Unknown {field}: {value}. Run openguildkit catalog or openguildkit patterns.")
        if add and value in current or not add and value not in current:
            state = "already in" if add else "not in"
            raise OgkError("OGK-PROFILE-012", f"{value} is {state} the profile's {key}. Nothing was written.")
        if add:
            current.append(value)
        else:
            current.remove(value)
    if field == "pack" and not add and "agent-workflow" in values:
        raise OgkError("OGK-PROFILE-013", "agent-workflow is required by OpenGuildKit and cannot be removed.")
    return {**profile, key: current}


def _approval_setting(value: str, options: dict) -> tuple[str, object]:
    """The approval mode: local, or signed by the approvers with the allowed signers file; the age limit and roles
    are kept."""
    # The limit on the age of an approval and the roles are set by their own commands.
    kept = {key: item for key, item in options["approval"].items() if key in ("max_age_days", "roles")}
    if value == "local":
        return "approval", {"mode": "local", **kept} if kept else None
    if not options["signers"] or not options["approver"]:
        raise OgkError("OGK-PROFILE-014", "profile set approval signed needs --signers PATH and at least one --approver NAME.")
    return "approval", {"mode": "signed", "allowed_signers": options["signers"], "approvers": options["approver"],
                        **kept}


def _approver_roles_setting(value: str, options: dict) -> tuple[str, object]:
    """The people of a board's approver role, or none to remove it."""
    approval, board, names = options["approval"], value, options["paths"][1:]
    roles = dict(approval.get("roles") or {})
    if not names:
        raise ValueError("profile set approver-roles BOARD needs the people of the role, or none. Nothing was "
                         "written.")
    if names == ["none"]:
        if board not in roles:
            raise ValueError(f"The {board} board has no role. Nothing was written.")
        del roles[board]
    elif roles.get(board) == names:
        raise ValueError(f"The role of the {board} board already holds {', '.join(names)}. Nothing was written.")
    else:
        roles[board] = names
    rest = {key: item for key, item in approval.items() if key != "roles"}
    return "approval", {**rest, "roles": roles} if roles else (rest if len(rest) > 1 else None)


def _restricted_setting(value: str, options: dict) -> tuple[str, object]:
    """The paths the team closes to the agent, or none."""
    if value == "none":
        if options["paths"][1:]:
            raise ValueError("profile set restricted-paths none takes no other path. Nothing was written.")
        return "restricted_paths", None
    return "restricted_paths", [{"paths": list(dict.fromkeys(path.strip() for path in options["paths"]))}]


def _max_age_setting(value: str, options: dict) -> tuple[str, object]:
    """The age in days after which an approval no longer covers the work, or none."""
    approval = options["approval"]
    if value == "none":
        rest = {key: item for key, item in approval.items() if key != "max_age_days"}
        return "approval", rest if len(rest) > 1 else None
    if not value.isdigit() or not 1 <= int(value) <= 366:
        raise OgkError("OGK-PROFILE-015", "profile set max-approval-age takes a whole number of days, 1 to 366, or none. Nothing "
                         "was written.")
    return "approval", {**approval, "max_age_days": int(value)}


def _waivers_setting(value: str, options: dict) -> tuple[str, object]:
    """Who may waive a blocker and for how many days, or none."""
    if value == "none":
        return "waivers", None
    if not options["allowed_by"] or options["max_days"] is None:
        raise OgkError("OGK-PROFILE-016", "profile set waivers allowed needs at least one --allowed-by NAME and --max-days DAYS.")
    return "waivers", {"allowed_by": options["allowed_by"], "max_days": options["max_days"]}


def _light_paths_setting(value: str, options: dict) -> tuple[str, object]:
    """The paths of the short lane, or none."""
    if value == "none":
        if options["paths"][1:]:
            raise ValueError("profile set light-paths none takes no other path. Nothing was written.")
        return "light_paths", None
    return "light_paths", short_lane.normalize_entries(options["paths"], "light-paths")


def _setting(field: str, value: str, options: dict) -> tuple[str, object]:
    """The profile key a set command writes and its new value; None removes the key."""
    if field == "approval":
        return _approval_setting(value, options)
    if field == "freeze":
        return "frozen", {"by": options["by"], "on": today().isoformat(), "reason": options["reason"]} \
            if value == "on" else None
    if field == "approver-roles":
        return _approver_roles_setting(value, options)
    if field == "restricted-paths":
        return _restricted_setting(value, options)
    if field == "max-approval-age":
        return _max_age_setting(value, options)
    if field == "waivers":
        return _waivers_setting(value, options)
    if field == "ask-every-rule":
        return "ask_every_rule", True if value == "yes" else None
    if field == "separate-requester":
        return requester.FIELD, True if value == "on" else None
    if field == "light-paths":
        return _light_paths_setting(value, options)
    return field.replace("-", "_"), value == "yes" if field in ("personal-data", "people-decisions") else value


def _set(profile: Profile, args, catalog: Catalog) -> dict:
    field, value = args.field, args.value
    if field not in FREE_VALUES:
        allowed = SET_FIELDS[field] or tuple(catalog["sectors"])
        if value not in allowed:
            raise OgkError("OGK-PROFILE-017", f"{field} must be one of {', '.join(allowed)}.")
        if args.more:
            raise OgkError("OGK-PROFILE-018", f"profile set {field} takes one value, not {len(args.more) + 1}. Nothing was written.")
    options = {name: getattr(args, name, None) for name in SET_OPTIONS}
    options["paths"] = [value, *args.more]
    options.update(approval=profile.get("approval") or {"mode": "local"}, by=args.by.strip(), reason=args.reason.strip())
    for name, owner in SET_OPTIONS.items():
        if options[name] is not None and owner != (field, value):
            option = name.replace("_", "-")
            raise OgkError("OGK-PROFILE-019", f"--{option} belongs to profile set {' '.join(owner)}. Nothing was written.")
    key, new = _setting(field, value, options)
    if field == "freeze" and new is not None and profile.get(key):
        raise OgkError("OGK-PROFILE-020", f"The project is already frozen by {as_dict(profile)[key]['by']} since {as_dict(profile)[key]['on']}. Nothing "
                         "was written.")
    if profile.get(key) == new:
        raise OgkError("OGK-PROFILE-021", f"{field} is already {value}. Nothing was written.")
    updated = {name: item for name, item in profile.items() if name != key}
    return updated if new is None else {**updated, key: new}


def _set_change(args, before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """The set command in a few words for the history, with who signs or who may waive, or the restricted paths it
    lifts, which host apply reads to remove the rules it wrote for them (hosts.py:lifted_rules)."""
    change = f"set {args.field} {args.value}"
    if args.field == "restricted-paths":
        words = " ".join(shell_word(path, powershell=False) for path in restricted_paths(after)) or "none"
        lifted = lifted_paths(before, after)
        return f"set restricted-paths {words}" + (
            f" ({LIFTED} {' '.join(shell_word(path, powershell=False) for path in lifted)})" if lifted else "")
    if args.field == "approval" and args.value == "signed":
        return f"{change} (signers {args.signers}; approvers {', '.join(args.approver or [])})"
    if args.field == "waivers" and args.value == "allowed":
        return f"{change} (by {', '.join(args.allowed_by or [])}; up to {args.max_days} days)"
    if args.field == "light-paths" and args.value != "none":
        return f"set light-paths {', '.join(short_lane.normalize_entries([args.value, *args.more], 'light-paths'))}"
    if args.field == "approver-roles":
        return f"set approver-roles {args.value} {' '.join(args.more)}"
    return change


def changed_profile(profile: Profile, args, catalog: Catalog) -> tuple[dict, str]:
    """The profile after the command and the change in a few words."""
    action = args.profile_action
    rule = rule_argument(args) if action in ("adopt", "decline") else None
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
    updated = _set(profile, args, catalog)
    return updated, _set_change(args, profile, updated)
