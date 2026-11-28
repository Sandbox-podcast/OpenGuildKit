"""Writes files atomically, refuses symbolic links, and serialises writing commands with the project lock.

Entry: parse_json, load_json, unique_fields, read_bytes, read_json, file_signature, json_text, print_json
Tests: tests/test_storage.py
"""

import hashlib
import json
import os
import stat
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import OgkError

# Windows refuses to replace a file while another process reads it, and to read it while it is
# being replaced; POSIX systems do neither.
RETRIES_BUSY_TARGET = os.name == "nt"
REPLACE_ATTEMPTS = 60
REPLACE_PAUSE = 0.05


def _current_umask() -> int:
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A JSON object whose fields each appear once: json.loads keeps the last of two silently."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise OgkError("OGK-CORE-008", f"duplicate JSON field {key!r}")
        result[key] = value
    return result


class NestedTooDeeply(ValueError):
    """JSON nested deeper than the parser can follow: refused even where invalid JSON is left aside."""


def _loads(content: bytes, pairs: Callable | None) -> Any:
    """JSON read as UTF-8 with or without a byte order mark; a value nested too deeply is a ValueError of one line, not
    a RecursionError and its traceback."""
    try:
        return json.loads(content.decode("utf-8-sig"), object_pairs_hook=pairs)
    except RecursionError as error:
        raise NestedTooDeeply("JSON nested too deeply") from error


def load_json(path: Any, *, pairs: Callable | None = None) -> Any:
    """The JSON value of a file (a path or a package resource). Text that is not UTF-8, JSON that is not valid and a
    value nested too deeply raise a ValueError of one line, which the caller prefixes with what the file is; an
    unreadable file raises OSError."""
    return _loads(path.read_bytes(), pairs)


def parse_json(content: bytes, label: str) -> dict:
    try:
        data = _loads(content, unique_fields)
    except ValueError as error:
        raise OgkError("OGK-CORE-009", f"Invalid JSON in {label}: {error}") from error
    if not isinstance(data, dict):
        raise OgkError("OGK-CORE-010", f"Expected a JSON object in {label}")
    return data


def read_bytes(path: Path) -> bytes:
    """Read a project file, waiting up to three seconds while another process replaces it on Windows."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            return path.read_bytes()
        except PermissionError:
            if not RETRIES_BUSY_TARGET or attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_PAUSE)
    raise AssertionError("unreachable")


def read_json(path: Path) -> dict:
    return parse_json(read_bytes(path), str(path))


def file_signature(path: Path, info: os.stat_result | None = None, *, content: bool = False) -> tuple:
    """What changes when a file is written: its size, modification and change times and inode, and with content a
    digest of its bytes. The one signature the task index and the caches of the catalog and its lock compare.

    The times alone miss a rewrite of the same size within one tick of a coarse file system (HFS+, FAT, SMB) or one
    that restores the modification time, and Windows reports the creation time as the change time: the task index
    reads again an entry written less than RACY_NANOSECONDS before it (task_index.py), and a cache of a file's parsed
    content asks for the digest. None for a file that cannot be read.
    """
    try:
        if not content:
            info = info or path.stat()
            return (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)
        with open(path, "rb") as handle:
            info = os.fstat(handle.fileno())
            digest = hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None
    return (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, digest)


def canonical_sha256(value: object) -> str:
    """The SHA-256 of a JSON value whatever the order of its keys: the one canonical form of the seals, the record
    digests and the profile fingerprint."""
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """The SHA-256 of a file's bytes, in hexadecimal; OSError when it cannot be read."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


# The version of the shape of a --json answer and of an error under --json (#484). With OPENGUILDKIT_JSON_ENVELOPE=1,
# a --json answer comes inside {"schema_version", "command", "data"}; without it, as it always came.
SCHEMA_VERSION = 1
ENVELOPE_VARIABLE = "OPENGUILDKIT_JSON_ENVELOPE"
_ANSWERING: list[str | None] = [None]


@contextmanager
def answering(command: str | None):
    """Inside the block, print_json answers the --json of `command` (its words, such as "task checks"); None when the
    command was not asked for JSON, whose JSON output (a template to fill in) never takes the envelope."""
    before, _ANSWERING[0] = _ANSWERING[0], command
    try:
        yield
    finally:
        _ANSWERING[0] = before


def print_json(data) -> None:
    """Print a command's JSON answer on standard output, as every command with --json does, in the envelope when
    OPENGUILDKIT_JSON_ENVELOPE is 1."""
    if _ANSWERING[0] is not None and os.environ.get(ENVELOPE_VARIABLE) == "1":
        data = {"schema_version": SCHEMA_VERSION, "command": _ANSWERING[0], "data": data}
    print(json_text(data), end="")


def _replace(source: Path, target: Path) -> None:
    """Put the new file in place, waiting up to three seconds for a reader to let go of the old one."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not RETRIES_BUSY_TARGET or attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_PAUSE)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() and (not path.exists() or path.is_file() or path.is_dir()):
        raise OgkError("OGK-CORE-011", f"Refusing to replace a symbolic link: {path}")
    if path.exists() and not path.is_file() and not path.is_dir():
        # A device or a pipe, such as /dev/null, cannot be replaced by a renamed file: write to it.
        with path.open("wb") as handle:
            handle.write(content.encode("utf-8"))
        return
    if path.exists() and read_bytes(path) == content.encode("utf-8"):
        return
    import tempfile  # Only a write needs it, and it imports shutil, random and the compressors (#539).

    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(content.encode("utf-8"))
            temporary.close()
            if path.exists():
                temporary_path.chmod(stat.S_IMODE(path.stat().st_mode))
            else:
                # Temporary files are private; a new file gets the usual permissions.
                temporary_path.chmod(0o666 & ~_current_umask())
            _replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    write_text(path, json_text(data))


@contextmanager
def project_lock(directory: Path):
    created = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    lock_file = directory / ".lock"
    if lock_file.is_symlink():
        raise ValueError(f"Refusing a symbolic link as project lock: {lock_file}")
    try:
        with _held_lock(lock_file):
            yield
    finally:
        # A command that failed in a folder it created leaves nothing behind.
        if created and [entry.name for entry in directory.iterdir()] == [".lock"]:
            try:
                lock_file.unlink(missing_ok=True)
                directory.rmdir()
            except OSError:
                pass  # Another command is waiting on the lock in this folder and will use it.


LOCK_TIMEOUT_VARIABLE = "OPENGUILDKIT_LOCK_TIMEOUT"
DEFAULT_LOCK_TIMEOUT = 10.0
LOCK_POLL_SECONDS = 0.05


def lock_timeout() -> float:
    """Seconds a writing command waits for another one to release the project lock."""
    value = os.environ.get(LOCK_TIMEOUT_VARIABLE, "").strip()
    if not value:
        return DEFAULT_LOCK_TIMEOUT
    try:
        seconds = float(value)
    except ValueError:
        seconds = -1.0
    if not 0 <= seconds <= 3600:
        raise OgkError("OGK-CORE-014", f"Set {LOCK_TIMEOUT_VARIABLE} to a number of seconds between 0 and 3600, or unset it.")
    return seconds


def _try_lock(handle) -> bool:
    """Take the exclusive lock without blocking; False when another process holds it."""
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _release(handle) -> None:
    """Release the lock explicitly: Windows keeps a byte-range lock until it is unlocked."""
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def _held_lock(lock_file: Path):
    # Polling rather than a blocking call: it works the same on Windows and POSIX and bounds the wait.
    deadline = time.monotonic() + lock_timeout()
    with lock_file.open("a+b") as handle:
        handle.seek(0)
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise OgkError("OGK-CORE-012", "Another OpenGuildKit command is writing this project. Try again.")
            time.sleep(LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            _release(handle)
