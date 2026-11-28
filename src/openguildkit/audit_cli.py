"""The audit commands: verify the chain of the audit log, or export its events for a SIEM (audit_log.py).

Entry: add_parser, run.
Tests: tests/test_audit_log.py.
"""

import sys
from pathlib import Path

from . import audit_log
from .command import Command


def add_parser(commands) -> None:
    audit = commands.add_parser("audit", help="Verify the audit log of the project, or export its events for a SIEM.")
    audit.add_argument("mode", choices=("verify", "export"),
                       help="verify reads the log and names the first line that no longer follows the one before it; "
                            "export prints, one JSON event per line, the approvals of the exported records and the "
                            "changes of the profile history.")
    audit.add_argument("path", nargs="?", type=Path, help="With verify: the log or an export (default: the project's log).")
    audit.add_argument("--since", metavar="YYYY-MM-DD", help="With export: only the events of this day and after.")


def run(command: Command) -> int:
    args, root = command.args, command.root
    if args.mode == "export":
        if args.path is not None:
            raise ValueError("audit export takes no path: it reads the records and the profile of the project.")
        for line in audit_log.reconstruct(root, audit_log.since_day(args.since)):
            print(line.decode("ascii"))
        return 0
    if args.since is not None:
        raise ValueError("--since is an option of openguildkit audit export.")
    path = args.path or audit_log.default_path(root)
    try:
        count, problem = audit_log.verify(path)
    except OSError as error:
        raise ValueError(f"The audit log {path.as_posix()} cannot be read: {error.strerror or error}.") from error
    if problem:
        print(f"OpenGuildKit: {path.as_posix()}: {count} {'event' if count == 1 else 'events'} intact, then {problem}.",
              file=sys.stderr)
        return 1
    print(f"{count} {'event' if count == 1 else 'events'}, chain intact")
    return 0
