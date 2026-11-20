"""Match project context to versioned rule packs."""

import re
import unicodedata
from collections import Counter

ROLE_TITLES = {
    "data": "Data and analytics",
    "design": "Design / UX",
    "devops": "DevOps and platform",
    "engineering": "Software development / Développement",
    "finance": "Finance",
    "hr": "Human resources / RH",
    "leadership": "Leadership / Direction générale / CEO",
    "marketing": "Marketing",
    "operations": "Operations / Opérations",
    "performance": "Performance",
    "product": "Product management / Produit",
    "project-management": "Project management / Gestion de projet",
    "qa": "Quality assurance / QA",
    "sales": "Sales / Commerce",
    "security": "Cybersecurity / Cybersécurité",
}

_VERSION_SUFFIX = re.compile(r"(?:@|\s+)v?(\d+(?:\.\d+)*)(?:[-+][\w.-]+)?$", flags=re.IGNORECASE)
VERSION_PATTERN = re.compile(r"\d+(?:\.\d+){0,3}")


def role_choices(patterns: dict) -> dict[str, dict]:
    roles = {role_id for pattern in patterns.values() for role_id in pattern["roles"]}
    return {
        role_id: {"id": role_id, "title": ROLE_TITLES.get(role_id, role_id.replace("-", " ").capitalize())}
        for role_id in sorted(roles)
    }


def technology_key(text: str) -> str:
    name = _VERSION_SUFFIX.sub("", text.strip())
    normalized = unicodedata.normalize("NFKD", name.casefold())
    return "".join(character for character in normalized if character.isalnum() or character in "+#")


_technology_key = technology_key


def technology_version(text: str) -> str | None:
    """Return the version written after a technology name, as in "Next.js 14.2" or "Postgres@16"."""
    match = _VERSION_SUFFIX.search(text.strip())
    return match.group(1) if match else None


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = [int(part) for part in version.split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def version_at_least(version: str, minimum: str) -> bool:
    return _version_tuple(version) >= _version_tuple(minimum)


def stack_contexts(stack: list[str], components: list[dict] | None) -> list[dict]:
    """Patterns match inside one component. Without components the project is one context."""
    if components:
        return [{"id": component["id"], "path": component.get("path"), "stack": component["stack"]} for component in components]
    return [{"id": None, "path": None, "stack": stack}]


def _match_context(pattern: dict, technologies: list[str]) -> dict | None:
    """Return the technologies that satisfy each group, the versions to confirm and any version conflict."""
    active = {}
    for technology in technologies:
        active.setdefault(technology_key(technology), technology)
    matched_stack = []
    for group in pattern["match"]["stack"]:
        technology = next((active[key] for alias in group if (key := technology_key(alias)) in active), None)
        if technology is None:
            return None
        matched_stack.append(technology)
    unknown, conflicts = [], []
    for alias, minimum in pattern["match"].get("min_versions", {}).items():
        technology = active.get(technology_key(alias))
        if technology is None:
            continue
        version = technology_version(technology)
        if version is None:
            unknown.append(f"{alias} >= {minimum}")
        elif not version_at_least(version, minimum):
            conflicts.append(f"{technology} is below {alias} {minimum}")
    return {"matched_stack": matched_stack, "version_unknown": unknown, "conflicts": conflicts}


def recommend_patterns(
    catalog: dict, stack: list[str], sector: str, roles: list[str], components: list[dict] | None = None
) -> dict:
    """Return matching technology patterns alongside methods the team can choose.

    With components, every technology group of a pattern must match inside the same
    component. A pattern whose minimum version is not met is listed in `excluded`.
    """
    contexts = stack_contexts(stack, components)
    applicable = []
    suggested = []
    excluded = []
    for pattern in catalog["patterns"].values():
        match = pattern.get("match")
        if match is None:
            relevant = [role for role in pattern["roles"] if role in roles]
            if relevant:
                suggested.append({**pattern, "matched_roles": relevant})
            continue
        if match.get("sectors") and sector not in match["sectors"]:
            continue
        scopes, matched_stack, unknown = [], [], []
        for context in contexts:
            result = _match_context(pattern, context["stack"])
            if result is None:
                continue
            if result["conflicts"]:
                excluded.append({"id": pattern["id"], "component": context["id"], "reasons": result["conflicts"]})
                continue
            scopes.append(context["id"])
            matched_stack.extend(item for item in result["matched_stack"] if item not in matched_stack)
            unknown.extend(item for item in result["version_unknown"] if item not in unknown)
        if not scopes:
            continue
        entry = {**pattern, "matched_stack": matched_stack}
        if components:
            entry["components"] = scopes
        if unknown:
            entry["version_unknown"] = unknown
        applicable.append(entry)

    exclusive = Counter(pattern["exclusive_group"] for pattern in applicable if "exclusive_group" in pattern)
    matched = []
    for pattern in applicable:
        if exclusive[pattern.get("exclusive_group")] > 1:
            suggested.append({**pattern, "choice_required": True})
        else:
            matched.append(pattern)
    return {"matched": matched, "suggested": suggested, "excluded": excluded}


def pattern_selection(entry: str | dict) -> tuple[str, list[str] | None]:
    """A selected pattern is an ID, or an object that limits it to some components."""
    if isinstance(entry, dict):
        return entry["id"], entry.get("components")
    return entry, None


def patterns_to_review(profile: dict, catalog: dict) -> list[dict]:
    """List selected stack patterns that the current stack, components or versions no longer support."""
    plan = recommend_patterns(
        catalog, profile.get("stack", []), profile["sector"], profile.get("roles", []), profile.get("components")
    )
    matched = {pattern["id"]: pattern for pattern in plan["matched"] + plan["suggested"] if "match" in pattern}
    excluded = {}
    for item in plan["excluded"]:
        excluded.setdefault(item["id"], []).extend(item["reasons"])
    review = []
    for entry in profile.get("patterns", []):
        pattern_id, scope = pattern_selection(entry)
        pattern = catalog["patterns"].get(pattern_id)
        if pattern is None or "match" not in pattern:
            continue
        current = matched.get(pattern_id)
        if current is None:
            reasons = excluded.get(pattern_id) or ["The declared stack no longer matches this pattern."]
            review.append({"id": pattern_id, "reasons": reasons})
            continue
        missing = sorted(set(scope or []) - set(current.get("components") or []))
        if missing:
            review.append({"id": pattern_id, "reasons": [f"No longer matches component {', '.join(missing)}."]})
    return review


def check_pattern_choices(pattern_ids: list[str], patterns: dict) -> None:
    selected = {}
    for pattern_id in pattern_ids:
        group = patterns[pattern_id].get("exclusive_group")
        if group is None:
            continue
        if group in selected:
            raise ValueError(f"Choose one pattern in {group}: {selected[group]} or {pattern_id}.")
        selected[group] = pattern_id
