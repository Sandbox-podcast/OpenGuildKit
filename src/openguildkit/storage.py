"""Local state helpers shared by the profile and task commands."""

import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path


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


def read_json(path: Path) -> dict:
    return parse_json(path.read_bytes(), str(path))


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a symbolic link: {path}")
    if path.exists() and path.read_bytes() == content.encode("utf-8"):
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
            os.replace(temporary_path, path)
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
            lock_file.unlink(missing_ok=True)
            directory.rmdir()


@contextmanager
def _held_lock(lock_file: Path):
    with lock_file.open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Another OpenGuildKit command is writing this project. Try again.") from error
        yield
