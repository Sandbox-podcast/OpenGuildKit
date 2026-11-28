"""Finds a project and its state folder, and validates and loads its profile.

Entry: project_root, state_path, validate_profile, load_profile
Tests: tests/test_brain_knowledge.py, tests/test_gemini_host.py, tests/test_host_scan.py, tests/test_host_surfaces.py,
tests/test_profile_reference.py, tests/test_rule_checks.py, tests/test_source_dates.py
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from . import lazy_re, short_lane
from .errors import OgkError
from .patterns import (
    check_pattern_choices,
    pattern_selection,
    recommend_patterns,
    role_choices,
)
from .records import Catalog, Profile
from .storage import read_json

STATE_DIR = ".openguildkit"
SCHEMA_VERSION = 1
# The agent's working files (answers, board entries, deliberation, result) go in work/: Git ignores it, and the guard
# lets the agent write there before any approval, as it is state the CLI reads rather than project work.
WORK_DIR = f"{STATE_DIR}/work"


def project_root(path: Path | None) -> Path:
    if path is not None:
        root = path.resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"Project path must be a directory: {root}")
        return root
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / STATE_DIR / "project.json").is_file():
            return candidate
    return current


def state_path(root: Path) -> Path:
    state = root / STATE_DIR
    if state.resolve() != state:
        raise ValueError(f"Project state must stay inside its project: {state}")
    return state


def _single_line(value: str) -> bool:
    """True when the text holds no line break of any kind, including a lone carriage return."""
    return len(value.strip().splitlines()) == 1


def _texts(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise OgkError("OGK-PROJECT-001", f"{field} must be a list of non-empty strings")
    if any(not _single_line(item) for item in value):
        raise OgkError("OGK-PROJECT-002", f"Each entry of {field} must be a single line")
    return list(dict.fromkeys(item.strip() for item in value))


def catalog_ids(value, field: str, available: dict) -> list[str]:
    chosen = _texts(value, field)
    unknown = sorted(set(chosen) - available.keys())
    if unknown:
        hint = (
            " It comes from a central policy: pass --policy-repo and --policy-commit."
            if "export-link-expiry" in unknown else " Run openguildkit catalog."
        )
        raise OgkError("OGK-PROJECT-003", f"Unknown {field}: {', '.join(unknown)}.{hint}")
    return chosen


def _recommended_packs(stack: list[str], catalog: Catalog) -> list[str]:
    aliases = {"react.js": "react", "openapi": "api-design"}
    tokens = {re.split(r"[\s@]+", item.lower(), maxsplit=1)[0] for item in stack}
    legacy_stack_packs = {"api-design", "python", "react", "typescript"}
    names = {aliases.get(token, token) for token in tokens}
    candidates = {"secure-sdlc", *(names & legacy_stack_packs)}
    return sorted(candidates & catalog["packs"].keys())


def default_packs(stack: list[str], components: list[dict], patterns: list, catalog: Catalog) -> list[str]:
    """Recommended packs. In a monorepo a language pack that a selected pattern brings keeps that pattern's scope."""
    packs = _recommended_packs(stack, catalog)
    if not components:
        return packs
    brought = {pack_id for entry in patterns for pack_id in catalog["patterns"][pattern_selection(entry)[0]]["packs"]}
    return [pack_id for pack_id in packs if pack_id not in brought]


COMPONENT_ID = lazy_re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _components(value) -> list[dict]:
    """Validate the project's components: an ID, an optional relative path and a stack each."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("components must be a list of objects with id, path and stack")
    components, seen = [], set()
    for component in value:
        if not isinstance(component, dict) or not {"id", "stack"} <= component.keys() <= {"id", "path", "stack"}:
            raise ValueError("Each component needs an id and a stack, and can have a path")
        component_id = component["id"]
        if not isinstance(component_id, str) or len(component_id) > 64 or not COMPONENT_ID.fullmatch(component_id):
            raise ValueError("Component IDs use up to 64 lowercase letters, digits and separating hyphens")
        if component_id in seen:
            raise ValueError(f"Duplicate component: {component_id}")
        seen.add(component_id)
        entry = {"id": component_id}
        if "path" in component:
            path = component["path"]
            parts = path.replace("\\", "/").split("/") if isinstance(path, str) else []
            if not isinstance(path, str) or not path.strip() or path.startswith(("/", "\\")) or ":" in path or ".." in parts:
                raise OgkError("OGK-PROJECT-004", f"Component {component_id} needs a path relative to the project root")
            entry["path"] = path.strip()
        entry["stack"] = _texts(component["stack"], f"components.{component_id}.stack")
        components.append(entry)
    return components


def project_context(answers: Mapping[str, Any], catalog: Catalog) -> tuple[str, list[str], list[str], list[dict]]:
    sector = answers.get("sector", "general")
    if not isinstance(sector, str) or sector not in catalog["sectors"]:
        raise OgkError("OGK-PROJECT-005", f"Unknown sector: {sector}. Run openguildkit catalog.")
    components = _components(answers.get("components"))
    stack = _texts(answers.get("stack", []), "stack")
    if components:
        # With components, the project stack is the union of what each component uses.
        stack = list(dict.fromkeys([*stack, *(item for component in components for item in component["stack"])]))
    roles = catalog_ids(answers.get("roles", []), "roles", role_choices(catalog["patterns"]))
    return sector, stack, roles, components


def _yes_no(value, field: str) -> bool | None:
    """A yes or no answer: true, false, or None when it was not asked."""
    if value is None or isinstance(value, bool):
        return value
    if value in ("yes", "no"):
        return value == "yes"
    raise OgkError("OGK-PROJECT-006", f"{field} must be yes, no, true or false")


def _personal_data(value) -> bool | None:
    """The answer to the personal data question: true, false, or None when it was not asked."""
    return _yes_no(value, "personal_data")


DECISION_FIELDS = ("by", "on", "reason")
DATE = lazy_re.compile(r"\d{4}-\d{2}-\d{2}")


def _decision_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or not _single_line(value):
        raise OgkError("OGK-PROJECT-007", f"{field} must be a non-empty single line")
    return value.strip()


def decision_record(entry: dict, label: str) -> dict:
    """Who decided, on which day and why: each a single line, the day as YYYY-MM-DD."""
    record = {key: _decision_text(entry[key], f"{label} {key}") for key in DECISION_FIELDS}
    if not DATE.fullmatch(record["on"]):
        raise ValueError(f"{label} on must be a date written YYYY-MM-DD")
    return record


def declined_entries(value, catalog: Catalog) -> list:
    """Declined patterns: plain IDs (written before declines were recorded), or objects with who, when and why."""
    if not isinstance(value, list):
        raise ValueError("declined must be a list")
    entries, seen = [], set()
    for entry in value:
        if isinstance(entry, dict):
            if set(entry) != {"id", *DECISION_FIELDS}:
                raise ValueError('A declined entry is an ID or {"id", "by", "on", "reason"}')
            pattern_id = entry["id"]
        else:
            pattern_id = entry
        if not isinstance(pattern_id, str) or pattern_id not in catalog["patterns"]:
            raise OgkError("OGK-PROJECT-008", f"Unknown declined: {pattern_id}. Run openguildkit catalog.")
        if pattern_id in seen:
            continue
        seen.add(pattern_id)
        decided = isinstance(entry, dict)
        entries.append({"id": pattern_id, **decision_record(entry, f"declined {pattern_id}")} if decided else pattern_id)
    return entries


def declined_ids(profile: Profile) -> list[str]:
    return [entry["id"] if isinstance(entry, dict) else entry for entry in profile.get("declined", [])]


# A pack whose description starts with this is a draft that task retro --all --draft-rules wrote: no profile uses it
# until a person has reviewed it and rewritten its description.
DRAFT_MARK = "DRAFT written by openguildkit task retro"


def _declined_rules(value, required: list[str]) -> list[dict]:
    """Single rules a person set aside (profile decline rule PACK/RULE), each with who, when and why. A rule the
    catalog no longer has is kept: it sets nothing aside, and the person restores it with profile adopt rule."""
    if not isinstance(value, list):
        raise ValueError("declined_rules must be a list")
    entries, seen = [], set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"id", *DECISION_FIELDS}:
            raise OgkError("OGK-PROJECT-009", 'A declined_rules entry is {"id": "PACK/RULE", "by", "on", "reason"}')
        rule = entry["id"]
        pack_id, _, rule_id = rule.partition("/") if isinstance(rule, str) else ("", "", "")
        if not pack_id or not rule_id or "/" in rule_id:
            raise OgkError("OGK-PROJECT-010", f"A declined rule is named PACK/RULE, as openguildkit catalog lists it: {rule!r} is not")
        both = [item for item in required if item in (pack_id, rule)]
        if both:
            raise OgkError("OGK-PROJECT-011", f"Rule {rule} is both required and declined: remove {both[0]} from the required rules "
                             f"(openguildkit profile remove required-rule {both[0]}) or restore the rule "
                             f"(openguildkit profile adopt rule {rule}).")
        if rule not in seen:
            seen.add(rule)
            entries.append({"id": rule, **decision_record(entry, f"declined rule {rule}")})
    return entries


def declined_rule_ids(profile: Profile) -> list[str]:
    return [entry["id"] for entry in profile.get("declined_rules", [])]


def rules_in_force(pack: dict, profile: Profile) -> dict:
    """The pack as a task of this profile is asked it: without the rules the person declined. The same pack when
    none of its rules is declined, so that a project that declines none reads exactly the catalog."""
    declined = {rule.partition("/")[2] for rule in declined_rule_ids(profile) if rule.partition("/")[0] == pack["id"]}
    if not declined:
        return pack
    return {**pack, "rules": [rule for rule in pack["rules"] if rule["id"] not in declined]}


def _approval_roles(value, catalog: Catalog) -> dict[str, list[str]]:
    """approval.roles: each board, by ID, with the people of its role (roles.py)."""
    if not isinstance(value, dict) or not value:
        raise ValueError("approval.roles must map a board to the people of its role")
    unknown = sorted(set(value) - catalog["boards"].keys())
    if unknown:
        raise OgkError("OGK-PROJECT-012", f"Unknown board in approval.roles: {', '.join(unknown)}. Run openguildkit catalog.")
    roles = {board: _texts(names, f"approval.roles.{board}") for board, names in sorted(value.items())}
    if not all(roles.values()):
        raise ValueError("Each role of approval.roles needs at least one person")
    return roles


def _changes(value) -> list[dict]:
    """The history of profile commands: who changed what, on which day and why."""
    if not isinstance(value, list):
        raise ValueError("changes must be a list")
    result = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"change", *DECISION_FIELDS}:
            raise ValueError('Each change needs change, by, on and reason')
        result.append({"change": _decision_text(entry["change"], "change"), **decision_record(entry, "change")})
    return result


def recommendation_inputs(answers: Mapping[str, Any], catalog: Catalog) -> dict:
    """Everything that preselects patterns besides the stack: personal data, decisions about people and
    declined patterns."""
    return {
        "personal_data": _personal_data(answers.get("personal_data")),
        "people_decisions": _yes_no(answers.get("people_decisions"), "people_decisions"),
        "declined": [entry["id"] if isinstance(entry, dict) else entry
                     for entry in declined_entries(answers.get("declined", []), catalog)],
    }


def profile_recommendations(answers: Mapping[str, Any], catalog: Catalog) -> dict:
    """Preselected and suggested patterns for setup answers or a saved profile, and the packs they bring."""
    sector, stack, roles, components = project_context(answers, catalog)
    inputs = recommendation_inputs(answers, catalog)
    result = recommend_patterns(catalog, stack, sector, roles, components, **inputs)
    result["declined"] = declined_entries(answers.get("declined", []), catalog)
    base_packs = ["agent-workflow", *_recommended_packs(stack, catalog)]
    for entry in [*result["matched"], *result["suggested"]]:
        entry["rules"] = pattern_rules(entry, catalog)
    result["recommended_packs"] = list(
        dict.fromkeys([*base_packs, *(pack for pattern in result["matched"] for pack in pattern["packs"])])
    )
    result["rule_count"] = sum(pack_rule_counts(result["recommended_packs"], catalog).values())
    return result


# One meaning for the rule count of a pattern, in recommend, preview and init.
RULES_NOTE = ("Each pattern's count is the rules of its own packs and their dependencies, even when another "
              "pattern or the baseline brings the same pack.")


def pattern_rules(pattern: dict, catalog: Catalog) -> int:
    """The rules of a pattern's packs and their dependencies: the same number wherever it is shown."""
    return sum(pack_rule_counts(pattern["packs"], catalog).values())


def pack_rule_counts(pack_ids: list[str], catalog: Catalog) -> dict[str, int]:
    """The rules of these packs and of their dependencies, each pack counted once."""
    counts: dict[str, int] = {}

    def add(pack_id: str) -> None:
        if pack_id in counts:
            return
        counts[pack_id] = 0
        for dependency in catalog["packs"][pack_id].get("depends_on", []):
            add(dependency)
        counts[pack_id] = len(catalog["packs"][pack_id]["rules"])

    for pack_id in pack_ids:
        add(pack_id)
    return counts


def pattern_entries(value, catalog: Catalog, components: list[dict]) -> list:
    """Validate selected patterns: plain IDs, or objects limiting a pattern to components."""
    if not isinstance(value, list):
        raise OgkError("OGK-PROJECT-013", "patterns must be a list")
    known_components = {component["id"] for component in components}
    entries, seen = [], set()
    for entry in value:
        if isinstance(entry, dict):
            if set(entry) != {"id", "components"}:
                raise ValueError("A scoped pattern needs exactly id and components")
            scope = _texts(entry["components"], "pattern components")
            unknown = sorted(set(scope) - known_components)
            if unknown:
                raise OgkError("OGK-PROJECT-014", f"Pattern {entry['id']} names unknown components: {', '.join(unknown)}")
            pattern_id = entry["id"]
        else:
            pattern_id, scope = entry, None
        if not isinstance(pattern_id, str) or pattern_id not in catalog["patterns"]:
            raise ValueError(f"Unknown patterns: {pattern_id}. Run openguildkit catalog.")
        if pattern_id in seen:
            continue
        seen.add(pattern_id)
        entries.append({"id": pattern_id, "components": scope} if scope else pattern_id)
    return entries


def _resolutions(value, catalog: Catalog) -> list[dict]:
    """Validate the team's choices between conflicting packs."""
    if not isinstance(value, list):
        raise ValueError("resolutions must be a list")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"packs", "keep", "reason"}:
            raise ValueError("Each resolution needs packs, keep and reason")
        packs = catalog_ids(item["packs"], "resolution packs", catalog["packs"])
        keep = catalog_ids(item["keep"], "resolution keep", catalog["packs"])
        if len(packs) < 2:
            raise ValueError("A resolution names at least two conflicting packs")
        if not keep or not set(keep) <= set(packs):
            raise OgkError("OGK-PROJECT-015", "keep must list one or more of the resolution's packs")
        reason = item["reason"]
        if not isinstance(reason, str) or not reason.strip() or not _single_line(reason):
            raise ValueError("A resolution needs a single-line reason")
        key = tuple(sorted(packs))
        if key in seen:
            raise ValueError(f"Duplicate resolution for {', '.join(key)}")
        seen.add(key)
        result.append({"packs": sorted(packs), "keep": sorted(keep), "reason": reason.strip()})
    return result


def pattern_ids(profile: Profile) -> list[str]:
    return [pattern_selection(entry)[0] for entry in profile.get("patterns", [])]


def restricted_paths(profile: Mapping[str, Any]) -> list[str]:
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
            raise OgkError("OGK-PROJECT-016", shape)
        paths += [item.strip() for item in listed]
    return list(dict.fromkeys(paths))


def validate_profile(answers: Mapping[str, Any], catalog: Catalog) -> Profile:
    """The profile the answers describe, each field checked, in the order project.json writes them; ValueError names
    the first field that is wrong."""
    fields = {
        "schema_version", "name", "sector", "stack", "components", "roles", "patterns", "packs",
        "resolutions", "boards", "required_boards", "required_rules", "research", "host", "guard", "waivers", "approval", "tools",
        "conventions", "checks", "personal_data", "people_decisions", "declined", "changes", "ask_every_rule",
        "light_paths", "declined_rules", "separate_requester", "frozen", "restricted_paths",
    }
    unknown = sorted(answers.keys() - fields)
    if unknown:
        raise ValueError(f"Unknown profile fields: {', '.join(unknown)}")
    version = answers.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise OgkError("OGK-PROJECT-017", f"Unsupported project schema version: {version}")
    name = answers.get("name")
    if not isinstance(name, str) or not name.strip() or not _single_line(name):
        raise ValueError("name must be a non-empty single line")
    sector, stack, roles, components = project_context(answers, catalog)
    research = answers.get("research", "local-only")
    if research not in ("local-only", "public-sources"):
        raise OgkError("OGK-PROJECT-018", "research must be local-only or public-sources")
    inputs = recommendation_inputs(answers, catalog)
    patterns, declined = _chosen_patterns(answers, catalog, (sector, stack, roles, components), inputs)
    packs = catalog_ids(answers.get("packs", default_packs(stack, components, patterns, catalog)), "packs", catalog["packs"])
    profile = cast(Profile, {  # The fields in the order project.json writes them, components when there are some.
        "schema_version": SCHEMA_VERSION,
        "name": name.strip(),
        "sector": sector,
        "stack": stack,
        **({"components": components} if components else {}),
        "packs": list(dict.fromkeys(["agent-workflow", *packs])),
        "boards": catalog_ids(answers.get("boards", []), "boards", catalog["boards"]),
        "research": research,
        "conventions": _texts(answers.get("conventions", []), "conventions"),
        "checks": _texts(answers.get("checks", []), "checks"),
    })
    if roles:
        profile["roles"] = roles
    if inputs["personal_data"] is not None:
        profile["personal_data"] = inputs["personal_data"]
    if inputs["people_decisions"] is not None:
        profile["people_decisions"] = inputs["people_decisions"]
    if patterns:
        profile["patterns"] = patterns
    if declined:
        profile["declined"] = declined
    _add_agent_settings(profile, answers)
    _add_rule_choices(profile, answers, catalog)
    _add_approval(profile, answers, catalog)
    _add_options(profile, answers, catalog)
    return profile


def _chosen_patterns(answers: Mapping[str, Any], catalog: Catalog, context: tuple, inputs: dict) -> tuple[list, list]:
    """The patterns of the profile, the recommended ones when it names neither patterns nor packs, and its declines."""
    sector, stack, roles, components = context
    patterns = pattern_entries(answers.get("patterns", []), catalog, components)
    if "patterns" not in answers and "packs" not in answers:
        patterns = [
            {"id": record["id"], "components": record["components"]} if record.get("components") else record["id"]
            for record in recommend_patterns(catalog, stack, sector, roles, components, **inputs)["matched"]
        ]
    declined = declined_entries(answers.get("declined", []), catalog)
    both = sorted(set(inputs["declined"]) & {pattern_selection(entry)[0] for entry in patterns})
    if both:
        raise OgkError("OGK-PROJECT-019", f"Pattern {', '.join(both)} is both selected and declined: remove it from one of the lists.")
    check_pattern_choices([pattern_selection(entry)[0] for entry in patterns], catalog["patterns"])
    return patterns, declined


def _add_agent_settings(profile: Profile, answers: Mapping[str, Any]) -> None:
    """The host, the tools and the guard mode."""
    host = answers.get("host")
    if host is not None:
        from .hosts import HOSTS
        if host not in HOSTS:
            raise OgkError("OGK-PROJECT-020", f"host must be one of {', '.join(HOSTS)}")
        profile["host"] = host
    tools = _texts(answers.get("tools", []), "tools")
    if tools:
        profile["tools"] = tools
    guard = answers.get("guard")
    if guard is not None:
        if guard not in ("off", "observe", "enforce"):
            raise OgkError("OGK-PROJECT-021", "guard must be off, observe or enforce")
        profile["guard"] = guard


def _add_rule_choices(profile: Profile, answers: Mapping[str, Any], catalog: Catalog) -> None:
    """The required and declined rules, then the check that no selected pack is a draft of task retro."""
    required_rules = _texts(answers.get("required_rules", []), "required_rules")
    for item in required_rules:
        pack_id, _, rule_id = item.partition("/")
        pack = catalog["packs"].get(pack_id)
        if pack is None or (rule_id and rule_id not in {rule["id"] for rule in pack["rules"]}):
            raise OgkError("OGK-PROJECT-022", f"Unknown required rule {item}: use PACK or PACK/RULE from openguildkit catalog")
    if required_rules:
        profile["required_rules"] = required_rules
    declined_rules = _declined_rules(answers.get("declined_rules", []), required_rules)
    if declined_rules:
        profile["declined_rules"] = declined_rules
    drafts = [pack_id for pack_id in selected_packs(profile, catalog)
              if str(catalog["packs"][pack_id].get("description", "")).startswith(DRAFT_MARK)]
    if drafts:
        raise OgkError("OGK-PROJECT-023", f"Pack {drafts[0]} is a draft written by task retro: review each rule, replace each TODO and "
                         "rewrite its description before a profile uses it.")


def _add_approval(profile: Profile, answers: Mapping[str, Any], catalog: Catalog) -> None:
    """The approval: local or signed, with its options max_age_days and roles."""
    approval = answers.get("approval")
    if approval is None:
        return
    if not isinstance(approval, dict) or approval.get("mode") not in ("local", "signed"):
        raise ValueError("approval.mode must be local or signed")
    # max_age_days (incident.py) and roles (roles.py) are options that go with either mode.
    setting = {key: value for key, value in approval.items() if key not in ("max_age_days", "roles")}
    if setting["mode"] == "signed":
        if set(setting) != {"mode", "allowed_signers", "approvers"}:
            raise ValueError("A signed approval needs allowed_signers (a project path) and approvers")
        path = setting["allowed_signers"]
        if not isinstance(path, str) or not path.strip() or path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/"):
            raise ValueError("approval.allowed_signers must be a path inside the project")
        profile["approval"] = {"mode": "signed", "allowed_signers": path.strip(),
                               "approvers": _texts(setting["approvers"], "approval.approvers")}
    elif set(setting) != {"mode"}:
        raise ValueError("A local approval takes no other setting")
    if "max_age_days" in approval:
        days = approval["max_age_days"]
        if type(days) is not int or not 1 <= days <= 366:
            raise ValueError("approval.max_age_days must be a whole number of days between 1 and 366")
        profile["approval"] = {**profile.get("approval", {"mode": "local"}), "max_age_days": days}
    if "roles" in approval:
        profile["approval"] = {**profile.get("approval", {"mode": "local"}),
                               "roles": _approval_roles(approval["roles"], catalog)}


def _add_options(profile: Profile, answers: Mapping[str, Any], catalog: Catalog) -> None:
    """The waivers and the options a person turns on: short lane, separate requester, freeze, restricted paths,
    a question per rule, required boards, conflict resolutions and the recorded changes."""
    waivers = answers.get("waivers")
    if waivers is not None:
        if not isinstance(waivers, dict) or set(waivers) != {"allowed_by", "max_days"}:
            raise ValueError("waivers needs allowed_by (names) and max_days")
        max_days = waivers["max_days"]
        if type(max_days) is not int or not 1 <= max_days <= 366:
            raise ValueError("waivers.max_days must be a whole number of days between 1 and 366")
        profile["waivers"] = {"allowed_by": _texts(waivers["allowed_by"], "waivers.allowed_by"), "max_days": max_days}
    # The short lane (short_lane.py): absent, or an empty list, means it is off.
    if answers.get("light_paths"):
        profile["light_paths"] = short_lane.normalize_entries(answers["light_paths"], "light_paths")
    # The requester and the approver (requester.py, RFC #445): absent means off; only true is written.
    if "separate_requester" in answers:
        if answers["separate_requester"] is not True:
            raise OgkError("OGK-PROJECT-024", "separate_requester must be true, or absent when the option is off")
        profile["separate_requester"] = True
    # A freeze (incident.py): who, when and why; absent means the project is not frozen.
    if "frozen" in answers:
        if not isinstance(answers["frozen"], dict) or set(answers["frozen"]) != set(DECISION_FIELDS):
            raise ValueError("frozen must name by, on and reason")
        profile["frozen"] = decision_record(answers["frozen"], "frozen")
    # Folders closed to the agent: the edit hook refuses them, host apply writes them into the host settings.
    if answers.get("restricted_paths"):
        restricted_paths(answers)
        profile["restricted_paths"] = answers["restricted_paths"]
    ask_every_rule = answers.get("ask_every_rule", False)
    if type(ask_every_rule) is not bool:
        raise OgkError("OGK-PROJECT-025", "ask_every_rule must be true or false")
    if ask_every_rule:
        profile["ask_every_rule"] = True
    required = catalog_ids(answers.get("required_boards", []), "required_boards", catalog["boards"])
    if required:
        profile["required_boards"] = required
    resolutions = _resolutions(answers.get("resolutions", []), catalog)
    if resolutions:
        profile["resolutions"] = resolutions
    changes = _changes(answers.get("changes", []))
    if changes:
        profile["changes"] = changes


def load_profile(state: Path, catalog: Catalog) -> Profile:
    path = state / "project.json"
    if not path.is_file():
        # Run from the wrong folder, a bare "run init" would start a second project there.
        raise OgkError("OGK-PROJECT-026", f"No OpenGuildKit project found for {state.parent.as_posix()}: {STATE_DIR}/project.json "
                         "does not exist. cd into the project folder or pass --project PATH; run openguildkit init "
                         "only to set up a new project here.")
    answers = read_json(path)
    sector = answers.get("sector", "general")
    if isinstance(sector, str) and sector not in catalog["sectors"]:
        raise OgkError("OGK-PROJECT-027",
            f".openguildkit/project.json names the sector {sector!r}, which neither this release nor the catalog "
            "lock provides: choose one listed by openguildkit catalog, set it in .openguildkit/project.json, "
            "then run openguildkit sync."
        )
    missing = _missing_records(answers, catalog)
    if missing:
        entries = ", ".join(f'"{record_id}" from "{field}"' for field, record_id in missing)
        raise OgkError("OGK-PROJECT-028",
            f".openguildkit/project.json uses records that neither this release nor the catalog lock provides: "
            f"remove {entries}, then run openguildkit sync."
        )
    return validate_profile(answers, catalog)


def _missing_records(answers: dict, catalog: Catalog) -> list[tuple[str, str]]:
    """Profile entries that name a pack, pattern or board no catalog in force provides."""
    fields = (
        ("packs", "packs"), ("patterns", "patterns"), ("declined", "patterns"), ("boards", "boards"),
        ("required_boards", "boards"),
    )
    missing = []
    for field, collection in fields:
        entries = answers.get(field)
        for entry in entries if isinstance(entries, list) else []:
            record_id = entry.get("id") if isinstance(entry, dict) else entry
            if isinstance(record_id, str) and record_id not in catalog[collection]:
                missing.append((field, record_id))
    return missing


def selected_packs(profile: Profile, catalog: Catalog) -> list[str]:
    """Packs from the profile and its patterns, each after its dependencies, before any resolution."""
    ordered = {}

    def add_pack(pack_id):
        if pack_id not in ordered:
            for dependency in catalog["packs"][pack_id].get("depends_on", []):
                add_pack(dependency)
            ordered[pack_id] = None

    pattern_packs = [
        pack_id
        for pattern_id in pattern_ids(profile)
        for pack_id in catalog["patterns"][pattern_id]["packs"]
    ]
    for pack_id in [*profile["packs"], *pattern_packs]:
        add_pack(pack_id)
    return list(ordered)
