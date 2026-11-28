"""The audit log: what OpenGuildKit itself did, one JSON event per line, chained by SHA-256, off by default.

A person turns it on with OPENGUILDKIT_AUDIT_LOG (1, or the name of a file) or `audit_log` in the workstation policy
(workstation.py). The file lives in .openguildkit/audit/, which the guard protects and Git ignores: a collector reads it
there. Every line holds `prev`, the SHA-256 of the line before it, so `openguildkit audit verify` names the first line
that no longer follows. The log never holds what an edit changes, a reason, or a credential.

Entry: record, refused, verify, reconstruct.
Tests: tests/test_audit_log.py.
"""

import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from . import clock

VARIABLE = "OPENGUILDKIT_AUDIT_LOG"
VERSION = 1
GENESIS = "0" * 64
# The folder is a literal, not project.STATE_DIR: the guard hook reaches this module without importing the project.
FOLDER = ".openguildkit/audit"
DEFAULT_FILE = "audit.jsonl"
TAIL = 65_536  # bytes read at the end of the file to find the previous line; a line is far shorter
MAX_PATHS, MAX_TEXT = 20, 300
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# Each event with the fields it may carry besides v, at, event, project, prev (and reconstructed).
EVENTS = {
    "guard.refused": ("host", "mode", "paths"),
    "guard.flagged": ("host", "mode", "paths"),
    "task.approved": ("task", "by", "signer", "seal"),
    "task.revoked": ("task", "by"),
    "blocker.cleared": ("task", "blocker", "by", "signer"),
    "blocker.waived": ("task", "blocker", "by", "until"),
    "task.authorized": ("task", "action", "target", "decision", "by"),
    "profile.changed": ("by", "change"),
    "org-catalog.pinned": ("by", "name", "commit"),
    "org-catalog.off": ("by", "commit"),
    "host.applied": ("host", "paths"),
}
COMMON = ("v", "at", "event", "project", "prev", "reconstructed")


def log_path(root: Path) -> Path | None:
    """The log of the project, or None while it is off. Raises ValueError for a name that is not a file of the folder."""
    value = os.environ.get(VARIABLE, "").strip()
    if not value:
        from .workstation import audit_setting

        value = audit_setting()
    if not value:
        return None
    name = DEFAULT_FILE if value.lower() in ("1", "true", "on", "yes") else value
    if not _NAME.fullmatch(name):
        raise ValueError(f"{VARIABLE} is 1 or the name of a file in {FOLDER}/ (letters, digits, dot, dash), not {value[:40]!r}")
    return root / FOLDER / name


def is_on(root: Path) -> bool:
    """Whether the log is on for this project. A person who turns it on also has the date of an approval sealed."""
    try:
        return log_path(root) is not None
    except ValueError:
        return False


def _squeezed(value: object, limit: int = MAX_TEXT) -> str:
    return " ".join(str(value).split())[:limit]


def _line(fields: dict, prev: str) -> bytes:
    return json.dumps({**fields, "prev": prev}, separators=(",", ":")).encode("ascii")


def _append(path: Path, fields: dict) -> None:
    """Add one line at the end of the file, under a lock so that two hooks never chain to the same line."""
    from .storage import project_lock

    root = path.parent.parent.parent
    folder = path.parent
    if folder.resolve() != root.resolve() / FOLDER or path.is_symlink():
        raise ValueError(f"{FOLDER} or its file is a link or leaves the project: nothing is written")
    with project_lock(folder):
        ignore = folder / ".gitignore"
        if ignore.is_symlink():  # A link to a file that does not exist would have the write create it elsewhere.
            raise ValueError(f"{FOLDER}/.gitignore is a link: nothing is written")
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags, 0o600), "a+b") as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - TAIL))
            tail = handle.read()
            last = tail.rstrip(b"\n").rsplit(b"\n", 1)[-1]
            # A line cut short by a crash stays as it is, on its own line, and verify names it.
            handle.write((b"" if not size or tail.endswith(b"\n") else b"\n")
                         + _line(fields, hashlib.sha256(last).hexdigest() if size else GENESIS) + b"\n")


def record(root: Path, event: str, **fields) -> None:
    """Write one event when the log is on. Never raises: a log that cannot be written says so on standard error and
    leaves the command, or the answer of the hook, as it was."""
    try:
        path = log_path(root)
        if path is None:
            return
        if event not in EVENTS:
            raise ValueError(f"unknown event {event}")
        shown = {key: value for key, value in fields.items() if key in EVENTS[event] and value not in (None, "", [])}
        shown = {key: [_squeezed(item) for item in value[:MAX_PATHS]] if isinstance(value, list) else _squeezed(value)
                 for key, value in shown.items()}
        _append(path, {"v": VERSION, "at": clock.real_timestamp(), "event": event, "project": _squeezed(root.name, 100), **shown})
    except Exception as error:  # An audit failure must not change what the command or the hook does.
        print(f"OpenGuildKit: the audit log could not be written ({_squeezed(error, 160)}): {event} is not in it.",
              file=sys.stderr)


def refused(raw: str | None, project: Path | None, event: str = "guard.refused") -> None:
    """The guard hook refused an edit (guard.refused) or flagged it in observe (guard.flagged): write the event with
    the paths and the host, never what the edit changes."""
    from .project import project_root

    try:
        root = project_root(project)
        if not (root / ".openguildkit").is_dir() or log_path(root) is None:
            return
        paths = []
        try:
            from .guard import edited_paths

            for item in edited_paths(json.loads(raw or "")):
                try:
                    paths.append((Path(item) if os.path.isabs(item) else root / item).resolve().relative_to(root.resolve()).as_posix())
                except (OSError, ValueError):
                    paths.append(item)
        except Exception:  # A hook input the guard could not read is refused without paths.
            paths = []
        try:
            from .storage import load_json

            profile = load_json(root / ".openguildkit" / "project.json")
        except (OSError, ValueError):
            profile = {}
        facts = profile if isinstance(profile, dict) else {}
        record(root, event, host=facts.get("host"), mode=facts.get("guard"), paths=paths)
    except Exception as error:
        print(f"OpenGuildKit: the audit log could not be written ({_squeezed(error, 160)}): {event} is not in it.",
              file=sys.stderr)


def problem_with_event(event: object) -> str | None:
    """Why a parsed line is not an event of this schema, or None."""
    if not isinstance(event, dict):
        return "an event is a JSON object"
    if event.get("v") != VERSION:
        return f"v is {VERSION}"
    if event.get("event") not in EVENTS:
        return f"unknown event {event.get('event')!r}"
    for key in ("at", "project", "prev"):
        if not isinstance(event.get(key), str) or not event[key]:
            return f"{key} is missing"
    unknown = sorted(set(event) - set(COMMON) - set(EVENTS[event["event"]]))
    return f"unknown field {unknown[0]!r} for {event['event']}" if unknown else None


def verify(path: Path) -> tuple[int, str | None]:
    """How many events the file holds before its first broken line, and what is wrong with that line, or None: a line
    that does not follow the one before it, or that follows it but is not an event of EVENTS (docs/audit-log.md)."""
    # An export redirected on Windows, or a log checked out with autocrlf, ends its lines with \r\n: the \r is not
    # part of the hashed event.
    lines = [line.removesuffix(b"\r") for line in path.read_bytes().split(b"\n")]
    cut = lines.pop()  # what follows the last newline: nothing in a complete file
    prev, count = GENESIS, 0
    for number, raw in enumerate(lines, start=1):
        try:
            event = json.loads(raw)
        except ValueError:
            return count, f"line {number} is not a JSON event"
        if not isinstance(event, dict) or event.get("prev") != prev:
            after = f"line {number - 1}" if number > 1 else "the start of the chain: the lines before it were removed"
            return count, f"line {number} does not follow {after}" + (
                ": a line was changed or removed, or one was inserted" if number > 1 else "")
        wrong = problem_with_event(event)
        if wrong:
            return count, f"line {number} follows the chain but is not an event of the schema: {wrong}"
        prev, count = hashlib.sha256(raw).hexdigest(), count + 1
    return count, f"line {count + 1} is not terminated: the write was cut short" if cut else None


def default_path(root: Path) -> Path:
    return log_path(root) or root / FOLDER / DEFAULT_FILE


def since_day(text: str | None) -> str | None:
    if text is None:
        return None
    try:
        return date.fromisoformat(text).isoformat() if re.fullmatch(r"\d{4}-\d\d-\d\d", text) else _bad(text)
    except ValueError:
        return _bad(text)


def _bad(text: str) -> str:
    raise ValueError(f"--since is a day written YYYY-MM-DD, not {text[:40]!r}.")


def reconstruct(root: Path, since: str | None = None) -> list[bytes]:
    """The approvals of the exported records, the changes of the profile history and the pins and stops of the
    organization catalog the lock keeps, as chained event lines, oldest first. A profile change, a pin and a stop carry
    a day only: their event is dated 00:00:00 UTC of that day."""
    from .decisions import exported_records
    from .storage import read_json

    state, events = root / ".openguildkit", []
    for _, found in exported_records(state):
        decision = found.get("decision") if found else None
        if found and isinstance(decision, dict) and isinstance(decision.get("at"), str) \
                and isinstance(decision.get("by"), str):
            events.append({"at": decision["at"], "event": "task.approved", "task": found["task"], "by": decision["by"],
                           "signer": decision.get("signer"), "seal": decision.get("seal")})
    profile = read_json(state / "project.json") if (state / "project.json").is_file() else {}
    for change in profile.get("changes", []) if isinstance(profile.get("changes"), list) else []:
        if isinstance(change, dict) and isinstance(change.get("on"), str):
            events.append({"at": f"{change['on']}T00:00:00+00:00", "event": "profile.changed", "by": change.get("by"),
                           "change": change.get("change")})
    lock = read_json(state / "catalog.lock.json") if (state / "catalog.lock.json").is_file() else {}
    history = lock.get("organization_history") if isinstance(lock, dict) else None
    for entry in history if isinstance(history, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("on"), str) and entry.get("action") in ("pinned", "stopped"):
            events.append({"at": f"{entry['on']}T00:00:00+00:00", "by": entry.get("by"), "commit": entry.get("commit"),
                           "event": "org-catalog.pinned" if entry["action"] == "pinned" else "org-catalog.off"})
    lines, prev = [], GENESIS
    for item in sorted(events, key=lambda item: item["at"]):
        if since and item["at"][:10] < since:
            continue
        shown = {key: _squeezed(value) for key, value in item.items() if value not in (None, "")}
        line = _line({"v": VERSION, "at": shown.pop("at"), "event": shown.pop("event"), "project": _squeezed(root.name, 100),
                      **shown, "reconstructed": True}, prev)
        lines.append(line)
        prev = hashlib.sha256(line).hexdigest()
    return lines
