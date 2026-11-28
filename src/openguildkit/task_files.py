"""Finds and reads a task record: its file, its check, and the records kept between the requests of the web page.

Entry: task_path, KeptRecords, keeping_records, read_task
Tests: tests/test_approval_lifecycle.py, tests/test_before_delivered_review.py, tests/test_blocker_clearances.py,
tests/test_blockers.py, tests/test_clock.py, tests/test_closing_points.py, tests/test_deliberation.py,
tests/test_delivered_review.py, tests/test_evidence_fingerprints.py, tests/test_requester.py, tests/test_retro.py,
tests/test_short_lane.py, tests/test_webui.py
"""

import contextlib
import difflib
import marshal
import re
import time
from pathlib import Path
from typing import cast

from . import task_index
from .records import Task, as_dict
from .storage import file_signature, read_json
from .tasks_record import task_record_problem

ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{digit}" for prefix in ("com", "lpt") for digit in range(1, 10)
}


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

    def get(self, path: Path, signature: tuple | None) -> Task | None:
        kept = self.entries.get(path)
        return marshal.loads(kept[1]) if kept is not None and signature is not None and kept[0] == signature else None

    def settled(self, path: Path, stat: tuple | None) -> Task | None:
        """The record kept for a file whose size, times and inode are unchanged and whose modification was settled
        when it was read (older than the racy window of task_index): no need to read the file for its digest."""
        kept = self.entries.get(path)
        if kept is None or stat is None or kept[0][:4] != stat or stat[1] + task_index.RACY_NANOSECONDS >= kept[2]:
            return None
        return marshal.loads(kept[1])

    def put(self, path: Path, signature: tuple | None, record: Task, read_at: int = 0) -> None:
        if signature is None:
            return
        blob = marshal.dumps(as_dict(record))
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


def read_task(state: Path, task_id: str) -> Task:
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


def _validated_task(state: Path, path: Path, task_id: str) -> Task:
    task = cast(Task, read_json(path))  # Checked below: task_record_problem names the first field that departs.
    if task.get("schema_version") != 1 or task.get("id") != task_id:
        raise ValueError(f"Unsupported or mismatched task record: {path}")
    problem = task_record_problem(task)
    if problem:
        # Task records are not under version control (.openguildkit/.gitignore lists tasks/).
        raise ValueError(
            f"Task record {task_id} is damaged: {problem}. Restore {path.relative_to(state.parent).as_posix()} from a "
            "backup, or delete that file and open a new task with openguildkit task new."
        )
    return task
