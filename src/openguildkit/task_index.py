"""Know each task's status without parsing every record, so the edit hook reads only the tasks that can cover it.

The index lives with the task records (ignored by git, refused to agent edits) and maps each record file to its
status and to the size, times and inode the file had when that status was read. An entry is used only while the
file still matches it; otherwise the record is read again and the entry replaced. The index only says which records
can be skipped: the guard still reads and checks every record it does not skip, so a missing, stale or corrupt index
costs time and never changes a decision. It is written whole and atomically, without the project lock, so the hook
never waits and concurrent commands each leave a complete index.
"""

import json
import os
import tempfile
from pathlib import Path

from .storage import file_signature

INDEX_FILE = ".status-index"
SCHEMA_VERSION = 1
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


def _record_status(path: Path) -> str | None:
    """The status a record declares, or None when it cannot be read."""
    try:
        status = json.loads(path.read_bytes().decode("utf-8-sig")).get("status")
    except (OSError, ValueError, RecursionError, AttributeError):
        return None
    return status if isinstance(status, str) else None


def _write_index(directory: Path, entries: dict) -> None:
    """Replace the index in one step; a failure leaves the previous one, which only costs time."""
    content = json.dumps({"schema_version": SCHEMA_VERSION, "tasks": entries}, sort_keys=True, separators=(",", ":"))
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
    directory = state / "tasks"
    try:
        files = sorted((item for item in os.scandir(directory) if item.name.endswith(".json")), key=lambda item: item.name)
    except OSError:
        return []
    known, written = _read_index(directory)
    entries, changed, candidates = {}, False, []
    for entry in files:
        try:
            if not entry.is_file():
                continue
            stamp = list(file_signature(Path(entry.path), entry.stat()))
        except OSError:
            candidates.append(entry.name[:-5])
            continue
        previous = known.get(entry.name)
        if isinstance(previous, dict) and previous.get("stamp") == stamp and stamp[1] + RACY_NANOSECONDS < written:
            status = previous.get("status")
        else:
            # The stamp is taken before the read: if the file changes in between, the next run sees a new stamp.
            status = _record_status(Path(entry.path))
            changed = True
        entries[entry.name] = {"status": status, "stamp": stamp}
        if status not in skipped:
            candidates.append(entry.name[:-5])
    if changed or entries.keys() != known.keys():
        _write_index(directory, entries)
    return candidates
