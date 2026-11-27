"""The policy of a workstation: one JSON file that its administrator deploys, read by the guard hook and the audit log.

The file is `/etc/openguildkit/config.json` (macOS also `/Library/Application Support/OpenGuildKit/config.json`, Windows
`%ProgramData%\\OpenGuildKit\\config.json`). No variable moves it: an agent that can set the environment of a command
must not be able to point the policy elsewhere. A file that cannot be read as an object with known keys is refused with
its name, never ignored.

Entry: policy, audit_setting.
Tests: tests/test_audit_log.py.
"""

import json
import os
import sys
from pathlib import Path

KEYS = ("audit_log",)


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
            found = json.loads(path.read_text(encoding="utf-8-sig"))
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
