"""What the commands say of an organization policy (RFC #452, org_policy.py): `org-catalog policy`, the lines `check`
fails on, the policy a commit brings in `org-catalog set`, and the options `guard --ci --org-policy PATH --org-commit
SHA`. A project whose organization catalog has no policy, or that follows none, sees nothing of it.
"""

import sys
from pathlib import Path

from .lock import project_catalog, read_lock
from .org_policy import findings, from_read, pinned
from .project import STATE_DIR, load_profile
from .project_instructions import RuleError
from .storage import print_json

__all__ = ["add_guard_options", "add_parser", "check_policy", "ci_copy", "from_read", "print_summary", "run"]
PROFILE = f"{STATE_DIR}/project.json"


def add_parser(actions) -> None:
    shown = actions.add_parser("policy", help="Show the minimum the organization policy of the pinned commit requires, "
                                              "and where the profile is under it.")
    shown.add_argument("--json", action="store_true", help="Print it as JSON.")


def add_guard_options(guard) -> None:
    guard.add_argument("--org-policy", metavar="PATH",
                       help="With --ci and --org-commit, the copy of the organization catalog whose policy.json sets "
                            "the minimum, instead of the one the base revision pins.")
    guard.add_argument("--org-commit", metavar="SHA", help="With --org-policy, the full SHA of the policy commit.")


def ci_copy(args) -> tuple[str, str] | None:
    """(PATH, SHA) of --org-policy and --org-commit, or None without them."""
    if (args.org_policy is None) != (args.org_commit is None):
        raise ValueError("Supply --org-policy and --org-commit together, such as --org-policy ../acme-catalog "
                         "--org-commit SHA.")
    return None if args.org_policy is None else (args.org_policy, args.org_commit)


def _lines(policy: dict) -> list[str]:
    minimum = policy["minimum"]
    lines = [f"{key.replace('_', '-')}: {'on' if value is True else value}" for key, value in minimum.items()]
    lines += [f"pack: {pack}" for pack in policy["packs"]]
    return lines


def print_summary(read: dict) -> None:
    """In org-catalog set: the minimum the commit's policy requires; nothing when it has none."""
    policy = from_read(read)
    if policy is None:
        return
    print(f"Organization policy at {policy['commit'][:12]}: {'; '.join(_lines(policy)) or 'no minimum'}."
          + (" It freezes every repository." if policy["frozen"] else ""))


def check_policy(state: Path, profile: dict, catalog: dict, report) -> None:
    """In check: each unmet requirement and the freeze, on standard error and in the report, then a failure."""
    found = findings(profile, catalog, pinned(read_lock(state), state))
    for code, message in found:
        print(f"OpenGuildKit: {message[0].upper()}{message[1:]}", file=sys.stderr)
        report.add(code, "error", message, PROFILE)
    if found:
        raise RuleError("The project does not meet the organization policy: each line above says what it requires.",
                        None)


def run(args, state: Path) -> int:
    policy = pinned(read_lock(state), state)
    if policy is None:
        if args.json:
            print_json({"policy": None})
        else:
            print("No organization policy: the project follows no organization catalog, or its pinned commit has no "
                  "policy.json. Each setting is the profile's own.")
        return 0
    catalog = project_catalog(args, state)
    found = findings(load_profile(state, catalog), catalog, policy) if (state / "project.json").is_file() else []
    if args.json:
        print_json({"policy": policy, "problems": [{"code": code, "message": message} for code, message in found]})
        return 0
    print(f"Organization policy at {policy['commit'][:12]}: {'; '.join(_lines(policy)) or 'no minimum'}.")
    for _, message in found:
        print(f"  {message[0].upper()}{message[1:]}")
    if not found:
        print("The profile meets it. A repository may be stricter, never less strict.")
    return 0
