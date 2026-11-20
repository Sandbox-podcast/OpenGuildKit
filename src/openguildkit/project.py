"""Collect a project profile and render its repository instructions."""

import hashlib
import json
import re
from pathlib import Path

from .patterns import (
    check_pattern_choices,
    pattern_selection,
    recommend_patterns,
    role_choices,
)
from .storage import read_json, write_json, write_text
from .workflow import AGENT_WORKFLOW

STATE_DIR = ".openguildkit"
SCHEMA_VERSION = 1
BEGIN = "<!-- BEGIN OPENGUILDKIT -->"
END = "<!-- END OPENGUILDKIT -->"
PROJECT_IGNORE = "tasks/\n.lock\n.*.tmp\n"


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


def _select(question_id, prompt, choices, default=None, multiple=False):
    question = {
        "id": question_id,
        "prompt": prompt,
        "type": "multi-select" if multiple else "select",
        "choices": [{"id": entry["id"], "label": entry["title"]} for entry in choices],
    }
    if default is not None:
        question["default"] = default
    return question


def init_questions(catalog: dict, project_name: str, detected: list[dict] | None = None) -> list[dict]:
    components = {
        "id": "components",
        "type": "components",
        "prompt": (
            "Which components does the repository contain? Confirm or correct each component's "
            "path and stack, with versions where you know them."
        ),
        "examples": [{"id": "web", "path": "apps/web", "stack": ["Next.js 14.2", "React 18.3", "TypeScript"]}],
    }
    if detected:
        components["default"] = detected
    return [
        {"id": "name", "type": "text", "prompt": "Project name", "default": project_name},
        _select("sector", "Which sector describes the project?", catalog["sectors"].values(), "general"),
        {
            "id": "stack",
            "type": "list",
            "prompt": "Which languages, frameworks and services are in the stack? Add a version where it matters.",
            "examples": ["Python 3.12", "FastAPI", "PostgreSQL 16"],
        },
        components,
        _select(
            "roles",
            "Which roles should this project support?",
            role_choices(catalog["patterns"]).values(),
            multiple=True,
        ),
        _select(
            "patterns",
            "Which patterns should apply? Enter for matches from the stack.",
            catalog["patterns"].values(),
            multiple=True,
        ),
        _select(
            "packs",
            "Which additional packs should apply? Enter for recommended baseline and language packs.",
            catalog["packs"].values(),
            multiple=True,
        ),
        _select(
            "boards",
            "Which boards can advise? Enter to enable all available boards.",
            catalog["boards"].values(),
            multiple=True,
        ),
        _select(
            "research",
            "Can the host agent consult public sources when you approve it for a task?",
            [
                {"id": "local-only", "title": "Use project sources"},
                {"id": "public-sources", "title": "Allow public research when requested for a task"},
            ],
            "local-only",
        ),
        {"id": "conventions", "type": "list", "prompt": "Which team conventions should the agent follow?"},
        {"id": "checks", "type": "list", "prompt": "Which project checks should the agent or CI run?"},
    ]


def _single_line(value: str) -> bool:
    """True when the text holds no line break of any kind, including a lone carriage return."""
    return len(value.strip().splitlines()) == 1


def _texts(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    if any(not _single_line(item) for item in value):
        raise ValueError(f"Each entry of {field} must be a single line")
    return list(dict.fromkeys(item.strip() for item in value))


def _ids(value, field: str, available: dict) -> list[str]:
    chosen = _texts(value, field)
    unknown = sorted(set(chosen) - available.keys())
    if unknown:
        hint = (
            " It comes from a central policy: pass --policy-repo and --policy-commit."
            if "export-link-expiry" in unknown else " Run openguildkit catalog."
        )
        raise ValueError(f"Unknown {field}: {', '.join(unknown)}.{hint}")
    return chosen


def _recommended_packs(stack: list[str], catalog: dict) -> list[str]:
    aliases = {"react.js": "react", "openapi": "api-design"}
    tokens = {re.split(r"[\s@]+", item.lower(), maxsplit=1)[0] for item in stack}
    legacy_stack_packs = {"api-design", "python", "react", "typescript"}
    names = {aliases.get(token, token) for token in tokens}
    candidates = {"secure-sdlc", *(names & legacy_stack_packs)}
    return sorted(candidates & catalog["packs"].keys())


COMPONENT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


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
                raise ValueError(f"Component {component_id} needs a path relative to the project root")
            entry["path"] = path.strip()
        entry["stack"] = _texts(component["stack"], f"components.{component_id}.stack")
        components.append(entry)
    return components


def _project_context(answers: dict, catalog: dict) -> tuple[str, list[str], list[str], list[dict]]:
    sector = answers.get("sector", "general")
    if not isinstance(sector, str) or sector not in catalog["sectors"]:
        raise ValueError(f"Unknown sector: {sector}. Run openguildkit catalog.")
    components = _components(answers.get("components"))
    stack = _texts(answers.get("stack", []), "stack")
    if components:
        # With components, the project stack is the union of what each component uses.
        stack = list(dict.fromkeys([*stack, *(item for component in components for item in component["stack"])]))
    roles = _ids(answers.get("roles", []), "roles", role_choices(catalog["patterns"]))
    return sector, stack, roles, components


def profile_recommendations(answers: dict, catalog: dict) -> dict:
    sector, stack, roles, components = _project_context(answers, catalog)
    result = recommend_patterns(catalog, stack, sector, roles, components)
    base_packs = ["agent-workflow", *_recommended_packs(stack, catalog)]
    result["recommended_packs"] = list(
        dict.fromkeys([*base_packs, *(pack for pattern in result["matched"] for pack in pattern["packs"])])
    )
    return result


def _pattern_entries(value, catalog: dict, components: list[dict]) -> list:
    """Validate selected patterns: plain IDs, or objects limiting a pattern to components."""
    if not isinstance(value, list):
        raise ValueError("patterns must be a list")
    known_components = {component["id"] for component in components}
    entries, seen = [], set()
    for entry in value:
        if isinstance(entry, dict):
            if set(entry) != {"id", "components"}:
                raise ValueError("A scoped pattern needs exactly id and components")
            scope = _texts(entry["components"], "pattern components")
            unknown = sorted(set(scope) - known_components)
            if unknown:
                raise ValueError(f"Pattern {entry['id']} names unknown components: {', '.join(unknown)}")
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


def _resolutions(value, catalog: dict) -> list[dict]:
    """Validate the team's choices between conflicting packs."""
    if not isinstance(value, list):
        raise ValueError("resolutions must be a list")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"packs", "keep", "reason"}:
            raise ValueError("Each resolution needs packs, keep and reason")
        packs = _ids(item["packs"], "resolution packs", catalog["packs"])
        keep = _ids(item["keep"], "resolution keep", catalog["packs"])
        if len(packs) < 2:
            raise ValueError("A resolution names at least two conflicting packs")
        if not keep or not set(keep) <= set(packs):
            raise ValueError("keep must list one or more of the resolution's packs")
        reason = item["reason"]
        if not isinstance(reason, str) or not reason.strip() or not _single_line(reason):
            raise ValueError("A resolution needs a single-line reason")
        key = tuple(sorted(packs))
        if key in seen:
            raise ValueError(f"Duplicate resolution for {', '.join(key)}")
        seen.add(key)
        result.append({"packs": sorted(packs), "keep": sorted(keep), "reason": reason.strip()})
    return result


def pattern_ids(profile: dict) -> list[str]:
    return [pattern_selection(entry)[0] for entry in profile.get("patterns", [])]


def validate_profile(answers: dict, catalog: dict) -> dict:
    fields = {
        "schema_version", "name", "sector", "stack", "components", "roles", "patterns", "packs",
        "resolutions", "boards", "required_boards", "research", "conventions", "checks",
    }
    unknown = sorted(answers.keys() - fields)
    if unknown:
        raise ValueError(f"Unknown profile fields: {', '.join(unknown)}")
    version = answers.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported project schema version: {version}")
    name = answers.get("name")
    if not isinstance(name, str) or not name.strip() or not _single_line(name):
        raise ValueError("name must be a non-empty single line")
    sector, stack, roles, components = _project_context(answers, catalog)
    research = answers.get("research", "local-only")
    if research not in ("local-only", "public-sources"):
        raise ValueError("research must be local-only or public-sources")
    patterns = _pattern_entries(answers.get("patterns", []), catalog, components)
    if "patterns" not in answers and "packs" not in answers:
        patterns = [
            {"id": record["id"], "components": record["components"]} if record.get("components") else record["id"]
            for record in recommend_patterns(catalog, stack, sector, roles, components)["matched"]
        ]
    check_pattern_choices([pattern_selection(entry)[0] for entry in patterns], catalog["patterns"])
    packs = _ids(answers.get("packs", _recommended_packs(stack, catalog)), "packs", catalog["packs"])
    profile = {
        "schema_version": SCHEMA_VERSION,
        "name": name.strip(),
        "sector": sector,
        "stack": stack,
        **({"components": components} if components else {}),
        "packs": list(dict.fromkeys(["agent-workflow", *packs])),
        "boards": _ids(answers.get("boards", []), "boards", catalog["boards"]),
        "research": research,
        "conventions": _texts(answers.get("conventions", []), "conventions"),
        "checks": _texts(answers.get("checks", []), "checks"),
    }
    if roles:
        profile["roles"] = roles
    if patterns:
        profile["patterns"] = patterns
    required = _ids(answers.get("required_boards", []), "required_boards", catalog["boards"])
    if required:
        profile["required_boards"] = required
    resolutions = _resolutions(answers.get("resolutions", []), catalog)
    if resolutions:
        profile["resolutions"] = resolutions
    return profile


def load_profile(state: Path, catalog: dict) -> dict:
    path = state / "project.json"
    if not path.is_file():
        raise ValueError("Project is missing a profile. Run openguildkit init.")
    return validate_profile(read_json(path), catalog)


def _selected_packs(profile: dict, catalog: dict) -> list[str]:
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


def rule_conflicts(profile: dict, catalog: dict) -> list[dict]:
    """Declared incompatibilities between selected packs that apply to a common scope."""
    selected = _selected_packs(profile, catalog)
    scopes = pack_scopes(profile, catalog)
    # A declaration on either pack is enough: conflicts are symmetric.
    pairs = sorted(
        {
            tuple(sorted((pack_id, other)))
            for pack_id in selected
            for other in catalog["packs"][pack_id].get("conflicts_with", [])
            if other in selected
        }
    )
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
    packs = [pack_id for pack_id in _selected_packs(profile, catalog) if pack_id not in excluded]
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
        for pack_id in catalog["patterns"][pattern_id]["packs"]:
            add(pack_id, f"pattern {pattern_id}")
    return reasons


def rule_plan(profile: dict, catalog: dict) -> dict:
    """Everything init or sync would write, with the origin and scope of each pack."""
    resolved = resolved_profile(profile, catalog)
    scopes = pack_scopes(profile, catalog)
    provenance = pack_provenance(profile, catalog)
    selected = _selected_packs(profile, catalog)
    return {
        "packs": [
            {
                "id": pack_id,
                "title": catalog["packs"][pack_id]["title"],
                "version": catalog["packs"][pack_id]["version"],
                "provenance": provenance.get(pack_id, []),
                "scope": scopes.get(pack_id),
                "rules": [rule["id"] for rule in catalog["packs"][pack_id]["rules"]],
            }
            for pack_id in resolved["packs"]
        ],
        "excluded": [pack_id for pack_id in selected if pack_id not in resolved["packs"]],
        "conflicts": rule_conflicts(profile, catalog),
        "conventions": profile.get("conventions", []),
        "checks": profile.get("checks", []),
    }


def require_resolved_conflicts(profile: dict, catalog: dict) -> None:
    open_conflicts = [conflict for conflict in rule_conflicts(profile, catalog) if conflict["resolution"] is None]
    if open_conflicts:
        names = "; ".join(" and ".join(conflict["packs"]) for conflict in open_conflicts)
        raise ValueError(
            f"Conflicting rule packs: {names}. Run openguildkit preview, then choose the rules that apply in "
            '"resolutions" of .openguildkit/project.json, for example '
            '{"packs": ["first", "second"], "keep": ["second"], "reason": "Why"}.'
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


def profile_fingerprint(profile: dict, catalog: dict) -> str:
    resolved = resolved_profile(profile, catalog)
    snapshot = {
        "profile": resolved,
        "packs": [catalog["packs"][pack_id] for pack_id in resolved["packs"]],
        "boards": [catalog["boards"][board_id] for board_id in resolved["boards"]],
        "sector": catalog["sectors"][resolved["sector"]],
    }
    if profile.get("patterns"):
        snapshot["patterns"] = [catalog["patterns"][pattern_id] for pattern_id in pattern_ids(profile)]
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bullets(values: list[str]) -> list[str]:
    return ["- " + value.replace("\n", "\n  ") for value in values]


def _source_link(source: dict) -> str:
    title = source["title"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{title}](<{source['url']}>)"


def rule_text(rule: dict) -> tuple[str, str]:
    if "check" not in rule:
        return rule["instruction"], rule["verification"]
    threshold = int(rule["check"]["max_minutes"])
    return (
        f"Limit downloadLinkMinutes in export.json to {threshold} minutes.",
        "Run the CI check on the target commit.",
    )


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
    lines.extend(["", "### Rule packs"])
    for pack_id in resolved["packs"]:
        pack = catalog["packs"][pack_id]
        lines.extend(["", f"#### {pack['title']} (`{pack_id}@{pack['version']}`)", "", pack["description"], ""])
        if scopes.get(pack_id):
            lines.extend([f"Applies to {scope_text(scopes[pack_id])}.", ""])
        if "policy_commit" in pack:
            lines.extend([f"Policy commit: `{pack['policy_commit']}`", ""])
        for rule in pack["rules"]:
            instruction, verification = rule_text(rule)
            lines.extend([f"- `{rule['id']}` {instruction}", f"  Verify: {verification}"])
        if pack["sources"]:
            lines.extend(["", *_bullets([_source_link(source) for source in pack["sources"]])])
    lines.extend(["", f"<!-- openguildkit profile {profile_fingerprint(profile, catalog)} -->"])
    return "\n".join(lines)


_MARKER_LINE = re.compile("(" + re.escape(BEGIN) + "|" + re.escape(END) + r")[ \t]*")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
BOM = "\ufeff"


def _marker_positions(text: str) -> list[tuple[str, int, int]]:
    """Find the OpenGuildKit markers that stand on their own line outside fenced code blocks."""
    found, fence, offset = [], None, 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        opening = _FENCE.match(content)
        if fence is None and opening:
            fence = opening.group(1)
        elif fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence) \
                    and not content[opening.end():].strip():
                fence = None
        else:
            match = _MARKER_LINE.fullmatch(content)
            if match:
                found.append((match.group(1), offset, offset + len(content)))
        offset += len(line)
    return found


def merged_instructions(current: str, generated: str, label: str = "AGENTS.md") -> str:
    """Replace the managed block in an instructions file, or append it, keeping the rest unchanged."""
    newline = "\r\n" if "\r\n" in current else "\n"
    if any(_MARKER_LINE.fullmatch(line.strip()) for line in generated.splitlines()):
        raise ValueError("Project instructions contain a reserved OpenGuildKit marker.")
    matches = _marker_positions(current)
    block = newline.join([BEGIN, generated.replace("\n", newline), END])
    if not matches:
        separator = newline if current.endswith(newline) else newline * 2
        return current + (separator if current else "") + block + newline
    if [kind for kind, _, _ in matches] != [BEGIN, END]:
        raise ValueError(f"{label} has malformed OpenGuildKit markers. Repair the marked block and retry.")
    return current[:matches[0][1]] + block + current[matches[1][2]:]


def _read_instructions(path: Path) -> tuple[str, bool]:
    """Read an instructions file and report whether it starts with a UTF-8 byte order mark."""
    if path.is_symlink():
        raise ValueError(f"Refusing a symbolic link as project instructions: {path}")
    if not path.exists():
        return "", False
    text = path.read_bytes().decode("utf-8")
    return (text[1:], True) if text.startswith(BOM) else (text, False)


def _instruction_text(path: Path) -> str:
    return _read_instructions(path)[0]


def _claude_links_to_agents(root: Path) -> bool:
    """A CLAUDE.md that is a symbolic link to the project's AGENTS.md already carries the rules."""
    claude, agents = root / "CLAUDE.md", root / "AGENTS.md"
    if not claude.is_symlink():
        return False
    try:
        return claude.resolve(strict=True) == agents.resolve(strict=True) and not agents.is_symlink()
    except OSError:
        return False


def _claude_instructions(current: str) -> str:
    standalone_import = any(line.strip() in {"@AGENTS.md", "@./AGENTS.md"} for line in current.splitlines())
    if not _marker_positions(current) and standalone_import:
        return current
    return merged_instructions(current, "@AGENTS.md", "CLAUDE.md")


def sync_instructions(root: Path, profile: dict, catalog: dict) -> None:
    state = state_path(root)
    instructions = root / "AGENTS.md"
    current, bom = _read_instructions(instructions)
    updated = merged_instructions(current, render_instructions(profile, catalog))
    claude = root / "CLAUDE.md"
    linked = _claude_links_to_agents(root)
    if not linked:
        current_claude, claude_bom = _read_instructions(claude)
        updated_claude = _claude_instructions(current_claude)
    ignore = state / ".gitignore"
    previous_ignore = _instruction_text(ignore)
    missing = [entry for entry in PROJECT_IGNORE.splitlines() if entry not in previous_ignore.splitlines()]
    if missing:
        separator = "\n" if previous_ignore and not previous_ignore.endswith("\n") else ""
        write_text(ignore, previous_ignore + separator + "\n".join(missing) + "\n")
    write_text(instructions, (BOM if bom else "") + updated)
    if not linked:
        write_text(claude, (BOM if claude_bom else "") + updated_claude)


def initialize(root: Path, state: Path, profile: dict, catalog: dict) -> None:
    path = state / "project.json"
    if path.exists():
        raise ValueError("Project is already initialized. Edit .openguildkit/project.json and run openguildkit sync.")
    sync_instructions(root, profile, catalog)
    write_json(path, profile)


def check_instructions(root: Path, profile: dict, catalog: dict) -> None:
    current = _instruction_text(root / "AGENTS.md")
    linked = _claude_links_to_agents(root)
    claude = "" if linked else _instruction_text(root / "CLAUDE.md")
    ignore = _instruction_text(state_path(root) / ".gitignore")
    if (
        current != merged_instructions(current, render_instructions(profile, catalog))
        or (not linked and claude != _claude_instructions(claude))
        or not set(PROJECT_IGNORE.splitlines()).issubset(ignore.splitlines())
    ):
        raise ValueError("OpenGuildKit instructions are out of date. Run openguildkit sync.")
