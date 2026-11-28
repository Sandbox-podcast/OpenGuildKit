"""The task actions after the approval: checks, verify, result, complete, runs, export, handoff and diff-review, with
the declarations that a check command cannot run.

Entry: run_checks, run_outcome, run_export, run_handoff, run_diff_review
Tests: tests/test_closing_points.py, tests/test_evidence_fingerprints.py, tests/test_results.py
"""

import sys
from pathlib import Path

from . import delivered_review, short_lane
from .alerts import blocking_alerts, load_register
from .approval_check import DONE_STATUSES
from .decisions import DECISIONS_DIR, git_revision
from .doc_links import doc_link
from .guard_export import changes_since_approval, export_decision, export_withdrawal, untracked_files
from .handoff import handoff
from .lock import require_instructions
from .project import STATE_DIR
from .relevance import changed_files, pack_relevance
from .result_form import SUPPLY, SUPPLY_OR_NOT_APPLICABLE, result_template
from .results import (
    answers_to_report,
    chaosfolk_checks,
    compare_runs,
    completion_problems,
    criteria_summary,
    decision_changes,
    decision_revision_message,
    declared_cannot_run,
    expected_checks,
    keep_declarations,
    missing_scenarios,
    outcomes,
    run_command_checks,
    set_aside_rules,
)
from .sensitive import redact_data
from .storage import print_json, project_lock, read_json, write_json
from .task_files import read_task, task_path
from .tasks import waiting_for, waits_line, write_task
from .tasks_blockers import verification_blocker_problems
from .tasks_closing import SENSITIVE_GROUP, complete_task, defer_evidence, points_left_open, record_result
from .tasks_command import TaskCommand
from .tasks_consult_cli import input_file, warn_inputs
from .tasks_list_cli import unshared_evidence
from .tasks_record import timestamp
from .tasks_review import cited_evidence
from .terminal import interactive, typed
from .wording import plural
from .workflow import TaskStateError, is_decision_task


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
            print(f"  {name} ({plural(count, 'check')}): {reason}")


def _lane_problems(root: Path, task: dict, profile: dict) -> list[str]:
    """What keeps a short-lane task from being done: the profile no longer allows its paths, or a file changed since
    its approval is outside them. A project outside Git has no list of changed files to compare."""
    problem = short_lane.lane_problem(task, profile)
    if problem or not short_lane.is_light(task):
        return [problem] if problem else []
    outside = short_lane.files_outside(task["paths"], profile["light_paths"], changes_since_approval(root, task) or [])
    return [short_lane.outside_message(task["id"], task["paths"], profile["light_paths"], outside, "this project")] \
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
        raise ValueError("Name the person who hands the evidence to a follow-up task: --by INITIALS.")
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
            f"{plural(len(set_aside), 'data protection, security or AI rule')} "
            f"{'is' if len(set_aside) == 1 else 'are'} declared not applicable:\n- "
            + "\n- ".join(set_aside) + f"\nA person confirms each: openguildkit task complete {args.id} --by INITIALS, "
            "at a terminal.")
    if args.by:
        refusal = "Closing a task with --by needs the person at an interactive terminal."
        if not interactive():
            raise ValueError(refusal)
        for group in closed["result"]["closing"]["open_points"]:
            print(f"{group['group']}:", file=sys.stderr)
            for point in group["points"]:
                print(f"  - {point}", file=sys.stderr)
        if set_aside:
            print("Data protection, security or AI rules declared not applicable, which you confirm:", file=sys.stderr)
            for line in set_aside:
                print(f"  - {line}", file=sys.stderr)
        typed(args.id, f"Type {args.id} to close it as {closed['status']}: ", refusal=refusal,
              cancelled="Closing cancelled.")
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
        print(f"{plural(count, 'open point')}, listed above and kept for later: openguildkit task show {task['id']} --closing.")
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
DECLARATION_REFUSAL = "Declaring whether a command can run needs the person at an interactive terminal."


def _declaration_checks(args, task: dict, profile: dict, check_id: str) -> dict:
    """The task's check commands; a declaration names one of them and the person, at a terminal."""
    commands = {check["id"]: check["command"] for check in expected_checks(task, profile) if check["kind"] == "command"}
    if check_id not in commands:
        raise ValueError(f"{check_id} is not a check command of the task: {', '.join(commands) or 'none'}.")
    if not (args.by or "").strip():
        raise ValueError("Name the person with --by INITIALS.")
    if not interactive():
        raise ValueError(DECLARATION_REFUSAL)
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
    typed(args.id, f"Type {args.id} to record that {args.cannot_run} (`{commands[args.cannot_run]}`) cannot run "
          "here: ", refusal=DECLARATION_REFUSAL, cancelled="Cancelled.")
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


def _no_check_command() -> str:
    return ("No project check command is configured: task verify ran no test. To have it run one: openguildkit "
            f"profile add check \"COMMAND\" --by INITIALS --reason WHY ({doc_link('docs/workflow.md', 'project-checks')}); "
            "the change applies to tasks consulted after it.")


def _print_remaining(args, task: dict, profile: dict, relevance: dict, root: Path, state: Path,
                     changed: list[str], held: list[str]) -> int:
    """Every point that keeps the task from being done, one per line, then their count.

    The exit status is 1 when task verify finds a mandatory check command failed, so a script or a CI
    job can tell; points that only need answers keep it at 0.
    """
    if args.action == "verify" and not task["consultation"]["scope"].get("checks") and not is_decision_task(task):
        print(_no_check_command())
    problems = (completion_problems(task, profile, relevance, changed=changed, root=root)
                + blocking_alerts(load_register(state), task) + verification_blocker_problems(task, profile, root)
                + _lane_problems(root, task, profile))
    # Before any report, task verify counts the answers the result file gives rather than one line per rule.
    folded = set(answers_to_report(task, profile, relevance)) if args.action == "verify" else set()
    if folded:
        print(f"- {plural(len(folded), 'rule')} and named evidence to report: openguildkit task result {args.id} --template "
              "lists them with the answers each accepts.")
    for problem in problems:
        if problem.split(" ", 1)[0] not in folded:
            print(f"- {problem}")
    if problems:
        print(f"{plural(len(problems), 'point')} before the task can be done.")
    elif held:
        print("Nothing else is missing, but some answers were not recorded (above): fix them, or run task complete "
              "with the answers already recorded.")
    elif (any(group["group"] == SENSITIVE_GROUP for group in points_left_open(task, profile, relevance))
          or set_aside_rules(task, profile, relevance)):
        # task complete refuses these without the person: say so now rather than at the closing.
        print(f"Ready to close with the person at a terminal: a data protection, security or AI point stays open, "
              f"so they run openguildkit task complete {args.id} --by INITIALS.")
    else:
        print("Ready: run task complete.")
    failed = [item for item in task["result"]["checks"]
              if item["check"].startswith("command:") and item["status"] == "failed"]
    return 1 if args.action == "verify" and failed else 0


def run_checks(command: TaskCommand) -> None:
    """The checks the approved task must report, and their outcomes so far."""
    args, root, profile, catalog, task = command.args, command.root, command.profile, command.catalog, command.task
    if task["status"] not in ("approved", *DONE_STATUSES):
        raise TaskStateError("Checks belong to an approved task.")
    relevance = _relevance(root, task, profile, catalog, args.all)
    checks = expected_checks(task, profile, relevance)
    reported = outcomes(task, profile, relevance)
    if args.json:
        print_json([{**check, "result": reported.get(check["id"])} for check in checks])
    else:
        _print_checks(checks, reported, task["id"])


def run_result_template(command: TaskCommand) -> None:
    """A result file to fill in."""
    args, root, profile, catalog, task = command.args, command.root, command.profile, command.catalog, command.task
    if task["status"] != "approved":
        raise TaskStateError("Results belong to an approved task that is not done yet.")
    relevance = _relevance(root, task, profile, catalog, args.all)
    changed = decision_changes(root, task)
    print_json(result_template(task, profile, relevance, changed=changed))
    if changed:
        print(decision_revision_message(changed), file=sys.stderr)


def _verify_payload(args, root: Path, state: Path, task: dict, profile: dict, relevance: dict,
                    decision: bool) -> tuple[dict, list[str]]:
    """What task verify records: the revision and the checks run, declared cannot-run, withdrawn or imported from
    a ChaosFolk replay; and the notes on the declarations kept."""
    payload: dict = {}
    notes: list[str] = []
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
    return payload, notes


def _print_export_next(state: Path, task_id: str) -> None:
    """After task complete: commit the work, then export the decision record again."""
    exported = (state / DECISIONS_DIR / f"{task_id}.json").is_file()
    print(f"OpenGuildKit: commit the work (git add, git commit), then "
          f"{'export the decision record again' if exported else 'export the decision record'} so it says the "
          f"task is completed, and commit it: openguildkit task export {task_id}. The record lists the files Git "
          "tracks, so a new file left out of Git is in no record. guard --ci accepts it with the work, or in a "
          "pull request of its own once the approval's record is merged: the same approval, with its completion "
          "added.", file=sys.stderr)


def _print_recorded(result: dict, profile: dict, held: list, decision: bool, task_id: str) -> None:
    """Print what the result recorded: the answers held back, each check and its status, the missing replays, the
    checks waiting for someone, the criteria and the warnings."""
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
              f"{item['why']}). Ask them for it, or hand it to a follow-up task: task complete {task_id} "
              f"--defer {item['check']}=FOLLOW-UP --by INITIALS.")
    if criteria_summary(result["result"]):
        print(criteria_summary(result["result"]))
    for warning in result["result"].get("warnings", []):
        print(f"Warning: {warning}", file=sys.stderr)


def run_outcome(command: TaskCommand) -> int | None:
    """Run the checks, record a result file, or close the task; then what is left before it is done."""
    args, root, state, profile, catalog, task = (command.args, command.root, command.state, command.profile,
                                                 command.catalog, command.task)
    action = args.action
    if task["status"] != "approved":
        raise TaskStateError("Run checks for an approved task that is not done yet." if action == "verify"
                             else "Results belong to an approved task that is not done yet.")
    decision = is_decision_task(task)
    changed = decision_changes(root, task)
    relevance = _relevance(root, task, profile, catalog, getattr(args, "all", False))
    notes: list[str] = []
    if action == "verify":
        payload, notes = _verify_payload(args, root, state, task, profile, relevance, decision)
    elif action == "complete":
        closing = _closing(args, state, task, profile, relevance, root, changed)
    with project_lock(state):
        current_task = read_task(state, args.id)
        if current_task != task:
            raise ValueError("The task changed meanwhile. Retry.")
        if action == "verify":
            result = record_result(current_task, profile, payload, "verify", relevance, root)
        elif action == "result":
            with input_file(args.file):
                reported = read_json(args.file)
                result = record_result(current_task, profile, reported, "report", relevance, root, changed=changed)
            warn_inputs(reported, redact_data(reported), "task result")
        else:
            result = closing
        held = result.pop("_held", [])
        write_task(task_path(state, args.id), result)
    for warning in unshared_evidence(root, {args.id: cited_evidence(result)}):
        print(f"OpenGuildKit: {warning}", file=sys.stderr)
    if action == "complete":
        _print_closing(result, listed=bool(args.by))
        _print_export_next(state, args.id)
        return None
    for line in notes:
        print(line)
    _print_recorded(result, profile, held, decision, args.id)
    return _print_remaining(args, result, profile, relevance, root, state, changed, held)


def run_runs(command: TaskCommand) -> None:
    """The scenarios whose outcome changed between the last two ChaosFolk replays."""
    args, task = command.args, command.task
    comparison = compare_runs(task)
    if comparison is None:
        raise TaskStateError("The task has fewer than two ChaosFolk replays to compare: task verify --chaosfolk "
                             "records them on an approved task.")
    if args.json:
        print_json(comparison)
    else:
        for name, (before, after) in comparison["changed"].items():
            print(f"{name}: {before or 'absent'} -> {after or 'absent'}")
        print(f"{plural(len(comparison['unchanged']), 'scenario')} unchanged")


def run_export(command: TaskCommand) -> None:
    """Write the shareable decision record, or the withdrawal of its approval into it."""
    args, root, state, profile, task = command.args, command.root, command.state, command.profile, command.task
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
        print(f"OpenGuildKit: {plural(len(untracked), 'new file')} Git does not track yet "
              f"{'is' if len(untracked) == 1 else 'are'} not in the record: {shown}. "
              "Add them with git add (or commit the work) and export again, or guard --ci finds them in no record.",
              file=sys.stderr)
    if "completed_at" not in task:
        print(f"OpenGuildKit: task {args.id} is not completed yet and the record says so. It lists the files Git "
              "tracks that changed since the approval, which guard --ci compares with the pull request: export it "
              "again once the work is committed, and after task complete, and commit it.", file=sys.stderr)
    print(f"Next: git add {STATE_DIR}/decisions, then commit the record with the work in the pull request.", file=sys.stderr)


def run_handoff(command: TaskCommand) -> None:
    """The approved implementation handoff, or the decision record of a decision task."""
    args, root, state, profile, catalog, task = (command.args, command.root, command.state, command.profile,
                                                 command.catalog, command.task)
    evidence, checks = [], None
    if task.get("status") in ("approved", *DONE_STATUSES):
        checks = expected_checks(task, profile, _relevance(root, task, profile, catalog))
    if task.get("status") == "approved":
        evidence = [check for check in checks or [] if check["concerned"] and check["kind"] == "evidence"]
    output = handoff(task, evidence, checks, root)
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


DIFF_REVIEW_HELP = "Have each board review the diff the task delivered, then record its findings."


def add_diff_review_parser(actions) -> None:
    """The diff-review action of the task command."""
    command = actions.add_parser("diff-review", help=DIFF_REVIEW_HELP)
    command.add_argument("id", help="Task ID.")
    shown = command.add_mutually_exclusive_group()
    shown.add_argument("--board", help="Print this board's brief: the diff, what the decision asked and its lens.")
    shown.add_argument("--submit", type=Path, metavar="FILE", help="Record one board's findings from a JSON file.")
    command.add_argument("--json", action="store_true", help="Print the brief or the review status as JSON.")


def run_diff_review(command: TaskCommand) -> None:
    """Print the review status or one board's brief, or record one board's findings."""
    args, root, state, task = command.args, command.root, command.state, command.task
    change = delivered_review.delivered_change(root, task)
    if args.submit:
        payload = read_json(args.submit)
        with project_lock(state):
            if read_task(state, args.id) != task:
                raise ValueError("The task changed meanwhile. Retry.")
            try:
                updated, board = delivered_review.record_findings(task, change, payload)
            except ValueError as error:
                raise ValueError(f"{args.submit.as_posix()}: {error}") from None
            write_json(task_path(state, args.id), updated)
        findings = updated["delivered_review"]["boards"][board]["findings"]
        print(f"{board}: {plural(len(findings), 'finding')} recorded.")
        print(delivered_review.status_line(updated))
        return
    if args.board:
        brief = delivered_review.board_brief(task, change, args.board)
        print_json(brief) if args.json else print(delivered_review.render_brief(brief))
        return
    delivered_review.print_overview(args, task, change)
