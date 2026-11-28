"""Blockers of an approved task: clearing one with evidence, waiving one within the project's policy, and the
waivers that expired.

Entry: resolve_blocker, unresolved_blockers, verification_blocker_problems, expired_waivers
Tests: tests/test_blocker_clearances.py, tests/test_blockers.py, tests/test_clock.py,
tests/test_evidence_fingerprints.py
"""

import re
from datetime import date, datetime
from pathlib import Path
from typing import cast

from . import clock, roles
from .approval_check import DONE_STATUSES
from .decisions import approval_policy, seal, verify_signature
from .errors import OgkError
from .records import Profile, Task, as_dict
from .results import evidence_fingerprint
from .tasks_approval import revoke_command
from .workflow import TaskStateError, blocker_list, resolution_field

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def waiver_policy(profile: Profile) -> dict | None:
    return profile.get("waivers")


def expired_on(resolution: object) -> str | None:
    """The end date of a waiver that has passed, by the real clock whatever SOURCE_DATE_EPOCH says; None for a waiver
    still running, a clearance or no resolution. A waiver holds through its until day."""
    if not isinstance(resolution, dict) or resolution.get("kind") != "waived":
        return None
    until = resolution.get("until")
    try:
        end = date.fromisoformat(until) if isinstance(until, str) and _DAY.fullmatch(until) else None
    except ValueError:
        return None
    return until if end is not None and end < clock.real_today() else None


def expired_waivers(blockers: list) -> list[dict]:
    """The blockers whose waiver expired: blocker_list of a task, or the blockers of an exported record."""
    return [item for item in blockers if isinstance(item, dict) and expired_on(item.get("resolution"))]


def expired_waiver_step(task: Task, item: dict) -> str:
    """What the person does about a waiver that expired on an approved task. A condition of approval is resolved
    again; a blocker the approval rested on is under its seal, so the approval is withdrawn."""
    task_id, blocker_id, until = task["id"], item["id"], item["resolution"]["until"]
    if item.get("phase") == "verification":
        return (f"The waiver of {blocker_id} expired on {until}, so the blocker is open again: the person clears it with "
                f"its evidence (openguildkit task clear {task_id} {blocker_id} --evidence PATH --supports TEXT --by "
                f"NAME), grants a new waiver (openguildkit task waive {task_id} {blocker_id} --by INITIALS --reason TEXT "
                f"--scope TEXT --until YYYY-MM-DD), or withdraws the approval: {revoke_command(task_id)}.")
    return (f"The waiver of {blocker_id} expired on {until}, and the approval rested on it: the person withdraws the "
            f"approval ({revoke_command(task_id)}), then the task is consulted again and the blocker cleared with its "
            "evidence or waived anew before the next decision.")


def expired_waiver_problem(record: dict, relative: str) -> str | None:
    """guard --ci: a record of a task not completed whose waiver expired is refused. A completed task's record is
    history: its waiver covered the work it delivered."""
    if record.get("completed") or record.get("status") in DONE_STATUSES:
        return None
    blockers = record.get("blockers")
    expired = expired_waivers(blockers if isinstance(blockers, list) else [])
    if not expired:
        return None
    named = ", ".join(f"{item.get('id')} on {item['resolution']['until']}" for item in expired)
    return (f"{relative}: the waiver of a blocker expired ({named}) and task {record['task']} is not completed, so the "
            "blocker is open again. The person clears it with its evidence, grants a new waiver or withdraws the "
            f"approval (openguildkit task list names the step), then export the record again.")


def _clearing_evidence(value: str, root: Path) -> str:
    """Evidence that clears a blocker is a file or folder of the project, or an https link someone can open."""
    if value.startswith("https://") and len(value) > len("https://") and not any(char.isspace() for char in value):
        return value
    project = root.resolve()
    path = (project / value).resolve()
    if path.exists() and (path == project or project in path.parents):
        return path.relative_to(project).as_posix() or "."
    raise OgkError("OGK-TASK-025",
        f"Clearing evidence must be an existing file or folder of the project, or an https link: {value}."
    )


def _clearance_payload(task: Task, blocker_id: str, entry: dict) -> dict:
    return {
        "kind": "blocker-clearance",
        "task": task["id"],
        "consultation_id": task["consultation"]["id"],
        "review_sha256": seal(task["review"]),
        "blocker": blocker_id,
        **{key: entry[key] for key in ("by", "evidence", "supports", "fingerprint") if key in entry},
    }


def _check_clearance_signature(task: Task, blocker_id: str, entry: dict, policy: dict, root: Path) -> None:
    """A signed clearance follows the rule of a signed approval: --by names the person, as it does for task decide, and
    the signature must verify for --signer, an approver of the project; both are recorded."""
    if not entry.get("signer") or not entry.get("signature"):
        raise OgkError("OGK-TASK-026", "This project requires a signed clearance. Run task clear with --payload FILE, "
                         "sign the payload, then pass --signature FILE --signer PRINCIPAL.")
    verify_signature(root, policy, _clearance_payload(task, blocker_id, entry), entry["signature"], entry["signer"])


def require_blocker_status(task: Task) -> None:
    """Blockers come from the boards' review: a person resolves them once it is recorded, before the decision or,
    for a condition of approval, before completion."""
    if task["status"] not in ("reviewed", "approved"):
        raise TaskStateError("A blocker is resolved once the boards' review is recorded, before the decision, or "
                             "after the approval for a condition of approval.")


def resolve_blocker(task: Task, blocker_id: str, resolution: dict, profile: Profile, root: Path,
                    *, signing_payload: bool = False) -> Task:
    """Clear a blocker with evidence, or cover it with a waiver the project's policy allows.

    The record says whether the command ran at a terminal, so the approver knows when an agent cleared it.
    """
    require_blocker_status(task)
    known = {item["id"]: item for item in blocker_list(task)}
    if blocker_id not in known:
        listed = ", ".join(known) or "none"
        raise OgkError("OGK-TASK-027", f"Unknown blocker {blocker_id}. Blockers: {listed}.")
    blocker = known[blocker_id]
    first = blocker["resolution"]
    expired = expired_on(first)
    if first and not expired:
        raise OgkError("OGK-TASK-028", f"Blocker {blocker_id} already has a resolution: {first['kind']} by {first['by']} on "
                         f"{first.get('at', '')[:10]}. It stays as recorded; see task blockers.")
    verification = blocker.get("phase") == "verification"
    if expired and not verification and task["status"] == "approved":
        raise OgkError("OGK-TASK-029", expired_waiver_step(task, blocker))
    if verification and task["status"] != "approved":
        raise OgkError("OGK-TASK-030", "Resolve a verification blocker after approval and before completion.")
    if not verification and task["status"] != "reviewed":
        raise ValueError("Resolve approval blockers after the review is recorded and before the decision.")
    by = resolution.get("by", "").strip()
    if not by:
        raise ValueError("Name the person who resolves the blocker.")
    entry = {"kind": resolution["kind"], "by": by, "at": clock.real_timestamp(),
             "recorded_from": "terminal" if resolution.get("terminal") else "no terminal"}
    if resolution["kind"] == "cleared":
        for field in ("evidence", "supports"):
            if not resolution.get(field, "").strip():
                raise ValueError(f"Clearing a blocker needs --{field}.")
            entry[field] = resolution[field].strip()
        entry["evidence"] = _clearing_evidence(entry["evidence"], root)
        entry["fingerprint"] = evidence_fingerprint(root, entry["evidence"])
        policy = approval_policy(profile)
        if signing_payload:
            if policy["mode"] != "signed":
                raise ValueError("A clearance payload is signed: it belongs to a project with signed approvals.")
            return cast(Task, _clearance_payload(task, blocker_id, entry))  # The payload to sign, not a task.
        if policy["mode"] == "signed":
            entry.update(signer=resolution.get("signer"), signature=resolution.get("signature"))
            _check_clearance_signature(task, blocker_id, entry, policy, root)
        # The role of the board that raised the blocker (roles.py): the verified signer, or the name typed.
        if problem := roles.clearance_problem(profile, blocker, by, entry.get("signer")):
            raise OgkError("OGK-TASK-031", problem)
    else:
        waivers = waiver_policy(profile)
        if not waivers:
            clear = (f"Clear {blocker_id} with its evidence at the person's terminal (openguildkit task clear "
                     f"{task['id']} {blocker_id} --evidence PATH --supports TEXT --by INITIALS)")
            if verification:
                raise OgkError("OGK-TASK-032", f"The project's policy allows no waiver. {clear}; if it cannot be met, the person "
                                 f"withdraws the approval: {revoke_command(task['id'])}.")
            raise OgkError("OGK-TASK-033", f"The project's policy allows no waiver. {clear}, or the person requests changes: "
                             f"openguildkit task decide {task['id']} --request-changes --by INITIALS --reason TEXT.")
        if by not in waivers["allowed_by"]:
            raise OgkError("OGK-TASK-034", f"{by} cannot grant waivers. Allowed: {', '.join(waivers['allowed_by'])}.")
        if problem := roles.clearance_problem(profile, blocker, by, waiver=True):
            raise OgkError("OGK-TASK-035", problem)
        until = resolution.get("until", "")
        if not _DAY.fullmatch(until):
            raise ValueError("Give the waiver's end date as YYYY-MM-DD.")
        days = (datetime.fromisoformat(until).date() - clock.real_now().date()).days
        if days < 1 or days > waivers["max_days"]:
            raise OgkError("OGK-TASK-036", f"A waiver lasts between 1 and {waivers['max_days']} days.")
        for field in ("reason", "scope"):
            if not resolution.get(field, "").strip():
                raise ValueError(f"A waiver needs --{field}.")
            entry[field] = resolution[field].strip()
        entry["until"] = until
    if expired:
        # The expired waiver stays in the record, under the resolution that replaces it.
        entry["replaces"] = first
    field = resolution_field(blocker.get("phase"))
    result = task.copy()
    as_dict(result)[field] = {**as_dict(task).get(field, {}), blocker_id: entry}
    return result


def unresolved_blockers(task: Task) -> list[str]:
    return [item["id"] for item in blocker_list(task)
            if (not item["resolution"] or expired_on(item["resolution"])) and item.get("phase") != "verification"]


def verification_blocker_problems(task: Task, profile: Profile, root: Path | None = None) -> list[str]:
    policy = approval_policy(profile)
    problems = []
    for item in blocker_list(task):
        if item.get("phase") != "verification":
            continue
        resolution = item["resolution"]
        if not resolution:
            problems.append(f"Verification blocker {item['id']} is open. Clear it when {item['clears_when']}")
        elif expired_on(resolution):
            problems.append(f"Verification blocker {item['id']}: {expired_waiver_step(task, item)}")
        elif root is not None and policy["mode"] == "signed" and resolution["kind"] == "cleared":
            try:
                _check_clearance_signature(task, item["id"], resolution, policy, root)
            except ValueError as error:
                problems.append(f"Verification blocker {item['id']}: {error}")
    return problems
