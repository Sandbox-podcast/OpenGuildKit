"""The task command: take a task from the request to its closing.

add_parser adds the task actions to the CLI's parser and run runs one of them, as tools_cli and the other command
modules do. Each action reads the task, checks what its status allows, and writes the record under the project
lock; what only a person may do (approve, withdraw an approval, clear, waive, close over open points) waits for
them at a terminal.
"""

import sys
from contextlib import contextmanager
from pathlib import Path

from . import alerts_cli, delivered_review, light_lane
from .alerts import blocking_alerts, load_register
from .brains import brief_knowledge, consultation_context
from .catalog import board_replacements
from .consultation import board_brief, pack_rules
from .decisions import (
    DECISIONS_DIR, EARLIER_SIGNERS, NAMESPACE, approval_policy, decision_payload, exported_records, git_revision,
    ignored_by_git, payload_text, reconsult_command, record_digest, verify_signature,
)
from .guard import (
    changes_since_approval, export_decision, export_withdrawal, exported_decisions, record_of_another_task,
    untracked_files,
)
from .hosts import host_controls
from .lock import project_catalog, require_instructions
from .market import load_dossier
from .market import scope_entry as market_scope_entry
from .project import STATE_DIR, WORK_DIR, Fingerprints, load_profile, task_scope_profile
from .prompts import prompt_questions
from .questionnaire import concerns_question, open_points, require_concerns, task_questions, validate_answers
from .relevance import changed_files, pack_relevance
from .retro import (
    DEFAULT_MINIMUM, facts_of_record, facts_of_task, project_summary, render_project, render_task, task_retro,
)
from .results import (
    DONE_STATUSES, SUPPLY, SUPPLY_OR_NOT_APPLICABLE, answers_to_report, chaosfolk_checks, compare_runs,
    completion_problems, criteria_summary, decision_changes, decision_revision_message, declared_cannot_run,
    expected_checks, keep_declarations, missing_scenarios, outcomes, result_template, run_command_checks,
    set_aside_rules,
)
from .routing import select_boards, trigger_matches
from .sensitive import input_warnings, redact_credentials, redact_data
from .shell import shell_word
from .storage import print_json, project_lock, read_json, write_json
from .tasks import (
    ACTIONS, SENSITIVE_GROUP, approval_problem, assemble_review, board_brief_problem, cited_evidence, complete_task,
    create_task, decided_message, decision_text, defer_evidence, earlier_sequential_pass, expired_on, last_approval,
    list_tasks,
    next_command, pass_progress, passes_left, points_left_open, previous_round_line, read_task, record_authorization,
    record_consultation, record_decision, record_deliberation, record_result, record_review, require_approval,
    require_blocker_status, require_current_scope, resolve_blocker, revoke_approval, start_pass, state_refusal,
    submit_pass, task_path, timestamp, verification_blocker_problems, waiting_for, waits_line,
)
from .terminal import interactive
from .tools import connected_tools, load_tools, match_tools, tool_evidence_warnings
from .workflow import (
    RESOLUTION_RULE, TaskStateError, blocker_list, challenge_report, deliberation_request, handoff, is_decision_task,
    nothing_to_deliberate, pending_removals, review_lines, validate_review, verdict_lines,
)


ACTION_HELP = {
    "questions": "Print the task questionnaire as JSON.",
    "route": "Preview the boards a consultation would select, and why.",
    "consult": "Save task answers and prepare the board consultation.",
    "brief": "Print the saved consultation for the host agent.",
    "template": "Print the review template as JSON.",
    "pass": "Start one board's independent pass and print what it needs.",
    "submit": "Record one board's review entry from its pass.",
    "progress": "Show which board passes are done, failed, started or missing.",
    "review": "Record the completed board reviews.",
    "challenge": "Print the decision brief and each board's challenge.",
    "deliberate": "Print the objections between boards and the response template.",
    "blockers": "List the review's blockers and how each was resolved.",
    "clear": "Record the evidence that clears a blocker (the person, at a terminal or with a signature).",
    "waive": "Waive a blocker within the project's waiver policy (needs a terminal).",
    "respond": "Record the boards' answers to each other's objections.",
    "decide": "Record a human decision.",
    "revoke": "Withdraw an approval: the task goes back to changes requested (the person, at a terminal).",
    "handoff": "Print the approved implementation handoff, or the decision record of a decision task.",
    "decision-payload": "Print the exact decision an approver signs in a project that requires signed approvals.",
    "show": "Print the task record as JSON.",
    "checks": "List the checks the approved task must report.",
    "verify": "Run the project's check commands and the rules' machine checks, and record their results.",
    "result": "Record the delivered revision, criteria and check outcomes.",
    "complete": "Close the task: done, or done-with-reservations when points stay open.",
    "runs": "Compare the last two ChaosFolk replays of the task.",
    "alerts": "Import dependency alerts for the task into the project register and review them.",
    "export": "Write a shareable decision record to .openguildkit/decisions for the pull request.",
    "authorize": "Record a person's decision on an external action outside the authorized scope.",
}


def add_parser(commands) -> None:
    task = commands.add_parser("task", help="Take a task from the request to its closing: frame it, consult the "
                                             "boards, record the person's decision, then verify, complete and export "
                                             "it.")
    actions = task.add_subparsers(dest="action", required=True)
    new = actions.add_parser("new", help="Create a task draft.")
    new.add_argument("brief", nargs="?", help="Short description of the work.")
    new.add_argument("--file", type=Path, help="Read the brief from a UTF-8 Markdown or text file.")
    new.add_argument("--id", help="Use a readable lowercase task ID.")
    new.add_argument("--follows", metavar="TASK", help="Link the task to an earlier task's decision.")
    new.add_argument("--after", action="append", metavar="TASK",
                     help="A task this one waits for; repeat it for each. task list --ready leaves the task out until "
                          "they are done.")
    new.add_argument("--lane", choices=(light_lane.LANE,),
                     help="Open the task in the short lane, which a person turned on in the profile: one board, no "
                          "questionnaire, limited to --paths.")
    new.add_argument("--paths", nargs="+", metavar="GLOB",
                     help="With --lane light: the folders or files the task may change, inside the profile's "
                          "light_paths. Write the brief first.")
    listing = actions.add_parser("list", help="List the project's tasks with their status and next open point.")
    listing.add_argument("--status", help="Only tasks in this status.")
    listing.add_argument("--owner", help="Only tasks whose current decision this person took: the approval, the "
                                         "change request or the withdrawal of an approval.")
    listing.add_argument("--since", help="Created on or after YYYY-MM-DD.")
    listing.add_argument("--until", help="Created on or before YYYY-MM-DD.")
    listing.add_argument("--ready", action="store_true",
                         help="Only open tasks whose dependencies (task new --after) are all done.")
    listing.add_argument("--json", action="store_true", help="Print the tasks as JSON.")
    listing.add_argument("--decisions", action="store_true",
                         help="List the decisions exported to .openguildkit/decisions, teammates' included.")
    retro = actions.add_parser("retro", help="Read what a closed task, or every closed task, left to learn: rules set "
                                             "aside, committees that said nothing, reservations, waived blockers. "
                                             "It writes nothing.")
    retro.add_argument("id", nargs="?", help="Task ID of a closed task, or none with --all.")
    retro.add_argument("--all", action="store_true",
                       help="Count what comes back in the project's closed tasks, with the profile command a person "
                            "could type for some of it.")
    retro.add_argument("--min", type=int, dest="minimum", metavar="N",
                       help=f"With --all, in how many closed tasks a finding must come back (default {DEFAULT_MINIMUM}).")
    retro.add_argument("--json", action="store_true", help="Print the retrospective as JSON.")
    for action, description in ACTION_HELP.items():
        command = actions.add_parser(action, help=description)
        command.add_argument("id", help="Task ID.")
        for add_options in ACTION_OPTIONS.get(action, ()):
            add_options(command)
    delivered_review.add_parser(actions)


def _json_option(text: str):
    return lambda command: command.add_argument("--json", action="store_true", help=text)


def _answers_option(command) -> None:
    command.add_argument("--answers", type=Path, help="Read task answers from a JSON file.")


def _follow_ups_option(command) -> None:
    command.add_argument("--follow-ups", action="store_true",
                         help="With --answers, print only follow_ups and open_points, not the questionnaire again.")


def _closing_option(command) -> None:
    command.add_argument("--closing", action="store_true",
                         help="Print only the open points the closing left, with who closed the task.")


def _reuse_answers_option(command) -> None:
    command.add_argument("--reuse-answers", action="store_true",
                         help="Consult again with the task's recorded answers, without a terminal; with --answers FILE, "
                              "the file's answers replace those recorded. Only a missing concerns answer is asked.")


def _revised_brief_options(command) -> None:
    command.add_argument("--market", metavar="DOSSIER", help="Attach a market dossier from .openguildkit/market/.")
    revised = command.add_mutually_exclusive_group()
    revised.add_argument("--brief", dest="revised_brief", metavar="TEXT",
                         help="Revise the brief: the passes start over, and after a change request the earlier round "
                              "is kept.")
    revised.add_argument("--brief-file", type=Path, metavar="FILE",
                         help="Read the revised brief from a UTF-8 text file instead of --brief.")


def _board_change_options(command) -> None:
    command.add_argument("--add", action="append", default=[], metavar="BOARD", help="Add a board to the consultation.")
    command.add_argument("--remove", action="append", default=[], metavar="BOARD", help="Remove a proposed board.")
    command.add_argument("--reason", help="Why the boards were added or removed.")
    command.add_argument("--delegate", action="append", default=[], metavar="BOARD=NAME",
                         help="Name the person who reviews a required board the project has not enabled.")


def _review_source_options(command) -> None:
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Completed review JSON.")
    source.add_argument("--summary", help="Assemble the review from completed board passes with this summary.")


def _pass_options(command) -> None:
    command.add_argument("board", help="Board ID.")
    command.add_argument("--again", action="store_true",
                         help="Redo a pass whose entry is already submitted; the entry is replaced at the next submit.")


def _brief_options(command) -> None:
    shown = command.add_mutually_exclusive_group()
    shown.add_argument("--board", help="Print this board's pass again without starting it.")
    shown.add_argument("--scope", action="store_true", help="Print the whole project scope as JSON, rule texts included.")
    shown.add_argument("--pack", help="Print the rules of one pack in force for the task.")


def _mode_option(command) -> None:
    command.add_argument("--mode", choices=("subagent", "sequential"), help="How the host runs this pass.")


def _file_option(text: str):
    return lambda command: command.add_argument("--file", type=Path, required=True, help=text)


def _blocker_options(command) -> None:
    command.add_argument("blocker", help="Blocker ID such as security:1 (see task blockers).")
    command.add_argument("--by", required=True, help="Person who resolves the blocker.")


def _clear_options(command) -> None:
    command.add_argument("--evidence", required=True, help="Path, document or link that clears it.")
    command.add_argument("--supports", required=True, help="What the evidence establishes.")
    signing = command.add_mutually_exclusive_group()
    signing.add_argument("--payload", type=Path, help="Write the exact clearance payload to sign.")
    signing.add_argument("--signature", type=Path, help="SSH signature of the clearance payload.")
    command.add_argument("--signer", help="Approver principal used to sign the clearance.")


def _waive_options(command) -> None:
    command.add_argument("--reason", required=True, help="Why the risk is accepted.")
    command.add_argument("--scope", required=True, help="What the waiver covers.")
    command.add_argument("--until", required=True, help="Last day of the waiver, YYYY-MM-DD.")


def _export_options(command) -> None:
    command.add_argument("--output", type=Path, help="Write the shareable record to this file instead.")


def _all_rules_option(command) -> None:
    command.add_argument("--all", action="store_true",
                         help="Ask every rule of the active packs, including those that do not concern the task.")


def _result_source_options(command) -> None:
    source = command.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="Result JSON.")
    source.add_argument("--template", action="store_true", help="Print a result file to fill in.")


def _complete_options(command) -> None:
    command.add_argument("--by", help="Person who closes the task over skipped sensitive rules or deferred evidence "
                                      "(needs a terminal).")
    command.add_argument("--defer", action="append", default=[], metavar="EVIDENCE=TASK",
                         help="Hand an awaited named evidence to a follow-up task (with --by).")


def _verify_options(command) -> None:
    command.add_argument("--chaosfolk", type=Path, metavar="SUMMARY",
                         help="Record a ChaosFolk regression summary.json instead of running the check commands.")
    command.add_argument("--tool-version", help="ChaosFolk version or commit that produced the summary.")
    command.add_argument("--cannot-run", metavar="COMMAND_CHECK",
                         help="Record that a check command such as command:1 cannot run in this environment (with "
                              "--by and --reason, at a terminal); the task then closes with that reservation.")
    command.add_argument("--withdraw", metavar="COMMAND_CHECK",
                         help="Withdraw a declaration that a command cannot run (with --by, at a terminal): the "
                              "command runs and its outcome is recorded.")
    command.add_argument("--by", help="Person who records or withdraws that the command cannot run.")
    command.add_argument("--reason", help="Why the command cannot run here.")


def _alerts_options(command) -> None:
    command.add_argument("--import", dest="import_file", type=Path, metavar="REPORT",
                         help="npm audit, pip-audit, OSV-Scanner or Dependabot JSON report.")
    command.add_argument("--set", dest="alert_id", metavar="ALERT", help="Alert ID to review.")
    command.add_argument("--link", metavar="ALERT", help="Link an alert of the register to the task.")
    command.add_argument("--status", choices=alerts_cli.STATUS_CHOICES, help="Review status for --set.")
    command.add_argument("--by", help="Reviewer's name for --set.")
    command.add_argument("--reason", default="", help="Reason, required to dismiss.")
    command.add_argument("--json", action="store_true", help="Print the alerts as JSON.")


def _authorize_options(command) -> None:
    command.add_argument("--action", dest="external_action", required=True, choices=ACTIONS,
                         help="Kind of external action.")
    command.add_argument("--target", required=True, help="Host or tool name, without query or private details.")
    outcome = command.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--allow", action="store_true", help="Allow the action (needs a terminal).")
    outcome.add_argument("--deny", action="store_true", help="Refuse the action.")
    _decision_reason_options(command)


def _decision_reason_options(command) -> None:
    command.add_argument("--by", required=True, help="Decision owner's name.")
    command.add_argument("--reason", required=True, help="Reason for the decision.")


def _decide_options(command) -> None:
    outcome = command.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--approve", action="store_true", help="Approve the reviewed scope in a terminal.")
    outcome.add_argument("--request-changes", action="store_true", help="Send the task back to consultation.")
    _decision_reason_options(command)
    command.add_argument("--signature", type=Path, help="SSH signature of task decision-payload (signed projects).")
    command.add_argument("--signer", help="Principal in the allowed signers file (signed projects).")


def _revoke_options(command) -> None:
    command.add_argument("--by", required=True, help="Person who withdraws the approval.")
    command.add_argument("--reason", required=True, help="Why the approval is withdrawn.")


def _payload_options(command) -> None:
    _decision_reason_options(command)
    command.add_argument("--output", type=Path, help="Write the exact bytes to sign to this file.")


# The options of each action, in the order its help lists them.
ACTION_OPTIONS = {
    "questions": (_answers_option, _follow_ups_option),
    "route": (_answers_option, _board_change_options, _json_option("Print the selection as JSON.")),
    "consult": (_answers_option, _reuse_answers_option, _revised_brief_options, _board_change_options),
    "show": (_closing_option,),
    "review": (_review_source_options,),
    "pass": (_pass_options, _mode_option),
    "brief": (_brief_options,),
    "submit": (_mode_option, _file_option("The board's filled-in JSON entry.")),
    "clear": (_blocker_options, _clear_options),
    "waive": (_blocker_options, _waive_options),
    "blockers": (_json_option("Print the blockers as JSON."),),
    "export": (_export_options,),
    "checks": (_json_option("Print the checks as JSON."), _all_rules_option),
    "result": (_all_rules_option, _result_source_options),
    "complete": (_complete_options,),
    "verify": (_verify_options,),
    "alerts": (_alerts_options,),
    "runs": (_json_option("Print the comparison as JSON."),),
    "respond": (_file_option("Completed deliberation JSON."),),
    "progress": (_json_option("Print the progress as JSON."),),
    "authorize": (_authorize_options,),
    "decide": (_decide_options,),
    "revoke": (_revoke_options,),
    "decision-payload": (_payload_options,),
}


@contextmanager
def _input_file(path: Path):
    """Name the file a refusal comes from, so the person knows which file to correct. A refusal of the task's status
    is not the file's: it goes on as it is."""
    try:
        yield
    except TaskStateError:
        raise
    except ValueError as error:
        raise ValueError(f"{path.as_posix()}: {error}") from error


def _show_exported(root: Path, state: Path, profile: dict, catalog: dict, task_id: str, closing: bool = False) -> None:
    """Show a task known here only by its exported record, with whether that record still holds."""
    row = next(item for item in exported_decisions(root, state, profile, Fingerprints(profile, catalog))
               if item["path"].endswith(f"/{task_id}.json"))
    print(f"OpenGuildKit: task {task_id} exists here only as the exported record {row['path']}.", file=sys.stderr)
    if row["problem"]:
        print(f"OpenGuildKit: {row['problem']['message']}", file=sys.stderr)
    record = read_json(root / row["path"])
    if closing and not isinstance((record.get("result") or {}).get("closing"), dict):
        raise ValueError(f"The exported record of {task_id} has no closing: the task was not completed when it was "
                         "exported.")
    print_json(_closing_points(record, task_id) if closing else record)


def _closing_points(task: dict, task_id: str) -> dict:
    """What a completed task left open, without the rest of its record: task list points here for a task done with
    reservations, whose whole record can weigh a hundred kilobytes."""
    closing = (task.get("result") or {}).get("closing")
    if not isinstance(closing, dict):
        raise TaskStateError("Only a completed task has a closing with its open points.")
    return {"id": task_id, "status": task.get("status"),
            **{key: closing[key] for key in ("by", "verification", "open_points") if key in closing}}


def _print_decision_rows(rows: list[dict]) -> None:
    if not rows:
        print(f"No exported decision in .openguildkit/{DECISIONS_DIR}.")
    for row in rows:
        if row["status"] == "unreadable":
            print(f"{row['path']} [unreadable]: {row['problem']['message']}")
            continue
        state = "completed" if row["completed"] else "not completed"
        print(f"{row['task']} [{row['status']} by {row['by']}, {state}] {row['brief']}")
        message = row["problem"]["message"].removeprefix(f"{row['path']}: ").removeprefix(f"{row['path']} ") if row["problem"] else ""
        notes = [row["path"], message or "holds under the current rules"]
        if not row["local"]:
            notes.append("no local task record (a teammate's task, or a deleted tasks folder)")
        print(f"    {'; '.join(notes)}")


def sharing_issues(root: Path, state: Path, records: list[dict], tasks: dict | None = None) -> list[tuple[str, str, str | None]]:
    """What git will not carry to a teammate: tasks named only by exported records, evidence left out of the repository.

    Each issue is its kind (task-absent, task-id-clash or evidence-unshared), the line check prints and the file it is
    about, None when it names none. tasks holds the task records the caller already read, by ID; without it they are
    read here."""
    issues = []
    absent = sorted({row["task"] for row in records if row["status"] != "unreadable" and not row["local"]})
    if absent:
        issues.append((
            "task-absent",
            f"exported decisions name tasks absent from this copy: {', '.join(absent)}. That is normal for a teammate's "
            "task; if the tasks folder was deleted, these records are what remains (openguildkit task list --decisions).",
            None,
        ))
    issues += [("task-id-clash", _clash_message(task_id, path), path) for task_id, path in _id_clashes(root, state).items()]
    cited = {}
    if tasks is not None:
        cited = {task_id: cited_evidence(task) for task_id, task in sorted(tasks.items())}
    else:
        for path in sorted((state / "tasks").glob("*.json")):  # An unreadable record is reported by check already.
            try:
                cited[path.stem] = cited_evidence(read_task(state, path.stem))
            except ValueError:
                continue
    return issues + _unshared_evidence(root, cited)


def _id_clashes(root: Path, state: Path) -> dict[str, str]:
    """Local tasks whose ID an exported record of another task uses, such as a teammate's taken in a merge.

    Only the tasks that share an ID with an exported record are read, so a project with many tasks and few
    records lists its tasks as fast as before.
    """
    clashes = {}
    for record in sorted((state / DECISIONS_DIR).glob("*.json")):
        try:
            if not task_path(state, record.stem).is_file():
                continue
            task = read_task(state, record.stem)
        except ValueError:
            continue
        path = record_of_another_task(state, task)
        if path is not None:
            clashes[record.stem] = path.relative_to(root).as_posix()
    return clashes


def _clash_message(task_id: str, path: str) -> str:
    return (f"task {task_id} of this copy and the exported decision {path} are different tasks with the same ID. "
            "Leave the record as it is and open your work under another ID with openguildkit task new \"BRIEF\" --id "
            "NEW-ID (see docs/workflow.md, \"When two copies use the same task ID\").")


def _unshared_evidence(root: Path, cited: dict[str, list[str]]) -> list[tuple[str, str, str | None]]:
    """Evidence a reviewer cannot open from the repository: ignored by git or kept under .openguildkit/tasks/."""
    issues = []
    ignored = ignored_by_git(root, sorted({path for paths in cited.values() for path in paths}))
    local_only = f"{STATE_DIR}/tasks/"
    for task_id, paths in cited.items():
        unshared = [path for path in paths if path in ignored or path.replace("\\", "/").startswith(local_only)]
        if unshared:
            issues.append((
                "evidence-unshared",
                f"task {task_id} cites evidence a reviewer cannot open from the repository (ignored by git or kept under "
                f"{local_only}): {', '.join(unshared)}. Move it to a committed folder and record it again.",
                f"{STATE_DIR}/tasks/{task_id}.json",
            ))
    return issues


def _prompt_task_questions(brief: str) -> dict:
    """Ask the base questions, then the follow-ups that the first answers call for."""
    base = [question for question in task_questions(brief) if question["id"] != "context"]
    answers = prompt_questions(base, "task consult")
    follow_ups = [question for question in task_questions(brief, answers) if question["id"] not in answers]
    answers.update(prompt_questions(follow_ups, "task consult"))
    for point in open_points(brief, validate_answers(answers)):
        print(f"  Open point: {point}", file=sys.stderr)
    return answers


def _selection(args) -> dict:
    delegate = {}
    for item in args.delegate:
        board_id, separator, name = item.partition("=")
        if not separator or not board_id.strip() or not name.strip():
            raise ValueError("Use --delegate BOARD=NAME.")
        delegate[board_id.strip()] = name.strip()
    return {"add": args.add, "remove": args.remove, "reason": args.reason, "delegate": delegate}


def _read_consultation(task: dict) -> dict:
    if "consultation" not in task:
        raise TaskStateError("The task has no consultation yet.")
    return task["consultation"]


def _revoke(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> None:
    """The person withdraws an approval at their terminal, as they gave it: never an agent."""
    result = revoke_approval(task, args.by, args.reason)
    if not interactive():
        raise ValueError("Withdrawing an approval is the person's act: they run openguildkit task revoke in their own "
                         "terminal, as they approved.")
    problem = approval_problem(task, profile, catalog, root)
    if problem:
        print(f"OpenGuildKit: {problem['message']}", file=sys.stderr)
    print(f"Type {args.id} to withdraw the approval {task['decision']['by']} gave on {task['decision']['at'][:10]}: ",
          end="", file=sys.stderr, flush=True)
    if input().strip() != args.id:
        raise ValueError("Withdrawal cancelled.")
    with project_lock(state):
        if read_task(state, args.id) != task:
            raise ValueError("The task changed while you were deciding. Review it and retry.")
        write_json(task_path(state, args.id), result)
    print(result["status"])
    print(f"The guard no longer counts {args.id}. Next: {reconsult_command(args.id)}, or close the work in a linked "
          f'task: openguildkit task new "BRIEF" --follows {args.id}', file=sys.stderr)
    record = state / DECISIONS_DIR / f"{args.id}.json"
    if record.is_file():
        print(f"OpenGuildKit: {record.relative_to(root).as_posix()} still says {args.id} is approved, and guard --ci "
              f"accepts it until it says otherwise: write the withdrawal into it with openguildkit task export "
              f"{args.id}, and commit it.", file=sys.stderr)


def _decision_prompt(state: Path, task: dict, profile: dict, register: dict) -> list[str]:
    """What the person reads before approving, the same at the approval prompt and in task decision-payload: the
    previous round, the decision text (tasks.decision_text, also task challenge's), the brief, the summary and each
    board's advice."""
    recall = previous_round_line(task)
    review = validate_review(task["consultation"], task["review"])
    return [*([recall] if recall else []), *decision_text(task, profile, last_approval(state), register),
            "", f"Brief: {task['brief'].strip()}", "", review["summary"], *review_lines(review), "",
            f"Full decision brief, with each board's evidence: openguildkit task challenge {task['id']}",
            *verdict_lines(review, task.get("deliberation"), is_decision_task(task))]


def _decide(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> None:
    if task["status"] == "approved":
        raise ValueError(decided_message(task, approval_problem(task, profile, catalog, root)))
    if args.approve and (lane := light_lane.lane_problem(task, profile)):
        raise ValueError(lane)
    policy = approval_policy(profile)
    base = git_revision(root) if args.approve else None
    signature = None
    if args.approve and policy["mode"] == "signed":
        if not args.signature or not args.signer:
            raise ValueError(
                "This project requires a signed approval: run task decision-payload, sign it with ssh-keygen -Y sign "
                f"-n {NAMESPACE}, then pass --signature FILE --signer PRINCIPAL."
            )
        text = args.signature.read_text(encoding="utf-8")
        verify_signature(root, policy, decision_payload(task, args.by, args.reason, base), text, args.signer)
        signature = {"signer": args.signer, "text": text}
    register = load_register(state)
    blocking = blocking_alerts(register, task) if args.approve else []
    if blocking:
        raise ValueError("Approval is blocked:\n- " + "\n- ".join(blocking))
    removals = pending_removals(task) if args.approve else []
    result = record_decision(task, args.approve, args.by, args.reason, base, signature, removals)
    if args.approve:
        if (signature is None or removals) and not interactive():
            raise ValueError("Approval requires a person at an interactive terminal.")
        # A signed approval shows the same text: the signature replaces the typed ID, not the reading.
        print("\n".join(_decision_prompt(state, task, profile, register)), file=sys.stderr)
        if signature is None:
            print(f"Type {args.id} to approve the reviewed scope: ", end="", file=sys.stderr, flush=True)
            if input().strip() != args.id:
                raise ValueError("Approval cancelled.")
        for board in removals:
            print(f"The agent removed the {board} board, which the data answer selected. "
                  f"Type {board} to confirm the removal: ", end="", file=sys.stderr, flush=True)
            if input().strip() != board:
                raise ValueError(
                    f"Approval cancelled: the removal of the {board} board was not confirmed. "
                    "Request changes and consult again with it."
                )
    with project_lock(state):
        if read_task(state, args.id) != task:
            raise ValueError("The task changed while you were deciding. Review it and retry.")
        if args.approve:
            catalog = project_catalog(args, state)
            profile = load_profile(state, catalog)
            require_current_scope(task, profile, catalog)
            require_instructions(args, root, state, profile, catalog)
        write_json(task_path(state, args.id), result)
    print(result["status"])


def _project_tools(state: Path, profile: dict, registry: dict) -> dict[str, str]:
    """The project's tools by ID: connected through the host, or only listed in the profile."""
    tools = {item["id"]: "connected" for item in connected_tools(state, registry)}
    for tool_id in match_tools([name for name in profile.get("tools", []) if isinstance(name, str)], registry)[0]:
        tools.setdefault(tool_id, "listed, not connected")
    return tools


def _print_route(state: Path, task: dict, answers: dict, profile: dict, selected: dict,
                 selection: dict | None = None, answers_path: Path | None = None) -> None:
    """Print the selected boards with their reasons and tools, what was left out and how to change it."""
    selection = selection or {}
    registry = load_tools(state / "catalog" / "tools")
    tools = _project_tools(state, profile, registry)
    for board_id, reasons in selected["routing"].items():
        print(f"{board_id}: {'; '.join(reasons)}")
        usable = [f"{registry[tool_id]['title']} ({how})" for tool_id, how in tools.items()
                  if board_id in registry[tool_id]["brains"]]
        if usable:
            print(f"  tools: {', '.join(usable)}")
    for item in selected["adjustments"]:
        print(f"  {item['action']} {item['board']}: {item['reason']}")
    for pattern in selected["patterns"]:
        print(f"Suggested pattern {pattern['id']}: {pattern['reason']}. See openguildkit patterns --id {pattern['id']}.")
    text = " ".join([task["brief"], *(value for value in answers.values() if isinstance(value, str))])
    names = {tool_id: {"triggers": [registry[tool_id]["title"], *registry[tool_id].get("aliases", [])]}
             for tool_id in tools}
    enabled = set(selected["routing"]) | set(selected["not_selected"]) | set(selected["excluded"])
    for tool_id in trigger_matches(names, text):
        boards = sorted(board_id for board_id in registry[tool_id]["brains"] if board_id in enabled)
        chosen = [f"{board_id} (selected)" for board_id in boards if board_id in selected["routing"]]
        others = [board_id for board_id in boards if board_id not in selected["routing"]]
        line = f"The brief names {registry[tool_id]['title']}: " + (f"{', '.join(chosen)} can query it" if chosen else "no selected board can query it")
        print(line + (f"; {', '.join(others)} could, with --add" if others else "") + ".")
    if selected["excluded"]:
        excluded = ", ".join(f"{board_id} ({'; '.join(passages)})" for board_id, passages in selected["excluded"].items())
        print(f"Mentioned as excluded: {excluded}")
    expected = selected.get("expected_not_selected", {})
    if expected:
        print("Not selected, although the project expects them:")
        for board_id, reason in expected.items():
            print(f"  {board_id}: {reason}")
    others = [board_id for board_id in selected["not_selected"] if board_id not in expected]
    if others:
        print(f"Other boards you can add with --add: {len(others)} (openguildkit brains lists them).")
    task_id = task["id"]
    answers_file = shell_word(answers_path.as_posix()) if answers_path else "FILE"
    print(f"Change the boards: openguildkit task route {task_id} --answers {answers_file} --add BOARD --remove BOARD "
          "--reason TEXT to preview.")
    options = [*(f"--add {shell_word(board_id)}" for board_id in selection.get("add") or []),
               *(f"--remove {shell_word(board_id)}" for board_id in selection.get("remove") or []),
               *(f"--delegate {shell_word(f'{board_id}={name}')}" for board_id, name in (selection.get("delegate") or {}).items())]
    if options:
        options.append(f"--reason {shell_word(selection.get('reason') or '')}")
    print(f"Apply: openguildkit task consult {task_id} --answers {answers_file}{''.join(' ' + item for item in options)}")


def _relevance(root: Path, task: dict, profile: dict, catalog: dict, every: bool = False) -> dict:
    """Which packs concern the task, from its answers, its boards and the files changed since its approval."""
    if "consultation" not in task:
        return {"packs": {}}
    changed = changed_files(root, task)
    return {"packs": pack_relevance(task, profile, catalog, changed, every), "changed": changed, "every": every}


def _print_checks(checks: list[dict], reported: dict, task_id: str) -> None:
    """The asked checks, each named evidence under its rule, then what does not concern the task, once per pack."""
    skipped: dict[str, list] = {}
    for check in checks:
        if not check["concerned"]:
            entry = skipped.setdefault(check.get("pack") or check["id"], [check["reason"], 0])
            entry[1] += 1
            continue
        outcome = reported.get(check["id"], {}).get("status", "not reported")
        if check["kind"] == "evidence":
            need = SUPPLY if check["must_supply"] else SUPPLY_OR_NOT_APPLICABLE
            print(f"    {check['id']} [{need}] {outcome}: {check['title']}, provided by {check['owner_role']}")
            continue
        label = "mandatory" if check["mandatory"] else "verify" if check["kind"] == "machine" else "report"
        found = reported.get(check["id"], {}).get("evidence") if check["kind"] == "machine" else None
        text = found or check.get("command") or check.get("verification")
        print(f"{check['id']} [{label}] {outcome}: {text}")
    if skipped:
        print(f"Not concerned, no answer needed (openguildkit task checks {task_id} --all asks them):")
        for name, (reason, count) in skipped.items():
            print(f"  {name} ({count} check(s)): {reason}")


def _lane_problems(root: Path, task: dict, profile: dict) -> list[str]:
    """What keeps a short-lane task from being done: the profile no longer allows its paths, or a file changed since
    its approval is outside them. A project outside Git has no list of changed files to compare."""
    problem = light_lane.lane_problem(task, profile)
    if problem or not light_lane.is_light(task):
        return [problem] if problem else []
    outside = light_lane.files_outside(task["paths"], profile["light_paths"], changes_since_approval(root, task) or [])
    return [light_lane.outside_message(task["id"], task["paths"], profile["light_paths"], outside, "this project")] \
        if outside else []


def _closing(args, state: Path, task: dict, profile: dict, relevance: dict, root: Path, changed: list[str]) -> dict:
    """The closed task. Deferring evidence or naming who closes needs the person at a terminal."""
    lane = _lane_problems(root, task, profile)
    if lane:
        raise ValueError("The task cannot be declared done:\n- " + "\n- ".join(lane))
    blocking = blocking_alerts(load_register(state), task)
    if blocking:
        raise ValueError("The task cannot be declared done:\n- " + "\n- ".join(blocking))
    if args.defer and not args.by:
        raise ValueError("Name the person who hands the evidence to a follow-up task: --by NAME.")
    deferrals = []
    for item in args.defer:
        check_id, _, follow_up = item.rpartition("=")
        if not check_id or not follow_up:
            raise ValueError("Write --defer EVIDENCE=TASK, for example --defer evidence:gdpr/x/y=privacy-record.")
        deferrals.append((check_id, read_task(state, follow_up)))
    current = defer_evidence(task, profile, deferrals, args.by.strip(), relevance) if deferrals else task
    closed = complete_task(current, profile, root, relevance, args.by, changed=changed)
    set_aside = set_aside_rules(current, profile, relevance)
    if set_aside and not (args.by or "").strip():
        raise ValueError(
            f"{len(set_aside)} data protection, security or AI rule(s) are declared not applicable:\n- "
            + "\n- ".join(set_aside) + f"\nA person confirms each: openguildkit task complete {args.id} --by NAME, "
            "at a terminal.")
    if args.by:
        if not interactive():
            raise ValueError("Closing a task with --by needs the person at an interactive terminal.")
        for group in closed["result"]["closing"]["open_points"]:
            print(f"{group['group']}:", file=sys.stderr)
            for point in group["points"]:
                print(f"  - {point}", file=sys.stderr)
        if set_aside:
            print("Data protection, security or AI rules declared not applicable, which you confirm:", file=sys.stderr)
            for line in set_aside:
                print(f"  - {line}", file=sys.stderr)
        print(f"Type {args.id} to close it as {closed['status']}: ", end="", file=sys.stderr, flush=True)
        if input().strip() != args.id:
            raise ValueError("Closing cancelled.")
    return closed


def _print_closing(task: dict, listed: bool = False) -> None:
    """The status and the open points grouped by nature, one per line; notes on what was not run or read go to stderr.

    listed: the person already read the open points at the confirmation prompt, so they are not printed again.
    """
    print(task["status"])
    if task["result"]["closing"].get("verification"):
        print(task["result"]["closing"]["verification"], file=sys.stderr)
    groups = task["result"]["closing"]["open_points"]
    if groups and listed:
        count = sum(len(group["points"]) for group in groups)
        print(f"{count} open point(s), listed above and kept for later: openguildkit task show {task['id']} --closing.")
        print(f'To follow up, open a task linked to this one: openguildkit task new "BRIEF" --follows {task["id"]}')
    elif groups:
        print("Left open, most serious first:")
        for group in groups:
            print(f"{group['group']}:")
            for point in group["points"]:
                print(f"  - {point}")
        print(f'To follow up, open a task linked to this one: openguildkit task new "BRIEF" --follows {task["id"]}')
    elif is_decision_task(task):
        print(f'Open the implementation task with openguildkit task new "BRIEF" --follows {task["id"]}.')
    if criteria_summary(task["result"]):
        print(criteria_summary(task["result"]), file=sys.stderr)
    evidence = [item for item in task["result"].get("checks", []) if item["check"].startswith("evidence:")
                and item["status"] == "passed"]
    if evidence:
        confirmed = ", ".join(f"{item.get('owner', 'nobody named')} ({item['check']})" for item in evidence)
        print(f"Named evidence: OpenGuildKit checked that each project path exists; it did not read the documents. "
              f"Confirmed by: {confirmed}.", file=sys.stderr)


MIN_REASON_WORDS = 3


def _declaration_checks(args, task: dict, profile: dict, check_id: str) -> dict:
    """The task's check commands; a declaration names one of them and the person, at a terminal."""
    commands = {check["id"]: check["command"] for check in expected_checks(task, profile) if check["kind"] == "command"}
    if check_id not in commands:
        raise ValueError(f"{check_id} is not a check command of the task: {', '.join(commands) or 'none'}.")
    if not (args.by or "").strip():
        raise ValueError("Name the person with --by NAME.")
    if not interactive():
        raise ValueError("Declaring whether a command can run needs the person at an interactive terminal.")
    return commands


def _cannot_run(args, root: Path, state: Path, task: dict, profile: dict, relevance: dict) -> dict:
    """A person records, at a terminal, that a check command cannot run in this environment.

    The command runs first: one that passes here can run, and is recorded as such instead.
    """
    commands = _declaration_checks(args, task, profile, args.cannot_run)
    if len((args.reason or "").split()) < MIN_REASON_WORDS:
        raise ValueError(f"Say why {args.cannot_run} cannot run here, in at least {MIN_REASON_WORDS} words: "
                         '--reason "The sandbox has no network for npm ci."')
    ran = run_command_checks(root, state, task, profile, relevance=relevance, only={args.cannot_run})
    if ran and ran[0]["status"] == "passed":
        raise ValueError(f"{args.cannot_run} passes in this environment: nothing to declare. Run task verify "
                         f"{args.id} to record it as passed.")
    print(f"Type {args.id} to record that {args.cannot_run} (`{commands[args.cannot_run]}`) cannot run here: ",
          end="", file=sys.stderr, flush=True)
    if input().strip() != args.id:
        raise ValueError("Cancelled.")
    return {"check": args.cannot_run, "status": "skipped", "reason": " ".join(args.reason.split()),
            "owner": args.by.strip(), "cannot_run": True}


def _withdraw(args, root: Path, state: Path, task: dict, profile: dict, relevance: dict) -> dict:
    """The person who declared that a command cannot run withdraws it: the command runs and its outcome stands."""
    _declaration_checks(args, task, profile, args.withdraw)
    declaration = declared_cannot_run(task).get(args.withdraw)
    if declaration is None:
        raise ValueError(f"No declaration that {args.withdraw} cannot run is recorded.")
    if declaration["owner"].casefold() != args.by.strip().casefold():
        raise ValueError(f"{declaration['owner']} declared it: only they withdraw it.")
    ran = run_command_checks(root, state, task, profile, relevance=relevance, only={args.withdraw})
    if not ran:
        raise ValueError(f"{args.withdraw} does not concern the task any more.")
    return ran[0]


NO_CHECK_COMMAND = (
    "No project check command is configured: task verify ran no test. To have it run one: openguildkit profile add "
    "check \"COMMAND\" --by NAME --reason WHY (docs/workflow.md#project-checks); the change applies to tasks "
    "consulted after it."
)


def _print_remaining(args, task: dict, profile: dict, relevance: dict, root: Path, state: Path,
                     changed: list[str], held: list[str]) -> int:
    """Every point that keeps the task from being done, one per line, then their count.

    The exit status is 1 when task verify finds a mandatory check command failed, so a script or a CI
    job can tell; points that only need answers keep it at 0.
    """
    if args.action == "verify" and not task["consultation"]["scope"].get("checks") and not is_decision_task(task):
        print(NO_CHECK_COMMAND)
    problems = (completion_problems(task, profile, relevance, changed=changed, root=root)
                + blocking_alerts(load_register(state), task) + verification_blocker_problems(task, profile, root)
                + _lane_problems(root, task, profile))
    # Before any report, task verify counts the answers the result file gives rather than one line per rule.
    folded = set(answers_to_report(task, profile, relevance)) if args.action == "verify" else set()
    if folded:
        print(f"- {len(folded)} rule(s) and named evidence to report: openguildkit task result {args.id} --template "
              "lists them with the answers each accepts.")
    for problem in problems:
        if problem.split(" ", 1)[0] not in folded:
            print(f"- {problem}")
    if problems:
        print(f"{len(problems)} point(s) before the task can be done.")
    elif held:
        print("Nothing else is missing, but some answers were not recorded (above): fix them, or run task complete "
              "with the answers already recorded.")
    elif (any(group["group"] == SENSITIVE_GROUP for group in points_left_open(task, profile, relevance))
          or set_aside_rules(task, profile, relevance)):
        # task complete refuses these without the person: say so now rather than at the closing.
        print(f"Ready to close with the person at a terminal: a data protection, security or AI point stays open, "
              f"so they run openguildkit task complete {args.id} --by NAME.")
    else:
        print("Ready: run task complete.")
    failed = [item for item in task["result"]["checks"]
              if item["check"].startswith("command:") and item["status"] == "failed"]
    return 1 if args.action == "verify" and failed else 0


def _warn_inputs(original: object, recorded: object, label: str) -> None:
    for warning in input_warnings(original, recorded, label):
        print(warning, file=sys.stderr)


def _questions(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The questionnaire as JSON, with the follow-ups and open points the answers leave."""
    if light_lane.is_light(task):
        raise ValueError(light_lane.no_questions_message(args.id))
    # One shape with or without answers: the follow-ups carry their prompt, so they can be asked as they are.
    if args.answers is None:
        answers, validated, open_list = {}, None, []
    else:
        answers = read_json(args.answers)
        with _input_file(args.answers):
            validated = validate_answers(answers)
        open_list = open_points(task["brief"], validated)
    questions = task_questions(task["brief"], validated)
    follow_ups = [{"id": question["id"], "prompt": question["prompt"]} for question in questions
                  if question.get("essential") is not None and question["id"] not in answers]
    if args.answers is not None and "concerns" not in answers:
        # Required for a new consultation: asked with its choices, as task consult will refuse without it.
        question = concerns_question()
        follow_ups.append({key: question[key] for key in ("id", "prompt", "type", "choices", "unsure")})
    if args.follow_ups and args.answers is None:
        raise ValueError(f"--follow-ups lists what the answers leave to ask: openguildkit task questions {args.id} "
                         "--answers FILE --follow-ups.")
    print_json({
        **({} if args.follow_ups else {"questions": questions}),
        "follow_ups": sorted(follow_ups, key=lambda item: item["id"]),
        "open_points": open_list,
    })


def _brief(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The saved consultation, a board's pass, the whole scope or the rules of one pack."""
    consultation = _read_consultation(task)
    if args.scope:
        print_json(consultation["scope"])
    elif args.pack:
        print(pack_rules(consultation, args.pack), end="")
    elif args.board:
        board_brief_problem(task, args.board)
        print(board_brief(consultation, args.board))
    else:
        print(consultation["markdown"])


def _template(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The review template as JSON."""
    print_json(_read_consultation(task)["review_template"])


def _blockers(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The review's blockers and how each was resolved."""
    items = blocker_list(task)
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
                print(f"    evidence: {resolution['evidence']}; supports: {resolution['supports']}")
            if expired:
                print(f"    waived by {resolution['by']}: {resolution['reason']} (scope: {resolution['scope']}); "
                      "the blocker is open again")
            if resolution and resolution.get("recorded_from") == "no terminal":
                print("    recorded without a terminal")


def _resolve(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The person clears a blocker with evidence, or waives it within the project's policy."""
    action = args.action
    require_approval(task, profile, catalog, root)
    require_blocker_status(task)
    if action == "waive":
        if not interactive():
            raise ValueError("A waiver needs a person at an interactive terminal.")
        details = {"kind": "waived", "by": args.by, "reason": args.reason, "scope": args.scope, "until": args.until}
    else:
        details = {"kind": "cleared", "by": args.by, "evidence": args.evidence, "supports": args.supports}
        if (args.signature is None) != (args.signer is None):
            raise ValueError("Pass --signature and --signer together.")
        if args.payload:
            payload = resolve_blocker(task, args.blocker, details, profile, root, signing_payload=True)
            args.payload.write_bytes(payload_text(payload).encode("utf-8"))
            print(args.payload)
            return
        if args.signature:
            if approval_policy(profile)["mode"] != "signed":
                raise ValueError("A clearance signature is only used in a project with signed approvals.")
            details.update(signature=args.signature.read_text(encoding="utf-8"), signer=args.signer)
    details["terminal"] = interactive()
    result = resolve_blocker(task, args.blocker, details, profile, root)
    # A signed clearance is the person's act through their key; otherwise the person types the task ID.
    if action == "clear" and "signature" not in details:
        if not details["terminal"]:
            raise ValueError(
                "Clearing a blocker is the person's act: show them the evidence, and they run task clear in "
                "their own terminal."
            )
        print(f"Type {args.id} to clear {args.blocker} with {args.evidence}: ", end="", file=sys.stderr,
              flush=True)
        if input().strip() != args.id:
            raise ValueError("Clearing cancelled.")
    if action == "waive":
        print(f"Type {args.id} to waive {args.blocker} until {args.until}: ", end="", file=sys.stderr, flush=True)
        if input().strip() != args.id:
            raise ValueError("Waiver cancelled.")
    with project_lock(state):
        if read_task(state, args.id) != task:
            raise ValueError("The task changed while you were deciding. Review it and retry.")
        write_json(task_path(state, args.id), result)
    print(details["kind"])


def _checks(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The checks the approved task must report, and their outcomes so far."""
    if task["status"] not in ("approved", *DONE_STATUSES):
        raise TaskStateError("Checks belong to an approved task.")
    relevance = _relevance(root, task, profile, catalog, args.all)
    checks = expected_checks(task, profile, relevance)
    reported = outcomes(task, profile, relevance)
    if args.json:
        print_json([{**check, "result": reported.get(check["id"])} for check in checks])
    else:
        _print_checks(checks, reported, task["id"])


def _result_template(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """A result file to fill in."""
    if task["status"] != "approved":
        raise TaskStateError("Results belong to an approved task that is not done yet.")
    relevance = _relevance(root, task, profile, catalog, args.all)
    changed = decision_changes(root, task)
    print_json(result_template(task, profile, relevance, changed=changed))
    if changed:
        print(decision_revision_message(changed), file=sys.stderr)


def _outcome(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Run the checks, record a result file, or close the task; then what is left before it is done."""
    action = args.action
    if task["status"] != "approved":
        raise TaskStateError("Run checks for an approved task that is not done yet." if action == "verify"
                             else "Results belong to an approved task that is not done yet.")
    decision = is_decision_task(task)
    changed = decision_changes(root, task)
    relevance = _relevance(root, task, profile, catalog, getattr(args, "all", False))
    notes = []
    if action == "verify":
        payload = {}
        if not decision:
            revision = git_revision(root)
            payload["revision"] = revision["commit"] if revision else "working tree"
        if decision and args.chaosfolk:
            raise ValueError("ChaosFolk replays are for implementation tasks.")
        if args.chaosfolk and (args.cannot_run or args.withdraw):
            raise ValueError("--cannot-run and --withdraw concern a check command: run them without --chaosfolk.")
        if args.cannot_run:
            payload["checks"] = [_cannot_run(args, root, state, task, profile, relevance)]
        elif args.withdraw:
            payload["checks"] = [_withdraw(args, root, state, task, profile, relevance)]
        elif args.chaosfolk:
            imported = chaosfolk_checks(root, args.chaosfolk, args.tool_version)
            payload.update(checks=imported["checks"], run={**imported["run"], "at": timestamp()})
        elif not decision:
            payload["checks"], notes = keep_declarations(
                task, run_command_checks(root, state, task, profile, relevance=relevance))
    elif action == "complete":
        closing = _closing(args, state, task, profile, relevance, root, changed)
    with project_lock(state):
        current_task = read_task(state, args.id)
        if current_task != task:
            raise ValueError("The task changed meanwhile. Retry.")
        if action == "verify":
            result = record_result(current_task, profile, payload, "verify", relevance, root)
        elif action == "result":
            with _input_file(args.file):
                reported = read_json(args.file)
                result = record_result(current_task, profile, reported, "report", relevance, root, changed=changed)
            _warn_inputs(reported, redact_data(reported), "task result")
        else:
            result = closing
        held = result.pop("_held", [])
        write_json(task_path(state, args.id), result)
    for warning in _unshared_evidence(root, {args.id: cited_evidence(result)}):
        print(f"OpenGuildKit: {warning}", file=sys.stderr)
    if action == "complete":
        _print_closing(result, listed=bool(args.by))
        exported = (state / DECISIONS_DIR / f"{args.id}.json").is_file()
        print(f"OpenGuildKit: commit the work (git add, git commit), then "
              f"{'export the decision record again' if exported else 'export the decision record'} so it says the "
              f"task is completed, and commit it: openguildkit task export {args.id}. The record lists the files Git "
              "tracks, so a new file left out of Git is in no record. guard --ci accepts it with the work, or in a "
              "pull request of its own once the approval's record is merged: the same approval, with its completion "
              "added.", file=sys.stderr)
        return
    for line in notes:
        print(line)
    kept = {item["check"] for item in result["result"]["checks"]}
    for item in held:
        earlier = " The earlier answer stays recorded." if item["check"] in kept else ""
        print(f"Not recorded: {item['message']}{earlier}", file=sys.stderr)
    machine = {check["id"] for check in expected_checks(result, profile) if check["kind"] == "machine"}
    for item in result["result"]["checks"]:
        print(f"{item['check']}: {item['status']}")
        if item["status"] == "failed" and item.get("message"):
            print(f"    {item['message']}")
        elif item.get("cannot_run"):
            print(f"    Cannot run here, declared by {item['owner']}: {item['reason']}")
        elif item["check"] in machine and item.get("evidence"):
            # What the check found or did not find: the rule's own sentence reads the same either way.
            print(f"    {item['evidence']}")
    for name in (() if decision else missing_scenarios(result)):
        print(f"chaosfolk:{name}: missing")
    for item in result["result"].get("waiting_for", []):
        print(f"Waiting for {item['check']}: {item['title']}, provided by {item['owner']} (required because "
              f"{item['why']}). Ask them for it, or hand it to a follow-up task: task complete {args.id} "
              f"--defer {item['check']}=FOLLOW-UP --by NAME.")
    if criteria_summary(result["result"]):
        print(criteria_summary(result["result"]))
    for warning in result["result"].get("warnings", []):
        print(f"Warning: {warning}")
    return _print_remaining(args, result, profile, relevance, root, state, changed, held)


def _alerts(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The task's dependency alerts: import, link and review them."""
    alerts_cli.task_command(args, state, task)


def _runs(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The scenarios whose outcome changed between the last two ChaosFolk replays."""
    comparison = compare_runs(task)
    if comparison is None:
        raise TaskStateError("The task has fewer than two ChaosFolk replays to compare: task verify --chaosfolk "
                             "records them on an approved task.")
    if args.json:
        print_json(comparison)
    else:
        for name, (before, after) in comparison["changed"].items():
            print(f"{name}: {before or 'absent'} -> {after or 'absent'}")
        print(f"{len(comparison['unchanged'])} scenario(s) unchanged")


def _export(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Write the shareable decision record, or the withdrawal of its approval into it."""
    if task["status"] not in ("approved", *DONE_STATUSES):
        path = export_withdrawal(root, state, task, args.output).resolve()
        print(path.relative_to(root).as_posix() if root in path.parents else str(path))
        print(f"OpenGuildKit: the record now carries the withdrawal of the approval of {args.id}: guard --ci refuses "
              "it, and task list --decisions shows it as withdrawn. Commit it.", file=sys.stderr)
        return
    path = export_decision(root, state, task, profile, args.output).resolve()
    print(path.relative_to(root).as_posix() if root in path.parents else str(path))
    untracked = untracked_files(root) if task["decision"].get("base_revision") else []
    if untracked:
        shown = ", ".join(untracked[:10]) + (f" and {len(untracked) - 10} more" if len(untracked) > 10 else "")
        print(f"OpenGuildKit: {len(untracked)} new file(s) Git does not track yet are not in the record: {shown}. "
              "Add them with git add (or commit the work) and export again, or guard --ci finds them in no record.",
              file=sys.stderr)
    if "completed_at" not in task:
        print(f"OpenGuildKit: task {args.id} is not completed yet and the record says so. It lists the files Git "
              "tracks that changed since the approval, which guard --ci compares with the pull request: export it "
              "again once the work is committed, and after task complete, and commit it.", file=sys.stderr)


def _deliberate(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The objections between boards and the response template; without objection, that there is nothing to answer."""
    request = deliberation_request(task)
    print_json(request)
    if not request["objections"]:
        print(f"OpenGuildKit: {nothing_to_deliberate(task['id'])}", file=sys.stderr)


def _respond(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Record the boards' answers to each other's objections."""
    payload = read_json(args.file)
    with project_lock(state):
        current_task = read_task(state, args.id)
        if current_task != task:
            raise ValueError("The task changed while you were deliberating. Run task deliberate again.")
        with _input_file(args.file):
            result = record_deliberation(current_task, payload)
        write_json(task_path(state, args.id), result)
    deliberation = result["deliberation"]
    print(f"{len(deliberation['agreed'])} resolved, {len(deliberation['open'])} open")
    print(RESOLUTION_RULE, file=sys.stderr)


def _challenge(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The decision brief and each board's challenge."""
    recall = previous_round_line(task)
    if recall:
        print(recall)
    lines = (decision_text(task, profile, last_approval(state), load_register(state))
             if "review" in task else None)
    print(challenge_report(task, lines), end="")


def _route(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Preview the boards a consultation would select, and why."""
    if light_lane.is_light(task):
        raise ValueError(light_lane.no_route_message(args.id))
    if args.answers is None and "answers" not in task:
        raise ValueError(f"Pass the answers: openguildkit task route {args.id} --answers FILE previews the boards "
                         f"before openguildkit task consult {args.id} --answers FILE records them.")
    if args.answers:
        with _input_file(args.answers):
            answers = validate_answers(read_json(args.answers))
            require_concerns(answers)
    else:
        answers = validate_answers(task["answers"])
    selected = select_boards(
        task_scope_profile(profile, catalog, answers.get("components", [])),
        catalog, {**task, "answers": answers}, answers, _selection(args)
    )
    if args.json:
        print_json(selected)
    else:
        _print_route(state, task, answers, profile, selected, _selection(args), args.answers)


def _consult(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Record the answers and prepare the consultation of the boards, under the project lock."""
    # Only a consultation reads the reference library and the Storybook record: the other commands start without.
    from .references import load_references, with_pattern_references
    from .storybook import scope_entry as storybook_scope_entry

    if args.brief_file is not None:
        with _input_file(args.brief_file):
            args.revised_brief = args.brief_file.read_text(encoding="utf-8-sig")
    if light_lane.is_light(task):
        answers = _light_answers(args, task, profile)
    elif args.reuse_answers:
        answers = _reused_answers(args, task)
    else:
        answers = (
            read_json(args.answers)
            if args.answers is not None
            else _prompt_task_questions(args.revised_brief or task["brief"])
        )
    if args.answers is not None and not args.reuse_answers:
        with _input_file(args.answers):
            validate_answers(answers)
            require_concerns(answers)
    else:
        require_concerns(answers)
    with project_lock(state):
        current_task = read_task(state, args.id)
        if current_task != task:
            raise ValueError("The task changed while you were answering. Review it and retry.")
        catalog = project_catalog(args, state)
        profile = load_profile(state, catalog)
        require_instructions(args, root, state, profile, catalog)
        controls = host_controls(root, profile, other_tools=False)
        market = None
        if args.market:
            public = profile.get("research") == "public-sources" and answers.get("research") == "public"
            research = "public-sources" if public else "local-only"
            market = market_scope_entry(load_dossier(state, args.market), research, brief=" ".join(
                [args.revised_brief or current_task["brief"], answers.get("context") or ""]))
        families = with_pattern_references(load_references(state / "catalog" / "references", catalog),
                                           catalog["patterns"])
        scoped_profile = task_scope_profile(profile, catalog, answers.get("components", []))
        active = set(scoped_profile["packs"])
        context = consultation_context(current_task, answers, scoped_profile, catalog)
        knowledge = {board_id: brief_knowledge(board_id, catalog, families, active, context)
                     for board_id in catalog["boards"]}
        registry = load_tools(state / "catalog" / "tools")
        for board_id in catalog["boards"]:
            usable = connected_tools(state, registry, board_id)
            if usable:
                knowledge[board_id]["tools"] = usable
        result = record_consultation(alerts_cli.consultation_task(state, current_task), answers, profile, catalog,
                                     _selection(args), controls, market, storybook_scope_entry(state), knowledge,
                                     connected_tools(state, registry), root,
                                     args.revised_brief)
        result.pop("dependency_alerts")
        if "dependency_alerts" in current_task:
            result["dependency_alerts"] = current_task["dependency_alerts"]
        write_json(task_path(state, args.id), result)
    if args.revised_brief is not None:
        _warn_inputs(args.revised_brief.strip(), result["brief"], "revised brief")
    _warn_inputs(answers, redact_data(answers), "task answers")
    print(result["consultation"]["markdown"])
    for line in board_replacements(catalog):
        print(f"OpenGuildKit: {line}", file=sys.stderr)


def _light_answers(args, task: dict, profile: dict) -> dict:
    """The answers of a short-lane task: the lane's own. The lane convenes one board and takes no answers of the
    requester's, so those options are refused, and a lane the profile no longer allows stops the consultation."""
    used = [option for option, given in (("--answers", args.answers), ("--add", args.add), ("--remove", args.remove)) if given]
    if used:
        raise ValueError(light_lane.options_message(args.id, used))
    problem = light_lane.lane_problem(task, profile)
    if problem:
        raise ValueError(problem)
    return light_lane.default_answers(task)


def _reused_answers(args, task: dict) -> dict:
    """The task's recorded answers for task consult --reuse-answers, those of --answers FILE replacing them, and
    concerns asked at a terminal when neither has it (a task consulted before the question was required). Without a
    terminal a missing concerns is answered unsure, which keeps every topic's rules open, and the command says so."""
    if "answers" not in task:
        raise ValueError(f"Task {task['id']} has no recorded answers to reuse: consult it with openguildkit task "
                         f"consult {task['id']} --answers FILE.")
    answers = dict(task["answers"])
    if args.answers is not None:
        with _input_file(args.answers):
            given = read_json(args.answers)
            if not isinstance(given, dict):
                raise ValueError("Task answers must be a JSON object.")
            answers.update(given)
            validate_answers(answers)
    if "concerns" not in answers:
        if interactive():
            answers.update(prompt_questions([concerns_question()], "task consult"))
        else:
            answers["concerns"] = ["unsure"]
            print(f"OpenGuildKit: the recorded answers of {task['id']} have no concerns, which a new consultation "
                  "needs: consulted as unsure, which keeps every topic's rules open and consults its boards. To narrow "
                  f'it, pass a file such as {{"concerns": ["none"]}}: openguildkit task consult {task["id"]} '
                  "--reuse-answers --answers FILE.", file=sys.stderr)
    return answers


def _review(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Record the completed board reviews."""
    review = read_json(args.file) if args.file else None
    with project_lock(state):
        current_task = read_task(state, args.id)
        if current_task != task:
            raise ValueError("The task changed while you were reviewing. Read the consultation and retry.")
        if review is not None:
            with _input_file(args.file):
                result = record_review(current_task, review, root)
        else:
            result = assemble_review(current_task, args.summary)
        write_json(task_path(state, args.id), result)
    print(result["status"])
    for warning in result["review"].get("warnings", []):
        print(f"Warning: {warning}", file=sys.stderr)
    if review is not None:
        for warning in tool_evidence_warnings(root, state, result["review"]["boards"]):
            print(f"Warning: {warning}", file=sys.stderr)


def _pass(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Start one board's pass, or record its entry."""
    action = args.action
    entry = read_json(args.file) if action == "submit" else None
    with project_lock(state):
        current_task = read_task(state, args.id)
        if action == "pass":
            board_brief_problem(current_task, args.board)
            result = start_pass(current_task, args.board, args.mode or "sequential", args.again)
            submitted = result.pop("_submitted", False)
        else:
            with _input_file(args.file):
                result = submit_pass(current_task, entry, args.mode, root)
        error = result.pop("_error", None)
        copied = result.pop("_warnings", [])
        write_json(task_path(state, args.id), result)
    if action == "pass":
        print(board_brief(result["consultation"], args.board, earlier_sequential_pass(result, args.board)))
        if submitted:
            print(f"The {args.board} pass is already submitted; to redo it on purpose, run openguildkit task pass "
                  f"{args.id} {args.board} --again. This copy is for reading only.", file=sys.stderr)
    elif error:
        raise ValueError(f"{args.file.as_posix()}: the pass is recorded as failed. {error}\nFix these points in the "
                         f"file and send it again: openguildkit task submit {args.id} --file {args.file.as_posix()}")
    else:
        print("done")
        for warning in copied:
            print(f"Warning: {warning}", file=sys.stderr)
        saved_entry = result["passes"]["boards"][entry["id"].strip()]["entry"]
        for warning in tool_evidence_warnings(root, state, [saved_entry]):
            print(f"Warning: {warning}", file=sys.stderr)
        print(passes_left(result), file=sys.stderr)


def _progress(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """Which board passes are done, failed, started or missing."""
    _read_consultation(task)
    progress = pass_progress(task)
    if args.json:
        print_json(progress)
    else:
        for item in progress:
            details = ", ".join(f"{key} {item[key]}" for key in ("mode", "attempts", "in") if key in item)
            print(f"{item['board']}: {item['status']}{f' ({details})' if details else ''}")
            if "error" in item:
                print(f"    {item['error']}")


def _decision_payload(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The exact decision an approver signs, after the text they read before approving."""
    if task["status"] != "reviewed":
        decided = decided_message(task, approval_problem(task, profile, catalog, root))
        if decided:
            raise ValueError(decided)
        raise TaskStateError("Record the boards' review before preparing a decision.")
    # The signer reads what they sign: the same lines as the approval prompt, then the payload with the brief.
    print("\n".join(_decision_prompt(state, task, profile, load_register(state))), file=sys.stderr)
    text = payload_text(decision_payload(task, args.by, args.reason, git_revision(root)))
    if args.output:
        # Exact UTF-8 bytes with LF line endings: a shell redirect could change the encoding.
        args.output.write_bytes(text.encode("utf-8"))
        print(args.output)
    else:
        print(text, end="")


def _authorize(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """A person allows or refuses an external action outside the authorized scope."""
    if args.allow and not interactive():
        raise ValueError("Allowing an external action requires a person at an interactive terminal.")
    result = record_authorization(task, args.external_action, args.target, args.allow, args.by, args.reason)
    if args.allow:
        print(f"Type {args.id} to allow {args.external_action} on {args.target}: ", end="", file=sys.stderr, flush=True)
        if input().strip() != args.id:
            raise ValueError("Authorization cancelled.")
    with project_lock(state):
        if read_task(state, args.id) != task:
            raise ValueError("The task changed while you were deciding. Review it and retry.")
        write_json(task_path(state, args.id), result)
    print(result["authorizations"][-1]["decision"])


def _handoff(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> int | None:
    """The approved implementation handoff, or the decision record of a decision task."""
    evidence, checks = [], None
    if task.get("status") in ("approved", *DONE_STATUSES):
        checks = expected_checks(task, profile, _relevance(root, task, profile, catalog))
    if task.get("status") == "approved":
        evidence = [check for check in checks if check["concerned"] and check["kind"] == "evidence"]
    output = handoff(task, evidence, checks)
    require_instructions(args, root, state, profile, catalog)
    waits = waiting_for(task, {name: _status_of(state, name) for name in task.get("after", [])})
    if task["status"] == "approved" and waits:
        print(f"Waits for {waits_line(waits)}: deliver {'it' if len(waits) == 1 else 'them'} first; the order stays "
              "the person's decision.")
    print(output)


def _status_of(state: Path, task_id: str) -> str:
    try:
        return read_task(state, task_id)["status"]
    except ValueError:
        return "unknown"


def _new(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    """Create a task draft and print its ID; the next step goes to the agent on standard error."""
    if (args.brief is None) == (args.file is None):
        raise ValueError("Supply either a task brief or --file PATH.")
    brief = args.file.read_text(encoding="utf-8-sig") if args.file else args.brief
    require_instructions(args, root, state, profile, catalog)
    lane = light_lane.declare(args.lane, args.paths, profile)
    with project_lock(state):
        record = state / DECISIONS_DIR / f"{args.id}.json" if args.id else None
        if record is not None and record.is_file() and not task_path(state, args.id).is_file():
            raise ValueError(f"Task ID {args.id} is already used by the exported decision "
                             f"{record.relative_to(root).as_posix()}, a teammate's task or an earlier one: read it "
                             f"with openguildkit task show {args.id}, and choose another ID.")
        task_id = create_task(state, brief, args.id, args.follows, lane, args.after)
        statuses = {name: read_task(state, name)["status"] for name in dict.fromkeys(args.after or [])}
    print(task_id)
    if statuses:
        waits = waiting_for({"after": list(statuses)}, statuses)
        print(f"Waits for {waits_line(waits)}." if waits else f"Its dependencies are done: {', '.join(statuses)}.",
              file=sys.stderr)
    _warn_inputs(brief.strip(), redact_credentials(brief.strip()), "task brief")
    # Standard output keeps only the ID, which scripts read; the next steps go to the agent on stderr, in the README's
    # order, with the folder the working files go in.
    if lane:
        print(light_lane.next_line(task_id, lane["paths"]), file=sys.stderr)
        return
    print(f"Next: read the questions with openguildkit task questions {task_id}; save the answers in {WORK_DIR}/ "
          f"(Git ignores it), get the follow-up questions they call for with openguildkit task questions {task_id} "
          f"--answers FILE --follow-ups, preview the boards with openguildkit task route {task_id} --answers FILE, "
          f"then consult the boards with openguildkit task consult {task_id} --answers FILE.", file=sys.stderr)


def _list(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    """The project's tasks with their status and next open point, or the exported decisions."""
    if args.decisions:
        rows = exported_decisions(root, state, profile, Fingerprints(profile, catalog))
        if args.json:
            print_json(rows)
        else:
            _print_decision_rows(rows)
        return
    rows = list_tasks(state, args.status, args.owner, args.since, args.until, profile=profile, catalog=catalog,
                      root=root)
    if args.ready:
        rows = [row for row in rows if row["status"] not in (*DONE_STATUSES, "unreadable") and not row.get("waiting_for")]
    clashes = _id_clashes(root, state)
    for row in rows:
        if row["id"] in clashes:
            row["id_used_by_record"] = clashes[row["id"]]
            if not args.json:
                print(f"OpenGuildKit: {_clash_message(row['id'], clashes[row['id']])}", file=sys.stderr)
    if args.json:
        print_json(rows)
    elif not rows:
        shared = len(exported_records(state))
        print("No task matches." + (f" {shared} exported decision(s) of the repository, teammates' included: "
                                    "openguildkit task list --decisions" if shared else ""))
    else:
        for row in rows:
            owner = f", {row['decided']}" if row.get("decided") else ""
            if row.get("closed_by"):
                owner += f", closed by {row['closed_by']}"
            follows = f" (follows {row['follows']})" if row.get("follows") else ""
            lane = f" (short lane: {', '.join(row['paths'])})" if row.get("lane") else ""
            print(f"{row['id']} [{row['status']}{owner}] {row.get('brief', '')}{lane}{follows}")
            print(f"    next: {row['next']}")
            if row.get("note"):
                print(f"    note: {row['note']}")
            if row.get("waiting_for"):
                print(f"    waits for: {', '.join(item['task'] + ' (' + item['status'] + ')' for item in row['waiting_for'])}")


def _retro_record(root: Path, state: Path, task_id: str) -> dict:
    """The facts of a closed task known here only by its exported record, or why the record cannot be read."""
    path = state / DECISIONS_DIR / f"{task_id}.json"
    record = read_json(path)
    where = path.relative_to(root).as_posix()
    if not isinstance(record, dict) or record.get("record_sha256") != record_digest(record):
        raise ValueError(f"The exported record {where} does not match its digest: it was changed after it was "
                         "exported. Restore it from git, or run openguildkit check to see what it reports.")
    try:
        return facts_of_record(record)
    except ValueError:
        raise ValueError(f"The exported record {where} was written before task {task_id} was completed, so it has no "
                         "closing to read. Look at it with openguildkit task list --decisions; once the task is "
                         f"closed, openguildkit task export {task_id} writes it.") from None


def _closed_facts(state: Path) -> tuple[list[dict], dict]:
    """The facts of every closed task of the project, the task records first and the exported records of the others,
    and how many records were left out. A task record read here is the one its exported record repeats."""
    facts, held, ignored = [], set(), {"unreadable_task_records": 0, "exported_records_not_holding": 0}
    for path in sorted((state / "tasks").glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError:
            ignored["unreadable_task_records"] += 1
            continue
        held.add((task["id"], task["created_at"]))
        if task["status"] in DONE_STATUSES:
            facts.append(facts_of_task(task))
    for _, record in exported_records(state):
        if record is None:
            ignored["exported_records_not_holding"] += 1
        elif record.get("completed") is True and record.get("status") in DONE_STATUSES:
            if record.get("record_sha256") != record_digest(record):
                ignored["exported_records_not_holding"] += 1
            elif (record["task"], record.get("task_created_at") or "") not in held:
                facts.append(facts_of_record(record))
    return facts, ignored


def _retro(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    """The retrospective of one closed task, or with --all of the project: read from the records, never written."""
    if bool(args.id) == args.all:
        raise ValueError("Name the closed task to read, openguildkit task retro ID, or count the whole project with "
                         "openguildkit task retro --all (task retro ID reads one task and --all counts them all)."
                         if not args.id else
                         "task retro ID reads one task and --all counts the project: give one of them.")
    if args.minimum is not None and not args.all:
        raise ValueError("--min counts tasks across the project: use it with openguildkit task retro --all.")
    minimum = DEFAULT_MINIMUM if args.minimum is None else args.minimum
    if minimum < 1:
        raise ValueError("--min counts tasks: give a number of 1 or more.")
    if args.all:
        facts, ignored = _closed_facts(state)
        summary = project_summary(facts, minimum, profile, catalog, ignored)
        if args.json:
            print_json(summary)
        else:
            print("\n".join(render_project(summary)))
        return
    if task_path(state, args.id).is_file():
        task = read_task(state, args.id)
        if task["status"] not in DONE_STATUSES:
            # Said without judging the approval, which would ask Git: the retrospective starts no process.
            raise ValueError(state_refusal(task, "Only a closed task has a retrospective."))
        facts = facts_of_task(task)
    elif (state / DECISIONS_DIR / f"{args.id}.json").is_file():
        facts = _retro_record(root, state, args.id)
    else:
        read_task(state, args.id)  # says the task is unknown, with the closest ID and the command that lists them
    retro = task_retro(facts)
    if args.json:
        print_json(retro)
    else:
        print("\n".join(render_task(retro)))


def _show(args, root: Path, state: Path, profile: dict, catalog: dict, task: dict) -> None:
    """The task record as JSON, or only the open points its closing left."""
    print_json(_closing_points(task, args.id) if args.closing else task)


# What runs each action on an existing task. new, list and retro come before the task is read.
HANDLERS = {
    "show": _show, "questions": _questions, "brief": _brief, "template": _template, "blockers": _blockers,
    "clear": _resolve, "waive": _resolve, "checks": _checks, "verify": _outcome, "result": _outcome,
    "complete": _outcome, "alerts": _alerts, "runs": _runs, "export": _export, "deliberate": _deliberate,
    "respond": _respond, "challenge": _challenge, "route": _route, "consult": _consult, "review": _review,
    "pass": _pass, "submit": _pass, "progress": _progress, "decide": _decide, "revoke": _revoke,
    "decision-payload": _decision_payload, "authorize": _authorize, "handoff": _handoff,
    "diff-review": lambda args, root, state, profile, catalog, task: delivered_review.run(args, root, state, task),
}
# The actions that read an approval: an approval that no longer holds stops them, or is shown with show and checks.
READ_APPROVAL = ("show", "checks", "handoff", "export", "verify", "result", "complete", "diff-review")


def run(args, root: Path, state: Path, profile: dict, catalog: dict) -> int | None:
    """Run one task action. Every action refused in the task's status ends with the status and the command that runs
    next."""
    try:
        return _run(args, root, state, profile, catalog)
    except TaskStateError as error:
        task = read_task(state, args.id)
        raise ValueError(state_refusal(task, str(error), approval_problem(task, profile, catalog, root))) from None


def _run(args, root: Path, state: Path, profile: dict, catalog: dict) -> int | None:
    action = args.action
    if action == "new":
        return _new(args, root, state, profile, catalog)
    if action == "list":
        return _list(args, root, state, profile, catalog)
    if action == "retro":
        return _retro(args, root, state, profile, catalog)
    record = state / DECISIONS_DIR / f"{args.id}.json"
    if not task_path(state, args.id).is_file() and record.is_file():
        if action == "show":
            _show_exported(root, state, profile, catalog, args.id, args.closing)
            return None
        raise ValueError(f"Task {args.id} exists here only as the exported record {record.relative_to(root).as_posix()}, "
                         f"a teammate's task or an earlier one: read it with openguildkit task show {args.id} or "
                         "openguildkit task list --decisions.")
    task = read_task(state, args.id)
    if action in READ_APPROVAL:
        # One answer for every reader: an error stops the action; a note (a completed task's history) is shown.
        problem = approval_problem(task, profile, catalog, root)
        if problem and problem["severity"] == "error" and action not in ("show", "checks"):
            raise ValueError(problem["message"])
        # An approval verified by the signers of the revision it was signed at holds: every reader says so.
        if problem and (action in ("show", "checks", "export") or problem["kind"] == EARLIER_SIGNERS):
            print(f"OpenGuildKit: {problem['message']}", file=sys.stderr)
        elif problem:
            raise ValueError(problem["message"])
    handler = _result_template if action == "result" and args.template else HANDLERS[action]
    return handler(args, root, state, profile, catalog, task)
