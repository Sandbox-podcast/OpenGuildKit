"""The shape of a task record: the fields each part may hold, the checks of a record read from disk and of a
brief, and the time stamp records carry."""

from collections.abc import Iterator
from typing import cast

from . import clock, short_lane

# The severities and actions of a finding of task diff-review (delivered_review.py).
SEVERITIES = ("blocking", "important", "minor")
ACTIONS = ("fix", "defer", "decision")
# Clearances and waivers are stored apart by phase, because the approval's seal covers only those given before it.
# blocker_resolutions(task) reads both: every reader goes through it.
RESOLUTION_FIELDS = ("blocker_resolutions", "verification_blocker_resolutions")


def timestamp() -> str:
    return clock.timestamp()


STATUSES = {
    "draft": (),
    "consulting": ("answers", "consultation", "profile_fingerprint"),
    "reviewed": ("answers", "consultation", "profile_fingerprint", "review"),
    "changes-requested": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
    "approved": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
    "done": ("answers", "consultation", "profile_fingerprint", "review", "decision", "result"),
    # Closed with points left open: skipped rules, deferred evidence, open disagreements, waivers.
    "done-with-reservations": ("answers", "consultation", "profile_fingerprint", "review", "decision", "result"),
}

# The shape of every field the commands read, checked once when a record is loaded. A type is a
# type, [shape] a list of that shape, a dict an object whose keys ending in "?" are optional and
# whose "*" gives the shape of every value, a tuple one of several shapes, a frozenset the values allowed.
_DECISION = {"outcome": str, "by": str, "reason": str, "at": str}
_TEMPLATE_BOARD = {"id": str, "challenge?": {"specialists": [{"id": str}]}}
# A rule states its text, or declares a machine check that stands in for it; either can name evidence.
_EVIDENCE = [{"id": str, "title": str}]
_RULE = (
    {"id": str, "instruction": str, "verification": str, "check?": dict, "evidence?": _EVIDENCE},
    {"id": str, "check": dict, "evidence?": _EVIDENCE},
)
_SCOPE = {
    "open_points?": [str],
    "checks?": [str],
    "code_not_found?": [str],
    "code_not_searched?": [str],
    "packs?": [{"id": str, "rules": [_RULE]}],
    "market?": {"id": str, "observations": [{"id": str}], "changes?": [dict]},
    "tools?": [{"id": str}],
    "storybook?": {"indexes": [{"ref": str, "stories": [str]}]},
    "host_controls?": [{"id": str, "status": str}],
}
_CONSULTATION = {
    "id": str, "boards": [str], "routing": {"*": [str]}, "scope": _SCOPE, "markdown": str,
    "review_template": {"boards": [_TEMPLATE_BOARD]},
    "adjustments?": [{"board": str, "action": str, "reason": str}],
    "delegations?": {"*": str},
    "domains?": {"*": [str]},
    # Checked when a pass is printed (board_brief_problem), so that listing tasks stays fast.
    "board_briefs?": {"*": dict},
}
_BOARD_BRIEF = {
    "title": str, "purpose": str, "routing": [str], "questions": [str],
    "lenses": [{"id": str, "title": str, "focus": str, "checks?": [str]}],
    "lenses_not_concerned": [{"id": str, "applies_to": [str]}],
    "evidence": [str], "challenge": [str], "decision_criteria": [str],
    "source_leads": [{"title": str, "url": str}], "methods": [str], "other_methods": int,
    "rules": [{"pack": str, "title": str, "rules": [{"id": str, "instruction": str}]}],
    "unprinted_packs?": [str], "not_concerned?": [{"reason": str, "items": [str]}], "other_packs": int,
    "references": [{"title": str, "url": str}],
    "tools?": [{"title": str, "server": str, "mode": str}], "reviewer?": str, "stories?": [str],
}
_CHALLENGE = {
    "verdict": str,
    "specialists": [{"id": str, "basis": str, "evidence_refs": [int], "finding": str}],
    "blockers": [({"finding": str, "phase?": frozenset({"approval", "verification"})}, str)],
}
_REVIEW = {
    "consultation_id": str, "summary": str, "warnings?": [str],
    "boards": [{"id": str, "recommendation": str, "evidence": [(str, {"source": str, "ref": str})],
                "open_questions": [str], "challenge?": _CHALLENGE}],
}
_RESOLUTION = {"kind": frozenset({"cleared", "waived"}), "by": str, "evidence?": str, "supports?": str, "fingerprint?": str,
               "reason?": str, "scope?": str, "until?": str, "signer?": str, "signature?": str}
_RECORD = {
    "created_at": str,
    "lane?": frozenset({short_lane.LANE}),
    "paths?": [str],
    "completed_at?": str,
    "profile_fingerprint?": str,
    "answers?": {"*": (str, [str])},
    "consultation?": _CONSULTATION,
    "review?": _REVIEW,
    "decision?": {**_DECISION, "confirmed_removals?": [str]},
    "passes?": {"consultation_id": str, "boards": {"*": {"status": str, "mode?": str, "attempts?": int, "error?": str}}},
    "deliberation?": {
        "objections": [{"id": str, "from": str, "to": str, "point": str}],
        "responses": [{"objection": str, "board": str}],
        "agreed": [str], "open": [str], "decision_needed": str,
    },
    "blocker_resolutions?": {"*": _RESOLUTION},
    "verification_blocker_resolutions?": {"*": _RESOLUTION},
    "result?": {
        "revision?": str, "pull_request?": str,
        "criteria?": [{"criterion": str, "status": str}],
        "checks?": [{"check": str, "status": str}],
        "runs?": [{"tool": str, "outcomes": {"*": str}}],
    },
    "follows?": {"task": str, "brief": str, "status": str, "decision": _DECISION},
    "after?": [str],
    "authorizations?": [{"action": str, "target": str, "decision": str, "by": str, "reason": str}],
    "dependency_alerts?": {"alerts?": [dict]},
    "delivered_review?": {"boards": {"*": {
        "base": str, "revision": str, "at": str,
        "findings": [{"file": str, "line": int, "severity": frozenset(SEVERITIES),
                      "action": frozenset(ACTIONS), "finding": str}]}}},
}
_RESOLUTION_FIELDS = {"cleared": ("evidence", "supports"), "waived": ("reason", "scope", "until")}


def shape_problem(value: object, shape: object, field: str) -> str | None:
    """Where value departs from shape (see _RECORD), named by its path such as review.boards[0].challenge."""
    problems: Iterator[str | None]
    if isinstance(shape, tuple):
        options = [shape_problem(value, option, field) for option in shape]
        return None if None in options else options[-1]
    if isinstance(shape, frozenset):
        return None if value in shape else f"{field} must be one of {', '.join(sorted(shape))}"
    if isinstance(shape, list):
        if not isinstance(value, list):
            return f"{field} must be a list"
        problems = (shape_problem(item, shape[0], f"{field}[{index}]") for index, item in enumerate(value))
        return next((problem for problem in problems if problem), None)
    if isinstance(shape, dict):
        return _dict_shape_problem(value, shape, field)
    if shape is int:
        return None if type(value) is int else f"{field} must be a whole number"
    if shape is str:
        return None if isinstance(value, str) else f"{field} must be text"
    return None if isinstance(value, cast(type, shape)) else f"{field} must be {'an object' if shape is dict else 'a list'}"


def _dict_shape_problem(value: object, shape: dict, field: str) -> str | None:
    """Where value departs from an object shape: a missing key, or the first of its fields that departs."""
    problems: Iterator[str | None]
    if not isinstance(value, dict):
        return f"{field} must be an object"
    for key, inner in shape.items():
        if key == "*":
            problems = (shape_problem(item, inner, f"{field}.{name}") for name, item in value.items())
        else:
            name = key.rstrip("?")
            if name not in value:
                if key.endswith("?"):
                    continue
                return f"{field}.{name} is missing" if field else f"{name} is missing"
            problems = iter([shape_problem(value[name], inner, f"{field}.{name}" if field else name)])
        problem = next((problem for problem in problems if problem), None)
        if problem:
            return problem
    return None


def task_record_problem(task: dict) -> str | None:
    """Describe the first field of a task record that the commands could not use, if any."""
    if not isinstance(task.get("brief"), str) or not task["brief"].strip():
        return "brief must be text"
    status = task.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        return f"status must be one of {', '.join(STATUSES)}"
    rounds = task.get("rounds")
    if not isinstance(rounds, list) or any(not isinstance(entry, dict) for entry in rounds):
        return "rounds must be a list of objects"
    for field in STATUSES[status]:
        if field not in task:
            return f"{'an' if status[0] in 'aeiou' else 'a'} {status} task needs {field}"
    problem = shape_problem(task, _RECORD, "")
    if problem:
        return problem
    if ("lane" in task) != bool(task.get("paths")):
        return "lane and paths go together: a short-lane task names the paths it may change"
    for field in RESOLUTION_FIELDS:
        for blocker, resolution in task.get(field, {}).items():
            missing = [key for key in _RESOLUTION_FIELDS[resolution["kind"]] if key not in resolution]
            if missing:
                return f"{field}.{blocker}.{missing[0]} is missing"
    return None


def board_brief_problem(task: dict, board_id: str) -> None:
    """Refuse to print a pass from a damaged stored brief, with the field to restore."""
    stored = task.get("consultation", {}).get("board_briefs", {}).get(board_id)
    problem = shape_problem(stored, _BOARD_BRIEF, f"consultation.board_briefs.{board_id}") if stored is not None else None
    if problem:
        raise ValueError(f"Task record {task['id']} is damaged: {problem}. Restore it from a backup or consult again.")


def validate_brief(brief: str) -> str:
    """The brief as recorded: one check for a new task and for a brief revised at a new consultation.

    A credential is replaced by a placeholder before anything is written; the rest of the words are kept.
    """
    brief = brief.strip()
    if not brief:
        raise ValueError("Supply a task brief.")
    from .sensitive import redact_credentials  # Only a new brief needs it: the edit hook reads records (#539).

    return redact_credentials(brief)
