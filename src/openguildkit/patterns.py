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

_VERSION_SUFFIX = re.compile(r"(?:@|\s+)v?\d+(?:\.\d+)*(?:[-+][\w.-]+)?$", flags=re.IGNORECASE)


def role_choices(patterns: dict) -> dict[str, dict]:
    roles = {role_id for pattern in patterns.values() for role_id in pattern["roles"]}
    return {
        role_id: {"id": role_id, "title": ROLE_TITLES.get(role_id, role_id.replace("-", " ").capitalize())}
        for role_id in sorted(roles)
    }


def _technology_key(text: str) -> str:
    name = _VERSION_SUFFIX.sub("", text.strip())
    normalized = unicodedata.normalize("NFKD", name.casefold())
    return "".join(character for character in normalized if character.isalnum() or character in "+#")


def recommend_patterns(catalog: dict, stack: list[str], sector: str, roles: list[str]) -> dict:
    """Return matching technology patterns alongside methods the team can choose."""
    active_technologies = {_technology_key(technology): technology for technology in stack}
    applicable = []
    suggested = []
    for pattern in catalog["patterns"].values():
        match = pattern.get("match")
        if match is None:
            relevant = [role for role in pattern["roles"] if role in roles]
            if relevant:
                suggested.append({**pattern, "matched_roles": relevant})
            continue
        if match.get("sectors") and sector not in match["sectors"]:
            continue
        matched_stack = []
        for group in match["stack"]:
            technology = next(
                (active_technologies[key] for alias in group if (key := _technology_key(alias)) in active_technologies),
                None,
            )
            if technology is None:
                break
            matched_stack.append(technology)
        else:
            applicable.append({**pattern, "matched_stack": matched_stack})

    exclusive = Counter(pattern["exclusive_group"] for pattern in applicable if "exclusive_group" in pattern)
    matched = []
    for pattern in applicable:
        if exclusive[pattern.get("exclusive_group")] > 1:
            suggested.append({**pattern, "choice_required": True})
        else:
            matched.append(pattern)
    return {"matched": matched, "suggested": suggested}


def check_pattern_choices(pattern_ids: list[str], patterns: dict) -> None:
    selected = {}
    for pattern_id in pattern_ids:
        group = patterns[pattern_id].get("exclusive_group")
        if group is None:
            continue
        if group in selected:
            raise ValueError(f"Choose one pattern in {group}: {selected[group]} or {pattern_id}.")
        selected[group] = pattern_id
