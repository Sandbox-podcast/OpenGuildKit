"""Each task's status without parsing every record, so the edit hook reads only the tasks that can cover an edit, and
task list skips the records it does not list and lists closed tasks from the line it kept.

The index lives with the task records (ignored by git, refused to agent edits) and maps each record file to its
status, to the date of its latest approval (earlier rounds included) and to the size, times and inode the file had
when they were read; task list adds that it read the
record whole and, for a closed task, the line it printed (tasks.list_tasks). An entry is used only while the file
still matches it; otherwise the record is read again and the entry replaced. The index only says which records can be
skipped: the guard still reads every record it does not skip, check reads them all, so a missing, stale or corrupt
index costs time and never changes a decision. It is written whole and atomically, without the project lock, so the
hook never waits and concurrent commands each leave a complete index.

Entry: tasks_with_status, entries, save
Tests: tests/test_performance.py
"""

import json
import os
from pathlib import Path

from .storage import file_signature

INDEX_FILE = ".status-index"
SCHEMA_VERSION = 2  # 2 adds "approved", the date of the record's latest approval (tasks.last_approval).
# A file changed less than this long before the index was written may have changed again within the same
# timestamp tick of a coarse file system, so its entry is checked again (2 s covers FAT).
RACY_NANOSECONDS = 2_000_000_000


def _read_index(directory: Path) -> tuple[dict, int]:
    """The entries of the index and its modification time; nothing when it is missing or unreadable."""
    try:
        with open(directory / INDEX_FILE, "rb") as handle:
            written = os.fstat(handle.fileno()).st_mtime_ns
            data = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}, 0
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("tasks"), dict):
        return {}, 0
    return data["tasks"], written


def latest_approval_at(record: object) -> str | None:
    """When the record was last approved, earlier rounds included; None when it never was or cannot say."""
    if not isinstance(record, dict):
        return None
    rounds = record.get("rounds")
    latest = None
    for entry in [*(rounds if isinstance(rounds, list) else []), record]:
        decision = entry.get("decision") if isinstance(entry, dict) else None
        if isinstance(decision, dict) and decision.get("outcome") == "approved" and isinstance(decision.get("at"), str) \
                and (latest is None or decision["at"] > latest):
            latest = decision["at"]
    return latest


def _record_status(path: Path) -> tuple[str | None, str | None]:
    """The status a record declares and the date of its latest approval; None for what cannot be read."""
    try:
        record = json.loads(path.read_bytes().decode("utf-8-sig"))
        status = record.get("status")
    except (OSError, ValueError, RecursionError, AttributeError):
        return None, None
    return (status if isinstance(status, str) else None), latest_approval_at(record)


def _write_index(directory: Path, entries: dict) -> None:
    """Replace the index in one step; a failure leaves the previous one, which only costs time."""
    # Not sorted: the entries come in file name order, and a line keeps the order of the fields task list prints.
    content = json.dumps({"schema_version": SCHEMA_VERSION, "tasks": entries}, separators=(",", ":"))
    import tempfile  # Not for the hook that only reads the index (#539).

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=f"{INDEX_FILE}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content.encode("utf-8"))
        os.replace(temporary, directory / INDEX_FILE)
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def tasks_with_status(state: Path, skipped: set[str]) -> list[str]:
    """IDs of the task records whose status may be outside skipped, by file name order.

    A record whose status cannot be read is returned, so the caller handles it as it would without the index.
    """
    return [name[:-5] for name, entry in entries(state).items() if entry["status"] not in skipped]


def entries(state: Path) -> dict[str, dict]:
    """Each task record file's entry, by file name in name order: the status it declares ("status", None when it
    cannot be read), the date of its latest approval ("approved") and the signature of the file it was read from ("stamp"), with what task list added to it
    (tasks.list_tasks). An entry that no longer matches its file is read again and replaced, which drops the rest."""
    directory = state / "tasks"
    try:
        files = sorted((item for item in os.scandir(directory) if item.name.endswith(".json")), key=lambda item: item.name)
    except OSError:
        return {}
    known, written = _read_index(directory)
    current: dict[str, dict] = {}
    changed = False
    for entry in files:
        try:
            if not entry.is_file():
                continue
            stamp = list(file_signature(Path(entry.path), entry.stat()))
        except OSError:
            current[entry.name] = {"status": None}  # Kept out of the index: the next run looks again.
            continue
        previous = known.get(entry.name)
        if isinstance(previous, dict) and isinstance(previous.get("status"), str | None) and \
                isinstance(previous.get("approved"), str | None) and previous.get("stamp") == stamp and stamp[1] + RACY_NANOSECONDS < written:
            current[entry.name] = previous
        else:
            # The stamp is taken before the read: if the file changes in between, the next run sees a new stamp.
            status, approved = _record_status(Path(entry.path))
            current[entry.name] = {"status": status, "approved": approved, "stamp": stamp}
            changed = True
    if changed or {name for name, entry in current.items() if "stamp" in entry} != known.keys():
        save(state, current)
    return current


def save(state: Path, entries: dict[str, dict]) -> None:
    """Write these entries as the whole index, those of files that could not be read left out."""
    _write_index(state / "tasks", {name: entry for name, entry in entries.items() if "stamp" in entry})
