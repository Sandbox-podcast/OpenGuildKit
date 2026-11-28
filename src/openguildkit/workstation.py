"""Reads the workstation policy file that an administrator deploys (`/etc/openguildkit/config.json` and its
equivalents), for the guard hook and the audit log.

The file is `/etc/openguildkit/config.json` (macOS also `/Library/Application Support/OpenGuildKit/config.json`, Windows
`%ProgramData%\\OpenGuildKit\\config.json`). No variable moves it: an agent that can set the environment of a command
must not be able to point the policy elsewhere. A file that cannot be read as an object with known keys is refused with
its name, never ignored.

Entry: policy, audit_setting, no_profile_answer.
Tests: tests/test_audit_log.py, tests/test_managed_settings.py.
"""

import os
import sys
from pathlib import Path

from .storage import load_json

KEYS = ("audit_log", "no_profile")
NO_PROFILE = ("allow", "observe", "refuse")


def _locations() -> tuple[Path, ...]:
    if os.name == "nt":
        return (Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OpenGuildKit" / "config.json",)
    mac = (Path("/Library/Application Support/OpenGuildKit/config.json"),) if sys.platform == "darwin" else ()
    return (*mac, Path("/etc/openguildkit/config.json"))


LOCATIONS = _locations()


def policy() -> dict:
    """The first policy file that exists, as a dict; empty when the workstation has none."""
    for path in LOCATIONS:
        if not path.is_file():
            continue
        try:
            found = load_json(path)
        except (OSError, ValueError) as error:
            raise ValueError(f"{path.as_posix()} cannot be read as the workstation policy: {error}") from error
        if not isinstance(found, dict) or set(found) - set(KEYS):
            raise ValueError(f"{path.as_posix()} must be a JSON object with the keys {', '.join(KEYS)} only.")
        return found
    return {}


def audit_setting() -> str:
    """What `audit_log` says: "" (off), "1" (the default file) or the name of a file of the audit folder."""
    value = policy().get("audit_log")
    return "1" if value is True else value if isinstance(value, str) else ""


def no_profile_answer(event: str, project: Path | None) -> tuple[int, str, str] | None:
    """What the guard hook answers in a folder with no OpenGuildKit profile, when the workstation policy asks for more
    than the silent exit 0 of today: `no_profile` is "allow" (the default), "observe" (the hook flags the edit) or
    "refuse" (it refuses the edit). None when a profile exists, whatever its guard says, or the policy allows."""
    start = project.resolve() if project is not None else Path.cwd().resolve()
    if any((folder / ".openguildkit").is_dir() for folder in ([start] if project is not None else [start, *start.parents])):
        return None
    from .guard import hook_answer

    try:
        found = policy().get("no_profile", "allow")
        error = None if found in NO_PROFILE else f"no_profile is one of {', '.join(NO_PROFILE)}, not {str(found)[:40]!r}"
    except ValueError as problem:
        error = str(problem)
    if error is None and found == "allow":
        return None
    detail = error or "this folder has no OpenGuildKit profile, and the policy of this workstation asks for one"
    return hook_answer(event, "enforce" if error or found == "refuse" else "observe", "unchecked", detail)
