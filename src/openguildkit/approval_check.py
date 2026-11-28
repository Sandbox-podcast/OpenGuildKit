"""Whether an approval still holds, with only the modules the edit hook already loads: its seal, its rules, its age, its
signature and its history."""

from datetime import UTC, datetime
from pathlib import Path

from . import clock, incident
from .decisions import (
    EARLIER_SIGNERS,
    check_decision_seal,
    history_message,
    signature_or_history_problem,
    stale_approval_message,
)
from .project_rules import Fingerprints

DONE_STATUSES = ("done", "done-with-reservations")


# An approval older than this, with nothing recorded since, may be abandoned: task list and the guard say so.
STALE_DAYS = 14


def approval_problem(task: dict, profile: dict, catalog: dict, root: Path | None = None, *,
                     fingerprints: Fingerprints | None = None, outside: set[str] | None = None,
                     explain: bool = True) -> dict | None:
    """Whether a task's approval still holds: its seal intact, its rules, checks and boards current, its signature
    valid and the revision it was approved at still in the project history.

    Every reader asks this one function and prints its message: task list, check, task consult (which reopens the
    task under the same ID), handoff, verify, result, complete, export and the guard. An error blocks the work; a note
    marks a completed task, whose record is history. Without the project root, the signature and the history are not
    read. outside and fingerprints let a reader of many tasks ask git and hash the profile once (covering_approvals);
    explain names what changed in the rules, which the guard does not need.
    """
    decision = task.get("decision")
    if not decision or decision.get("outcome") != "approved":
        return None
    completed = task["status"] in DONE_STATUSES
    try:
        payload = check_decision_seal(task)
    except ValueError as error:
        if completed and "seal" not in decision:
            return {"kind": "no-seal", "severity": "note", "message": history_message(task["id"], sealed=False)}
        return {"kind": "invalid-seal" if "seal" in decision else "no-seal", "severity": "error", "message": str(error)}
    fingerprints = fingerprints or Fingerprints(profile, catalog)
    if not fingerprints.holds(task.get("profile_fingerprint")):
        if explain:  # The edit hook does not explain: it loads the consultation modules only here (#539).
            from .tasks_approval import rule_changes
        changes = rule_changes(task, profile, catalog) if explain else None
        if completed:
            return {"kind": "earlier-rules", "severity": "note", "message": history_message(task["id"], changes)}
        return {"kind": "earlier-rules", "severity": "error", "message": stale_approval_message(task["id"], changes)}
    # An approval over the project's limit (incident.py) covers no more work; a completed task is history.
    if not completed and (expired := incident.expired_problem(task, profile)):
        return expired
    # A completed task's record is history: a squash merge is expected to take its revision out of the history.
    found = None if completed or root is None else signature_or_history_problem(task, root, profile, payload, outside)
    if not found:
        return None
    return {"kind": found[0], "severity": "note" if found[0] == EARLIER_SIGNERS else "error", "message": found[1]}


def days_since(moment: str | None) -> int | None:
    """Whole days since a recorded time; None when the time cannot be read."""
    if moment is None:
        return None
    try:
        then = datetime.fromisoformat(moment)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return (clock.real_now() - then).days
