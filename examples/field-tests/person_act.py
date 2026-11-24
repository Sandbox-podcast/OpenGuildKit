"""Stand-in for the person's other acts at a terminal, in field campaigns only.

    person-act --project DIR [--answer TEXT ...] task clear TASK_ID BLOCKER --by NAME --evidence PATH --supports TEXT
    person-act --project DIR task complete TASK_ID --by NAME
    person-act --project DIR task verify TASK_ID --cannot-run command:1 --by NAME --reason TEXT

Approving goes through person-decide. The other acts that OpenGuildKit keeps for a person at a
terminal (clearing a blocker, a waiver, closing over a skipped sensitive rule or a deferred
evidence, declaring that a check cannot run, allowing an external action, accepting an alert)
go through this one. It runs the command at a pseudo-terminal, types the third argument (the
task or alert ID) at the first prompt, then each --answer at the next ones, and prints what the
prompt showed. A tester calls it only when its scenario says the person acts.

Linux and macOS only: Windows has no pseudo-terminal in the standard library.
"""

import argparse
import os
import sys
from pathlib import Path

from person_decide import at_terminal

# The person's acts at a terminal; approving and requesting changes go through person-decide.
ACTS = {"task": {"clear", "waive", "complete", "verify", "authorize", "revoke"},
        "alerts": {"accept", "severity", "set"}, "profile": {"set", "decline", "accept"}}


def act(project: Path, arguments: list[str], answers: list[str]) -> tuple[int, str]:
    if len(arguments) < 3 or arguments[1] not in ACTS.get(arguments[0], ()):
        known = "; ".join(f"{group} {'|'.join(sorted(names))}" for group, names in ACTS.items())
        raise ValueError(f"person-act runs one of the person's acts: {known}. Approving goes through person-decide.")
    return at_terminal(project, arguments, [arguments[2], *answers])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--answer", action="append", default=[], help="A line to type at a further prompt.")
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="The openguildkit command, without --project.")
    args = parser.parse_args()
    if os.name != "posix":
        raise SystemExit("person-act needs a pseudo-terminal, available on Linux and macOS.")
    try:
        code, shown = act(args.project, args.arguments, args.answer)
    except ValueError as error:
        raise SystemExit(f"person-act: {error}")
    sys.stdout.write(shown)
    sys.exit(code)


if __name__ == "__main__":
    main()
