"""Collect a project profile and render its repository instructions."""

import hashlib
import json
import re
from pathlib import Path

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


def init_questions(catalog: dict, project_name: str) -> list[dict]:
    return [
        {"id": "name", "type": "text", "prompt": "Project name", "default": project_name},
        _select("sector", "Which sector describes the project?", catalog["sectors"].values(), "general"),
        {
            "id": "stack",
            "type": "list",
            "prompt": "Which languages, frameworks and services are in the stack?",
            "examples": ["Python", "FastAPI", "PostgreSQL"],
        },
        _select(
            "packs",
            "Which rule packs should apply? Enter for recommendations based on the stack.",
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


def _texts(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return list(dict.fromkeys(item.strip() for item in value))


def _ids(value, field: str, available: dict) -> list[str]:
    chosen = _texts(value, field)
    unknown = sorted(set(chosen) - available.keys())
    if unknown:
        raise ValueError(f"Unknown {field}: {', '.join(unknown)}. Run openguildkit catalog.")
    return chosen


def _recommended_packs(stack: list[str], catalog: dict) -> list[str]:
    aliases = {"react.js": "react", "openapi": "api-design"}
    tokens = {re.split(r"[\s@]+", item.lower(), maxsplit=1)[0] for item in stack}
    candidates = {"secure-sdlc", *(aliases.get(token, token) for token in tokens)}
    return sorted(candidates & catalog["packs"].keys())


def validate_profile(answers: dict, catalog: dict) -> dict:
    fields = {"schema_version", "name", "sector", "stack", "packs", "boards", "research", "conventions", "checks"}
    unknown = sorted(answers.keys() - fields)
    if unknown:
        raise ValueError(f"Unknown profile fields: {', '.join(unknown)}")
    version = answers.get("schema_version", SCHEMA_VERSION)
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported project schema version: {version}")
    name = answers.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.splitlines()) != 1:
        raise ValueError("name must be a non-empty single line")
    sector = answers.get("sector", "general")
    if not isinstance(sector, str) or sector not in catalog["sectors"]:
        raise ValueError(f"Unknown sector: {sector}. Run openguildkit catalog.")
    research = answers.get("research", "local-only")
    if research not in ("local-only", "public-sources"):
        raise ValueError("research must be local-only or public-sources")
    stack = _texts(answers.get("stack", []), "stack")
    packs = _ids(answers.get("packs", _recommended_packs(stack, catalog)), "packs", catalog["packs"])
    return {
        "schema_version": SCHEMA_VERSION,
        "name": name.strip(),
        "sector": sector,
        "stack": stack,
        "packs": list(dict.fromkeys(["agent-workflow", *packs])),
        "boards": _ids(answers.get("boards", []), "boards", catalog["boards"]),
        "research": research,
        "conventions": _texts(answers.get("conventions", []), "conventions"),
        "checks": _texts(answers.get("checks", []), "checks"),
    }


def load_profile(state: Path, catalog: dict) -> dict:
    path = state / "project.json"
    if not path.is_file():
        raise ValueError("Project is missing a profile. Run openguildkit init.")
    return validate_profile(read_json(path), catalog)


def resolved_profile(profile: dict, catalog: dict) -> dict:
    ordered = {}

    def add_pack(pack_id):
        if pack_id not in ordered:
            for dependency in catalog["packs"][pack_id].get("depends_on", []):
                add_pack(dependency)
            ordered[pack_id] = None

    for pack_id in profile["packs"]:
        add_pack(pack_id)
    return {**profile, "packs": list(ordered), "boards": profile["boards"] or sorted(catalog["boards"])}


def profile_fingerprint(profile: dict, catalog: dict) -> str:
    resolved = resolved_profile(profile, catalog)
    snapshot = {
        "profile": resolved,
        "packs": [catalog["packs"][pack_id] for pack_id in resolved["packs"]],
        "boards": [catalog["boards"][board_id] for board_id in resolved["boards"]],
        "sector": catalog["sectors"][resolved["sector"]],
    }
    canonical = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bullets(values: list[str]) -> list[str]:
    return ["- " + value.replace("\n", "\n  ") for value in values]


def _source_link(source: dict) -> str:
    title = source["title"].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{title}](<{source['url']}>)"


def render_instructions(profile: dict, catalog: dict) -> str:
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
    for title, field in (("Team conventions", "conventions"), ("Project checks", "checks")):
        if profile[field]:
            lines.extend(["", f"### {title}", "", *_bullets(profile[field])])
    lines.extend(["", "### Rule packs"])
    for pack_id in resolved["packs"]:
        pack = catalog["packs"][pack_id]
        lines.extend(["", f"#### {pack['title']} (`{pack_id}@{pack['version']}`)", "", pack["description"], ""])
        for rule in pack["rules"]:
            lines.extend([f"- `{rule['id']}` {rule['instruction']}", f"  Verify: {rule['verification']}"])
        if pack["sources"]:
            lines.extend(["", *_bullets([_source_link(source) for source in pack["sources"]])])
    lines.extend(["", f"<!-- openguildkit profile {profile_fingerprint(profile, catalog)} -->"])
    return "\n".join(lines)


def merged_instructions(current: str, generated: str) -> str:
    newline = "\r\n" if "\r\n" in current else "\n"
    marker = re.compile(r"(?m)^(" + re.escape(BEGIN) + "|" + re.escape(END) + r")[ \t]*(?=\r?$)")
    if marker.search(generated):
        raise ValueError("Project instructions contain a reserved OpenGuildKit marker.")
    matches = list(marker.finditer(current))
    block = newline.join([BEGIN, generated.replace("\n", newline), END])
    if not matches:
        separator = newline if current.endswith(newline) else newline * 2
        return current + (separator if current else "") + block + newline
    if [match.group(1) for match in matches] != [BEGIN, END]:
        raise ValueError("AGENTS.md has malformed OpenGuildKit markers. Repair the marked block and retry.")
    return current[:matches[0].start()] + block + current[matches[1].end():]


def _instruction_text(path: Path) -> str:
    if path.is_symlink():
        raise ValueError(f"Refusing a symbolic link as project instructions: {path}")
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def _claude_instructions(current: str) -> str:
    standalone_import = any(line.strip() in {"@AGENTS.md", "@./AGENTS.md"} for line in current.splitlines())
    if BEGIN not in current and END not in current and standalone_import:
        return current
    return merged_instructions(current, "@AGENTS.md")


def sync_instructions(root: Path, profile: dict, catalog: dict) -> None:
    state = state_path(root)
    instructions = root / "AGENTS.md"
    updated = merged_instructions(_instruction_text(instructions), render_instructions(profile, catalog))
    claude = root / "CLAUDE.md"
    updated_claude = _claude_instructions(_instruction_text(claude))
    ignore = state / ".gitignore"
    previous_ignore = _instruction_text(ignore)
    missing = [entry for entry in PROJECT_IGNORE.splitlines() if entry not in previous_ignore.splitlines()]
    if missing:
        separator = "\n" if previous_ignore and not previous_ignore.endswith("\n") else ""
        write_text(ignore, previous_ignore + separator + "\n".join(missing) + "\n")
    write_text(instructions, updated)
    write_text(claude, updated_claude)


def initialize(root: Path, state: Path, profile: dict, catalog: dict) -> None:
    path = state / "project.json"
    if path.exists():
        raise ValueError("Project is already initialized. Edit .openguildkit/project.json and run openguildkit sync.")
    sync_instructions(root, profile, catalog)
    write_json(path, profile)


def check_instructions(root: Path, profile: dict, catalog: dict) -> None:
    current = _instruction_text(root / "AGENTS.md")
    claude = _instruction_text(root / "CLAUDE.md")
    ignore = _instruction_text(state_path(root) / ".gitignore")
    if (
        current != merged_instructions(current, render_instructions(profile, catalog))
        or claude != _claude_instructions(claude)
        or not set(PROJECT_IGNORE.splitlines()).issubset(ignore.splitlines())
    ):
        raise ValueError("OpenGuildKit instructions are out of date. Run openguildkit sync.")
