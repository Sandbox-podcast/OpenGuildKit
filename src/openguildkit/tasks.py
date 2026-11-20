"""Track task consultations and decisions in the project."""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .project import profile_fingerprint, resolved_profile
from .storage import read_json, write_json
from .workflow import consult, validate_answers, validate_board_entry, validate_review

ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{digit}" for prefix in ("com", "lpt") for digit in range(1, 10)
}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def task_path(state: Path, task_id: str) -> Path:
    if task_id in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{task_id} is a reserved file name on Windows. Choose another task ID.")
    if len(task_id) > 64 or not ID_PATTERN.fullmatch(task_id):
        raise ValueError("Use a task ID of up to 64 lowercase letters, digits and separating hyphens.")
    path = state / "tasks" / f"{task_id}.json"
    if path.resolve() != path:
        raise ValueError(f"Task records must stay inside their project: {path}")
    return path


def read_task(state: Path, task_id: str) -> dict:
    path = task_path(state, task_id)
    if not path.is_file():
        raise ValueError(f"Unknown task: {task_id}")
    task = read_json(path)
    if task.get("schema_version") != 1 or task.get("id") != task_id:
        raise ValueError(f"Unsupported or mismatched task record: {path}")
    problem = _record_problem(task)
    if problem:
        raise ValueError(f"Task record {path} is inconsistent: {problem}. Restore it from version control or open a new task.")
    return task


STATUSES = {
    "draft": (),
    "consulting": ("answers", "consultation", "profile_fingerprint"),
    "reviewed": ("answers", "consultation", "profile_fingerprint", "review"),
    "changes-requested": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
    "approved": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
}
CONSULTATION_FIELDS = ("id", "boards", "routing", "scope", "markdown", "review_template")


def _record_problem(task: dict) -> str | None:
    """Describe the first field of a task record that the CLI could not use, if any."""
    if not isinstance(task.get("brief"), str) or not task["brief"].strip():
        return "brief must be text"
    status = task.get("status")
    if status not in STATUSES:
        return f"status must be one of {', '.join(STATUSES)}"
    rounds = task.get("rounds")
    if not isinstance(rounds, list) or any(not isinstance(entry, dict) for entry in rounds):
        return "rounds must be a list of objects"
    for field in STATUSES[status]:
        if field not in task:
            return f"a {status} task needs {field}"
    for field in ("answers", "consultation", "review", "decision"):
        if field in task and not isinstance(task[field], dict):
            return f"{field} must be an object"
    consultation = task.get("consultation")
    if consultation is not None:
        missing = [field for field in CONSULTATION_FIELDS if field not in consultation]
        if missing:
            return f"consultation needs {', '.join(missing)}"
        if not isinstance(consultation["boards"], list) or not isinstance(consultation["markdown"], str):
            return "consultation boards must be a list and markdown text"
    return None


def create_task(state: Path, brief: str, task_id: str | None) -> str:
    brief = brief.strip()
    if not brief:
        raise ValueError("Supply a task brief.")
    if task_id is not None and not task_id.strip():
        raise ValueError("The task ID is empty. Omit --id to generate one.")
    task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
    path = task_path(state, task_id)
    if path.exists():
        raise ValueError(f"Task already exists: {task_id}")
    write_json(
        path,
        {
            "schema_version": 1,
            "id": task_id,
            "brief": brief,
            "created_at": timestamp(),
            "status": "draft",
            "rounds": [],
        },
    )
    return task_id


def record_consultation(
    task: dict, answers: dict, profile: dict, catalog: dict, selection: dict | None = None,
    host_controls: list[dict] | None = None,
) -> dict:
    if task["status"] not in {"draft", "consulting", "changes-requested"}:
        raise ValueError("Start a new task or request changes before consulting again.")
    rounds = list(task["rounds"])
    if task["status"] == "changes-requested":
        rounds.append({key: task[key] for key in ("answers", "consultation", "review", "decision", "profile_fingerprint")})
    result = {**task, "answers": validate_answers(answers), "rounds": rounds}
    result.update(
        status="consulting",
        consultation=consult(resolved_profile(profile, catalog), catalog, result, selection, host_controls),
        profile_fingerprint=profile_fingerprint(profile, catalog),
    )
    result.pop("review", None)
    result.pop("decision", None)
    result.pop("passes", None)
    return result


def record_review(task: dict, review: dict) -> dict:
    if task["status"] != "consulting":
        raise ValueError("Run task consult before recording a review.")
    review = validate_review(task["consultation"], review)
    result = {**task, "status": "reviewed", "review": review}
    result.pop("passes", None)
    return result


def _passes(task: dict) -> dict:
    if task["status"] != "consulting":
        raise ValueError("Board passes can only run while the task is being consulted.")
    passes = task.get("passes")
    if not passes or passes.get("consultation_id") != task["consultation"]["id"]:
        return {"consultation_id": task["consultation"]["id"], "boards": {}}
    return {"consultation_id": passes["consultation_id"], "boards": dict(passes["boards"])}


def start_pass(task: dict, board_id: str, mode: str) -> dict:
    """Mark a board's pass as started; starting again replaces a failed or interrupted pass."""
    if board_id not in task["consultation"]["boards"]:
        raise ValueError(f"Board {board_id!r} is not part of this consultation.")
    if mode not in ("subagent", "sequential"):
        raise ValueError("A pass runs as a subagent or in sequence.")
    passes = _passes(task)
    previous = passes["boards"].get(board_id, {})
    passes["boards"][board_id] = {"status": "started", "mode": mode, "started_at": timestamp(),
                                  "attempts": previous.get("attempts", 0) + 1}
    return {**task, "passes": passes}


def submit_pass(task: dict, entry: dict, mode: str | None = None) -> dict:
    """Record one board's entry. An invalid entry is recorded as a failure to retry."""
    passes = _passes(task)
    board_id = entry.get("id") if isinstance(entry, dict) else None
    current = passes["boards"].get(board_id, {}) if isinstance(board_id, str) else {}
    mode = mode or current.get("mode", "sequential")
    try:
        validated = validate_board_entry(task["consultation"], entry)
    except ValueError as error:
        if isinstance(board_id, str) and board_id in task["consultation"]["boards"]:
            passes["boards"][board_id] = {**current, "status": "failed", "mode": mode, "error": str(error),
                                          "at": timestamp(), "attempts": current.get("attempts", 1)}
            return {**task, "passes": passes, "_error": str(error)}
        raise
    passes["boards"][validated["id"]] = {"status": "done", "mode": mode, "entry": validated, "at": timestamp(),
                                         "attempts": current.get("attempts", 1)}
    return {**task, "passes": passes}


def pass_progress(task: dict) -> list[dict]:
    """Each selected board with its pass status: done, failed, started (or interrupted) or missing."""
    passes = task.get("passes") if task["status"] == "consulting" else None
    if passes and passes.get("consultation_id") != task["consultation"]["id"]:
        passes = None
    progress = []
    for board_id in task["consultation"]["boards"]:
        state = (passes or {}).get("boards", {}).get(board_id)
        item = {"board": board_id, "status": state["status"] if state else "missing"}
        if state:
            item.update({key: state[key] for key in ("mode", "attempts", "error") if key in state})
        progress.append(item)
    return progress


def assemble_review(task: dict, summary: str) -> dict:
    """Build the full review from completed passes once every board is done."""
    passes = _passes(task)
    progress = pass_progress({**task, "passes": passes})
    waiting = [item["board"] for item in progress if item["status"] != "done"]
    if waiting:
        raise ValueError(f"Board passes are not done for {', '.join(waiting)}. Run task progress.")
    modes = {passes["boards"][board_id]["mode"] for board_id in task["consultation"]["boards"]}
    execution = "subagents" if modes == {"subagent"} else "sequential" if modes == {"sequential"} else "mixed"
    review = {
        "consultation_id": task["consultation"]["id"],
        "summary": summary,
        "boards": [passes["boards"][board_id]["entry"] for board_id in task["consultation"]["boards"]],
        "execution": execution,
    }
    return record_review(task, review)


def record_decision(task: dict, approve: bool, by: str, reason: str) -> dict:
    if task["status"] != "reviewed":
        raise ValueError("Record the boards' review before deciding.")
    if not by.strip() or not reason.strip():
        raise ValueError("Supply the decision owner and a reason.")
    status = "approved" if approve else "changes-requested"
    decision = {"outcome": status, "by": by.strip(), "reason": reason.strip(), "at": timestamp()}
    return {**task, "status": status, "decision": decision}


ACTIONS = ("public-research", "external-api", "send-message", "publish", "install-dependency", "other")
_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")


def record_authorization(task: dict, action: str, target: str, allow: bool, by: str, reason: str) -> dict:
    """Record a person's decision on an external action outside the authorized scope."""
    if action not in ACTIONS:
        raise ValueError(f"Choose the action from {', '.join(ACTIONS)}.")
    if not _TARGET.fullmatch(target) or "?" in target or "@" in target:
        raise ValueError("Name the target as a host or tool name, without a query, an address or private details.")
    if not by.strip() or not reason.strip():
        raise ValueError("Supply the decision owner and a reason.")
    entry = {
        "action": action, "target": target, "decision": "allow" if allow else "deny",
        "by": by.strip(), "reason": reason.strip(), "at": timestamp(),
    }
    return {**task, "authorizations": [*task.get("authorizations", []), entry]}


def require_current_scope(task: dict, profile: dict, catalog: dict) -> None:
    if task.get("profile_fingerprint") != profile_fingerprint(profile, catalog):
        next_step = "Open a new task." if task["status"] == "approved" else "Request changes and consult again."
        raise ValueError(f"The project profile or catalog changed. {next_step}")
