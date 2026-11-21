"""Track task consultations and decisions in the project."""

import re
import uuid
from datetime import datetime
from pathlib import Path

from . import clock
from .decisions import approval_policy, check_decision_seal, decision_payload, seal, stale_approval_message, verify_signature
from .project import profile_fingerprint, task_scope_profile
from .results import completion_problems, expected_checks, merge_results, validate_result
from .storage import read_json, write_json
from .workflow import blocker_list, consult, entry_problems, is_decision_task, pending_removals, validate_answers, validate_board_entry, validate_deliberation, validate_review

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


def read_task(state: Path, task_id: str) -> dict:
    path = task_path(state, task_id)
    if not path.is_file():
        raise ValueError(f"Unknown task: {task_id}")
    task = read_json(path)
    if task.get("schema_version") != 1 or task.get("id") != task_id:
        raise ValueError(f"Unsupported or mismatched task record: {path}")
    problem = _record_problem(task)
    if problem:
        # Task records are not under version control (.openguildkit/.gitignore lists tasks/).
        raise ValueError(f"Task record {task_id} is damaged: {problem}. Restore it from a backup or open a new task.")
    return task


STATUSES = {
    "draft": (),
    "consulting": ("answers", "consultation", "profile_fingerprint"),
    "reviewed": ("answers", "consultation", "profile_fingerprint", "review"),
    "changes-requested": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
    "approved": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
    "done": ("answers", "consultation", "profile_fingerprint", "review", "decision", "result"),
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
    "packs?": [{"id": str, "rules": [_RULE]}],
    "market?": {"id": str, "observations": [{"id": str}], "changes?": [dict], "relevance?": str},
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
            return f"a {status} task needs {field}"
    problem = _shape_problem(task, _RECORD, "")
    if problem:
        return problem
    for field in ("blocker_resolutions", "verification_blocker_resolutions"):
        for blocker, resolution in task.get(field, {}).items():
            missing = [key for key in _RESOLUTION_FIELDS[resolution["kind"]] if key not in resolution]
            if missing:
                return f"{field}.{blocker}.{missing[0]} is missing"
    return None


def create_task(state: Path, brief: str, task_id: str | None, follows: str | None = None) -> str:
    brief = brief.strip()
    if not brief:
        raise ValueError("Supply a task brief.")
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
        if task.get("answers", {}).get("kind") == "decision":
            return "Decision recorded. Open a follow-up task to act on it."
        return "Implement, then record the results and complete the task."
    return "Done."


def approval_problem(task: dict, current_fingerprint: str) -> dict | None:
    if task["status"] not in ("approved", "done"):
        return None
    try:
        check_decision_seal(task)
    except ValueError as error:
        return {"kind": "invalid-seal", "message": str(error)}
    if task.get("profile_fingerprint") != current_fingerprint:
        return {"kind": "earlier-rules", "message": stale_approval_message(task["id"])}
    return None


def list_tasks(state: Path, status: str | None = None, owner: str | None = None,
               since: str | None = None, until: str | None = None, *, current_fingerprint: str | None = None) -> list[dict]:
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
        problem = approval_problem(task, current_fingerprint) if current_fingerprint is not None else None
        decided_by = task.get("decision", {}).get("by")
        if problem and problem["kind"] == "invalid-seal":
            decided_by = None
        if owner and (decided_by or "").casefold() != owner.casefold():
            continue
        row = {"id": task["id"], "status": task["status"], "created": day, "owner": decided_by,
               "brief": task["brief"].splitlines()[0][:80], "next": problem["message"] if problem else next_step(task)}
        if problem:
            row["approval_problem"] = problem["kind"]
        if task.get("follows"):
            row["follows"] = task["follows"]["task"]
        rows.append(row)
    return rows


def consultation_brief(task: dict, revised_brief: str | None = None) -> str:
    if revised_brief is None:
        return task["brief"]
    if task["status"] != "changes-requested":
        raise ValueError("Revise a task brief after a request for changes.")
    brief = revised_brief.strip()
    if not brief:
        raise ValueError("Supply a revised task brief.")
    return brief


def record_consultation(
    task: dict, answers: dict, profile: dict, catalog: dict, selection: dict | None = None,
    host_controls: list[dict] | None = None, market: dict | None = None, storybook: dict | None = None,
    knowledge: dict | None = None, tools: list[dict] | None = None, *, revised_brief: str | None = None,
) -> dict:
    brief = consultation_brief(task, revised_brief)
    if task["status"] not in {"draft", "consulting", "changes-requested"}:
        raise ValueError("Start a new task or request changes before consulting again.")
    rounds = list(task["rounds"])
    if task["status"] == "changes-requested":
        archived = {key: task[key] for key in ("brief", "answers", "consultation", "review", "decision", "profile_fingerprint")}
        for key in ("deliberation", "blocker_resolutions"):
            if key in task:
                archived[key] = task[key]
        rounds.append(archived)
    validated = validate_answers(answers)
    result = {**task, "brief": brief, "answers": validated, "rounds": rounds}
    result.update(
        status="consulting",
        consultation=consult(
            task_scope_profile(profile, catalog, validated.get("components", [])),
            catalog, result, selection, host_controls, market, storybook,
            knowledge, tools,
        ),
        profile_fingerprint=profile_fingerprint(profile, catalog),
    )
    result.pop("review", None)
    result.pop("decision", None)
    result.pop("passes", None)
    result.pop("deliberation", None)
    result.pop("blocker_resolutions", None)
    result.pop("verification_blocker_resolutions", None)
    return result


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


def start_pass(task: dict, board_id: str, mode: str) -> dict:
    """Mark a board's pass as started; starting again replaces a failed or interrupted pass."""
    passes = _passes(task)
    if board_id not in task["consultation"]["boards"]:
        raise ValueError(f"Board {board_id!r} is not part of this consultation.")
    if mode not in ("subagent", "sequential"):
        raise ValueError("A pass runs as a subagent or in sequence.")
    previous = passes["boards"].get(board_id, {})
    passes["boards"][board_id] = {"status": "started", "mode": mode, "started_at": timestamp(),
                                  "attempts": previous.get("attempts", 0) + 1}
    return {**task, "passes": passes}


def submit_pass(task: dict, entry: dict, mode: str | None = None, root: Path | None = None) -> dict:
    """Record one board's entry. An invalid entry is recorded as a failure to retry."""
    passes = _passes(task)
    board_id = entry.get("id") if isinstance(entry, dict) else None
    current = passes["boards"].get(board_id, {}) if isinstance(board_id, str) else {}
    mode = mode or current.get("mode", "sequential")
    if isinstance(board_id, str) and board_id in task["consultation"]["boards"] and current.get("status") not in (
            "started", "failed", "done"):
        raise ValueError(f"The {board_id} pass was not started: run openguildkit task pass {task['id']} {board_id} "
                         "first, so that the entry belongs to a pass of this consultation.")
    try:
        validated = validate_board_entry(task["consultation"], entry, root)
    except ValueError as error:
        if isinstance(board_id, str) and board_id in task["consultation"]["boards"]:
            problems = entry_problems(task["consultation"], entry, root) or [str(error)]
            message = "; ".join(problems) if len(problems) == 1 else "\n  - " + "\n  - ".join(problems)
            passes["boards"][board_id] = {**current, "status": "failed", "mode": mode, "error": message,
                                          "at": timestamp(), "attempts": current.get("attempts", 1)}
            return {**task, "passes": passes, "_error": message}
        problems = entry_problems(task["consultation"], entry, root)
        if problems:
            raise ValueError(problems[0]) from None
        raise
    passes["boards"][validated["id"]] = {"status": "done", "mode": mode, "entry": validated, "at": timestamp(),
                                         "attempts": current.get("attempts", 1)}
    return {**task, "passes": passes}


def pass_progress(task: dict) -> list[dict]:
    """Each selected board with its pass status: done, failed, started (or interrupted) or missing."""
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
        raise ValueError(f"Blocker {blocker_id} already has a resolution. See task blockers.")
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


def record_result(task: dict, profile: dict, payload: dict, source: str = "report",
                  *, changed: list[str] | None = None) -> dict:
    """Add a delivery report to an approved task; later reports update earlier checks."""
    if task["status"] != "approved":
        raise ValueError("Results belong to an approved task that is not done yet.")
    result = merge_results(task.get("result"), validate_result(task, profile, payload, source, changed=changed))
    if source == "report" and task.get("answers", {}).get("outcome") and not result["criteria"]:
        raise ValueError(
            "The task has an expected outcome: report at least one acceptance criterion. Run task result ID --template."
        )
    return {**task, "result": result}


def complete_task(task: dict, profile: dict, root: Path | None = None, *, changed: list[str] | None = None) -> dict:
    problems = verification_blocker_problems(task, profile, root) + completion_problems(task, profile, changed=changed)
    if problems:
        raise ValueError("The task cannot be declared done:\n- " + "\n- ".join(problems))
    return {**task, "status": "done", "completed_at": timestamp()}


def points_left_open(task: dict, profile: dict) -> list[str]:
    """What a completed task leaves for later: rules not passed, waived blockers, disagreements still open."""
    mandatory = {check["id"] for check in expected_checks(task, profile) if check["mandatory"]}
    checks = [] if is_decision_task(task) else task.get("result", {}).get("checks", [])
    points = [
        f"{item['check']} is {item['status']}" for item in checks
        if item["status"] != "passed" and item["check"] not in mandatory and item["status"] != "not-applicable"
    ]
    points += [f"blocker {item['id']} is waived until {item['resolution']['until']}"
               for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "waived"]
    points += [
        f"{item['check']} was unavailable ({item['owner']}): {item['reason']}"
        for item in task.get("result", {}).get("checks", [])
        if item.get("environment_unavailable") is True and item["status"] == "skipped"
    ]
    points += [f"disagreement {item_id} was left open" for item_id in task.get("deliberation", {}).get("open", [])]
    return points


def record_deliberation(task: dict, payload: dict) -> dict:
    return {**task, "deliberation": validate_deliberation(task, payload)}


def record_decision(
    task: dict, approve: bool, by: str, reason: str, base_revision: dict | None = None, signature: dict | None = None,
    confirmed_removals: list[str] | None = None,
) -> dict:
    """Record the person's decision. Approving needs their confirmation of each protected board removed."""
    if task["status"] != "reviewed":
        raise ValueError("Record the boards' review before deciding.")
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
        if task["status"] in ("approved", "done"):
            raise ValueError(stale_approval_message(task["id"]))
        raise ValueError("The project profile or catalog changed. Request changes and consult again.")
