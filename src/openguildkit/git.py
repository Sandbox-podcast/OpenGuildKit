"""Run Git: one place for its options, for a machine without Git, and for reading file names as they are on disk."""

import os
import shutil
import subprocess
from pathlib import Path

# No way to reach a network: a replaced or lazily fetched object, or a remote protocol, would read outside the copy.
_OFFLINE = ("--no-replace-objects", "-c", "protocol.allow=never")


def run(root: Path, *args: str, stdin: bytes | None = None, offline: bool = False) -> subprocess.CompletedProcess[bytes] | None:
    """Git's result in root, its output in bytes; None when Git is not installed. Optional locks are off, so reading
    never refreshes the index, and Git never asks for a password."""
    if shutil.which("git") is None:
        return None
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", **({"GIT_NO_LAZY_FETCH": "1"} if offline else {})}
    try:
        return subprocess.run(["git", *(_OFFLINE if offline else ()), "-C", str(root), *args], input=stdin,
                              capture_output=True, check=False, env=env)
    except OSError:
        return None


def text(root: Path, *args: str) -> str | None:
    """What Git prints; None when it fails or is not installed."""
    result = run(root, *args)
    return None if result is None or result.returncode else result.stdout.decode("utf-8", errors="replace")


def split_names(output: bytes) -> list[str]:
    """The names of a listing Git printed with -z, which never quotes them."""
    return [name for name in output.decode("utf-8", errors="replace").split("\0") if name]


def names(root: Path, command: str, *args: str) -> list[str] | None:
    """The file names a Git command lists, read with -z: a name with an accent, a space or a quote comes back as it is
    on disk, not as "docs/r\\303\\251sum\\303\\251.md". None when Git fails or is not installed."""
    result = run(root, command, "-z", *args)
    return None if result is None or result.returncode else split_names(result.stdout)

