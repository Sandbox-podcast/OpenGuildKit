"""Writes the implementation handoff of an approved task: what to build, the checks to run and the rules that hold.

Entry: handoff, review_lines
Tests: tests/test_assumptions.py, tests/test_blockers.py, tests/test_board_entries.py, tests/test_brain_selection.py,
tests/test_brains.py, tests/test_clock.py, tests/test_decision_brief.py, tests/test_evidence_fingerprints.py,
tests/test_output_size.py, tests/test_owners.py, tests/test_sensitive.py, tests/test_short_lane.py
"""

from pathlib import Path

from . import owners, short_lane
from .board_entries import required_text, validate_review
from .consultation import answer_lines, json_section, scope_lines
from .records import Task
from .workflow import TaskStateError, blocker_list, is_decision_task


def _evidence_section(evidence: list[dict]) -> list[str]:
    """The named evidence the closing will ask for, and who provides each: never the agent."""
    if not evidence:
        return []
    lines = ["## Evidence the closing will ask for", "",
             "These documents belong to the people named here. Ask them for each one (a project path or an https "
             "link) early; do not write them yourself to satisfy the check.", ""]
    for check in evidence:
        need = (f"required because {check['must_supply']}" if check["must_supply"]
                else "may be declared not applicable with a reason and an owner")
        lines.append(f"- `{check['id']}`: {check['title']}, provided by {check['owner_role']} ({need}).")
    return [*lines, ""]


def _checks_section(task: Task) -> list[str]:
    """The check commands task verify will run, and what they need, so nothing surprises the agent at the end."""
    if is_decision_task(task):
        return []
    commands = task["consultation"]["scope"].get("checks", [])
    if not commands:
        return ["## Checks task verify will run", "",
                "None: the profile lists no check command, so no test runs before the task closes. The person can "
                "add one for the next tasks: openguildkit profile add check \"COMMAND\" --by INITIALS --reason WHY.", ""]
    if task.get("status") in ("done", "done-with-reservations"):
        lines = ["## Checks task verify ran", "",
                 "Each one had to pass, or be recorded by a person as unable to run here, before the task was closed. "
                 f"Their outcomes are in openguildkit task show {task['id']} --full (result.checks).", ""]
    else:
        lines = ["## Checks task verify will run", "",
                 "Each one must pass before the task is done. Install the project's dependencies and the tools these "
                 "commands call first: a command that cannot run fails with its cause and its log. When one cannot "
                 f"run in this environment, the person records it with `openguildkit task verify {task['id']} "
                 "--cannot-run command:N --by INITIALS --reason TEXT`, and the task closes with that reservation.", ""]
    lines += [f"- `command:{index}`: `{command}`" for index, command in enumerate(commands, start=1)]
    return [*lines, ""]


def _rules_section(task: Task, checks: list[dict] | None) -> list[str]:
    """The rules task checks asks, pack by pack, then one line for the packs and rules it does not ask. checks
    are those of results.expected_checks; without them every rule is listed. A decision task asks none."""
    if is_decision_task(task):
        return []
    task_id = task["id"]
    judged = {check["id"][len("rule:"):]: check for check in checks or [] if check["kind"] in ("rule", "machine")}
    asked, skipped = [], {}
    for pack in task["consultation"]["scope"].get("packs", []):
        ids = [rule["id"] for rule in pack.get("rules", [])
               if judged.get(f"{pack['id']}/{rule['id']}", {"concerned": True})["concerned"]]
        if ids:
            asked.append(f"- {pack['id']}@{pack.get('version', '')}: {', '.join(ids)}")
        if len(ids) < len(pack.get("rules", [])):
            skipped[pack["id"]] = (len(pack["rules"]) - len(ids), len(pack["rules"]))
    lines = ["## Rules to apply and their checks", "",
             "AGENTS.md names the rules by ID and leaves their text out. One pack in full: "
             f"openguildkit task brief {task_id} --pack PACK; the whole scope with every rule text: openguildkit "
             f"task brief {task_id} --scope. What to report for each rule: openguildkit task checks {task_id}.",
             "", *(asked or ["No rule of the packs in force concerns this task."])]
    if skipped:
        counts = ", ".join(f"{pack} ({count} of {total} rules)" if count < total else f"{pack} ({total} rules)"
                           for pack, (count, total) in skipped.items())
        lines.append(f"Not concerned by this task, so not asked (each reason: openguildkit task checks {task_id}): "
                     f"{counts}.")
    return [*lines, ""]


def _handoff_heading(task: Task, status: str) -> tuple[str, str]:
    """The heading and the instruction of a handoff: a decision to report, a scope to implement, or a task already
    closed and shown for reference."""
    if is_decision_task(task):
        heading = "# Approved decision record"
        instruction = (
            "Report this decision and its review to the user. Leave the project files "
            f"unchanged. Close the task with `openguildkit task complete {task['id']}`, then export its record with "
            f"`openguildkit task export {task['id']}`. To act on the decision, open a follow-up task with "
            f"`openguildkit task new \"BRIEF\" --follows {task['id']}`, which records the link and carries this "
            "decision into its consultation, and get that task's scope approved before implementing it."
        )
    else:
        heading = "# Approved task handoff"
        instruction = (
            "Implement the approved scope. Apply the recorded rules and conventions, "
            "run the relevant project checks and report the results. Bring scope "
            "changes and unresolved decisions back to the user."
        ) + short_lane.handoff_note(task)
    if status != "approved":
        heading += f" (task {status})"
        instruction = (
            f"Task {task['id']} is {status}: nothing is left to implement. This handoff is shown for reference. To "
            f"change the work, open a follow-up with `openguildkit task new \"BRIEF\" --follows {task['id']}`."
        )
    return heading, instruction


def _conditions_section(task: Task) -> list[str]:
    """The blockers the approval left open for the verification phase, which only the finished work clears."""
    pending_verification = [item for item in blocker_list(task) if item.get("phase") == "verification"
                            and not item["resolution"]]
    if not pending_verification:
        return []
    return ["## Conditions of the approval, to meet before the task completes", "",
            "The person approved with these blockers open: only the finished work can clear them. Build the "
            "evidence each one names, show it to the person, and let them clear it in their terminal with "
            f"openguildkit task clear {task['id']} BLOCKER --evidence PATH --supports TEXT --by INITIALS. "
            "task complete refuses the task while one is open.", "",
            *(f"- {item['id']} ({item['owner']}): {item['finding']} Clears when: {item['clears_when']}"
              for item in pending_verification), ""]


def _resolved_section(task: Task) -> list[str]:
    """The waivers and resolutions of the blockers resolved before the approval, to respect."""
    if not any(item["resolution"] for item in blocker_list(task)):
        return []
    return [
        "## Conditions from resolved blockers",
        "",
        "Respect each waiver's scope and expiry. A waiver that expires before the work ships needs a "
        "new decision.",
        "",
        json_section([item for item in blocker_list(task) if item["resolution"]]),
        "",
    ]


def handoff(task: Task, evidence: list[dict] | None = None, checks: list[dict] | None = None,
            root: Path | None = None) -> str:
    """Render the authorized scope, decision and advisory findings, with the named evidence first.

    checks are the expected checks of the approved task (results.expected_checks): the rules to apply are those
    they ask. With the project root, the code owners of what the task touches, read from CODEOWNERS and never
    recorded."""
    owner = owners.owner_line(root, task) if root is not None else None
    status = task.get("status")
    if status == "changes-requested":
        raise ValueError(f"Task {task['id']} has changes requested by {task['decision']['by']}: there is nothing to "
                         f"implement. Next: openguildkit task consult {task['id']} --reuse-answers")
    if status not in ("approved", "done", "done-with-reservations"):
        raise TaskStateError("A human approval is required before implementation.")
    consultation = task["consultation"]
    review = validate_review(consultation, task["review"])
    decision = task["decision"]
    approval = {
        "by": required_text(decision.get("by"), "Approver"),
        "reason": required_text(decision.get("reason"), "Approval reason"),
    }
    heading, instruction = _handoff_heading(task, status)
    task_id = task["id"]
    return "\n".join(
        [
            heading,
            "",
            instruction,
            "",
            *_conditions_section(task),
            *_evidence_section(evidence or []),
            *_checks_section(task),
            "## Human approval",
            "",
            json_section(approval),
            "",
            "## Reviewed scope" if is_decision_task(task) else "## Approved project scope",
            "",
            f"{task_id}: {consultation['scope']['brief'].strip()}",
            "",
            *answer_lines(consultation["scope"]),
            *scope_lines(consultation["scope"]),
            *([f"- {owner}"] if owner else []),
            "",
            *_rules_section(task, checks),
            "## Advisory review",
            "",
            review["summary"],
            "",
            *review_lines(review),
            "",
            f"Each board's evidence and lens findings: openguildkit task challenge {task_id}.",
            "",
            *(
                ["## External actions decided by a person", "", json_section(task["authorizations"]), ""]
                if task.get("authorizations") else []
            ),
            *_resolved_section(task),
        ]
    )


def review_lines(review: dict) -> list[str]:
    """Each board's advice in a few lines: verdict, recommendation, verification, blockers and open questions."""
    lines = []
    for entry in review["boards"]:
        challenge = entry.get("challenge", {})
        verdict = f" {challenge['verdict']} ({challenge['confidence']} confidence)." if challenge else ""
        lines.append(f"- {entry['id']}:{verdict} {entry['recommendation']}")
        if challenge.get("verification"):
            lines.append(f"  - Verification: {challenge['verification']}")
        for blocker in challenge.get("blockers", []):
            lines.append(f"  - Blocker: {blocker['finding'] if isinstance(blocker, dict) else blocker}")
        lines.extend(f"  - Open question: {question}" for question in entry["open_questions"])
    return lines
