"""The task actions a person decides at a terminal: decide, revoke, decision-payload, authorize, blockers, clear, waive,
alerts.

Entry: run_decide, run_revoke, run_resolve, run_authorize
Tests: tests/test_approval_lifecycle.py, tests/test_blockers.py, tests/test_requester.py
"""

import sys
from pathlib import Path

from . import audit_log, requester, roles, short_lane
from .alerts import blocking_alerts, load_register
from .approval_check import approval_problem
from .board_entries import validate_review
from .decisions import (
    DECISIONS_DIR,
    NAMESPACE,
    SignerNotCurrent,
    approval_policy,
    decision_payload,
    git_revision,
    payload_text,
    reconsult_command,
    signing_time,
    verify_signature,
)
from .errors import OgkError
from .handoff import review_lines
from .lock import project_catalog, require_instructions
from .project import load_profile
from .records import Profile, Task
from .results import evidence_state
from .storage import print_json, project_lock
from .task_files import read_task, task_path
from .tasks import last_approval, write_task
from .tasks_approval import decided_message, require_approval, require_current_scope
from .tasks_blockers import expired_on, require_blocker_status, resolve_blocker
from .tasks_closing import record_authorization, record_decision, revoke_approval
from .tasks_command import TaskCommand
from .tasks_review import decision_text, previous_round_line
from .terminal import interactive, typed
from .workflow import TaskStateError, blocker_list, is_decision_task, pending_removals, verdict_lines


def _save_decided(state: Path, task: Task, result: Task, still_holds=None) -> None:
    """Write what the person decided, under the lock, unless the task changed while they read and typed."""
    with project_lock(state):
        if read_task(state, task["id"]) != task:
            raise OgkError("OGK-TASK-013", "The task changed while you were deciding. Review it and retry.")
        if still_holds:
            still_holds()
        write_task(task_path(state, task["id"]), result)


def run_revoke(command: TaskCommand) -> None:
    """The person withdraws an approval at their terminal, as they gave it: never an agent."""
    args, root, state, profile, catalog, task = (command.args, command.root, command.state, command.profile,
                                                 command.catalog, command.task)
    result = revoke_approval(task, args.by, args.reason)
    refusal = ("Withdrawing an approval is the person's act: they run openguildkit task revoke in their own terminal, "
               "as they approved.")
    if not interactive():
        raise OgkError("OGK-TASK-062", refusal)
    problem = approval_problem(task, profile, catalog, root)
    if problem:
        print(f"OpenGuildKit: {problem['message']}", file=sys.stderr)
    typed(args.id, f"Type {args.id} to withdraw the approval {task['decision']['by']} gave on "
          f"{task['decision']['at'][:10]}: ", refusal=refusal, cancelled="Withdrawal cancelled.")
    _save_decided(state, task, result)
    audit_log.record(root, "task.revoked", task=args.id, by=args.by)
    print(result["status"])
    print(f"The guard no longer counts {args.id}. Next: {reconsult_command(args.id)}, or close the work in a linked "
          f'task: openguildkit task new "BRIEF" --follows {args.id}', file=sys.stderr)
    record = state / DECISIONS_DIR / f"{args.id}.json"
    if record.is_file():
        print(f"OpenGuildKit: {record.relative_to(root).as_posix()} still says {args.id} is approved, and guard --ci "
              f"accepts it until it says otherwise: write the withdrawal into it with openguildkit task export "
              f"{args.id}, and commit it.", file=sys.stderr)


def _decision_prompt(state: Path, task: Task, profile: Profile, register: dict) -> list[str]:
    """What the person reads before approving, the same at the approval prompt and in task decision-payload: the
    previous round, the decision text (tasks_review.decision_text, also task challenge's), the brief, the summary and each
    board's advice."""
    recall = previous_round_line(task)
    review = validate_review(task["consultation"], task["review"])
    return [*([recall] if recall else []), *decision_text(task, profile, last_approval(state), register),
            "", f"Brief: {task['brief'].strip()}", "", review["summary"], *review_lines(review), "",
            f"Full decision brief, with each board's evidence: openguildkit task challenge {task['id']}",
            *verdict_lines(review, task.get("deliberation"), is_decision_task(task))]


def run_decide(command: TaskCommand) -> None:
    args, root, state, profile, catalog, task = (command.args, command.root, command.state, command.profile,
                                                 command.catalog, command.task)
    if task["status"] == "approved":
        raise OgkError("OGK-TASK-063", decided_message(task, approval_problem(task, profile, catalog, root)))
    if args.approve and (lane := short_lane.lane_problem(task, profile)):
        raise OgkError("OGK-TASK-064", lane)
    if args.approve and (same := requester.approval_problem(task, profile, args.by, args.signer)):
        raise OgkError("OGK-TASK-065", same)
    separate = requester.active(profile)
    policy = approval_policy(profile)
    base = git_revision(root) if args.approve else None
    signature = None
    if args.signed_at and not (args.approve and policy["mode"] == "signed"):
        raise OgkError("OGK-TASK-066", "--signed-at goes with approving in a project that requires signed approvals. Nothing was "
                         "written.")
    signed_at = signing_time(args.signed_at)
    if args.approve and policy["mode"] == "signed":
        if not args.signature or not args.signer:
            raise OgkError("OGK-TASK-067",
                "This project requires a signed approval: run task decision-payload, sign it with ssh-keygen -Y sign "
                f"-n {NAMESPACE}, then pass --signature FILE --signer PRINCIPAL."
            )
        text = args.signature.read_text(encoding="utf-8")
        try:
            # Always at the current time: a key or a certificate that has expired signs no new approval.
            verify_signature(root, policy, decision_payload(task, args.by, args.reason, base, separate=separate,
                                                            signed_at=signed_at), text, args.signer)
        except SignerNotCurrent as error:
            hint = " If the payload you signed has a signed_at line, pass --signed-at VALUE." if not signed_at else ""
            raise SignerNotCurrent("OGK-TASK-091", f"{error}{hint}") from None
        signature = {"signer": args.signer, "text": text}
    # The roles of the boards that blocked (roles.py): the verified signer, or the name typed.
    if args.approve and (outside := roles.approval_problem(task, profile, args.by, args.signer)):
        raise OgkError("OGK-TASK-068", outside)
    register = load_register(state)
    blocking = blocking_alerts(register, task) if args.approve else []
    if blocking:
        raise OgkError("OGK-TASK-069", "Approval is blocked:\n- " + "\n- ".join(blocking))
    removals = pending_removals(task) if args.approve else []
    result = record_decision(task, args.approve, args.by, args.reason, base, signature, removals,
                             separate=args.approve and separate, signed_at=signed_at, dated=audit_log.is_on(root))
    if args.approve:
        if (signature is None or removals) and not interactive():
            raise OgkError("OGK-TASK-070", "Approval requires a person at an interactive terminal.")
        # A signed approval shows the same text: the signature replaces the typed ID, not the reading.
        print("\n".join(_decision_prompt(state, task, profile, register)), file=sys.stderr)
        if signature is None:
            typed(args.id, f"Type {args.id} to approve the reviewed scope: ", cancelled="Approval cancelled.",
                  refusal="Approval requires a person at an interactive terminal.")
        for board in removals:
            typed(board, f"The agent removed the {board} board, which the data answer selected. "
                  f"Type {board} to confirm the removal: ", refusal="Approval requires a person at an interactive "
                  "terminal.", cancelled=f"Approval cancelled: the removal of the {board} board was not confirmed. "
                  "Request changes and consult again with it.")
    def still_holds() -> None:
        if args.approve:
            current = project_catalog(args, state)
            current_profile = load_profile(state, current)
            require_current_scope(task, current_profile, current)
            require_instructions(args, root, state, current_profile, current)

    _save_decided(state, task, result, still_holds)
    if args.approve:
        audit_log.record(root, "task.approved", task=args.id, by=args.by, signer=args.signer, seal=result["decision"]["seal"])
    if args.json:
        print_json({"task": args.id, "status": result["status"],
                    "decision": {key: result["decision"][key] for key in ("outcome", "by", "reason", "at")}})
    else:
        print(result["status"])
    print(f"Next: openguildkit task handoff {args.id} gives the agent the implementation brief." if args.approve
          else f"Next: {reconsult_command(args.id)}, with the changes requested.", file=sys.stderr)


def run_blockers(command: TaskCommand) -> None:
    """The review's blockers and how each was resolved."""
    args, root, task = command.args, command.root, command.task
    items = blocker_list(task)
    for item in items:
        resolution = item["resolution"]
        if resolution and resolution["kind"] == "cleared" and "fingerprint" in resolution:
            item["evidence_state"] = evidence_state(root, resolution["evidence"], resolution["fingerprint"])
    if args.json:
        print_json(items)
    elif not items:
        print("No blockers.")
    else:
        for item in items:
            resolution = item["resolution"]
            shown = f"{resolution['kind']} by {resolution['by']}" if resolution else "open"
            expired = expired_on(resolution)
            if expired:
                shown = f"waiver expired on {expired}"
            phase = " (due at verification)" if item.get("phase") == "verification" else ""
            print(f"{item['id']} [{shown}]{phase} {item['finding']}")
            if item.get("owner"):
                print(f"    owner: {item['owner']}; clears when: {item['clears_when']}")
            if resolution and resolution["kind"] == "cleared":
                words = EVIDENCE_WORDS[item.get("evidence_state", "no fingerprint")]
                print(f"    evidence: {resolution['evidence']}; supports: {resolution['supports']}; {words}")
            if expired:
                print(f"    waived by {resolution['by']}: {resolution['reason']} (scope: {resolution['scope']}); "
                      "the blocker is open again")
            if resolution and resolution.get("recorded_from") == "no terminal":
                print("    recorded without a terminal")


EVIDENCE_WORDS = {"unchanged": "fingerprint: unchanged since it was cleared",
                  "changed": "fingerprint: changed since it was cleared",
                  "missing": "fingerprint: the evidence is missing since it was cleared",
                  "external": "fingerprint: external link, cannot be checked",
                  "no fingerprint": "no fingerprint: cleared before OpenGuildKit recorded one"}


def run_resolve(command: TaskCommand) -> None:
    """The person clears a blocker with evidence, or waives it within the project's policy."""
    args, root, state, profile, catalog, task = (command.args, command.root, command.state, command.profile,
                                                 command.catalog, command.task)
    action = args.action
    require_approval(task, profile, catalog, root)
    require_blocker_status(task)
    if action == "waive":
        if not interactive():
            raise OgkError("OGK-TASK-071", "A waiver needs a person at an interactive terminal.")
        details = {"kind": "waived", "by": args.by, "reason": args.reason, "scope": args.scope, "until": args.until}
    else:
        details = {"kind": "cleared", "by": args.by, "evidence": args.evidence, "supports": args.supports}
        if (args.signature is None) != (args.signer is None):
            raise OgkError("OGK-TASK-141", "Pass --signature and --signer together.")
        if args.payload:
            payload = resolve_blocker(task, args.blocker, details, profile, root, signing_payload=True)
            args.payload.write_bytes(payload_text(payload).encode("utf-8"))
            print(args.payload)
            return
        if args.signature:
            if approval_policy(profile)["mode"] != "signed":
                raise OgkError("OGK-TASK-142", "A clearance signature is only used in a project with signed approvals.")
            details.update(signature=args.signature.read_text(encoding="utf-8"), signer=args.signer)
    details["terminal"] = interactive()
    result = resolve_blocker(task, args.blocker, details, profile, root)
    # A signed clearance is the person's act through their key; otherwise the person types the task ID.
    if action == "clear" and "signature" not in details:
        typed(args.id, f"Type {args.id} to clear {args.blocker} with {args.evidence}: ", cancelled="Clearing "
              "cancelled.", refusal="Clearing a blocker is the person's act: show them the evidence, and they run "
              "task clear in their own terminal.")
    if action == "waive":
        typed(args.id, f"Type {args.id} to waive {args.blocker} until {args.until}: ", cancelled="Waiver cancelled.",
              refusal="A waiver needs a person at an interactive terminal.")
    _save_decided(state, task, result)
    audit_log.record(root, f"blocker.{details['kind']}", task=args.id, blocker=args.blocker, by=args.by,
                     signer=details.get("signer"), until=details.get("until"))
    print(details["kind"])


def run_alerts(command: TaskCommand) -> None:
    """The task's dependency alerts: import, link and review them."""
    args, state, task = command.args, command.state, command.task
    from .alerts_cli import task_command  # Not imported by the other task commands (#539).

    task_command(args, state, task)


def run_decision_payload(command: TaskCommand) -> None:
    """The exact decision an approver signs, after the text they read before approving."""
    args, root, state, profile, catalog, task = (command.args, command.root, command.state, command.profile,
                                                 command.catalog, command.task)
    if task["status"] != "reviewed":
        decided = decided_message(task, approval_problem(task, profile, catalog, root))
        if decided:
            raise OgkError("OGK-TASK-143", decided)
        raise TaskStateError("OGK-TASK-104", "Record the boards' review before preparing a decision.")
    # The signer is not known yet: decide compares the requester to the signer as well.
    same = requester.approval_problem(task, profile, args.by)
    if same:
        raise OgkError("OGK-TASK-072", same)
    # The signer reads what they sign: the same lines as the approval prompt, then the payload with the brief.
    print("\n".join(_decision_prompt(state, task, profile, load_register(state))), file=sys.stderr)
    text = payload_text(decision_payload(task, args.by, args.reason, git_revision(root),
                                         separate=requester.active(profile),
                                         signed_at=signing_time(args.signed_at, now_ok=True)))
    if args.output:
        # Exact UTF-8 bytes with LF line endings: a shell redirect could change the encoding.
        args.output.write_bytes(text.encode("utf-8"))
        print(args.output)
    else:
        print(text, end="")


def run_authorize(command: TaskCommand) -> None:
    """A person allows or refuses an external action outside the authorized scope."""
    args, root, state, task = command.args, command.root, command.state, command.task
    refusal = "Allowing an external action requires a person at an interactive terminal."
    if args.allow and not interactive():
        raise OgkError("OGK-TASK-073", refusal)
    result = record_authorization(task, args.external_action, args.target, args.allow, args.by, args.reason)
    if args.allow:
        typed(args.id, f"Type {args.id} to allow {args.external_action} on {args.target}: ", refusal=refusal,
              cancelled="Authorization cancelled.")
    _save_decided(state, task, result)
    entry = result["authorizations"][-1]
    audit_log.record(root, "task.authorized", task=args.id, action=entry["action"], target=entry["target"],
                     decision=entry["decision"], by=entry["by"])
    print(entry["decision"])
