"""The rule plan of a profile: packs and their conflicts, scopes, provenance and the profile fingerprint."""

import hashlib
import json
from pathlib import PurePosixPath

from . import lazy_re
from .catalog import rule_check
from .patterns import condition_reasons, core_roles, is_stack_pattern, pattern_selection
from .project import (
    declined_ids,
    declined_rule_ids,
    pack_rule_counts,
    pattern_ids,
    pattern_rules,
    rules_in_force,
    selected_packs,
)


def rule_conflicts(profile: dict, catalog: dict) -> list[dict]:
    """Declared incompatibilities between selected packs that apply to a common scope."""
    selected = selected_packs(profile, catalog)
    scopes = pack_scopes(profile, catalog)
    # A declaration on either pack is enough: conflicts are symmetric.
    declared = {
        tuple(sorted((pack_id, other)))
        for pack_id in selected
        for other in catalog["packs"][pack_id].get("conflicts_with", [])
        if other in selected
    }
    # A choice the team recorded stays in force when the catalog stops declaring the conflict.
    recorded = {
        tuple(sorted((first, second)))
        for item in profile.get("resolutions", [])
        for first in item["packs"]
        for second in item["packs"]
        if first != second and {first, second} <= set(selected)
    }
    pairs = sorted(declared | recorded)
    conflicts = []
    for first, second in pairs:
        left, right = scopes.get(first), scopes.get(second)
        if left is None or right is None:
            shared = right if left is None else left
        else:
            shared = sorted(set(left) & set(right))
            if not shared:
                continue
        resolution = next(
            (item for item in profile.get("resolutions", []) if {first, second} <= set(item["packs"])), None
        )
        conflicts.append({"packs": [first, second], "scope": shared, "resolution": resolution})
    return conflicts


def _excluded_packs(profile: dict, catalog: dict) -> set[str]:
    excluded = set()
    for conflict in rule_conflicts(profile, catalog):
        resolution = conflict["resolution"]
        if resolution:
            excluded |= set(conflict["packs"]) - set(resolution["keep"])
    return excluded


def resolved_profile(profile: dict, catalog: dict) -> dict:
    excluded = _excluded_packs(profile, catalog) if profile.get("resolutions") else set()
    packs = [pack_id for pack_id in selected_packs(profile, catalog) if pack_id not in excluded]
    return {**profile, "packs": packs, "boards": profile["boards"] or sorted(catalog["boards"])}


def pack_provenance(profile: dict, catalog: dict) -> dict[str, list[str]]:
    """Explain why each pack is active: required, selected, from a pattern or as a dependency."""
    reasons: dict[str, list[str]] = {}

    def add(pack_id: str, reason: str) -> None:
        known = reasons.setdefault(pack_id, [])
        if reason in known:
            return
        known.append(reason)
        for dependency in catalog["packs"][pack_id].get("depends_on", []):
            add(dependency, f"dependency of {pack_id}")

    for pack_id in profile["packs"]:
        add(pack_id, "required by OpenGuildKit" if pack_id == "agent-workflow" else "selected")
    for pattern_id in pattern_ids(profile):
        origin = pattern_origin(catalog["patterns"][pattern_id], profile)
        for pack_id in catalog["patterns"][pattern_id]["packs"]:
            add(pack_id, f"pattern {pattern_id}" + (f" ({origin})" if origin else ""))
    return reasons


def pattern_origin(pattern: dict, profile: dict) -> str:
    """Why a selected pattern without a stack concerns the project: its sector, personal data or roles."""
    if is_stack_pattern(pattern):
        return ""
    reasons = condition_reasons(
        pattern, profile["sector"], profile.get("personal_data"), profile.get("people_decisions"))
    roles = [role for role in pattern["roles"] if role in profile.get("roles", [])]
    if roles:
        reasons.append(f"role {', '.join(roles)}")
    return "; ".join(reasons)


# Above this many rules, the preview warns. A rule is read by the agent and answered by every task it
# concerns, so the count is what a profile brings, whatever a given task is asked. The default selection
# of each of the thirty field-test teams, recomputed with the core methods of its roles and every norm it
# meets accepted, stays at or under 74 rules (a payments API with DORA, GDPR and PCI DSS: 62; a seven-role
# monorepo: 74), and the field called 77 rules and more too heavy: 80 flags what optional methods add on
# top of a regulated project's own baseline.
RULE_WARNING = 80


def _pattern_reason(pattern: dict, profile: dict) -> str:
    """Why a selected pattern applies, in one line: its stack, sector, personal data, core role, or a decision."""
    adopted = [change for change in profile.get("changes", []) if change["change"] == f"adopt {pattern['id']}"]
    if adopted:
        last = adopted[-1]
        return f"adopted by {last['by']} on {last['on']}: {last['reason']}"
    if is_stack_pattern(pattern):
        return "stack " + ", ".join(" / ".join(group) for group in pattern["match"]["stack"])
    conditions = condition_reasons(pattern, profile["sector"], profile.get("personal_data"),
                                   profile.get("people_decisions"))
    if conditions:
        return "; ".join(conditions)
    core = core_roles(pattern, profile.get("roles", []))
    return f"role {', '.join(core)} (core method)" if core else "chosen by the team"


def regulation_demands(pattern: dict, catalog: dict) -> str:
    """One sentence saying what a regulation asks of each task: rules to answer, evidence to supply, checks run."""
    packs = pack_rule_counts(pattern["packs"], catalog)
    rules = [rule for pack_id in packs for rule in catalog["packs"][pack_id]["rules"]]
    evidence = [item["title"] for rule in rules for item in rule.get("evidence", [])]
    machine = sum(1 for rule in rules if rule_check(rule) is not None)
    text = f"{len(rules)} rules, asked of a task whose data or concerns it touches"
    if evidence:
        text += f"; such a task supplies or declares not applicable: {'; '.join(evidence)}"
    if machine:
        text += f"; task verify runs {machine} automatic check{'s' if machine > 1 else ''}"
    return text + "."


def rule_plan(profile: dict, catalog: dict) -> dict:
    """Everything init or sync would write, with the origin and scope of each pack, the patterns with their
    reason and rule count, what each regulation asks of a task, and the recorded profile decisions."""
    resolved = resolved_profile(profile, catalog)
    scopes = pack_scopes(profile, catalog)
    provenance = pack_provenance(profile, catalog)
    selected = selected_packs(profile, catalog)
    patterns = [catalog["patterns"][pattern_id] for pattern_id in pattern_ids(profile)]
    count = sum(len(rules_in_force(catalog["packs"][pack_id], profile)["rules"]) for pack_id in resolved["packs"])
    plan = {
        "rule_count": count,
        "rule_warning": (
            f"{count} rules in force. A task is asked only the rules that concern it, but each pattern adds rules "
            f"to read and to answer: above {RULE_WARNING}, check that each pattern below concerns the project and "
            "decline the others (openguildkit profile decline PATTERN --by INITIALS --reason WHY)."
            if count > RULE_WARNING else None
        ),
        "patterns": [
            {"id": pattern["id"], "title": pattern["title"], "reason": _pattern_reason(pattern, profile),
             "rules": pattern_rules(pattern, catalog)}
            for pattern in patterns
        ],
        "regulations": [
            {"id": pattern["id"], "title": pattern["title"], "asks": regulation_demands(pattern, catalog)}
            for pattern in patterns if pattern.get("kind") == "regulation"
        ],
        "declined": [entry if isinstance(entry, dict) else {"id": entry} for entry in profile.get("declined", [])],
        "changes": profile.get("changes", []),
        "packs": [
            {
                "id": pack_id,
                "title": catalog["packs"][pack_id]["title"],
                "version": catalog["packs"][pack_id]["version"],
                "provenance": provenance.get(pack_id, []),
                "scope": scopes.get(pack_id),
                "rules": [rule["id"] for rule in rules_in_force(catalog["packs"][pack_id], profile)["rules"]],
            }
            for pack_id in resolved["packs"]
        ],
        "excluded": [pack_id for pack_id in selected if pack_id not in resolved["packs"]],
        "conflicts": rule_conflicts(profile, catalog),
        "conventions": profile.get("conventions", []),
        "checks": profile.get("checks", []),
    }
    if profile.get("declined_rules"):
        plan["declined_rules"] = profile["declined_rules"]
    return plan


def require_resolved_conflicts(profile: dict, catalog: dict) -> None:
    open_conflicts = [conflict for conflict in rule_conflicts(profile, catalog) if conflict["resolution"] is None]
    if open_conflicts:
        names = "; ".join(" and ".join(conflict["packs"]) for conflict in open_conflicts)
        # During init the profile is still the answers file: .openguildkit/project.json does not exist yet.
        raise ValueError(
            f"Conflicting rule packs: {names}. Keep only one of them, or record which apply in \"resolutions\" of "
            "the profile (the file passed to init --answers, or .openguildkit/project.json once the project is set "
            'up), for example {"packs": ["first", "second"], "keep": ["second"], "reason": "Why"}. '
            "Run openguildkit preview --answers FILE to check it."
        )


def pack_scopes(profile: dict, catalog: dict) -> dict[str, list[str] | None]:
    """Map each resolved pack to the components it applies to, or None for the whole project."""
    scopes: dict[str, set[str] | None] = {}

    def apply(pack_id: str, scope: set[str] | None) -> None:
        current = scopes.get(pack_id, set())
        merged = None if current is None or scope is None else current | scope
        if pack_id in scopes and merged == current:
            return
        scopes[pack_id] = merged
        for dependency in catalog["packs"][pack_id].get("depends_on", []):
            apply(dependency, merged)

    for pack_id in profile["packs"]:
        apply(pack_id, None)
    for entry in profile.get("patterns", []):
        pattern_id, components = pattern_selection(entry)
        for pack_id in catalog["patterns"][pattern_id]["packs"]:
            apply(pack_id, set(components) if components else None)
    return {pack_id: (sorted(scope) if scope is not None else None) for pack_id, scope in scopes.items()}


def _without_dates(record: dict) -> dict:
    """The record without its sources' checked dates: a page read again does not change the advice."""
    sources = [{key: value for key, value in source.items() if key != "checked"} for source in record.get("sources", [])]
    return {**record, "sources": sources} if "sources" in record else record


def task_scope_profile(profile: dict, catalog: dict, component_ids: list[str]) -> dict:
    """Resolve the project rules for all components or the ones named in the task answers."""
    resolved = resolved_profile(profile, catalog)
    if not component_ids:
        return resolved
    selected = set(component_ids)
    components = [component for component in resolved.get("components", []) if component["id"] in selected]
    available = {component["id"] for component in resolved.get("components", [])}
    if unknown := selected - available:
        raise ValueError(f"Unknown task components: {', '.join(sorted(unknown))}. "
                         f"Use project component IDs: {', '.join(sorted(available)) or 'none'}.")
    scopes = pack_scopes(profile, catalog)
    resolved["packs"] = [
        pack for pack in resolved["packs"] if scopes.get(pack) is None or selected.intersection(scopes[pack])
    ]
    patterns = []
    for entry in resolved.get("patterns", []):
        pattern, scope = pattern_selection(entry)
        if not scope:
            patterns.append(entry)
        elif scoped := [name for name in scope if name in selected]:
            patterns.append({"id": pattern, "components": scoped})
    resolved["checks"] = [command for command in resolved.get("checks", [])
                          if check_component(command, resolved.get("components", [])) in (None, *selected)]
    resolved["components"] = components
    resolved["stack"] = list(dict.fromkeys(technology for component in components for technology in component["stack"]))
    resolved["patterns"] = patterns
    return resolved


_CHECK_FOLDER = lazy_re.compile(r"""\s*cd\s+("[^"]+"|'[^']+'|[^\s;&|]+)\s*&&""")


def check_component(command: str, components: list[dict]) -> str | None:
    """The component a check command runs in, from its leading `cd FOLDER &&` as init proposes it, or None when it
    runs for the whole project. A folder inside a component belongs to it; the deepest component wins."""
    match = _CHECK_FOLDER.match(command)
    if not match:
        return None
    folder = PurePosixPath(match.group(1).strip("\"'").replace("\\", "/")).as_posix().strip("/")
    owners = [(len(path), component["id"]) for component in components
              for path in [PurePosixPath((component.get("path") or "").strip()).as_posix().strip("/")]
              if path not in ("", ".") and (folder == path or folder.startswith(path + "/"))]
    return max(owners)[1] if owners else None


# Profile fields that change neither the rules, nor the checks, nor the boards of a task: changing one leaves every
# approval standing. A convention or a tool reaches the next consultations; the guard, host, research, approval,
# waiver, short lane and requester settings are read when they act (the signature, for one, is verified again by every reader of
# an approval, and the lane's paths by the edit hook, task complete and guard --ci).
APPROVAL_NEUTRAL_FIELDS = ("name", "conventions", "tools", "host", "guard", "research", "approval", "waivers",
                           "light_paths", "separate_requester", "frozen", "restricted_paths")


def _advice_profile(profile: dict, neutral: tuple = ()) -> dict:
    """The profile without its decision history, and without the neutral fields given: who declined or changed
    what does not change the advice."""
    advice = {key: value for key, value in profile.items() if key != "changes" and key not in neutral}
    if "declined" in advice:
        advice["declined"] = declined_ids(profile)
    if "declined_rules" in advice:
        advice["declined_rules"] = sorted(declined_rule_ids(profile))
    return advice


def profile_fingerprint(profile: dict, catalog: dict, *, legacy: bool = False) -> str:
    """The digest of what an approval rests on: the rules, the checks and the boards of the profile.

    legacy gives the digest of releases before 0.17, which covered every field; approvals recorded under it hold
    while the profile has not changed since (fingerprint_holds).
    """
    neutral = () if legacy else APPROVAL_NEUTRAL_FIELDS
    resolved = resolved_profile(_advice_profile(profile, neutral), catalog)
    snapshot = {
        "profile": resolved,
        "packs": [_without_dates(catalog["packs"][pack_id]) for pack_id in resolved["packs"]],
        "boards": [_without_dates(catalog["boards"][board_id]) for board_id in resolved["boards"]],
        "sector": _without_dates(catalog["sectors"][resolved["sector"]]),
    }
    if profile.get("patterns"):
        snapshot["patterns"] = [
            {key: value for key, value in _without_dates(catalog["patterns"][pattern_id]).items() if key != "core_for"}
            for pattern_id in pattern_ids(profile)
        ]
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Fingerprints:
    """The current fingerprint of a profile, and the earlier releases' one computed only when a record needs it."""

    def __init__(self, profile: dict, catalog: dict):
        self.profile, self.catalog = profile, catalog
        self.current = profile_fingerprint(profile, catalog)
        self._legacy = None

    def holds(self, recorded: str | None) -> bool:
        """Whether rules recorded under this fingerprint are still the rules, checks and boards of the profile."""
        if recorded == self.current:
            return True
        if self._legacy is None:
            self._legacy = profile_fingerprint(self.profile, self.catalog, legacy=True)
        return recorded == self._legacy


def fingerprint_holds(recorded: str | None, profile: dict, catalog: dict) -> bool:
    """Whether a fingerprint recorded with an approval still matches the rules, checks and boards of the profile."""
    return Fingerprints(profile, catalog).holds(recorded)


