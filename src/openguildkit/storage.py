"""Local state helpers shared by the profile and task commands."""

import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


# Windows refuses to replace a file while another process reads it, and to read it while it is
# being replaced; POSIX systems do neither.
RETRIES_BUSY_TARGET = os.name == "nt"
REPLACE_ATTEMPTS = 60
REPLACE_PAUSE = 0.05


def _current_umask() -> int:
    mask = os.umask(0o022)
    os.umask(mask)
    return mask


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(content: bytes, label: str) -> dict:
    try:
        data = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except (UnicodeError, ValueError) as error:
        raise ValueError(f"Invalid JSON in {label}: {error}") from error
    except RecursionError as error:
        raise ValueError(f"Invalid JSON in {label}: nested too deeply") from error
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {label}")
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


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


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
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a symbolic link: {path}")
    if path.exists() and not path.is_file() and not path.is_dir():
        # A device or a pipe, such as /dev/null, cannot be replaced by a renamed file: write to it.
        with path.open("wb") as handle:
            handle.write(content.encode("utf-8"))
        return
    if path.exists() and read_bytes(path) == content.encode("utf-8"):
        return
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


def write_json(path: Path, data: dict) -> None:
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
        raise ValueError(f"Set {LOCK_TIMEOUT_VARIABLE} to a number of seconds between 0 and 3600, or unset it.")
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
                raise ValueError("Another OpenGuildKit command is writing this project. Try again.")
            time.sleep(LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            _release(handle)
