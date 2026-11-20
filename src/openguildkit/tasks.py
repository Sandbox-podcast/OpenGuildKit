"""Track task consultations and decisions in the project."""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .project import profile_fingerprint, resolved_profile
from .storage import read_json, write_json
from .workflow import consult, validate_answers, validate_review

ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{digit}" for prefix in ("com", "lpt") for digit in range(1, 10)
}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def task_path(state: Path, task_id: str) -> Path:
    if len(task_id) > 64 or not ID_PATTERN.fullmatch(task_id) or task_id in WINDOWS_RESERVED_NAMES:
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
    return task


def create_task(state: Path, brief: str, task_id: str | None) -> str:
    brief = brief.strip()
    if not brief:
        raise ValueError("Supply a task brief.")
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


def record_consultation(task: dict, answers: dict, profile: dict, catalog: dict) -> dict:
    if task["status"] not in {"draft", "consulting", "changes-requested"}:
        raise ValueError("Start a new task or request changes before consulting again.")
    rounds = list(task["rounds"])
    if task["status"] == "changes-requested":
        rounds.append({key: task[key] for key in ("answers", "consultation", "review", "decision", "profile_fingerprint")})
    result = {**task, "answers": validate_answers(answers), "rounds": rounds}
    result.update(
        status="consulting",
        consultation=consult(resolved_profile(profile, catalog), catalog, result),
        profile_fingerprint=profile_fingerprint(profile, catalog),
    )
    result.pop("review", None)
    result.pop("decision", None)
    return result


def record_review(task: dict, review: dict) -> dict:
    if task["status"] != "consulting":
        raise ValueError("Run task consult before recording a review.")
    review = validate_review(task["consultation"], review)
    return {**task, "status": "reviewed", "review": review}


def record_decision(task: dict, approve: bool, by: str, reason: str) -> dict:
    if task["status"] != "reviewed":
        raise ValueError("Record the boards' review before deciding.")
    if not by.strip() or not reason.strip():
        raise ValueError("Supply the decision owner and a reason.")
    status = "approved" if approve else "changes-requested"
    decision = {"outcome": status, "by": by.strip(), "reason": reason.strip(), "at": timestamp()}
    return {**task, "status": status, "decision": decision}


def require_current_scope(task: dict, profile: dict, catalog: dict) -> None:
    if task.get("profile_fingerprint") != profile_fingerprint(profile, catalog):
        next_step = "Open a new task." if task["status"] == "approved" else "Request changes and consult again."
        raise ValueError(f"The project profile or catalog changed. {next_step}")
