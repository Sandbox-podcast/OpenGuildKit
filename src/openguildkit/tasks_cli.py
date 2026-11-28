"""The `task` command: its parser, `task new`, and the table that runs each action, with a refusal that names the
command to run next.

add_parser adds the task actions to the CLI's parser and run runs one of them, as tools_cli and the other command
modules do. Each action reads the task, checks what its status allows, and writes the record under the project
lock; what only a person may do (approve, withdraw an approval, clear, waive, close over open points) waits for
them at a terminal. The actions live in tasks_consult_cli, tasks_decide_cli, tasks_close_cli and tasks_list_cli;
this module keeps the parser, task new and the table that runs the others.

Entry: add_parser, run
Tests: tests/e2e/test_short_lane.py, tests/e2e/test_task_retro.py, tests/test_audit_log.py,
tests/test_before_delivered_review.py, tests/test_brain_knowledge.py, tests/test_delivered_review.py,
tests/test_evidence_fingerprints.py, tests/test_next_steps.py, tests/test_performance.py, tests/test_requester.py,
tests/test_short_lane.py, tests/test_task_dependencies.py, tests/test_task_index.py, tests/test_unhooked_hosts.py
"""

import contextlib
import sys
from pathlib import Path

from . import requester, short_lane
from .alerts import STATUS_CHOICES as ALERT_STATUSES
from .approval_check import approval_problem
from .cli_surface import add_by
from .command import Command
from .decisions import DECISIONS_DIR, EARLIER_SIGNERS
from .errors import OgkError
from .lock import require_instructions
from .project import WORK_DIR
from .records import Catalog, Profile
from .retro import DEFAULT_MINIMUM
from .sensitive import redact_credentials
from .storage import print_json, project_lock
from .task_files import read_task, task_path
from .tasks import create_task, waiting_for, waits_line
from .tasks_close_cli import (
    add_diff_review_parser,
    run_checks,
    run_diff_review,
    run_export,
    run_handoff,
    run_outcome,
    run_result_template,
    run_runs,
)
from .tasks_closing import ACTIONS
from .tasks_command import TaskCommand
from .tasks_consult_cli import (
    run_brief,
    run_challenge,
    run_consult,
    run_deliberate,
    run_pass,
    run_progress,
    run_questions,
    run_respond,
    run_review,
    run_route,
    run_template,
    warn_inputs,
)
from .tasks_decide_cli import (
    run_alerts,
    run_authorize,
    run_blockers,
    run_decide,
    run_decision_payload,
    run_resolve,
    run_revoke,
)
from .tasks_list_cli import run_list, run_retro, run_show, show_exported
from .tasks_record import STATUSES
from .tasks_status import state_refusal
from .workflow import TaskStateError

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
    "show": "Print the task record as JSON, or a short summary with --summary.",
    "checks": "List the checks the approved task must report.",
    "verify": "Run the project's check commands and the rules' machine checks, and record their results.",
    "result": "Record the delivered revision, criteria and check outcomes.",
    "complete": "Close the task: done, or done-with-reservations when points stay open.",
    "runs": "Compare the last two ChaosFolk replays of the task.",
    "alerts": "Shortcut of the alerts commands for one task: import (--import), review (--set) or link (--link) alerts.",
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
    new.add_argument("--requested-by", metavar="NAME",
                     help="The person who asked for the work; required when the profile separates the requester from "
                          "the approver, who cannot then be the same person.")
    new.add_argument("--lane", choices=(short_lane.LANE,),
                     help="Open the task in the short lane, which a person turned on in the profile: one board, no "
                          "questionnaire, limited to --paths.")
    new.add_argument("--paths", nargs="+", metavar="GLOB",
                     help="With --lane light: the folders or files the task may change, inside the profile's "
                          "light_paths. Write the brief first.")
    listing = actions.add_parser("list", help="List the project's tasks with their status and next open point.")
    listing.add_argument("--status", choices=list(STATUSES), help="Only tasks in this status.")
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
                                             "aside, boards that said nothing, reservations, waived blockers. "
                                             "It writes nothing.")
    retro.add_argument("id", nargs="?", help="Task ID of a closed task, or none with --all.")
    retro.add_argument("--all", action="store_true",
                       help="Count what comes back in the project's closed tasks, with the profile command a person "
                            "could type for some of it.")
    retro.add_argument("--min", type=int, dest="minimum", metavar="N",
                       help=f"With --all, in how many closed tasks a finding must come back (default {DEFAULT_MINIMUM}).")
    retro.add_argument("--json", action="store_true", help="Print the retrospective as JSON.")
    retro.add_argument("--draft-rules", type=Path, metavar="FOLDER",
                       help="With --all, also write a draft project rule pack in FOLDER (inside the project, outside "
                            ".openguildkit/), one rule to write for each reservation that comes back; not active until "
                            "a person reviews it and adds it to the project catalog.")
    for action, description in ACTION_HELP.items():
        command = actions.add_parser(action, help=description)
        command.add_argument("id", help="Task ID.")
        for add_options in ACTION_OPTIONS.get(action, ()):
            add_options(command)
    add_diff_review_parser(actions)


def _json_option(text: str):
    return lambda command: command.add_argument("--json", action="store_true", help=text)


def _answers_option(command) -> None:
    command.add_argument("--answers", type=Path, help="Read task answers from a JSON file.")


def _follow_ups_option(command) -> None:
    command.add_argument("--follow-ups", action="store_true",
                         help="With --answers, print only follow_ups and open_points, not the questionnaire again.")


def _show_options(command) -> None:
    shown = command.add_mutually_exclusive_group()
    shown.add_argument("--closing", action="store_true",
                       help="Print only the open points the closing left, with who closed the task.")
    shown.add_argument("--summary", action="store_true",
                       help="Print a screen instead of the whole record: status, decision, boards, result, next step.")
    command.add_argument("--json", action="store_true",
                         help="Print the record as JSON, which is what show prints without --summary; write it in "
                              "scripts, so that they keep working if the summary becomes the plain form.")


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
    add_by(command, required=True)


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
    add_by(command)
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
    add_by(command)
    command.add_argument("--reason", help="Why the command cannot run here.")


def _alerts_options(command) -> None:
    command.add_argument("--import", dest="import_file", type=Path, metavar="REPORT",
                         help="npm audit, pip-audit, OSV-Scanner or Dependabot JSON report.")
    command.add_argument("--set", dest="alert_id", metavar="ALERT", help="Alert ID to review.")
    command.add_argument("--link", metavar="ALERT", help="Link an alert of the register to the task.")
    command.add_argument("--status", choices=ALERT_STATUSES, help="Review status for --set.")
    add_by(command)
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
    add_by(command, required=True)
    command.add_argument("--reason", required=True, help="Reason for the decision.")


def _decide_options(command) -> None:
    outcome = command.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--approve", action="store_true", help="Approve the reviewed scope in a terminal.")
    outcome.add_argument("--request-changes", action="store_true", help="Send the task back to consultation.")
    _decision_reason_options(command)
    command.add_argument("--signature", type=Path, help="SSH signature of task decision-payload (signed projects).")
    command.add_argument("--signer", help="Principal in the allowed signers file (signed projects).")
    command.add_argument("--signed-at", metavar="TIME", help="The signed_at line of the payload (signed projects), "
                                                             "UTC as YYYY-MM-DDTHH:MM:SSZ.")


def _revoke_options(command) -> None:
    add_by(command, required=True)
    command.add_argument("--reason", required=True, help="Why the approval is withdrawn.")


def _payload_options(command) -> None:
    _decision_reason_options(command)
    command.add_argument("--output", type=Path, help="Write the exact bytes to sign to this file.")
    command.add_argument("--signed-at", nargs="?", const="now", metavar="TIME",
                         help="Add the time you sign at (now, or UTC as YYYY-MM-DDTHH:MM:SSZ): once recorded, the "
                              "approval is verified at that time, so a key or certificate that expires later voids "
                              "nothing. Pass the same value to task decide.")


# The options of each action, in the order its help lists them.
ACTION_OPTIONS = {
    "questions": (_answers_option, _follow_ups_option),
    "route": (_answers_option, _board_change_options, _json_option("Print the selection as JSON.")),
    "consult": (_answers_option, _reuse_answers_option, _revised_brief_options, _board_change_options),
    "show": (_show_options,),
    "review": (_review_source_options,),
    "pass": (_pass_options, _mode_option),
    "brief": (_brief_options,),
    "submit": (_mode_option, _file_option("The board's filled-in JSON entry.")),
    "clear": (_blocker_options, _clear_options),
    "waive": (_blocker_options, _waive_options),
    "blockers": (_json_option("Print the blockers as JSON."),),
    "export": (_export_options, _json_option("Print the record written as JSON.")),
    "checks": (_json_option("Print the checks as JSON."), _all_rules_option),
    "result": (_all_rules_option, _result_source_options),
    "complete": (_complete_options,),
    "verify": (_verify_options, _json_option("Print the recorded result as JSON; the text goes to standard error.")),
    "alerts": (_alerts_options,),
    "runs": (_json_option("Print the comparison as JSON."),),
    "respond": (_file_option("Completed deliberation JSON."),),
    "progress": (_json_option("Print the progress as JSON."),),
    "authorize": (_authorize_options,),
    "decide": (_decide_options, _json_option("Print the decision recorded as JSON.")),
    "revoke": (_revoke_options,),
    "decision-payload": (_payload_options,),
}


def _new(args, root: Path, state: Path, profile: Profile, catalog: Catalog) -> None:
    """Create a task draft and print its ID; the next step goes to the agent on standard error."""
    if (args.brief is None) == (args.file is None):
        raise OgkError("OGK-TASK-007", "Supply either a task brief or --file PATH.")
    brief = args.file.read_text(encoding="utf-8-sig") if args.file else args.brief
    require_instructions(args, root, state, profile, catalog)
    lane = short_lane.declare(args.lane, args.paths, profile)
    requested_by = requester.declared(args.requested_by, profile, root)
    with project_lock(state):
        record = state / DECISIONS_DIR / f"{args.id}.json" if args.id else None
        if record is not None and record.is_file() and not task_path(state, args.id).is_file():
            raise OgkError("OGK-TASK-008", f"Task ID {args.id} is already used by the exported decision "
                           f"{record.relative_to(root).as_posix()}, a teammate's task or an earlier one: read it "
                           f"with openguildkit task show {args.id}, and choose another ID.")
        task_id = create_task(state, brief, args.id, args.follows, lane, args.after, requested_by)
        statuses = {name: read_task(state, name)["status"] for name in dict.fromkeys(args.after or [])}
    print(task_id)
    if statuses:
        waits = waiting_for({"after": list(statuses)}, statuses)
        print(f"Waits for {waits_line(waits)}." if waits else f"Its dependencies are done: {', '.join(statuses)}.",
              file=sys.stderr)
    warn_inputs(brief.strip(), redact_credentials(brief.strip()), "task brief")
    # Standard output keeps only the ID, which scripts read; the next steps go to the agent on stderr, in the README's
    # order, with the folder the working files go in.
    if lane:
        print(short_lane.next_line(task_id, lane["paths"]), file=sys.stderr)
        return
    print(f"Next: read the questions with openguildkit task questions {task_id}; save the answers in {WORK_DIR}/ "
          f"(Git ignores it), get the follow-up questions they call for with openguildkit task questions {task_id} "
          f"--answers FILE --follow-ups, preview the boards with openguildkit task route {task_id} --answers FILE, "
          f"then consult the boards with openguildkit task consult {task_id} --answers FILE.", file=sys.stderr)


# What runs each action on an existing task. new, list and retro come before the task is read.
# One function per action, named after it (#530): several actions share the body of run_resolve, run_outcome or
# run_pass, which reads args.action.
def run_clear(command: TaskCommand) -> None:
    run_resolve(command)


def run_waive(command: TaskCommand) -> None:
    run_resolve(command)


def run_verify(command: TaskCommand) -> int | None:
    """task verify; with --json, its text goes to standard error and the result it recorded to standard output."""
    if not command.args.json:
        return run_outcome(command)
    with contextlib.redirect_stdout(sys.stderr):
        code = run_outcome(command)
    task = read_task(command.state, command.args.id)
    print_json({"task": task["id"], "status": task["status"], "result": task["result"]})
    return code


def run_result(command: TaskCommand) -> int | None:
    return run_outcome(command)


def run_complete(command: TaskCommand) -> int | None:
    return run_outcome(command)


def run_submit(command: TaskCommand) -> None:
    run_pass(command)


HANDLERS = {
    "show": run_show, "questions": run_questions, "brief": run_brief, "template": run_template,
    "blockers": run_blockers, "clear": run_clear, "waive": run_waive, "checks": run_checks, "verify": run_verify,
    "result": run_result, "complete": run_complete, "alerts": run_alerts, "runs": run_runs, "export": run_export,
    "deliberate": run_deliberate, "respond": run_respond, "challenge": run_challenge, "route": run_route,
    "consult": run_consult, "review": run_review, "pass": run_pass, "submit": run_submit, "progress": run_progress,
    "decide": run_decide, "revoke": run_revoke, "decision-payload": run_decision_payload, "authorize": run_authorize,
    "handoff": run_handoff,
    "diff-review": run_diff_review,
}
# The actions that read an approval: an approval that no longer holds stops them, or is shown with show and checks.
READ_APPROVAL = ("show", "checks", "handoff", "export", "verify", "result", "complete", "diff-review")


def run(command: Command) -> int | None:
    """Run one task action. Every action refused in the task's status ends with the status and the command that runs
    next."""
    args, root, state, profile, catalog = command.args, command.root, command.state, command.profile, command.catalog
    try:
        return _run(args, root, state, profile, catalog)
    except TaskStateError as error:
        task = read_task(state, args.id)
        raise OgkError("OGK-TASK-009", state_refusal(task, str(error), approval_problem(task, profile, catalog, root))) from None


def _run(args, root: Path, state: Path, profile: Profile, catalog: Catalog) -> int | None:
    action = args.action
    if action == "new":
        _new(args, root, state, profile, catalog)
        return None
    if action == "list":
        run_list(args, root, state, profile, catalog)
        return None
    if action == "retro":
        run_retro(args, root, state, profile, catalog)
        return None
    record = state / DECISIONS_DIR / f"{args.id}.json"
    if not task_path(state, args.id).is_file() and record.is_file():
        if action == "show":
            if args.summary:
                raise OgkError("OGK-TASK-010", f"Task {args.id} exists here only as the exported record, which has "
                                               f"no summary: run openguildkit task show {args.id}.")
            show_exported(root, state, profile, catalog, args.id, args.closing)
            return None
        raise OgkError("OGK-TASK-011", f"Task {args.id} exists here only as the exported record "
                                       f"{record.relative_to(root).as_posix()}, a teammate's task or an earlier one: "
                                       f"read it with openguildkit task show {args.id} or openguildkit task list "
                                       "--decisions.")
    task = read_task(state, args.id)
    if action in READ_APPROVAL:
        # One answer for every reader: an error stops the action; a note (a completed task's history) is shown.
        problem = approval_problem(task, profile, catalog, root)
        # An approval verified by the signers of the revision it was signed at holds: every reader says so.
        shown = problem and (action in ("show", "checks", "export") or problem["kind"] == EARLIER_SIGNERS)
        if problem and (problem["severity"] == "error" and action not in ("show", "checks") or not shown):
            raise OgkError("OGK-TASK-012", problem["message"])
        if problem:
            print(f"OpenGuildKit: {problem['message']}", file=sys.stderr)
    handler = run_result_template if action == "result" and args.template else HANDLERS[action]
    return handler(TaskCommand(args, root, state, profile, catalog, task))
