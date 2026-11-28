"""Response to an incident (#481): a freeze that stops edits and a longest age of an approval, both off by default.

`openguildkit profile set freeze on --by INITIALS --reason WHY` writes `frozen` (who, when, why) in the profile: the edit
hook then refuses every edit inside the project, even under an approved task, and `guard --ci` refuses every change
of a base revision that is frozen, except the one that lifts the freeze. `approval.max_age_days` ends the cover of an
approval after that many days. Both only restrict, so no terminal is needed to set them; lifting or loosening one
weakens a protection and is a person's act at a terminal (profile_cli). A project that sets neither is unchanged.

Entry: frozen, frozen_text, max_age_days, expired_problem, lifts_freeze
Tests: tests/test_incident.py
"""

from datetime import UTC, datetime
from pathlib import Path

from . import clock
from .decisions import reconsult_hint
from .project import STATE_DIR
from .storage import read_json

LIFT = ("Only a person lifts it, at a terminal: openguildkit profile set freeze off --by INITIALS --reason WHY. "
        "Ask them.")
PROFILE = f"{STATE_DIR}/project.json"
# Files the change that lifts a freeze may carry besides the profile: the catalog lock the command rewrites, and
# the decision records that cover it.
LIFTING_FILES = (PROFILE, f"{STATE_DIR}/catalog.lock.json")


def frozen(profile: dict) -> dict | None:
    """Who froze the project, when and why; None when it is not frozen."""
    found = profile.get("frozen")
    return found if isinstance(found, dict) else None


def frozen_text(found: dict) -> str:
    return f"the project is frozen by {found['by']} since {found['on']}: {found['reason']}"


def max_age_days(profile: dict) -> int | None:
    limit = (profile.get("approval") or {}).get("max_age_days")
    return limit if type(limit) is int else None


def expired_problem(task: dict, profile: dict) -> dict | None:
    """The approval_problem of an approval older than the project's limit, or None. An approval whose time cannot be
    read cannot be shown to be recent."""
    limit = max_age_days(profile)
    if limit is None:
        return None
    try:
        then = datetime.fromisoformat(task["decision"]["at"])
        age = (clock.real_now() - (then if then.tzinfo else then.replace(tzinfo=UTC))).days
    except (KeyError, TypeError, ValueError):
        age = None
    if age is not None and age <= limit:
        return None
    task_id = task["id"]
    old = "has no readable date" if age is None else f"is {age} days old"
    return {"kind": "approval-expired", "severity": "error",
            "message": f"The approval of {task_id} {old}, over the {limit} days this project allows "
                       f"(approval.max_age_days). {reconsult_hint(task_id)}"}


def lifts_freeze(base_file: Path, head_file: Path, changed: list[str], records: list[str]) -> bool:
    """Whether a change does nothing but lift the freeze its base revision holds: it touches the profile, the catalog
    lock and decision records only, the profile loses `frozen` and nothing else but its history, and the history gains
    the entries of `profile set freeze off`, which say who lifted it and why."""
    if not set(changed) <= {*LIFTING_FILES, *records} or PROFILE not in changed:
        return False
    try:
        before, after = read_json(base_file), read_json(head_file)
        history, kept = after.get("changes", []), before.get("changes", [])
    except (OSError, ValueError, AttributeError):
        return False

    def rest(profile: dict) -> dict:
        return {key: value for key, value in profile.items() if key not in ("frozen", "changes")}

    return ("frozen" in before and "frozen" not in after and rest(before) == rest(after)
            and history[:len(kept)] == kept and len(history) > len(kept)
            and str(history[-1].get("change", "")).startswith("set freeze off"))
