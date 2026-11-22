"""Track task consultations and decisions in the project."""

import difflib
import re
import uuid
from datetime import datetime
from pathlib import Path

from . import clock
from .decisions import (
    approval_policy, check_decision_seal, decision_payload, history_message, seal,
    stale_approval_message, verify_signature,
)
from .project import profile_fingerprint, task_scope_profile
from .relevance import sensitive_area
from .sensitive import redact_credentials, redact_data
from .results import (
    DONE_STATUSES, asked_checks, completion_problems, merge_results, not_concerned, outcomes, result_warnings,
    validate_result, waiting_evidence,
)
from .storage import read_json, write_json
from .workflow import blocker_list, code_not_found, consult, is_decision_task, pending_removals, profile_settings, validate_answers, validate_board_entry, validate_deliberation, validate_review

ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{digit}" for prefix in ("com", "lpt") for digit in range(1, 10)
}


def timestamp() -> str:
    return clock.timestamp()


def task_path(state: Path, task_id: str) -> Path:
    if task_id in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{task_id} is a reserved file name on Windows. Choose another task ID.")
    if len(task_id) > 64 or not ID_PATTERN.fullmatch(task_id):
        raise ValueError("Use a task ID of up to 64 lowercase letters, digits and separating hyphens.")
    path = state / "tasks" / f"{task_id}.json"
    if path.resolve() != path:
        raise ValueError(f"Task records must stay inside their project: {path}")
    return path


def _unknown_task(state: Path, task_id: str) -> str:
    """The error for a task ID with no record, with the closest existing ID when one is near."""
    known = sorted(path.stem for path in (state / "tasks").glob("*.json")) if (state / "tasks").is_dir() else []
    close = difflib.get_close_matches(task_id, known, n=1)
    hint = f"Did you mean {close[0]}? " if close else ""
    return f"Unknown task: {task_id}. {hint}Run openguildkit task list to see the tasks."


def read_task(state: Path, task_id: str) -> dict:
    path = task_path(state, task_id)
    if not path.is_file():
        raise ValueError(_unknown_task(state, task_id))
    task = read_json(path)
    if task.get("schema_version") != 1 or task.get("id") != task_id:
        raise ValueError(f"Unsupported or mismatched task record: {path}")
    problem = _record_problem(task)
    if problem:
        # Task records are not under version control (.openguildkit/.gitignore lists tasks/).
        raise ValueError(
            f"Task record {task_id} is damaged: {problem}. Restore {path.relative_to(state.parent).as_posix()} from a "
            "backup, or delete that file and open a new task with openguildkit task new."
        )
    return task


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
_RESOLUTION = {"kind": frozenset({"cleared", "waived"}), "by": str, "evidence?": str, "supports?": str,
               "reason?": str, "scope?": str, "until?": str, "signer?": str, "signature?": str}
_RECORD = {
    "created_at": str,
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
    "authorizations?": [{"action": str, "target": str, "decision": str, "by": str, "reason": str}],
    "dependency_alerts?": {"alerts?": [dict]},
}
_RESOLUTION_FIELDS = {"cleared": ("evidence", "supports"), "waived": ("reason", "scope", "until")}


def _shape_problem(value: object, shape: object, field: str) -> str | None:
    """Where value departs from shape (see _RECORD), named by its path such as review.boards[0].challenge."""
    if isinstance(shape, tuple):
        problems = [_shape_problem(value, option, field) for option in shape]
        return None if None in problems else problems[-1]
    if isinstance(shape, frozenset):
        return None if value in shape else f"{field} must be one of {', '.join(sorted(shape))}"
    if isinstance(shape, list):
        if not isinstance(value, list):
            return f"{field} must be a list"
        problems = (_shape_problem(item, shape[0], f"{field}[{index}]") for index, item in enumerate(value))
        return next((problem for problem in problems if problem), None)
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return f"{field} must be an object"
        for key, inner in shape.items():
            if key == "*":
                problems = (_shape_problem(item, inner, f"{field}.{name}") for name, item in value.items())
            else:
                name = key.rstrip("?")
                if name not in value:
                    if key.endswith("?"):
                        continue
                    return f"{field}.{name} is missing" if field else f"{name} is missing"
                problems = iter([_shape_problem(value[name], inner, f"{field}.{name}" if field else name)])
            problem = next((problem for problem in problems if problem), None)
            if problem:
                return problem
        return None
    if shape is int:
        return None if type(value) is int else f"{field} must be a whole number"
    if shape is str:
        return None if isinstance(value, str) else f"{field} must be text"
    return None if isinstance(value, shape) else f"{field} must be {'an object' if shape is dict else 'a list'}"


def _record_problem(task: dict) -> str | None:
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
    problem = _shape_problem(task, _RECORD, "")
    if problem:
        return problem
    for field in ("blocker_resolutions", "verification_blocker_resolutions"):
        for blocker, resolution in task.get(field, {}).items():
            missing = [key for key in _RESOLUTION_FIELDS[resolution["kind"]] if key not in resolution]
            if missing:
                return f"{field}.{blocker}.{missing[0]} is missing"
    return None


def board_brief_problem(task: dict, board_id: str) -> None:
    """Refuse to print a pass from a damaged stored brief, with the field to restore."""
    stored = task.get("consultation", {}).get("board_briefs", {}).get(board_id)
    problem = _shape_problem(stored, _BOARD_BRIEF, f"consultation.board_briefs.{board_id}") if stored is not None else None
    if problem:
        raise ValueError(f"Task record {task['id']} is damaged: {problem}. Restore it from a backup or consult again.")


def validate_brief(brief: str) -> str:
    """The brief as recorded: one check for a new task and for a brief revised at a new consultation.

    A credential is replaced by a placeholder before anything is written; the rest of the words are kept.
    """
    brief = brief.strip()
    if not brief:
        raise ValueError("Supply a task brief.")
    return redact_credentials(brief)


def create_task(state: Path, brief: str, task_id: str | None, follows: str | None = None) -> str:
    brief = validate_brief(brief)
    if task_id is not None and not task_id.strip():
        raise ValueError("The task ID is empty. Omit --id to generate one.")
    task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
    path = task_path(state, task_id)
    if path.exists():
        raise ValueError(f"Task already exists: {task_id}")
    record = {
        "schema_version": 1,
        "id": task_id,
        "brief": brief,
        "created_at": timestamp(),
        "status": "draft",
        "rounds": [],
    }
    if follows is not None:
        previous = read_task(state, follows)
        if "decision" not in previous:
            raise ValueError(f"Task {follows} has no recorded decision to follow.")
        record["follows"] = {
            "task": follows,
            "brief": previous["brief"],
            "status": previous["status"],
            "decision": {key: previous["decision"][key] for key in ("outcome", "by", "reason", "at")},
        }
    write_json(path, record)
    return task_id


def next_step(task: dict) -> str:
    """The open point that keeps a task from moving on."""
    status = task["status"]
    if status == "draft":
        return "Answer the questionnaire and consult the boards."
    if status == "consulting":
        passes = pass_progress(task)
        waiting = [item["board"] for item in passes if item["status"] != "done"]
        return f"Board reviews pending: {', '.join(waiting)}." if waiting else "Write the summary and record the review."
    if status == "reviewed":
        blockers = unresolved_blockers(task)
        return f"Resolve blockers {', '.join(blockers)}." if blockers else "Waiting for the person's decision."
    if status == "changes-requested":
        return f"Consult again: {task['decision']['reason']}"
    if status == "approved":
        return _approved_step(task)
    if status == "done-with-reservations":
        return "Done with reservations: see the open points in task show (result.closing)."
    return "Done."


def _setting_change(name: str, before, after) -> str:
    """One setting's change in words, such as "guard enforce -> observe"."""
    if isinstance(after, list):
        return f"{name} changed ({', '.join(before or []) or 'none'} -> {', '.join(after) or 'none'})"
    return f"{name} {before} -> {after}"


def rule_changes(task: dict, profile: dict, catalog: dict) -> list[str]:
    """What changed, pack by pack and rule by rule, in the rules the task was consulted under."""
    scope = task["consultation"]["scope"]
    try:
        current = task_scope_profile(profile, catalog, task.get("answers", {}).get("components", []))
    except ValueError:
        return ["the task's components changed"]
    before = {pack["id"]: pack for pack in scope.get("packs", [])}
    after = {pack_id: catalog["packs"][pack_id] for pack_id in current["packs"]}
    changes = [f"pack {pack_id} added" for pack_id in after if pack_id not in before]
    changes += [f"pack {pack_id} removed" for pack_id in before if pack_id not in after]
    for pack_id in [pack_id for pack_id in after if pack_id in before]:
        old = {rule["id"]: rule for rule in before[pack_id]["rules"]}
        new = {rule["id"]: rule for rule in after[pack_id]["rules"]}
        changes += [f"rule {pack_id}/{rule_id} added" for rule_id in new if rule_id not in old]
        changes += [f"rule {pack_id}/{rule_id} changed" for rule_id in new if rule_id in old and old[rule_id] != new[rule_id]]
        changes += [f"rule {pack_id}/{rule_id} removed" for rule_id in old if rule_id not in new]
    if scope.get("sector", {}).get("id") != current["sector"]:
        changes.append("sector changed")
    changes += [f"{field} changed" for field in ("stack", "conventions", "checks")
                if scope.get(field, []) != current.get(field, [])]
    settings = profile_settings(profile)
    if "settings" in scope:
        changes += [_setting_change(name, scope["settings"].get(name), value)
                    for name, value in settings.items() if scope["settings"].get(name) != value]
    if not changes and "settings" in scope:
        return ["a board's definition changed: openguildkit update shows the catalog changes"]
    if not changes:
        # A task consulted before the settings were recorded: name what may have changed.
        return [f"a project setting changed ({', '.join(settings)}), or a board's definition; "
                "openguildkit preview shows the profile"]
    return changes[:6] + ([f"{len(changes) - 6} more changes: openguildkit update shows them"] if len(changes) > 6 else [])


def _approved_step(task: dict) -> str:
    """The next step of an approved task, from what its result already holds."""
    task_id = task["id"]
    if is_decision_task(task):
        if task.get("answers", {}).get("outcome") and not (task.get("result") or {}).get("criteria"):
            return (f"Decision recorded: report its acceptance criterion with task result {task_id} --template, "
                    f"then task complete {task_id}, then open a follow-up task to act on it.")
        return f"Decision recorded: close it with task complete {task_id}, then open a follow-up task to act on it."
    result = task.get("result")
    if not result:
        return (f"Implement, then record the results: task verify {task_id} and task result {task_id}, "
                f"then task complete {task_id}.")
    commands = task["consultation"]["scope"].get("checks", [])
    failed = sorted((item for item in result.get("checks", []) if item["status"] == "failed"),
                    key=lambda item: not item["check"].startswith("command:"))
    if failed:
        item = failed[0]
        index = int(item["check"].split(":")[1]) - 1 if item["check"].startswith("command:") else None
        what = f" (`{commands[index]}`)" if index is not None and index < len(commands) else ""
        cause = f": {item['message']}" if item.get("message") else ""
        more = f" and {len(failed) - 1} other check(s)" if len(failed) > 1 else ""
        return f"{item['check']}{what} failed{cause}{more}. Fix it, then run task verify {task_id}."
    waiting = result.get("waiting_for", [])
    if waiting:
        return "Waiting for evidence: " + "; ".join(f"{item['title']} from {item['owner']}" for item in waiting) + "."
    return f"Result recorded: run task verify {task_id} to list what remains, then task complete {task_id}."


def approval_problem(task: dict, current_fingerprint: str, profile: dict | None = None,
                     catalog: dict | None = None) -> dict | None:
    """Whether a task's approval still holds: its seal intact and its rules current.

    Every reader asks this one function and prints its message. An error blocks the work; a note marks a
    completed task, whose record is history. With the profile and catalog, the message names what changed.
    """
    decision = task.get("decision")
    if not decision or decision.get("outcome") != "approved":
        return None
    completed = task["status"] in DONE_STATUSES
    try:
        check_decision_seal(task)
    except ValueError as error:
        if completed and "seal" not in decision:
            return {"kind": "no-seal", "severity": "note", "message": history_message(task["id"], sealed=False)}
        return {"kind": "invalid-seal" if "seal" in decision else "no-seal", "severity": "error", "message": str(error)}
    if task.get("profile_fingerprint") == current_fingerprint:
        return None
    changes = rule_changes(task, profile, catalog) if profile is not None and catalog is not None else None
    if completed:
        return {"kind": "earlier-rules", "severity": "note", "message": history_message(task["id"], changes)}
    return {"kind": "earlier-rules", "severity": "error", "message": stale_approval_message(task["id"], changes)}


def list_tasks(state: Path, status: str | None = None, owner: str | None = None,
               since: str | None = None, until: str | None = None, *, current_fingerprint: str | None = None,
               profile: dict | None = None, catalog: dict | None = None) -> list[dict]:
    """Every task of the project with its status, decision owner and next open point."""
    directory = state / "tasks"
    rows = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError as error:
            rows.append({"id": path.stem, "status": "unreadable", "next": str(error)})
            continue
        day = task["created_at"][:10]
        if status and task["status"] != status:
            continue
        if (since and day < since) or (until and day > until):
            continue
        problem = (approval_problem(task, current_fingerprint, profile, catalog)
                   if current_fingerprint is not None else None)
        decided_by = task.get("decision", {}).get("by")
        if problem and problem["kind"] == "invalid-seal":
            decided_by = None
        if owner and (decided_by or "").casefold() != owner.casefold():
            continue
        row = {"id": task["id"], "status": task["status"], "created": day, "owner": decided_by,
               "brief": task["brief"].splitlines()[0][:80], "next": problem["message"] if problem else next_step(task)}
        if problem:
            row.update(approval_problem=problem["kind"], severity=problem["severity"])
        closed_by = task.get("result", {}).get("closing", {}).get("by")
        if closed_by:
            row["closed_by"] = closed_by
        if task.get("follows"):
            row["follows"] = task["follows"]["task"]
        rows.append(row)
    return rows


# What a change of rules means for a task in each status; a completed task keeps its record as history.
_TOUCHED_STEP = {
    "consulting": "consult it again",
    "reviewed": "request changes and consult it again",
    "approved": "consult it again (openguildkit task consult ID) or open a linked task with --follows",
}


def tasks_touched(state: Path, profile: dict, catalog: dict) -> list[dict]:
    """The open tasks consulted under other rules than these, each with what to do; update and sync name the same."""
    fingerprint = profile_fingerprint(profile, catalog)
    touched = []
    for path in sorted((state / "tasks").glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError:
            continue
        step = _TOUCHED_STEP.get(task["status"])
        if step and task.get("profile_fingerprint") != fingerprint:
            touched.append({"id": task["id"], "status": task["status"], "step": step.replace("ID", task["id"])})
    return touched


def cited_evidence(task: dict) -> list[str]:
    """The project paths a task names as evidence for a reviewer: named evidence, rule and pack answers,
    acceptance criteria and blocker clearings.

    Free text ("Tried by hand.") is not a path and is left out, and so are the logs task verify writes for
    the check commands under .openguildkit/tasks/: they are the tool's own record, not evidence to share.
    """
    result = task.get("result", {})
    paths = [item.get("evidence") for item in result.get("checks", []) if "exit_code" not in item]
    paths += [item.get("evidence") for item in result.get("packs", [])]
    for criterion in result.get("criteria", []):
        paths += [criterion.get("evidence"), criterion.get("verified_by")]
    paths += [item["evidence"] for item in task.get("blocker_resolutions", {}).values() if item["kind"] == "cleared"]
    logs = f".openguildkit/tasks/{task['id']}-checks/"
    return [path for path in dict.fromkeys(paths)
            if isinstance(path, str) and path and not path.startswith(("https://", "command:", logs))
            and not any(character.isspace() for character in path)]


def record_consultation(
    task: dict, answers: dict, profile: dict, catalog: dict, selection: dict | None = None,
    host_controls: list[dict] | None = None, market: dict | None = None, storybook: dict | None = None,
    knowledge: dict | None = None, tools: list[dict] | None = None, root: Path | None = None,
    brief: str | None = None,
) -> dict:
    """Record a consultation. With the project root, a bug brief's files and functions are looked for in it.

    After a change request, the earlier round is kept and the brief may be revised.
    """
    # An approval that no longer holds (earlier rules, a seal missing or broken) can be consulted again;
    # it is kept in rounds with the reason, like a change request.
    reopened = None
    if task["status"] == "approved":
        reopened = approval_problem(task, profile_fingerprint(profile, catalog), profile, catalog)
    if task["status"] not in {"draft", "consulting", "changes-requested"} and not reopened:
        raise ValueError("Start a new task or request changes before consulting again.")
    if brief is not None and task["status"] not in {"changes-requested", "approved"}:
        raise ValueError("Revise the brief when you consult again after a change request (task decide --request-changes).")
    rounds = list(task["rounds"])
    if task["status"] in {"changes-requested", "approved"}:
        archived = {key: task[key] for key in ("brief", "answers", "consultation", "review", "decision", "profile_fingerprint")}
        for key in ("deliberation", "blocker_resolutions", "result"):
            if key in task:
                archived[key] = task[key]
        if reopened:
            archived["reopened"] = reopened["message"]
        rounds.append(archived)
    validated = validate_answers(redact_data(answers))
    result = {**task, "answers": validated, "rounds": rounds}
    if brief is not None:
        result["brief"] = validate_brief(brief)
    missing = None
    if root is not None and validated["kind"] == "bug":
        missing = code_not_found(" ".join([result["brief"], validated.get("context", "")]), root)
    result.update(
        status="consulting",
        consultation=consult(
            task_scope_profile(profile, catalog, validated.get("components", [])),
            catalog, result, selection, host_controls, market, storybook,
            knowledge, tools, missing,
        ),
        profile_fingerprint=profile_fingerprint(profile, catalog),
    )
    result.pop("review", None)
    result.pop("decision", None)
    result.pop("passes", None)
    result.pop("deliberation", None)
    result.pop("blocker_resolutions", None)
    result.pop("verification_blocker_resolutions", None)
    result.pop("result", None)
    return result


def previous_round_line(task: dict) -> str | None:
    """One line recalling the previous round's decision and its reason, for the next round's decision."""
    if not task.get("rounds"):
        return None
    earlier = task["rounds"][-1]
    decision = earlier["decision"]
    outcome = "changes requested" if decision["outcome"] == "changes-requested" else decision["outcome"]
    revised = " The brief was revised since." if earlier.get("brief", task["brief"]) != task["brief"] else ""
    reopened = f" Reopened: {earlier['reopened']}" if earlier.get("reopened") else ""
    return (f"Round {len(task['rounds']) + 1}. Round {len(task['rounds'])}: {outcome} by {decision['by']} "
            f"on {decision['at'][:10]}: {decision['reason'].rstrip('.')}.{revised}{reopened}")


def record_review(task: dict, review: dict, root: Path | None = None) -> dict:
    """Record the review; with the project root, the project files and tests it cites must exist."""
    if task["status"] != "consulting":
        raise ValueError("Run task consult before recording a review.")
    review = validate_review(task["consultation"], review, root)
    result = {**task, "status": "reviewed", "review": review}
    result.pop("passes", None)
    return result


def _passes(task: dict) -> dict:
    if task["status"] != "consulting":
        raise ValueError("Board passes can only run while the task is being consulted.")
    passes = task.get("passes")
    if not passes or passes.get("consultation_id") != task["consultation"]["id"]:
        return {"consultation_id": task["consultation"]["id"], "boards": {}}
    return {"consultation_id": passes["consultation_id"], "boards": dict(passes["boards"])}


def start_pass(task: dict, board_id: str, mode: str, again: bool = False) -> dict:
    """Mark a board's pass as started. A done pass is only printed, unless again asks to redo it; starting again
    after a failed or done pass counts a new attempt, printing a pass that is already started does not."""
    passes = _passes(task)
    if board_id not in task["consultation"]["boards"]:
        raise ValueError(f"Board {board_id!r} is not part of this consultation.")
    if mode not in ("subagent", "sequential"):
        raise ValueError("A pass runs as a subagent or in sequence.")
    previous = passes["boards"].get(board_id, {})
    if previous.get("status") == "done" and not again:
        return {**task, "passes": passes, "_submitted": True}
    if previous.get("status") == "started" and previous.get("mode") == mode:
        return {**task, "passes": passes}
    passes["boards"][board_id] = {"status": "started", "mode": mode, "started_at": timestamp(),
                                  "attempts": previous.get("attempts", 0) + (0 if previous.get("status") == "started" else 1)}
    return {**task, "passes": passes}


def submit_pass(task: dict, entry: dict, mode: str | None = None, root: Path | None = None) -> dict:
    """Record one board's entry. An invalid entry is recorded as a failure; the corrected file can be sent again."""
    passes = _passes(task)
    raw_id = entry.get("id") if isinstance(entry, dict) else None
    # The entry is validated with its ID stripped: look its pass up the same way.
    board_id = raw_id.strip() if isinstance(raw_id, str) else None
    current = passes["boards"].get(board_id, {}) if isinstance(board_id, str) else {}
    if isinstance(board_id, str) and board_id in task["consultation"]["boards"] and not current:
        raise ValueError(
            f"The {board_id} pass was not started on the current consultation. Run openguildkit task pass "
            f"{task['id']} {board_id}, review through that brief, then submit the entry."
        )
    mode = mode or current.get("mode", "sequential")
    try:
        validated = validate_board_entry(task["consultation"], entry, root)
    except ValueError as error:
        if isinstance(board_id, str) and board_id in task["consultation"]["boards"]:
            passes["boards"][board_id] = {**current, "status": "failed", "mode": mode, "error": str(error),
                                          "at": timestamp(), "attempts": current.get("attempts", 1)}
            return {**task, "passes": passes, "_error": str(error)}
        raise
    passes["boards"][validated["id"]] = {"status": "done", "mode": mode, "entry": validated, "at": timestamp(),
                                         "attempts": current.get("attempts", 1)}
    return {**task, "passes": passes}


def pass_progress(task: dict) -> list[dict]:
    """Each selected board with its pass status: done, failed, started (or interrupted) or missing.

    Once the review is recorded, the passes are part of it: each of its boards is done, in the review.
    """
    if task["status"] != "consulting" and "review" in task:
        return [{"board": entry["id"], "status": "done", "in": "review"} for entry in task["review"]["boards"]]
    passes = task.get("passes") if task["status"] == "consulting" else None
    if passes and passes.get("consultation_id") != task["consultation"]["id"]:
        passes = None
    progress = []
    for board_id in task["consultation"]["boards"]:
        state = (passes or {}).get("boards", {}).get(board_id)
        item = {"board": board_id, "status": state["status"] if state else "missing"}
        if state:
            item.update({key: state[key] for key in ("mode", "attempts", "error") if key in state})
        progress.append(item)
    return progress


def assemble_review(task: dict, summary: str) -> dict:
    """Build the full review from completed passes once every board is done."""
    passes = _passes(task)
    progress = pass_progress({**task, "passes": passes})
    waiting = [item["board"] for item in progress if item["status"] != "done"]
    if waiting:
        raise ValueError(f"Board passes are not done for {', '.join(waiting)}. Run task progress.")
    modes = {passes["boards"][board_id]["mode"] for board_id in task["consultation"]["boards"]}
    execution = "subagents" if modes == {"subagent"} else "sequential" if modes == {"sequential"} else "mixed"
    review = {
        "consultation_id": task["consultation"]["id"],
        "summary": summary,
        "boards": [passes["boards"][board_id]["entry"] for board_id in task["consultation"]["boards"]],
        "execution": execution,
    }
    return record_review(task, review)


_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def waiver_policy(profile: dict) -> dict | None:
    return profile.get("waivers")


def _clearing_evidence(value: str, root: Path) -> str:
    """Evidence that clears a blocker is a file or folder of the project, or an https link someone can open."""
    if value.startswith("https://") and len(value) > len("https://") and not any(char.isspace() for char in value):
        return value
    project = root.resolve()
    path = (project / value).resolve()
    if path.exists() and (path == project or project in path.parents):
        return path.relative_to(project).as_posix() or "."
    raise ValueError(
        f"Clearing evidence must be an existing file or folder of the project, or an https link: {value}."
    )


def _clearance_payload(task: dict, blocker_id: str, entry: dict) -> dict:
    return {
        "kind": "blocker-clearance",
        "task": task["id"],
        "consultation_id": task["consultation"]["id"],
        "review_sha256": seal(task["review"]),
        "blocker": blocker_id,
        **{key: entry[key] for key in ("by", "evidence", "supports")},
    }


def _check_clearance_signature(task: dict, blocker_id: str, entry: dict, policy: dict, root: Path) -> None:
    if not entry.get("signer") or not entry.get("signature"):
        raise ValueError("This project requires a signed clearance. Run task clear with --payload FILE, "
                         "sign the payload, then pass --signature FILE --signer PRINCIPAL.")
    if entry["by"] != entry["signer"]:
        raise ValueError("For a signed clearance, --by must match the signer principal.")
    verify_signature(root, policy, _clearance_payload(task, blocker_id, entry), entry["signature"], entry["signer"])


def resolve_blocker(task: dict, blocker_id: str, resolution: dict, profile: dict, root: Path,
                    *, signing_payload: bool = False) -> dict:
    """Clear a blocker with evidence, or cover it with a waiver the project's policy allows.

    The record says whether the command ran at a terminal, so the approver knows when an agent cleared it.
    """
    known = {item["id"]: item for item in blocker_list(task)}
    if blocker_id not in known:
        listed = ", ".join(known) or "none"
        raise ValueError(f"Unknown blocker {blocker_id}. Blockers: {listed}.")
    blocker = known[blocker_id]
    if blocker["resolution"]:
        first = blocker["resolution"]
        raise ValueError(f"Blocker {blocker_id} already has a resolution: {first['kind']} by {first['by']} on "
                         f"{first.get('at', '')[:10]}. It stays as recorded; see task blockers.")
    verification = blocker.get("phase") == "verification"
    if verification and task["status"] != "approved":
        raise ValueError("Resolve a verification blocker after approval and before completion.")
    if not verification and task["status"] != "reviewed":
        raise ValueError("Resolve approval blockers after the review is recorded and before the decision.")
    by = resolution.get("by", "").strip()
    if not by:
        raise ValueError("Name the person who resolves the blocker.")
    entry = {"kind": resolution["kind"], "by": by, "at": timestamp(),
             "recorded_from": "terminal" if resolution.get("terminal") else "no terminal"}
    if resolution["kind"] == "cleared":
        for field in ("evidence", "supports"):
            if not resolution.get(field, "").strip():
                raise ValueError(f"Clearing a blocker needs --{field}.")
            entry[field] = resolution[field].strip()
        entry["evidence"] = _clearing_evidence(entry["evidence"], root)
        policy = approval_policy(profile)
        if signing_payload:
            if policy["mode"] != "signed" or by not in policy["approvers"]:
                raise ValueError("A clearance payload needs a signed project and --by set to an approver principal.")
            return _clearance_payload(task, blocker_id, entry)
        if policy["mode"] == "signed":
            entry.update(signer=resolution.get("signer"), signature=resolution.get("signature"))
            _check_clearance_signature(task, blocker_id, entry, policy, root)
    else:
        policy = waiver_policy(profile)
        if not policy:
            raise ValueError("The project's policy allows no waiver. Clear the blocker or request changes.")
        if by not in policy["allowed_by"]:
            raise ValueError(f"{by} cannot grant waivers. Allowed: {', '.join(policy['allowed_by'])}.")
        until = resolution.get("until", "")
        if not _DAY.fullmatch(until):
            raise ValueError("Give the waiver's end date as YYYY-MM-DD.")
        days = (datetime.fromisoformat(until).date() - clock.now().date()).days
        if days < 1 or days > policy["max_days"]:
            raise ValueError(f"A waiver lasts between 1 and {policy['max_days']} days.")
        for field in ("reason", "scope"):
            if not resolution.get(field, "").strip():
                raise ValueError(f"A waiver needs --{field}.")
            entry[field] = resolution[field].strip()
        entry["until"] = until
    field = "verification_blocker_resolutions" if verification else "blocker_resolutions"
    return {**task, field: {**task.get(field, {}), blocker_id: entry}}


def unresolved_blockers(task: dict) -> list[str]:
    return [item["id"] for item in blocker_list(task) if not item["resolution"] and item.get("phase") != "verification"]


def verification_blocker_problems(task: dict, profile: dict, root: Path | None = None) -> list[str]:
    policy = approval_policy(profile)
    problems = []
    for item in blocker_list(task):
        if item.get("phase") != "verification":
            continue
        resolution = item["resolution"]
        if not resolution:
            problems.append(f"Verification blocker {item['id']} is open. Clear it when {item['clears_when']}")
        elif root is not None and policy["mode"] == "signed" and resolution["kind"] == "cleared":
            try:
                _check_clearance_signature(task, item["id"], resolution, policy, root)
            except ValueError as error:
                problems.append(f"Verification blocker {item['id']}: {error}")
    return problems


def record_result(task: dict, profile: dict, payload: dict, source: str = "report", relevance: dict | None = None,
                  root: Path | None = None, *, changed: list[str] | None = None) -> dict:
    """Add a delivery report to an approved task; later reports update earlier checks.

    A named evidence that cannot be recorded is held back under "_held" (for the caller to print and
    drop) and the rest is recorded: the task then waits for that evidence from its owner.
    """
    if task["status"] != "approved":
        raise ValueError("Results belong to an approved task that is not done yet.")
    validated = validate_result(task, profile, payload, source, relevance, root, changed=changed)
    held = validated.pop("_held", [])
    result = merge_results(task.get("result"), validated)
    if source == "report" and task.get("answers", {}).get("outcome") and not result["criteria"]:
        raise ValueError(
            "The task has an expected outcome: report at least one acceptance criterion. Run task result ID --template."
        )
    updated = {**task, "result": result}
    for key, value in (("waiting_for", waiting_evidence(updated, profile, relevance)),
                       ("warnings", result_warnings(updated, profile, relevance))):
        result.pop(key, None)
        if value:
            result[key] = value
    return {**_with_wait(updated), "_held": held}


def _with_wait(task: dict) -> dict:
    """Next to the status, the evidence an approved task waits for, so task show and the export say it too."""
    task = {key: value for key, value in task.items() if key != "waiting_for"}
    waiting = task.get("result", {}).get("waiting_for", [])
    if waiting:
        task["waiting_for"] = [f"{item['title']} ({item['check']}) from {item['owner']}" for item in waiting]
    return task


def defer_evidence(task: dict, profile: dict, deferrals: list[tuple[str, dict]], by: str,
                   relevance: dict | None = None) -> dict:
    """Hand named evidence that is still awaited to a follow-up task, recorded on behalf of its owner."""
    waiting = {item["check"]: item for item in waiting_evidence(task, profile, relevance)}
    entries = []
    for check_id, follow_up in deferrals:
        if check_id not in waiting:
            listed = ", ".join(waiting) or "none"
            raise ValueError(f"{check_id} is not a named evidence this task waits for. Awaited: {listed}.")
        if follow_up.get("follows", {}).get("task") != task["id"]:
            raise ValueError(f"Task {follow_up['id']} does not follow {task['id']}: open it with "
                             f'openguildkit task new "BRIEF" --follows {task["id"]}.')
        entries.append({"check": check_id, "task": follow_up["id"], "owner": waiting[check_id]["owner"],
                        "by": by, "at": timestamp()})
    result = {**task["result"], "deferred": [*task["result"].get("deferred", []), *entries]}
    result.pop("waiting_for", None)
    return _with_wait({**task, "result": result})


def complete_task(task: dict, profile: dict, root: Path | None = None, relevance: dict | None = None,
                  by: str | None = None, *, changed: list[str] | None = None) -> dict:
    """Close the task: done when nothing is left open, done-with-reservations otherwise.

    Closing over a skipped or failed data protection, security or AI rule that concerns the task
    needs the person's name (the command line also asks for a terminal).
    """
    problems = (verification_blocker_problems(task, profile, root)
                + completion_problems(task, profile, relevance, changed=changed))
    if problems:
        raise ValueError("The task cannot be declared done:\n- " + "\n- ".join(problems))
    groups = points_left_open(task, profile, relevance)
    sensitive = next((group for group in groups if group["group"] == SENSITIVE_GROUP), None)
    if sensitive and not (by or "").strip():
        raise ValueError(
            f"{len(sensitive['points'])} data protection, security or AI point(s) are skipped, failed or declared not "
            "applicable as a pack. A person "
            f"confirms closing over them: openguildkit task complete {task['id']} --by NAME, at a terminal."
        )
    result = {**task.get("result", {}),
              "closing": {"open_points": groups, "not_concerned": not_concerned(task, profile, relevance)}}
    if by and by.strip():
        result["closing"]["by"] = by.strip()
    if not task["consultation"]["scope"].get("checks") and not is_decision_task(task):
        result["closing"]["verification"] = NO_COMMAND
    status = "done-with-reservations" if groups else "done"
    return _with_wait({**task, "status": status, "completed_at": timestamp(), "result": result})


SENSITIVE_GROUP = "Data protection, security or AI rules skipped, failed or declared not applicable as a pack"
NO_COMMAND = ("No project check command ran for this task: the profile lists none (checks in "
              ".openguildkit/project.json), so nothing was run to verify the change.")


def _open_disagreements(task: dict) -> list[str]:
    """Each disagreement left open with its point and its two boards, then the decision the person takes."""
    deliberation = task.get("deliberation", {})
    objections = {item["id"]: item for item in deliberation.get("objections", [])}
    points = []
    for item_id in deliberation.get("open", []):
        objection = objections.get(item_id)
        points.append(f"{objection['from']} objects to {objection['to']}: {objection['point']}" if objection
                      else f"disagreement {item_id} was left open")
    if points and deliberation.get("decision_needed"):
        points.append(f"Decision needed: {deliberation['decision_needed']}")
    return points


def _blocks_not_lifted(task: dict) -> list[str]:
    """A board that said block, approved over blockers that were waived or left open rather than cleared."""
    points = []
    for entry in task.get("review", {}).get("boards", []):
        if entry.get("challenge", {}).get("verdict") != "block":
            continue
        open_ones = [item for item in blocker_list(task) if item["board"] == entry["id"]
                     and not (item["resolution"] and item["resolution"]["kind"] == "cleared")]
        details = "; ".join(
            f"blocker {item['id']} is waived until {item['resolution']['until']}, not cleared"
            if item["resolution"] else f"blocker {item['id']} is not cleared" for item in open_ones)
        if open_ones:
            points.append(f"{entry['id']} said block; {details}")
    return points


def points_left_open(task: dict, profile: dict, relevance: dict | None = None) -> list[dict]:
    """What a closed task leaves open, grouped by nature, most serious first; empty groups are left out."""
    checks = {check["id"]: check for check in asked_checks(task, profile, relevance)}
    reported = outcomes(task, profile, relevance)
    sensitive, other = [], []
    for item in reported.values():
        check = checks.get(item["check"])
        if check is None or check["kind"] == "command" or item["status"] not in ("skipped", "failed"):
            continue
        detail = f": {item['reason']} ({item['owner']})" if item.get("reason") else ""
        line = f"{item['check']} is {item['status']}{detail}"
        area = sensitive_area(check.get("pack", ""))
        (sensitive if area else other).append(f"{line} [{area}]" if area else line)
    result = task.get("result", {})
    sweeping = {item.get("via_pack") for item in reported.values()}
    for item in result.get("packs", []):
        area = sensitive_area(item["pack"])
        if area and item["pack"] in sweeping:
            sensitive.append(f"pack {item['pack']} is declared not applicable as a whole: {item['reason']} "
                             f"({item['owner']}) [{area}]")
    groups = [
        (SENSITIVE_GROUP, sensitive),
        ("Board blocks not lifted", _blocks_not_lifted(task)),
        ("Project checks that could not run in this environment", [
            f"{item['check']} could not run: {item['reason']} (recorded by {item['owner']})"
            for item in result.get("checks", []) if item.get("cannot_run")]),
        ("Blockers waived rather than cleared", [
            f"blocker {item['id']} is waived until {item['resolution']['until']}"
            for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "waived"]),
        ("Disagreements between boards left open", _open_disagreements(task)),
        ("Named evidence handed to a follow-up task", [
            f"{item['check']} is handed to task {item['task']}, provided by {item['owner']} (recorded by {item['by']})"
            for item in result.get("deferred", [])]),
        ("Other rules skipped or failed", other),
        ("Warnings on the result", list(result.get("warnings", []))),
    ]
    found = [{"group": title, "points": points} for title, points in groups if points]
    verdicts = [f"{entry['id']} said {entry['challenge']['verdict']}" for entry in task.get("review", {}).get("boards", [])
                if entry.get("challenge", {}).get("verdict") == "revise"]
    if found and verdicts:
        found.append({"group": "Board verdicts at approval that asked for changes", "points": verdicts})
    return found


def record_deliberation(task: dict, payload: dict) -> dict:
    return {**task, "deliberation": validate_deliberation(task, payload)}


def decided_message(task: dict) -> str | None:
    """For a task a person already decided: its status, who decided and when, and the one command that fits next."""
    decision, task_id, status = task.get("decision"), task["id"], task["status"]
    if not decision:
        return None
    who = f"by {decision['by']} on {decision['at'][:10]}"
    if status == "approved":
        return f"Task {task_id} is already approved {who}. Next: openguildkit task handoff {task_id}"
    if status in DONE_STATUSES:
        return (f"Task {task_id} is already decided and {status}: approved {who}. To change the work, open a follow-up: "
                f"openguildkit task new \"BRIEF\" --follows {task_id}")
    if status == "changes-requested":
        return (f"Task {task_id} already has changes requested {who}. Next: openguildkit task consult {task_id}, "
                "then record the new review before deciding.")
    return None


def record_decision(
    task: dict, approve: bool, by: str, reason: str, base_revision: dict | None = None, signature: dict | None = None,
    confirmed_removals: list[str] | None = None,
) -> dict:
    """Record the person's decision. Approving needs their confirmation of each protected board removed."""
    if task["status"] != "reviewed":
        raise ValueError(decided_message(task) or "Record the boards' review before deciding.")
    unconfirmed = [board for board in pending_removals(task) if board not in (confirmed_removals or [])]
    if approve and unconfirmed:
        raise ValueError(
            f"Approval cancelled: the removal of the {', '.join(unconfirmed)} board was not confirmed. Type its name "
            "at the approval prompt, or request changes and consult again with it."
        )
    open_blockers = unresolved_blockers(task)
    if approve and open_blockers:
        raise ValueError(
            f"Resolve each blocker before approving: {', '.join(open_blockers)}. Clear it with evidence "
            "(task clear), waive it if the project allows (task waive), or request changes."
        )
    if not by.strip() or not reason.strip():
        raise ValueError("Supply the decision owner and a reason.")
    status = "approved" if approve else "changes-requested"
    decision = {"outcome": status, "by": by.strip(), "reason": reason.strip(), "at": timestamp()}
    if approve:
        payload = decision_payload(task, by, reason, base_revision)
        decision.update(base_revision=base_revision, seal=seal(payload))
        if signature is not None:
            decision.update(signer=signature["signer"], signature=signature["text"])
        if pending_removals(task):
            decision["confirmed_removals"] = pending_removals(task)
    return {**task, "status": status, "decision": decision}


ACTIONS = ("public-research", "external-api", "send-message", "publish", "install-dependency", "other")
_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")


def record_authorization(task: dict, action: str, target: str, allow: bool, by: str, reason: str) -> dict:
    """Record a person's decision on an external action outside the authorized scope."""
    if action not in ACTIONS:
        raise ValueError(f"Choose the action from {', '.join(ACTIONS)}.")
    if not _TARGET.fullmatch(target) or "?" in target or "@" in target:
        raise ValueError("Name the target as a host or tool name, without a query, an address or private details.")
    if not by.strip() or not reason.strip():
        raise ValueError("Supply the decision owner and a reason.")
    entry = {
        "action": action, "target": target, "decision": "allow" if allow else "deny",
        "by": by.strip(), "reason": reason.strip(), "at": timestamp(),
    }
    return {**task, "authorizations": [*task.get("authorizations", []), entry]}


def require_current_scope(task: dict, profile: dict, catalog: dict) -> None:
    if task.get("profile_fingerprint") != profile_fingerprint(profile, catalog):
        if task["status"] in ("approved", *DONE_STATUSES):
            raise ValueError(stale_approval_message(task["id"], rule_changes(task, profile, catalog)))
        raise ValueError("The project profile or catalog changed. Request changes and consult again.")
