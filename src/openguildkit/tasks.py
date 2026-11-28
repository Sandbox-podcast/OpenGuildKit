"""Read, write and create the task records of a project, list them, and follow the tasks each one waits for.

The rest of the task path has its own modules: tasks_record (the shape of a record), tasks_approval (whether an
approval holds), tasks_blockers, tasks_review (consultation, review and passes), tasks_closing (decision, result,
closing) and tasks_status (the next step and the line of the task list)."""

import contextlib
import difflib
import importlib
import json
import marshal
import re
import time
import uuid
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from . import task_index
from .decisions import base_commit, check_decision_seal, revisions_outside_history
from .project import Fingerprints
from .results import DONE_STATUSES
from .storage import file_signature, read_json, write_text
from .tasks_approval import approval_problem
from .tasks_blockers import _DAY
from .tasks_record import STATUSES, record_problem, timestamp, validate_brief
from .tasks_status import kept_line, line_to_keep, task_row

ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{digit}" for prefix in ("com", "lpt") for digit in range(1, 10)
}


def write_task(path: Path, task: dict) -> None:
    """Write a task record without indentation, which made 29 % of a closed task's weight: git ignores the records
    and only the commands read them. Nothing compares their bytes (seals and digests hash the parsed fields), and any
    JSON reader, an earlier release's included, reads the same fields."""
    write_text(path, json.dumps(task, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def task_path(state: Path, task_id: str) -> Path:
    if task_id in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{task_id} is a reserved file name on Windows. Choose another task ID.")
    if len(task_id) > 64 or not ID_PATTERN.fullmatch(task_id):
        raise ValueError("Use a task ID of up to 64 lowercase letters, digits and separating hyphens.")
    path = state / "tasks" / f"{task_id}.json"
    if path.resolve() != path:
        raise ValueError(f"Task records must stay inside their project: {path}")
    return path


def _unknown_task(state: Path, task_id: str) -> str:
    """The error for a task ID with no record, with the closest existing ID when one is near."""
    known = sorted(path.stem for path in (state / "tasks").glob("*.json")) if (state / "tasks").is_dir() else []
    close = difflib.get_close_matches(task_id, known, n=1)
    hint = f"Did you mean {close[0]}? " if close else ""
    return f"Unknown task: {task_id}. {hint}Run openguildkit task list to see the tasks."


class KeptRecords:
    """The task records a process that outlives its commands (openguildkit ui) has read, by file signature, so that
    listing the tasks again after nothing changed reads none. A record is kept serialized and handed out as a new
    copy, because commands change what they read. What would pass the limit in bytes is read as it always was."""

    def __init__(self, limit: int = 256 * 1024 * 1024):
        self.limit = limit
        self.size = 0
        self.entries: dict[Path, tuple[tuple, bytes, int]] = {}

    def get(self, path: Path, signature: tuple | None) -> dict | None:
        kept = self.entries.get(path)
        return marshal.loads(kept[1]) if kept is not None and signature is not None and kept[0] == signature else None

    def settled(self, path: Path, stat: tuple | None) -> dict | None:
        """The record kept for a file whose size, times and inode are unchanged and whose modification was settled
        when it was read (older than the racy window of task_index): no need to read the file for its digest."""
        kept = self.entries.get(path)
        if kept is None or stat is None or kept[0][:4] != stat or stat[1] + task_index.RACY_NANOSECONDS >= kept[2]:
            return None
        return marshal.loads(kept[1])

    def put(self, path: Path, signature: tuple | None, record: dict, read_at: int = 0) -> None:
        if signature is None:
            return
        blob = marshal.dumps(record)
        before = self.entries.pop(path, None)
        self.size -= len(before[1]) if before else 0
        if self.size + len(blob) <= self.limit:
            self.entries[path] = (signature, blob, read_at)
            self.size += len(blob)


# Where records are kept: only inside keeping_records. A command that runs once reads each record once.
_KEPT: KeptRecords | None = None


@contextlib.contextmanager
def keeping_records(kept: KeptRecords):
    """Inside the block, read_task serves the records of `kept` while their file is as it was, and adds the others."""
    global _KEPT
    before, _KEPT = _KEPT, kept
    try:
        yield
    finally:
        _KEPT = before


def read_task(state: Path, task_id: str) -> dict:
    path = task_path(state, task_id)
    if not path.is_file():
        raise ValueError(_unknown_task(state, task_id))
    kept = _KEPT
    if kept is None:
        return _validated_task(state, path, task_id)
    task = kept.settled(path, file_signature(path))
    if task is not None:
        return task
    # The signature is taken before the read: a file that changes in between is read again next time.
    read_at = time.time_ns()
    signature = file_signature(path, content=True)
    task = kept.get(path, signature)
    if task is None:
        task = _validated_task(state, path, task_id)
    kept.put(path, signature, task, read_at)
    return task


def _validated_task(state: Path, path: Path, task_id: str) -> dict:
    task = read_json(path)
    if task.get("schema_version") != 1 or task.get("id") != task_id:
        raise ValueError(f"Unsupported or mismatched task record: {path}")
    problem = record_problem(task)
    if problem:
        # Task records are not under version control (.openguildkit/.gitignore lists tasks/).
        raise ValueError(
            f"Task record {task_id} is damaged: {problem}. Restore {path.relative_to(state.parent).as_posix()} from a "
            "backup, or delete that file and open a new task with openguildkit task new."
        )
    return task


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


def waiting_for(task: dict, statuses: dict[str, str]) -> list[dict]:
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
    record = {
        "schema_version": 1,
        "id": task_id,
        "brief": brief,
        "created_at": timestamp(),
        "status": "draft",
        "rounds": [],
        **(lane or {}),
        # Who asked for the work (requester.py): written only when named, so a task without one is as before.
        **({"requested_by": requested_by} if requested_by is not None else {}),
    }
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
               since: str | None = None, until: str | None = None, *, profile: dict | None = None,
               catalog: dict | None = None, root: Path | None = None, read: dict | None = None,
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
    fingerprints = Fingerprints(profile, catalog) if judged else None
    skip = {*skip, *(set(STATUSES) - {status} if status else ())}
    index = task_index.entries(state) if indexed else {}
    entries, statuses, learnt = [], {}, False

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
                       if judged else None)
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


def _seal_holds(task: dict) -> bool:
    try:
        check_decision_seal(task)
    except ValueError:
        return False
    return True


def tasks_touched(state: Path, profile: dict, catalog: dict) -> list[dict]:
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


def _latest_approval(task: dict) -> dict | None:
    """The task's most recent approval, earlier rounds included, as last_approval gives it."""
    latest = None
    for entry in [*task["rounds"], task]:
        decision = entry.get("decision") or {}
        if decision.get("outcome") == "approved" and (latest is None or decision["at"] > latest["at"]):
            latest = {"task": task["id"], "at": decision["at"],
                      "checks": entry.get("consultation", {}).get("scope", {}).get("checks", [])}
    return latest


# #506 moved these names to their own modules: they are read from here for one release, then this goes.
_MOVED = {name: module for module, names in (
    ("tasks_record", "board_brief_problem"),
    ("tasks_approval", ("revoke_command rule_changes require_approval decided_message stale_review_message "
      "require_current_scope")),
    ("tasks_blockers", ("waiver_policy expired_on expired_waivers expired_waiver_step expired_waiver_problem "
      "require_blocker_status resolve_blocker unresolved_blockers verification_blocker_problems")),
    ("tasks_review", ("cited_evidence record_consultation ROUND_FIELDS archived_round kept_passes kept_passes_note "
      "previous_round_line check_command_lines decision_text record_review start_pass "
      "earlier_sequential_pass submit_pass pass_progress assemble_review")),
    ("tasks_closing", ("CHANGED_EVIDENCE_GROUP evidence_states changed_evidence record_result defer_evidence "
      "complete_task SENSITIVE_GROUP NOT_RUN_GROUP OTHER_RULES_GROUP VERDICTS_GROUP NO_COMMAND "
      "points_left_open record_deliberation record_decision revoke_approval ACTIONS "
      "record_authorization")),
    ("tasks_status", "next_step next_command passes_left state_refusal STALE_DAYS days_since decision_words"),
) for name in names.split()}


def __getattr__(name: str):
    if name in _MOVED:
        return getattr(importlib.import_module(f".{_MOVED[name]}", __package__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
