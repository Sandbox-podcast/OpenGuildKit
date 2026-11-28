"""Deciding and closing a task: the decision and its withdrawal, authorizations of external actions, the result,
evidence handed to a follow-up task, and the points left open.

Entry: record_decision, revoke_approval, record_authorization, record_result, complete_task, points_left_open
Tests: tests/test_blocker_clearances.py, tests/test_blockers.py, tests/test_closing_points.py,
tests/test_deliberation.py
"""

import re
from pathlib import Path

from . import clock, delivered_review
from .approval_check import DONE_STATUSES
from .decisions import decision_payload, seal, signing_time_of
from .relevance import sensitive_area
from .result_form import validate_result
from .results import (
    asked_checks,
    completion_problems,
    evidence_state,
    merge_results,
    not_concerned,
    outcomes,
    result_warnings,
    waiting_evidence,
)
from .tasks_approval import decided_message
from .tasks_blockers import expired_waiver_step, expired_waivers, unresolved_blockers, verification_blocker_problems
from .tasks_record import timestamp
from .tasks_review import archived_round
from .wording import plural
from .workflow import (
    TaskStateError,
    blocker_list,
    is_decision_task,
    pending_removals,
    resolution_field,
    validate_deliberation,
)

CHANGED_EVIDENCE_GROUP = "Evidence changed since it was accepted"


def accepted_evidence(task: dict) -> list[tuple[str, str, str | None]]:
    """Each evidence a clearance or a passed named evidence cites: the evidence, what it was accepted for and its
    fingerprint, None for one recorded before fingerprints."""
    cited = [(item["resolution"]["evidence"], f"blocker {item['id']}", item["resolution"].get("fingerprint"))
             for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "cleared"]
    return cited + [(item["evidence"], item["check"], item.get("fingerprint"))
                    for item in task.get("result", {}).get("checks", [])
                    if item["check"].startswith("evidence:") and item["status"] == "passed" and "evidence" in item]


def evidence_states(task: dict, root: Path) -> list[dict]:
    """Each evidence a clearance or a passed named evidence cites, with its state now, once one has a fingerprint:
    a task recorded before fingerprints lists none."""
    cited = accepted_evidence(task)
    if not any(fingerprint for _, _, fingerprint in cited):
        return []
    return [{"evidence": value, "for": name, "state": evidence_state(root, value, fingerprint)}
            for value, name, fingerprint in cited]


def changed_evidence(task: dict, root: Path) -> list[str]:
    """The evidence changed or gone since it was accepted, with who accepted it and when: an open point of the
    closing and a line of task list. guard --ci does not read it (question Q2 of the plan is not decided)."""
    accepted = {f"blocker {item['id']}": f"cleared on {item['resolution'].get('at', '')[:10]} by {item['resolution']['by']}"
                for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "cleared"}
    accepted.update({item["check"]: f"confirmed by {item.get('owner', 'nobody named')}"
                     for item in task.get("result", {}).get("checks", []) if item["check"].startswith("evidence:")})
    points = []
    for item in evidence_states(task, root):
        if item["state"] in ("changed", "missing"):
            how = "was cleared" if item["for"].startswith("blocker ") else "was recorded"
            points.append(f"{item['evidence']} {'changed' if item['state'] == 'changed' else 'is missing'} since "
                          f"{item['for']} {how} ({accepted[item['for']]})")
    return points


def record_result(task: dict, profile: dict, payload: dict, source: str = "report", relevance: dict | None = None,
                  root: Path | None = None, *, changed: list[str] | None = None) -> dict:
    """Add a delivery report to an approved task; later reports update earlier checks.

    A named evidence that cannot be recorded is held back under "_held" (for the caller to print and
    drop) and the rest is recorded: the task then waits for that evidence from its owner.
    """
    if task["status"] != "approved":
        raise TaskStateError("Results belong to an approved task that is not done yet.")
    validated = validate_result(task, profile, payload, source, relevance, root, changed=changed)
    held = validated.pop("_held", [])
    result = merge_results(task.get("result"), validated, source)
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
                + [f"Blocker {item['id']}: {expired_waiver_step(task, item)}" for item in expired_waivers(blocker_list(task))
                   if item.get("phase") != "verification"]
                + completion_problems(task, profile, relevance, changed=changed, root=root))
    if problems:
        raise ValueError("The task cannot be declared done:\n- " + "\n- ".join(problems))
    groups = points_left_open(task, profile, relevance, root)
    sensitive = next((group for group in groups if group["group"] == SENSITIVE_GROUP), None)
    if sensitive and not (by or "").strip():
        raise ValueError(
            f"{plural(len(sensitive['points']), 'data protection, security or AI point')} "
            f"{'is' if len(sensitive['points']) == 1 else 'are'} skipped, failed or declared not "
            "applicable as a pack. A person "
            f"confirms closing over them: openguildkit task complete {task['id']} --by INITIALS, at a terminal."
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
# The other titles of the closing that other readers (the retrospective) tell apart.
NOT_RUN_GROUP = "Project checks that could not run in this environment"
OTHER_RULES_GROUP = "Other rules skipped or failed"
VERDICTS_GROUP = "Board verdicts at approval that asked for changes"
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


def points_left_open(task: dict, profile: dict, relevance: dict | None = None, root: Path | None = None) -> list[dict]:
    """What a closed task leaves open, grouped by nature, most serious first; empty groups are left out. With the
    project root, evidence changed since it was accepted too."""
    checks = {check["id"]: check for check in asked_checks(task, profile, relevance)}
    reported = outcomes(task, profile, relevance)
    sensitive: list[str] = []
    other: list[str] = []
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
        (delivered_review.FINDINGS_GROUP, delivered_review.open_points(task)),
        (CHANGED_EVIDENCE_GROUP, changed_evidence(task, root) if root is not None else []),
        (NOT_RUN_GROUP, [
            f"{item['check']} could not run: {item['reason']} (recorded by {item['owner']})"
            for item in result.get("checks", []) if item.get("cannot_run")]),
        ("Blockers waived rather than cleared", [
            f"blocker {item['id']} is waived until {item['resolution']['until']}"
            for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "waived"]),
        ("Disagreements between boards left open", _open_disagreements(task)),
        ("Named evidence handed to a follow-up task", [
            f"{item['check']} is handed to task {item['task']}, provided by {item['owner']} (recorded by {item['by']})"
            for item in result.get("deferred", [])]),
        (OTHER_RULES_GROUP, other),
        ("Warnings on the result", list(result.get("warnings", []))),
    ]
    found = [{"group": title, "points": points} for title, points in groups if points]
    verdicts = [f"{entry['id']} said {entry['challenge']['verdict']}" for entry in task.get("review", {}).get("boards", [])
                if entry.get("challenge", {}).get("verdict") == "revise"]
    if found and verdicts:
        found.append({"group": VERDICTS_GROUP, "points": verdicts})
    return found


def record_deliberation(task: dict, payload: dict) -> dict:
    return {**task, "deliberation": validate_deliberation(task, payload)}


def record_decision(
    task: dict, approve: bool, by: str, reason: str, base_revision: dict | None = None, signature: dict | None = None,
    confirmed_removals: list[str] | None = None, separate: bool = False, signed_at: str | None = None,
    dated: bool = False,
) -> dict:
    """Record the person's decision. Approving needs their confirmation of each protected board removed. separate
    says that the profile separated the requester from the approver: the approval and its seal record it. signed_at,
    when the approver signed a payload that carries it, is recorded and sealed with the approval. dated has a local
    approval carry the time of its decision as signed_at, under its seal (the audit log, #454); a signed approval
    keeps the time its signer gave, or none: the signer signs before the decision is dated."""
    if task["status"] != "reviewed":
        decided = decided_message(task)
        if decided:
            raise ValueError(decided)
        raise TaskStateError("Record the boards' review before deciding.")
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
    # A person's decision is dated by the real clock, which its age is measured with (clock.py).
    at = clock.real_timestamp()
    decision: dict[str, object] = {"outcome": status, "by": by.strip(), "reason": reason.strip(), "at": at}
    if approve:
        if dated and signature is None and not signed_at:
            signed_at = signing_time_of(at)
        payload = decision_payload(task, by, reason, base_revision, separate=separate, signed_at=signed_at)
        decision.update(base_revision=base_revision, seal=seal(payload))
        if separate:
            decision["separate_requester"] = True
        if signed_at:
            decision["signed_at"] = signed_at
        if signature is not None:
            decision.update(signer=signature["signer"], signature=signature["text"])
        if pending_removals(task):
            decision["confirmed_removals"] = pending_removals(task)
    return {**task, "status": status, "decision": decision}


def revoke_approval(task: dict, by: str, reason: str) -> dict:
    """Withdraw an approval: the task goes back to changes requested, and the approval goes to the rounds with who
    withdrew it, when and why. The person does it at their terminal, as they approved; the guard stops counting the
    task at once."""
    task_id, status = task["id"], task["status"]
    if status in DONE_STATUSES:
        raise ValueError(decided_message(task))
    if status != "approved":
        raise TaskStateError("Only an approved task has an approval to withdraw.")
    if not by.strip() or not reason.strip():
        raise ValueError("Name the person who withdraws the approval with --by and say why with --reason.")
    at = clock.real_timestamp()
    archived = {**archived_round(task), "revoked": {"by": by.strip(), "reason": reason.strip(), "at": at}}
    decision = {"outcome": "changes-requested", "by": by.strip(), "reason": f"Approval withdrawn: {reason.strip()}",
                "at": at, "withdraws": task["decision"]["at"]}
    result = {**task, "status": "changes-requested", "decision": decision, "rounds": [*task["rounds"], archived]}
    for key in (resolution_field("verification"), "result", "waiting_for", "completed_at"):
        result.pop(key, None)
    return result


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
        "by": by.strip(), "reason": reason.strip(), "at": clock.real_timestamp(),
    }
    return {**task, "authorizations": [*task.get("authorizations", []), entry]}
