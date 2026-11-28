"""What changed in the rules since an approval, the scope it covered, and the messages for a task already decided or a
stale review; `approval_check.py` says whether it holds.

Entry: require_approval, rule_changes, require_current_scope
Tests: tests/test_approval_lifecycle.py, tests/test_rule_changes.py
"""

from pathlib import Path

from .approval_check import DONE_STATUSES, approval_problem
from .consultation import profile_settings
from .decisions import reconsult_command, stale_approval_message
from .errors import OgkError
from .project import rules_in_force
from .project_rules import fingerprint_holds, task_scope_profile
from .records import Catalog, Profile, Task


def _setting_change(name: str, before, after) -> str:
    """One setting's change in words, such as "required boards changed (none -> legal)"."""
    if isinstance(after, list):
        return f"{name} changed ({', '.join(before or []) or 'none'} -> {', '.join(after) or 'none'})"
    return f"{name} {'unset' if before is None else before} -> {'unset' if after is None else after}"


def rule_changes(task: Task, profile: Profile, catalog: Catalog) -> list[str]:
    """What changed, pack by pack and rule by rule, in the rules the task was consulted under."""
    scope = task["consultation"]["scope"]
    try:
        current = task_scope_profile(profile, catalog, task.get("answers", {}).get("components", []))
    except ValueError:
        return ["the task's components changed"]
    before = {pack["id"]: pack for pack in scope.get("packs", [])}
    after = {pack_id: rules_in_force(catalog["packs"][pack_id], current) for pack_id in current["packs"]}
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
    # Only what voids an approval is named: conventions, tools and the guard, host or research settings do not.
    changes += [f"{field} changed" for field in ("stack", "checks") if scope.get(field, []) != current.get(field, [])]
    # The consultation recorded the settings of the resolved profile (every board when none is listed).
    settings, stored = profile_settings(current), scope.get("settings", {})
    changes += [_setting_change(name, stored[name], value) for name, value in settings.items()
                if name in stored and stored[name] != value]
    if not changes and settings.keys() <= stored.keys():
        return ["a board's definition changed: openguildkit update shows the catalog changes"]
    if not changes:
        # A task consulted before these settings were recorded: name what may have changed.
        return [f"a project setting changed ({', '.join(settings)}), or a board's definition; "
                "openguildkit preview shows the profile"]
    return changes[:6] + ([f"{len(changes) - 6} more changes: openguildkit update shows them"] if len(changes) > 6 else [])


def revoke_command(task_id: str) -> str:
    """The person's command that withdraws an approval, the same in every message that names it."""
    return f"openguildkit task revoke {task_id} --by INITIALS --reason TEXT"


def require_approval(task: Task, profile: Profile, catalog: Catalog, root: Path | None = None) -> None:
    """Refuse to act on an approved task whose approval no longer holds, with the one message every reader prints."""
    problem = approval_problem(task, profile, catalog, root)
    if problem and problem["severity"] == "error":
        raise ValueError(problem["message"])


def decided_message(task: Task, problem: dict | None = None) -> str | None:
    """For a task a person already decided: its status, who decided and when, and the one command that fits next.

    problem is the task's approval_problem: an approval that no longer holds leads to a new consultation, not to the
    handoff, which would refuse it.
    """
    decision, task_id, status = task.get("decision"), task["id"], task["status"]
    if not decision:
        return None
    who = f"by {decision['by']} on {decision['at'][:10]}"
    if status == "approved" and problem and problem["severity"] == "error":
        return f"Task {task_id} was approved {who}, but the approval no longer holds. {problem['message']}"
    if status == "approved":
        return (f"Task {task_id} is already approved {who}. Next: openguildkit task handoff {task_id}. To change the "
                f"work, the person withdraws the approval at their terminal ({revoke_command(task_id)}), then you "
                "consult again.")
    if status in DONE_STATUSES:
        return (f"Task {task_id} is already decided and {status}: approved {who}. To change the work, open a follow-up: "
                f"openguildkit task new \"BRIEF\" --follows {task_id}")
    if status == "changes-requested":
        return (f"Task {task_id} already has changes requested {who}. Next: {reconsult_command(task_id)}, then "
                "record the new review before deciding.")
    return None


def stale_review_message(task_id: str) -> str:
    """What a review given under other rules, checks or boards than the profile's waits for: task decide, task list
    and task consult say it in the same words (a project upgraded from 0.16.1 has its reviewed tasks in this state)."""
    return (f"The rules, checks or boards of the project changed since {task_id} was consulted. The person requests "
            f"changes (openguildkit task decide {task_id} --request-changes --by INITIALS --reason TEXT), then you consult "
            "again.")


def require_current_scope(task: Task, profile: Profile, catalog: Catalog) -> None:
    """Refuse to decide over a review given under other rules, checks or boards than the profile's."""
    if not fingerprint_holds(task.get("profile_fingerprint"), profile, catalog):
        if task["status"] in ("approved", *DONE_STATUSES):
            raise ValueError(stale_approval_message(task["id"], rule_changes(task, profile, catalog)))
        raise OgkError("OGK-TASK-024", stale_review_message(task["id"]))
