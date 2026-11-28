"""Read a single OpenGuildKit project's metadata over local MCP."""

import json
import re
from pathlib import Path

from .catalog import COLLECTION_FIELDS, ID_PATTERN
from .lock import lock_path, package_version, project_catalog
from .mcp_protocol import INVALID_PARAMS, ProtocolError, ToolServer, serve
from .project import Fingerprints, load_profile, rule_plan
from .results import RESULT_STATUSES
from .sensitive import redact_credentials
from .tasks import list_tasks, read_task, task_path
from .tasks_approval import approval_problem, stale_review_message
from .tasks_blockers import expired_on
from .tasks_record import STATUSES
from .tasks_status import next_command, next_step
from .workflow import blocker_list

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
_TASK_STATUS = {**_TEXT, "enum": [*STATUSES, "unreadable"]}
_MAYBE_TEXT = {"type": ["string", "null"]}
BLOCKER_STATES = ("open", "cleared", "waived", "waiver-expired")
_BLOCKER = _object_schema(id=_TEXT, board=_TEXT, phase={**_TEXT, "enum": ["approval", "verification"]},
                          finding=_TEXT, owner=_MAYBE_TEXT, clears_when=_MAYBE_TEXT,
                          state={**_TEXT, "enum": list(BLOCKER_STATES)})
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
    _tool("task_list", "List the project's tasks with their status and next open point, as task list --json does.",
          _object_schema(tasks={"type": "array", "items": _object_schema(id=_TEXT, status=_TASK_STATUS, next=_TEXT)})),
    _tool("task_next",
          "Read the command that moves a task on, and whether it is a person's act (needs_person). The server never "
          "runs it.",
          _object_schema(id=_TEXT, status={**_TEXT, "enum": list(STATUSES)}, command=_TEXT,
                         needs_person={"type": "boolean"}), "task_id"),
    _tool("task_blockers", "Read a task's review blockers: owner, what clears each one, and whether it is still open.",
          _object_schema(id=_TEXT, blockers={"type": "array", "items": _BLOCKER}), "task_id"),
]


def _check_path(path: Path, state: Path) -> None:
    if path.resolve() != path or not path.is_relative_to(state):
        raise ValueError("Project metadata must stay inside the project state directory.")


def _project(state: Path) -> tuple[dict, dict]:
    """The profile and the catalog in force, read only from inside the project state directory."""
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
    return load_profile(state, catalog), catalog


def _plan(state: Path) -> tuple[dict, list[dict]]:
    profile, catalog = _project(state)
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


def _without_free_text(task: dict) -> dict:
    """The task without what a person or a command wrote that next_step quotes: a change request's reason, a failed
    check's command line and output. The open point keeps the same words otherwise."""
    pointer = f"the person's reason is in openguildkit task show {task['id']}"
    cleaned = dict(task)
    if task["status"] == "changes-requested" and "decision" in task:
        cleaned["decision"] = {**task["decision"], "reason": pointer}
    if isinstance(task.get("result"), dict):
        checks = [{key: value for key, value in item.items() if key != "message"}
                  for item in task["result"].get("checks", [])]
        cleaned["result"] = {**task["result"], "checks": checks}
    if isinstance(task.get("consultation"), dict):
        scope = {**task["consultation"].get("scope", {}), "checks": []}
        cleaned["consultation"] = {**task["consultation"], "scope": scope}
    return cleaned


def _open_point(row: dict, task: dict | None, profile: dict) -> str:
    """task list's next open point, with the free text it may quote replaced by where to read it."""
    if task is None:
        return "The task record cannot be read. Run openguildkit check in this project."
    if row.get("severity") == "error":
        return f"The approval no longer holds: openguildkit task show {task['id']} says why and what runs next."
    if row["next"] != next_step(task, profile):
        return row["next"]  # The review predates the rules in force: a fixed message.
    return next_step(_without_free_text(task), profile)


def _task_list(state: Path) -> dict:
    profile, catalog = _project(state)
    read: dict = {}
    rows = list_tasks(state, profile=profile, catalog=catalog, root=state.parent, read=read)
    return {"tasks": [{"id": row["id"], "status": row["status"],
                       "next": redact_credentials(_open_point(row, read.get(row["id"]), profile))} for row in rows]}


def _task_next(state: Path, task_id: str) -> dict:
    profile, catalog = _project(state)
    task = _load_task(state, task_id)
    problem = approval_problem(task, profile, catalog, state.parent)
    needs_person = task["status"] == "reviewed"
    if problem and problem["severity"] == "error":
        command = f"read why the approval no longer holds and what runs next with openguildkit task show {task_id}"
    elif needs_person and not Fingerprints(profile, catalog).holds(task.get("profile_fingerprint")):
        command = stale_review_message(task_id)
    else:
        command = next_command(task)
    return {"id": task_id, "status": task["status"], "command": command, "needs_person": needs_person}


def _maybe_redacted(value: object) -> str | None:
    return redact_credentials(value) if isinstance(value, str) else None


def _blocker_state(resolution: dict | None) -> str:
    if not resolution:
        return "open"
    return "waiver-expired" if expired_on(resolution) else resolution["kind"]


def _task_blockers(state: Path, task_id: str) -> dict:
    """task blockers --json, with each resolution reduced to its state: who cleared or waived it, the evidence and
    the reason stay in the terminal."""
    task = _load_task(state, task_id)
    return {"id": task_id, "blockers": [
        {"id": item["id"], "board": item["board"], "phase": item.get("phase", "approval"),
         "finding": redact_credentials(item["finding"]), "owner": _maybe_redacted(item.get("owner")),
         "clears_when": _maybe_redacted(item.get("clears_when")), "state": _blocker_state(item["resolution"])}
        for item in blocker_list(task)]}


HANDLERS = {
    "project_profile": _profile,
    "project_rule": _rule,
    "task_status": _status,
    "task_check_results": _results,
    "task_list": _task_list,
    "task_next": _task_next,
    "task_blockers": _task_blockers,
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
        instructions="Consult the selected OpenGuildKit project's rule metadata, its tasks, their next command and "
                     "blockers, and recorded task outcomes. Nothing here runs a command or changes the project.",
        tools=TOOLS,
        call=lambda name, arguments: _call(state, name, arguments),
    ))
