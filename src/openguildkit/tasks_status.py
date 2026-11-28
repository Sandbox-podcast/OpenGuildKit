"""The next step of a task and the command that takes it, what its status refuses, the words that describe its
decision, and the line the task list shows for it, kept while nothing it was built from changed."""

import hashlib
import os
import time
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from . import clock, light_lane, task_index
from .decisions import DECISIONS_DIR, EARLIER_SIGNERS, reconsult_command
from .project import Fingerprints
from .results import DONE_STATUSES
from .storage import file_signature
from .tasks_approval import decided_message, revoke_command, stale_review_message
from .tasks_blockers import expired_waiver_step, expired_waivers, unresolved_blockers, waiver_policy
from .tasks_closing import accepted_evidence, changed_evidence
from .tasks_record import shape_problem
from .tasks_review import pass_progress
from .wording import plural
from .workflow import blocker_list, is_decision_task


def next_step(task: dict, profile: dict | None = None) -> str:
    """The open point that keeps a task from moving on; with the profile, whether a waiver can still close it."""
    status = task["status"]
    if status == "draft":
        return ("Consult the boards: the short lane asks no questions." if light_lane.is_light(task)
                else "Answer the questionnaire and consult the boards.")
    if status == "consulting":
        progress = pass_progress(task)
        waiting = [item["board"] + (" (failed)" if item["status"] == "failed" else "") for item in progress
                   if item["status"] in ("missing", "failed")]
        started = [item["board"] for item in progress if item["status"] == "started"]
        if not waiting and not started:
            return "Write the summary and record the review."
        # A started pass is under way, not pending: it waits for its entry.
        parts = [f"Board reviews pending: {', '.join(waiting)}"] if waiting else []
        if started:
            parts.append(f"{'p' if waiting else 'P'}asses started, waiting for their entry: {', '.join(started)}")
        return "; ".join(parts) + "."
    if status == "reviewed":
        blockers = unresolved_blockers(task)
        return f"Resolve blockers {', '.join(blockers)}." if blockers else "Waiting for the person's decision."
    if status == "changes-requested":
        return f"Consult again: {task['decision']['reason']}"
    if status == "approved":
        return _approved_step(task) + _conditions_step(task, profile) + _abandoned_step(task)
    if status == "done-with-reservations":
        return f"Done with reservations: see the open points with openguildkit task show {task['id']} --closing."
    return "Done."


# How a refusal names a status that has no decision yet.
_STATUS_WORDS = {"draft": "a draft, not consulted yet", "consulting": "being consulted",
                 "reviewed": "reviewed and waits for the person's decision"}


def next_command(task: dict) -> str:
    """The command that moves a task on from its status, said to the agent: a refusal ends with it, so that a refused
    command leads to one that runs."""
    task_id, status = task["id"], task["status"]
    if status == "draft" and light_lane.is_light(task):
        return (f"consult the one board its paths call for with openguildkit task consult {task_id}: the short lane asks "
                "no questions")
    if status == "draft":
        return (f"read the questions with openguildkit task questions {task_id}, then consult the boards with "
                f"openguildkit task consult {task_id} --answers FILE")
    if status == "consulting":
        progress = pass_progress(task)
        review = f"openguildkit task review {task_id} --summary TEXT"
        to_run = [item["board"] for item in progress if item["status"] in ("missing", "failed")]
        started = [item["board"] for item in progress if item["status"] == "started"]
        steps = [f"run the passes of {', '.join(to_run)} (openguildkit task pass {task_id} BOARD)"] if to_run else []
        if started:
            steps.append(f"submit the entries of {', '.join(started)} (openguildkit task submit {task_id} --file ENTRY)")
        return f"{'; '.join(steps)}; then {review}" if steps else f"every pass is done: {review}"
    if status == "reviewed":
        decide = (f"the person decides at their terminal: openguildkit task decide {task_id} --approve (or "
                  "--request-changes) --by INITIALS --reason TEXT")
        blockers = unresolved_blockers(task)
        if blockers:
            return (f"the person clears {', '.join(blockers)} at their terminal (openguildkit task clear {task_id} "
                    f"BLOCKER --evidence PATH --supports TEXT --by INITIALS) or requests changes, then {decide}")
        return decide
    if status == "changes-requested":
        return f"consult again: {reconsult_command(task_id)} (--answers FILE to change the answers)"
    if status == "approved":
        if is_decision_task(task):
            return f"close the decision with openguildkit task complete {task_id}"
        if not task.get("result"):
            return f"implement the handoff (openguildkit task handoff {task_id}), then openguildkit task verify {task_id}"
        return f"openguildkit task verify {task_id}, then openguildkit task complete {task_id}"
    return f'open a follow-up task: openguildkit task new "BRIEF" --follows {task_id}'


def passes_left(task: dict) -> str:
    """After an entry is recorded: how many passes are left and the command that comes next."""
    left = [item for item in pass_progress(task) if item["status"] != "done"]
    if not left:
        return f"Every pass is done: write the summary and run openguildkit task review {task['id']} --summary TEXT."
    return f"{len(left)} {'pass' if len(left) == 1 else 'passes'} left: {next_command(task)}."


def state_refusal(task: dict, refused: str, problem: dict | None = None) -> str:
    """A refused action on a task whose status it does not fit: what is refused, then the status and the next
    command that runs. A decided task says who decided and what fits next (decided_message, with the task's
    approval_problem when an approval no longer holds)."""
    decided = decided_message(task, problem)
    if decided:
        return f"{refused} {decided}"
    words = _STATUS_WORDS.get(task["status"], task["status"])
    return f"{refused} Task {task['id']} is {words}: next, {next_command(task)}."


# An approval older than this, with nothing recorded since, may be abandoned: task list and the guard say so.
STALE_DAYS = 14


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


def _conditions_step(task: dict, profile: dict | None) -> str:
    """The conditions of approval still open and, without a waiver policy, the way out if one cannot be met; then the
    waivers that expired since, each with what the person can do."""
    waiting = [item["id"] for item in blocker_list(task)
               if item.get("phase") == "verification" and not item["resolution"]]
    expired = "".join(f" {expired_waiver_step(task, item)}" for item in expired_waivers(blocker_list(task)))
    if not waiting:
        return expired
    text = (f" {'Condition' if len(waiting) == 1 else 'Conditions'} of approval still open: {', '.join(waiting)}. The person clears each with its evidence at "
            f"their terminal: openguildkit task clear {task['id']} BLOCKER --evidence PATH --supports TEXT --by INITIALS.")
    if profile is not None and not waiver_policy(profile):
        text += (" The project allows no waiver, so the task cannot complete while one is open: if one cannot be met, "
                 f"the person withdraws the approval at their terminal: {revoke_command(task['id'])}.")
    return text + expired


def _abandoned_step(task: dict) -> str:
    """An old approval with nothing recorded since still lets every edit through the guard: name the way to end it."""
    age = days_since(task["decision"].get("at"))
    if task.get("result") or is_decision_task(task) or age is None or age <= STALE_DAYS:
        return ""
    return (f" Approved {age} days ago with no result recorded, and the guard lets every edit through while it is "
            f"approved: if the work is abandoned, the person withdraws the approval: {revoke_command(task['id'])}.")


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
        more = f" and {plural(len(failed) - 1, 'other check')}" if len(failed) > 1 else ""
        return f"{item['check']}{what} failed{cause}{more}. Fix it, then run task verify {task_id}."
    waiting = result.get("waiting_for", [])
    if waiting:
        return "Waiting for evidence: " + "; ".join(f"{item['title']} from {item['owner']}" for item in waiting) + "."
    return f"Result recorded: run task verify {task_id} to list what remains, then task complete {task_id}."


def task_row(task: dict, problem: dict | None, profile: dict | None, fingerprints: Fingerprints | None,
             root: Path | None) -> dict:
    """A task's line of task list, but for the tasks it waits for, which depend on the others; problem is its
    approval_problem, fingerprints those of the profile when the approval is judged."""
    # An approval that holds through the signers of the revision it was signed at keeps its next step.
    note = problem if problem and problem["kind"] == EARLIER_SIGNERS else None
    row = {"id": task["id"], "status": task["status"], "created": task["created_at"][:10],
           "owner": None if problem and problem["kind"] == "invalid-seal" else task.get("decision", {}).get("by"),
           "brief": task["brief"].splitlines()[0][:80],
           "next": problem["message"] if problem and not note else next_step(task, profile)}
    if fingerprints is not None and task["status"] == "reviewed" and \
            not fingerprints.holds(task.get("profile_fingerprint")):
        row["next"] = stale_review_message(task["id"])
    decided = decision_words(task, problem)
    if decided:
        row["decided"] = decided
    if note:
        row["note"] = note["message"]
    if problem:
        row.update(approval_problem=problem["kind"], severity=problem["severity"])
    closed_by = task.get("result", {}).get("closing", {}).get("by")
    if closed_by:
        row["closed_by"] = closed_by
    if task.get("follows"):
        row["follows"] = task["follows"]["task"]
    if light_lane.is_light(task):
        row.update(lane=task["lane"], paths=task["paths"])
    changed = changed_evidence(task, root) if root is not None else []
    if changed:
        row["evidence_changed"] = changed
    if task.get("after"):
        row["after"] = task["after"]
    return row


# The line of a closed task the status index keeps (line_to_keep), checked again when it is read back (kept_line).
_LINE_ROW = {"id": str, "status": str, "created": str, "owner": (str, type(None)), "brief": str, "next": str,
             "decided?": str, "closed_by?": str, "follows?": str, "lane?": str, "paths?": [str], "after?": [str]}
_LINE_FIELDS = {key.rstrip("?") for key in _LINE_ROW}
_LINE = {"code": str, "fingerprint": str, "row": _LINE_ROW, "export": ([int], type(None))}


@cache
def _code_stamp() -> str | None:
    """What changes with the code that writes the lines the status index keeps: the name, size and modification time
    of each module of the package, so that another release or an edited checkout reads the records again."""
    try:
        modules = sorted((item.name, item.stat().st_size, item.stat().st_mtime_ns)
                         for item in os.scandir(Path(__file__).parent) if item.name.endswith(".py"))
    except OSError:
        return None
    return hashlib.sha256(repr(modules).encode()).hexdigest()


def line_to_keep(state: Path, task: dict, row: dict, problem: dict | None,
                 fingerprints: Fingerprints | None) -> dict | None:
    """What the status index keeps of a closed task's line: the row, the fingerprint of the rules it was approved
    under and the signature of its exported record (None without one). None when the line depends on more than the
    record and the rules: an approval that does not hold, evidence whose file may change, an exported record of
    another task under its ID, which task list names at each run."""
    from .guard import record_of_another_task  # The guard reads task records: it is loaded once this module is.

    code = _code_stamp()
    if task["status"] not in DONE_STATUSES or problem or fingerprints is None or code is None or \
            any(fingerprint for _, _, fingerprint in accepted_evidence(task)):
        return None
    # Taken before the record is read, and not trusted just after a write: as for the index, a second write within
    # the same clock tick could keep the signature.
    export = file_signature(state / DECISIONS_DIR / f"{task['id']}.json")
    if (export and export[1] + task_index.RACY_NANOSECONDS >= time.time_ns()) or record_of_another_task(state, task):
        return None
    return {"code": code, "fingerprint": task["profile_fingerprint"], "row": dict(row),
            "export": list(export) if export else None}


def kept_line(state: Path, entry: dict, task_id: str, fingerprints: Fingerprints | None) -> dict | None:
    """The line the status index keeps for a closed task while its record, its exported record, the code that wrote
    the line and the rules it was approved under all hold; None otherwise, and the record is read."""
    line = entry.get("line")
    if entry.get("checked") is not True or fingerprints is None or not isinstance(line, dict) or \
            shape_problem(line, _LINE, "line"):
        return None
    row, export = line["row"], file_signature(state / DECISIONS_DIR / f"{task_id}.json")
    if (line["code"], row["id"], row["status"], line["export"]) != \
            (_code_stamp(), task_id, entry.get("status"), list(export) if export else None) or \
            row["status"] not in DONE_STATUSES or not set(row) <= _LINE_FIELDS:
        return None
    return line if fingerprints.holds(line["fingerprint"]) else None


def decision_words(task: dict, problem: dict | None = None) -> str | None:
    """Who took the task's current decision, in the words task list prints: "approved by X", "changes requested by
    X", "withdrawn by X (approved by Y)", or that the approval no longer holds (problem is its approval_problem)."""
    decision = task.get("decision")
    if not decision:
        return None
    by = decision["by"]
    if decision["outcome"] == "changes-requested":
        if decision.get("withdraws"):
            approver = next((entry["decision"]["by"] for entry in reversed(task["rounds"]) if entry.get("revoked")), None)
            return f"withdrawn by {by}" + (f" (approved by {approver})" if approver else "")
        return f"changes requested by {by}"
    if problem and problem["severity"] == "error":
        # A broken seal means the name itself may have been edited.
        return ("approval no longer holds" if problem["kind"] == "invalid-seal"
                else f"approved by {by}, approval no longer holds")
    return f"approved by {by}"
