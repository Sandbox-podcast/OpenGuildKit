"""The consultation and the boards' review of a task: recording them, the rounds kept when it is consulted again,
the sequential passes, and the text a person reads before deciding.

Entry: record_consultation, record_review, start_pass, submit_pass, assemble_review, decision_text
Tests: tests/test_approval_lifecycle.py, tests/test_blocker_clearances.py, tests/test_blockers.py,
tests/test_deliberation.py
"""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from . import requester, short_lane
from .alerts import resolution_line, resolved_by_import
from .approval_check import approval_problem
from .board_entries import review_warnings, validate_board_entry, validate_review
from .code_lookup import code_lookup
from .consultation import consult
from .project_rules import fingerprint_holds, profile_fingerprint, task_scope_profile
from .questionnaire import validate_answers
from .sensitive import redact_data
from .tasks_approval import decided_message, stale_review_message
from .tasks_record import RESOLUTION_FIELDS, timestamp, validate_brief
from .workflow import TaskStateError, blocker_resolutions, decision_summary, is_decision_task


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
    paths += [item["evidence"] for item in blocker_resolutions(task).values() if item["kind"] == "cleared"]
    logs = f".openguildkit/tasks/{task['id']}-checks/"
    return [path for path in dict.fromkeys(paths)
            if isinstance(path, str) and path and not path.startswith(("https://", "command:", logs))
            and not any(character.isspace() for character in path)]


def record_consultation(
    task: dict, answers: dict, profile: dict, catalog: dict, selection: dict | None = None,
    host_controls: list[dict] | None = None, market: dict | None = None, storybook: dict | None = None,
    knowledge: Mapping[str, dict] | None = None, tools: list[dict] | None = None, root: Path | None = None,
    brief: str | None = None,
) -> dict:
    """Record a consultation. With the project root, a bug brief's files and functions are looked for in it.

    A brief can be revised at any consultation, the passes then start over; after a change request, the earlier round
    is kept. An approval that no longer holds (earlier rules, a revision a rebase replaced, a seal or a signature that
    fails) is consulted again under the same ID: it is kept in rounds with the reason, and the passes of the boards
    whose brief did not change are kept.
    """
    reopened = None
    if task["status"] == "approved":
        reopened = approval_problem(task, profile, catalog, root)
        if not reopened or reopened["severity"] != "error":
            raise ValueError(decided_message(task))
    elif task["status"] == "reviewed" and not fingerprint_holds(task.get("profile_fingerprint"), profile, catalog):
        raise ValueError(stale_review_message(task["id"]))
    elif task["status"] not in {"draft", "consulting", "changes-requested"}:
        raise ValueError(decided_message(task) or (
            f"The review of {task['id']} is recorded and waits for the person's decision: they approve it or request "
            f"changes at their terminal (openguildkit task decide {task['id']}), and you consult again after a change "
            "request."))
    rounds = list(task["rounds"])
    # A withdrawn approval went to the rounds when the person withdrew it.
    if task["status"] in {"changes-requested", "approved"} and not task["decision"].get("withdraws"):
        archived = archived_round(task)
        if reopened:
            archived["reopened"] = reopened["message"]
        rounds.append(archived)
    validated = validate_answers(cast(dict, redact_data(answers)))
    result = {**task, "answers": validated, "rounds": rounds}
    if brief is not None:
        result["brief"] = validate_brief(brief)
    missing, not_searched = None, None
    if root is not None and validated["kind"] == "bug":
        missing, not_searched = code_lookup(" ".join([result["brief"], validated.get("context", "")]), root)
    result.update(
        status="consulting",
        consultation=consult(
            task_scope_profile(profile, catalog, validated.get("components", [])),
            catalog, result, selection, host_controls, market, storybook,
            knowledge, tools, missing, not_searched,
        ),
        profile_fingerprint=profile_fingerprint(profile, catalog),
    )
    for key in ("review", "decision", "passes", "deliberation", *RESOLUTION_FIELDS, "result", "waiting_for"):
        result.pop(key, None)
    # A broken seal means the review itself may have been edited: every board reviews again.
    if reopened and reopened["kind"] not in ("invalid-seal", "no-seal"):
        kept = kept_passes(task, result["consultation"])
        if kept["boards"]:
            result["passes"] = kept
            left = [board_id for board_id in result["consultation"]["boards"] if board_id not in kept["boards"]]
            result["consultation"]["markdown"] += kept_passes_note(task["id"], sorted(kept["boards"]), left)
    return result


# Each round of a task keeps these fields of the record it closes, the clearances of both phases included.
ROUND_FIELDS = ("brief", "answers", "consultation", "review", "decision", "profile_fingerprint", "deliberation",
                *RESOLUTION_FIELDS, "result")


def archived_round(task: dict) -> dict:
    """The record of a round as the rounds keep it, when the task is consulted again or its approval withdrawn."""
    return {key: task[key] for key in ROUND_FIELDS if key in task}


def kept_passes(task: dict, consultation: dict) -> dict:
    """The passes of the approved round whose board brief and entry template did not change: same board, same rules,
    same questions. The person approves again over them; task pass BOARD --again redoes one."""
    previous = task["consultation"]
    entries = {entry["id"]: entry for entry in task["review"]["boards"]}
    templates = [{item["id"]: item for item in source["review_template"]["boards"]}
                 for source in (previous, consultation)]
    mode = "subagent" if task["review"].get("execution") == "subagents" else "sequential"
    boards = {}
    for board_id in consultation["boards"]:
        before = previous.get("board_briefs", {}).get(board_id)
        unchanged = before is not None and before == consultation.get("board_briefs", {}).get(board_id)
        if board_id in entries and unchanged and templates[0].get(board_id) == templates[1].get(board_id):
            boards[board_id] = {"status": "done", "mode": mode, "entry": entries[board_id], "at": timestamp(),
                                "attempts": 0, "kept_from": previous["id"]}
    return {"consultation_id": consultation["id"], "boards": boards}


def kept_passes_note(task_id: str, kept: list[str], left: list[str]) -> str:
    """The consultation's note on the passes kept from the approved round, and what remains before the decision."""
    remaining = (f"Run the passes of {', '.join(left)} (openguildkit task pass {task_id} BOARD), then" if left
                 else "Every pass is kept: run")
    return (f"\n\n## Passes kept from the approved round\n\nThe brief, the rules and the entry template of these "
            f"boards did not change, so their passes are kept as done: {', '.join(kept)}. {remaining} openguildkit "
            f"task review {task_id} --summary TEXT; the person approves again. To redo a kept pass: openguildkit "
            f"task pass {task_id} BOARD --again.\n")


def previous_round_line(task: dict) -> str | None:
    """One line recalling the previous round's decision and its reason, for the next round's decision."""
    if not task.get("rounds"):
        return None
    earlier = task["rounds"][-1]
    decision = earlier["decision"]
    outcome = "changes requested" if decision["outcome"] == "changes-requested" else decision["outcome"]
    revised = " The brief was revised since." if earlier.get("brief", task["brief"]) != task["brief"] else ""
    reopened = f" Reopened: {earlier['reopened']}" if earlier.get("reopened") else ""
    revoked = earlier.get("revoked")
    withdrawn = (f" Withdrawn by {revoked['by']} on {revoked['at'][:10]}: {revoked['reason'].rstrip('.')}."
                 if revoked else "")
    return (f"Round {len(task['rounds']) + 1}. Round {len(task['rounds'])}: {outcome} by {decision['by']} "
            f"on {decision['at'][:10]}: {decision['reason'].rstrip('.')}.{revised}{reopened}{withdrawn}")


def _check_change(profile: dict, action: str, command: str) -> str:
    """Who changed a check command through the profile commands, when and why, from the profile's history."""
    for entry in reversed(profile.get("changes", [])):
        if entry["change"].startswith(f"{action} check ") and command in entry["change"]:
            return f"{action} check by {entry['by']} on {entry['on']}: {entry['reason']}"
    return "no profile command recorded it: the profile was edited by hand"


def check_command_lines(task: dict, profile: dict, previous: dict | None = None) -> list[str]:
    """The shell commands task verify will run for the task, and those added or removed since the previous approval
    of the project, each with who changed it: a command added after one approval runs after the next."""
    if is_decision_task(task):
        return []
    commands = task["consultation"]["scope"].get("checks", [])
    lines = [f"Check command command:{index}, which task verify runs as a shell command in the project root: "
             f"`{command}`" for index, command in enumerate(commands, start=1)]
    if not commands:
        lines.append("Check commands: none; task verify runs no test for this task.")
    if previous is None:
        return lines
    since = f"since the last approval of the project ({previous['task']} on {previous['at'][:10]})"
    lines += [f"Check command added {since}: `{command}` ({_check_change(profile, 'add', command)})."
              for command in commands if command not in previous["checks"]]
    lines += [f"Check command removed {since}: `{command}` ({_check_change(profile, 'remove', command)})."
              for command in previous["checks"] if command not in commands and command not in profile.get("checks", [])]
    return lines


def decision_text(task: dict, profile: dict, previous: dict | None = None, register: dict | None = None) -> list[str]:
    """What the person reads before deciding, built once for the approval prompt, task challenge and task
    decision-payload: the decision summary (verdicts, warnings, conditions of approval, removals, blockers), the check
    commands task verify will run with those changed since the project's last approval, and the task's confirmed
    critical alerts that an import resolved since its last decision."""
    lines = (requester.brief_line(task, profile) + short_lane.decision_lines(task) + decision_summary(task)) + check_command_lines(task, profile, previous)
    if register is not None:
        since = task["rounds"][-1]["decision"]["at"] if task["rounds"] else None
        lines += [resolution_line(alert) for alert in resolved_by_import(register, task, since)]
    return lines


def record_review(task: dict, review: dict, root: Path | None = None, kept: list[str] | None = None) -> dict:
    """Record the review; with the project root, the project files and tests it cites must exist.

    kept names the passes kept from an approved round (kept_passes), so the person reads which boards did not review
    again; a review file cannot claim it.
    """
    if task["status"] != "consulting":
        raise TaskStateError("A review is recorded while the task is being consulted.")
    review = validate_review(task["consultation"], {key: value for key, value in review.items() if key != "kept"}
                             if isinstance(review, dict) else review, root)
    if kept:
        review["kept"] = kept
    result = {**task, "status": "reviewed", "review": review}
    result.pop("passes", None)
    return result


def _passes(task: dict) -> dict:
    if task["status"] != "consulting":
        raise TaskStateError("Board passes can only run while the task is being consulted.")
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


def earlier_sequential_pass(task: dict, board_id: str) -> str | None:
    """In passes run one after the other, another board whose pass of this consultation was already started: it
    printed the instructions every pass shares, which the one agent running the sequence keeps in mind."""
    boards = (task.get("passes") or {}).get("boards", {})
    if boards.get(board_id, {}).get("mode") != "sequential":
        return None
    return next((other for other in task["consultation"]["boards"] if other != board_id
                 and boards.get(other, {}).get("mode") == "sequential" and not boards[other].get("kept_from")), None)


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
    others = [state["entry"] for other, state in passes["boards"].items()
              if other != validated["id"] and state.get("status") == "done"]
    passes["boards"][validated["id"]] = {"status": "done", "mode": mode, "entry": validated, "at": timestamp(),
                                         "attempts": current.get("attempts", 1)}
    # The signs of copied advice that concern this entry, against the passes already done: each submit says what
    # its own pass adds, not the warnings of the earlier passes again.
    copied = review_warnings([*others, validated], focus=validated["id"])
    return {**task, "passes": passes, **({"_warnings": copied} if copied else {})}


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
        raise TaskStateError(f"The review assembles every board's pass, and {', '.join(waiting)} "
                             f"{'is' if len(waiting) == 1 else 'are'} not done.")
    modes = {passes["boards"][board_id]["mode"] for board_id in task["consultation"]["boards"]}
    execution = "subagents" if modes == {"subagent"} else "sequential" if modes == {"sequential"} else "mixed"
    review = {
        "consultation_id": task["consultation"]["id"],
        "summary": summary,
        "boards": [passes["boards"][board_id]["entry"] for board_id in task["consultation"]["boards"]],
        "execution": execution,
    }
    kept = [board_id for board_id in task["consultation"]["boards"] if passes["boards"][board_id].get("kept_from")]
    return record_review(task, review, kept=kept)
