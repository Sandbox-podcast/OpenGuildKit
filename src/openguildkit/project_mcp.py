"""Read a single OpenGuildKit project's metadata over local MCP."""

import json
import re
from pathlib import Path

from .catalog import COLLECTION_FIELDS, ID_PATTERN
from .lock import lock_path, package_version, project_catalog
from .mcp_protocol import INVALID_PARAMS, ProtocolError, ToolServer, serve
from .project import load_profile, rule_plan
from .results import RESULT_STATUSES
from .tasks import STATUSES, read_task, task_path

REVISION = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})")
SLUG = ID_PATTERN.pattern
CHECK_ID = re.compile(rf"(?:command:[0-9]+|rule:{SLUG}/{SLUG}|evidence:{SLUG}/{SLUG}/{SLUG}|chaosfolk:{SLUG})")


def _object_schema(**properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _tool(name: str, description: str, output: dict, *arguments: str) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": _object_schema(**{key: {"type": "string", "pattern": f"^{SLUG}$"} for key in arguments}),
        "outputSchema": output,
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }


_TEXT = {"type": "string"}
_REVISION = {"type": ["string", "null"]}
_COUNT = {"type": "integer", "minimum": 0}
_PACK = _object_schema(id=_TEXT, version=_TEXT, scope={"type": ["array", "null"], "items": _TEXT})
_CHECK = _object_schema(check=_TEXT, status={**_TEXT, "enum": list(RESULT_STATUSES)}, revision=_REVISION)
TOOLS = [
    _tool("project_profile", "Read the project's sector, component IDs and active rule packs.", _object_schema(
        sector=_TEXT,
        components={"type": "array", "items": _object_schema(id=_TEXT)},
        packs={"type": "array", "items": _PACK},
    )),
    _tool("project_rule", "Read the identity and scope of a rule in an active pack.",
          _object_schema(pack=_PACK, rule_id=_TEXT), "pack_id", "rule_id"),
    _tool("task_status", "Read a task's recorded status by ID.",
          _object_schema(id=_TEXT, status={**_TEXT, "enum": list(STATUSES)}), "task_id"),
    _tool("task_check_results",
          "Read recorded check statuses and Git revisions for a task, and how many checks it leaves out.",
          _object_schema(id=_TEXT, revision=_REVISION, checks={"type": "array", "items": _CHECK},
                         omitted=_COUNT, failed_omitted=_COUNT), "task_id"),
]


def _check_path(path: Path, state: Path) -> None:
    if path.resolve() != path or not path.is_relative_to(state):
        raise ValueError("Project metadata must stay inside the project state directory.")


def _plan(state: Path) -> tuple[dict, list[dict]]:
    _check_path(state / "project.json", state)
    _check_path(lock_path(state), state)
    catalog_dir = state / "catalog"
    _check_path(catalog_dir, state)
    for collection in COLLECTION_FIELDS:
        directory = catalog_dir / collection
        _check_path(directory, state)
        for path in directory.glob("*.json"):
            _check_path(path, state)
            if not path.is_file():
                raise ValueError("Catalog entries must be files.")
    catalog = project_catalog(None, state)
    profile = load_profile(state, catalog)
    return profile, rule_plan(profile, catalog)["packs"]


def _pack_ref(pack: dict) -> dict:
    return {key: pack[key] for key in ("id", "version", "scope")}


def _profile(state: Path) -> dict:
    profile, packs = _plan(state)
    return {
        "sector": profile["sector"],
        "components": [{"id": component["id"]} for component in profile.get("components", [])],
        "packs": [_pack_ref(pack) for pack in packs],
    }


def _rule(state: Path, pack_id: str, rule_id: str) -> dict:
    _, packs = _plan(state)
    for pack in packs:
        if pack["id"] == pack_id and rule_id in pack["rules"]:
            return {"pack": _pack_ref(pack), "rule_id": rule_id}
    raise ProtocolError(INVALID_PARAMS, "No matching active rule. Use project_profile to find active packs.")


def _load_task(state: Path, task_id: str) -> dict:
    if not task_path(state, task_id).is_file():
        raise ProtocolError(INVALID_PARAMS, "No matching task ID in this project.")
    return read_task(state, task_id)


def _status(state: Path, task_id: str) -> dict:
    task = _load_task(state, task_id)
    return {"id": task["id"], "status": task["status"]}


def _revision(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("commit")
    if isinstance(value, str) and (value == "working tree" or REVISION.fullmatch(value)):
        return value
    return None


def _results(state: Path, task_id: str) -> dict:
    report = _load_task(state, task_id).get("result", {})
    checks, omitted = [], []
    for item in report.get("checks", []):
        if CHECK_ID.fullmatch(item["check"]) and item["status"] in RESULT_STATUSES:
            checks.append({"check": item["check"], "status": item["status"],
                           "revision": _revision(item.get("revision"))})
        else:
            omitted.append(item["status"])
    return {"id": task_id, "revision": _revision(report.get("revision")), "checks": checks,
            "omitted": len(omitted), "failed_omitted": omitted.count("failed")}


HANDLERS = {
    "project_profile": _profile,
    "project_rule": _rule,
    "task_status": _status,
    "task_check_results": _results,
}
SCHEMAS = {tool["name"]: tool["inputSchema"] for tool in TOOLS}


def _call(state: Path, name: str, arguments: object) -> dict:
    schema = SCHEMAS.get(name)
    if schema is None:
        raise ProtocolError(INVALID_PARAMS, "Unknown tool. Use tools/list to see available tools.")
    if arguments is None:
        arguments = {}
    fields = schema["required"]
    if not isinstance(arguments, dict) or arguments.keys() != set(fields) or any(
        not isinstance(value, str) or not ID_PATTERN.fullmatch(value) for value in arguments.values()
    ):
        expected = ", ".join(fields) or "no arguments"
        raise ProtocolError(INVALID_PARAMS, f"Expected {expected}. IDs use lowercase letters, digits and hyphens.")
    try:
        data = HANDLERS[name](state, **arguments)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        # Invalid local records can contain sensitive values and paths. The CLI has detailed diagnostics.
        return {
            "isError": True,
            "content": [{"type": "text", "text": "Project metadata is unavailable. Run openguildkit check in this project."}],
        }
    return {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data}


def serve_project(state: Path) -> int:
    """Serve only the explicitly selected project's read operations."""
    return serve(ToolServer(
        info={"name": "openguildkit", "version": package_version()},
        instructions="Consult the selected OpenGuildKit project's rule metadata and recorded task outcomes.",
        tools=TOOLS,
        call=lambda name, arguments: _call(state, name, arguments),
    ))
