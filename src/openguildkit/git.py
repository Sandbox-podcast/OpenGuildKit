"""Runs Git for every module: one place for its options, for a machine without Git, and for file names read with `-z` as
they are on disk.

Entry: run, text, names, split_names, unquote
Tests: tests/test_guard.py, tests/test_trace.py
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

# No way to reach a network: a replaced or lazily fetched object, or a remote protocol, would read outside the copy.
_OFFLINE = ("--no-replace-objects", "-c", "protocol.allow=never")
_ESCAPE = re.compile(rb'\\([0-7]{3}|.)')
_ESCAPED = {b"a": b"\a", b"b": b"\b", b"t": b"\t", b"n": b"\n", b"v": b"\v", b"f": b"\f", b"r": b"\r"}


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


def required(root: Path, *args: str, needs: str, stdin: bytes | None = None,
             offline: bool = False) -> subprocess.CompletedProcess[bytes]:
    """Git's result in root, as run gives it, for a command that cannot go on without Git: needs names that command in
    the error raised when Git is not installed."""
    result = run(root, *args, stdin=stdin, offline=offline)
    if result is None:
        raise ValueError(f"{needs} needs Git: it is not installed or not on the PATH.")
    return result


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


def unquote(name: str) -> str:
    """A name as Git printed it without -z, as it is on disk: records exported before names were read with -z hold
    the quoted form. Git quotes a name only to escape something in it, so a name without a backslash is left as it is."""
    if len(name) < 2 or name[0] != '"' or name[-1] != '"' or "\\" not in name:
        return name
    raw = _ESCAPE.sub(lambda match: bytes([int(match[1], 8)]) if len(match[1]) == 3 else _ESCAPED.get(match[1], match[1]),
                      name[1:-1].encode("utf-8"))
    return raw.decode("utf-8", errors="replace")
