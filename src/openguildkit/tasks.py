"""Writes and creates task records, lists the tasks and follows the tasks each one waits for; `task_files.py` reads
them.

The rest of the task path has its own modules: tasks_record (the shape of a record), tasks_approval (whether an
approval holds), tasks_blockers, tasks_review (consultation, review and passes), tasks_closing (decision, result,
closing) and tasks_status (the next step and the line of the task list).

Entry: create_task, write_task, list_tasks
Tests: tests/test_approval_lifecycle.py, tests/test_before_delivered_review.py, tests/test_blocker_clearances.py,
tests/test_blockers.py, tests/test_clock.py, tests/test_closing_points.py, tests/test_deliberation.py,
tests/test_delivered_review.py, tests/test_evidence_fingerprints.py, tests/test_requester.py, tests/test_retro.py,
tests/test_short_lane.py
"""

import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any, cast

from . import task_index
from .approval_check import DONE_STATUSES, approval_problem
from .decisions import base_commit, check_decision_seal, revisions_outside_history
from .project_rules import Fingerprints
from .records import Catalog, Profile, Task
from .storage import write_text
from .task_files import read_task, task_path
from .tasks_blockers import _DAY
from .tasks_record import STATUSES, timestamp, validate_brief
from .tasks_status import kept_line, line_to_keep, task_row


def write_task(path: Path, task: Task) -> None:
    """Write a task record without indentation, which made 29 % of a closed task's weight: git ignores the records
    and only the commands read them. Nothing compares their bytes (seals and digests hash the parsed fields), and any
    JSON reader, an earlier release's included, reads the same fields."""
    write_text(path, json.dumps(task, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def _dependency_cycle(state: Path, task_id: str, after: list[str]) -> list[str] | None:
    """The chain of --after links that would lead from a new task back to itself, if any: a task can only wait for
    one that is gone and whose ID is taken again."""
    def walk(current: str, path: list[str]) -> list[str] | None:
        if current == task_id:
            return path
        if current in seen:
            return None
        seen.add(current)
        try:
            waits = read_task(state, current).get("after", [])
        except ValueError:
            return None
        return next((found for name in waits if (found := walk(name, [*path, name]))), None)
    seen: set[str] = set()
    return next((found for name in after if (found := walk(name, [task_id, name]))), None)


def dependencies(state: Path, task_id: str, after: list[str]) -> dict[str, str]:
    """The tasks a new task waits for, with their status; an unknown ID, the task itself or a cycle is refused."""
    found = {}
    for name in dict.fromkeys(after):
        if name == task_id:
            raise ValueError(f"A task cannot wait for itself: {task_id}.")
        found[name] = read_task(state, name)["status"]
    cycle = _dependency_cycle(state, task_id, list(found))
    if cycle:
        raise ValueError(f"Task {task_id} cannot wait for {cycle[1]}: that would close a cycle "
                         f"({' -> '.join(cycle)}). Remove that --after.")
    return found


def waiting_for(task: Mapping[str, Any], statuses: dict[str, str]) -> list[dict]:
    """The tasks this one waits for that are not done yet, with their status; one that no longer exists still holds
    it back, as unknown."""
    return [{"task": name, "status": statuses.get(name, "unknown")} for name in task.get("after", [])
            if statuses.get(name) not in DONE_STATUSES]


def waits_line(waiting: list[dict]) -> str:
    """auth-flow (draft) and api-schema (approved)."""
    names = [f"{item['task']} ({item['status']})" for item in waiting]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def create_task(state: Path, brief: str, task_id: str | None, follows: str | None = None,
                lane: dict | None = None, after: list[str] | None = None, requested_by: str | None = None) -> str:
    brief = validate_brief(brief)
    if task_id is not None and not task_id.strip():
        raise ValueError("The task ID is empty. Omit --id to generate one.")
    task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
    path = task_path(state, task_id)
    if path.exists():
        raise ValueError(f"Task already exists: {task_id}")
    record = cast(Task, {  # lane, when given, adds the short lane and its paths.
        "schema_version": 1,
        "id": task_id,
        "brief": brief,
        "created_at": timestamp(),
        "status": "draft",
        "rounds": [],
        **(lane or {}),
        # Who asked for the work (requester.py): written only when named, so a task without one is as before.
        **({"requested_by": requested_by} if requested_by is not None else {}),
    })
    if after:
        record["after"] = list(dependencies(state, task_id, after))
    if follows is not None:
        previous = read_task(state, follows)
        if "decision" not in previous:
            raise ValueError(f"Task {follows} has no recorded decision to follow.")
        record["follows"] = {
            "task": follows,
            "brief": previous["brief"],
            "status": previous["status"],
            "decision": {key: previous["decision"][key] for key in ("outcome", "by", "reason", "at")},
        }
    write_task(path, record)
    return task_id


def _period_day(value: str | None, option: str) -> str | None:
    """The day a period option names, written YYYY-MM-DD and a real date."""
    if value is None:
        return None
    try:
        if not _DAY.fullmatch(value):
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"{option}: {value!r} is not a real date. Write it YYYY-MM-DD.") from None


def list_tasks(state: Path, status: str | None = None, owner: str | None = None,
               since: str | None = None, until: str | None = None, *, profile: Profile | None = None,
               catalog: Catalog | None = None, root: Path | None = None, read: dict | None = None,
               skip: Iterable[str] = (), indexed: bool = False) -> list[dict]:
    """Every task of the project with its status, decision owner and next open point.

    With the profile and the catalog, each approval is judged by approval_problem, and with the project root its
    signature and revision too (one git call for every approval). A dict given as read receives every task record
    read, by ID, so that a caller that needs them too does not read them again; a record it already holds is not
    read again either. skip leaves out tasks of those statuses, as status leaves out the others.

    indexed reads the status index first (task_index.py) and writes back what the reads taught it: a record read
    whole at its current signature is not read again when its status is left out, nor when it is a closed task whose
    line the index keeps (kept_line), which read then does not receive. The index only saves reads: missing, stale
    or corrupt, it gives the same list.
    """
    since, until = _period_day(since, "--since"), _period_day(until, "--until")
    directory = state / "tasks"
    rows = []
    if not directory.is_dir():
        return rows
    judged = profile is not None and catalog is not None
    fingerprints = Fingerprints(profile, catalog) if profile is not None and catalog is not None else None
    skip = {*skip, *(set(STATUSES) - {status} if status else ())}
    index = task_index.entries(state) if indexed else {}
    entries: list[tuple[Task | None, Any]] = []
    statuses: dict[str, str] = {}
    learnt = False

    def in_period(day: str) -> bool:
        return not ((since and day < since) or (until and day > until))

    for path in sorted(directory.glob("*.json")):
        known = index.get(path.name, {})
        if known.get("checked") is True and known.get("status") in skip:
            statuses[path.stem] = known["status"]
            continue
        line = kept_line(state, known, path.stem, fingerprints)
        if line:
            statuses[path.stem] = known["status"]
            if in_period(line["row"]["created"]):
                entries.append((None, dict(line["row"])))
            continue
        try:
            task = (read or {}).get(path.stem) or read_task(state, path.stem)
        except ValueError as error:
            entries.append((None, {"id": path.stem, "status": "unreadable", "next": str(error)}))
            continue
        if "stamp" in known and (known.get("checked"), known.get("status")) != (True, task["status"]):
            index[path.name], learnt = {"status": task["status"], "approved": task_index.latest_approval_at(task),
                                        "stamp": known["stamp"], "checked": True}, True
        statuses[task["id"]] = task["status"]
        if read is not None:
            read[task["id"]] = task
        if task["status"] not in skip and in_period(task["created_at"][:10]):
            entries.append((task, None))
    approved = [base_commit(task) for task, _ in entries if task and task["status"] == "approved"]
    outside = revisions_outside_history(root, approved) if judged and root is not None else None
    for task, row in entries:
        if task is not None:
            problem = (approval_problem(task, profile, catalog, root, fingerprints=fingerprints, outside=outside)
                       if profile is not None and catalog is not None else None)
            row = task_row(task, problem, profile, fingerprints, root)
            name = f"{task['id']}.json"
            if index.get(name, {}).get("checked") is True:
                line = line_to_keep(state, task, row, problem, fingerprints)
                if line and index[name].get("line") != line:
                    index[name], learnt = {**index[name], "line": line}, True
        elif row["status"] == "unreadable":
            rows.append(row)
            continue
        # owner is who took the task's current decision: the approval, the change request or the withdrawal.
        if owner and (row["owner"] or "").casefold() != owner.casefold():
            continue
        waiting = waiting_for(row, statuses)
        if waiting:
            row["waiting_for"] = waiting
        rows.append(row)
    if learnt:
        task_index.save(state, index)
    return rows


# What a change of rules means for a task in each status; a completed task keeps its record as history.
_TOUCHED_STEP = {
    "consulting": "consult it again",
    "reviewed": "request changes and consult it again",
    "approved": "consult it again (openguildkit task consult ID --reuse-answers), which keeps the passes of unchanged "
                "boards, or open a linked task with --follows",
}
# An approval without a seal, written by a release older than sealed decisions, or with a broken one keeps no pass.
_UNSEALED_STEP = ("consult it again (openguildkit task consult ID --reuse-answers): its approval has no valid seal, so "
                  "every board reviews again and check fails on it until then; or open a linked task with --follows")


def _seal_holds(task: Task) -> bool:
    try:
        check_decision_seal(task)
    except ValueError:
        return False
    return True


def tasks_touched(state: Path, profile: Profile, catalog: Catalog) -> list[dict]:
    """The open tasks consulted under other rules, checks or boards than this profile's, each with what to do.

    update, sync and the profile commands name the same: given the profile about to be written, these are the tasks
    whose consultation or approval the change voids (a change of a neutral field, APPROVAL_NEUTRAL_FIELDS, voids none).
    """
    fingerprints = Fingerprints(profile, catalog)
    touched = []
    for path in sorted((state / "tasks").glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError:
            continue
        step = _TOUCHED_STEP.get(task["status"])
        if task["status"] == "approved" and not _seal_holds(task):
            step = _UNSEALED_STEP
        if step and not fingerprints.holds(task.get("profile_fingerprint")):
            touched.append({"id": task["id"], "status": task["status"], "step": step.replace("ID", task["id"])})
    return touched


def last_approval(state: Path) -> dict | None:
    """The project's most recent approval, earlier rounds included: its task, when, and the check commands it was
    given with. The decision brief compares the commands of the task to decide with these.

    The status index gives each record's latest approval date, so only the record that holds the most recent one is
    read; when the index cannot say, or the record read does not hold the date its entry gives, every record is."""
    index = task_index.entries(state)
    if all("approved" in entry and "stamp" in entry for entry in index.values()):
        at, name = None, ""
        for file_name, entry in index.items():
            if isinstance(entry["approved"], str) and (at is None or entry["approved"] > at):
                at, name = entry["approved"], file_name
        if at is None:
            return None
        try:
            latest = _latest_approval(read_task(state, name[:-5]))
        except ValueError:
            latest = None
        if latest is not None and latest["at"] == at:
            return latest
    latest = None
    for path in sorted((state / "tasks").glob("*.json")) if (state / "tasks").is_dir() else []:
        try:
            found = _latest_approval(read_task(state, path.stem))
        except ValueError:
            continue
        if found is not None and (latest is None or found["at"] > latest["at"]):
            latest = found
    return latest


def _latest_approval(task: Task) -> dict | None:
    """The task's most recent approval, earlier rounds included, as last_approval gives it."""
    latest = None
    for entry in [*task["rounds"], task]:
        decision = entry.get("decision") or {}
        if decision.get("outcome") == "approved" and (latest is None or decision["at"] > latest["at"]):
            latest = {"task": task["id"], "at": decision["at"],
                      "checks": entry.get("consultation", {}).get("scope", {}).get("checks", [])}
    return latest
