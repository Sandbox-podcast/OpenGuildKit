"""The task actions from the questions to the boards' review: questions, route, consult, brief, template, pass,
submit, progress, review, deliberate, respond and challenge, with the input files they read."""

import sys
from contextlib import contextmanager
from pathlib import Path

from . import short_lane
from .alerts import load_register
from .board_brief import board_brief, pack_rules
from .brains import BriefKnowledge, consultation_context
from .catalog import board_replacements
from .hosts import host_controls
from .lock import project_catalog, require_instructions
from .market import load_dossier
from .market import scope_entry as market_scope_entry
from .project import load_profile
from .project_rules import task_scope_profile
from .prompts import prompt_questions
from .questionnaire import concerns_question, open_points, require_concerns, task_questions, validate_answers
from .routing import select_boards, trigger_matches
from .sensitive import input_warnings, redact_data
from .shell import shell_word
from .storage import print_json, project_lock, read_json
from .tasks import last_approval, read_task, task_path, write_task
from .tasks_closing import record_deliberation
from .tasks_command import TaskCommand
from .tasks_record import board_brief_problem
from .tasks_review import (
    assemble_review,
    decision_text,
    earlier_sequential_pass,
    pass_progress,
    previous_round_line,
    record_consultation,
    record_review,
    start_pass,
    submit_pass,
)
from .tasks_status import passes_left
from .terminal import interactive
from .tool_connections import connected_tools
from .tool_registry import load_tools
from .tools import match_tools, tool_evidence_warnings
from .workflow import RESOLUTION_RULE, TaskStateError, challenge_report, deliberation_request, nothing_to_deliberate


@contextmanager
def input_file(path: Path):
    """Name the file a refusal comes from, so the person knows which file to correct. A refusal of the task's status
    is not the file's: it goes on as it is."""
    try:
        yield
    except TaskStateError:
        raise
    except ValueError as error:
        raise ValueError(f"{path.as_posix()}: {error}") from error


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


def warn_inputs(original: object, recorded: object, label: str) -> None:
    for warning in input_warnings(original, recorded, label):
        print(warning, file=sys.stderr)


def run_questions(command: TaskCommand) -> None:
    """The questionnaire as JSON, with the follow-ups and open points the answers leave."""
    args, task = command.args, command.task
    if short_lane.is_light(task):
        raise ValueError(short_lane.no_questions_message(args.id))
    # One shape with or without answers: the follow-ups carry their prompt, so they can be asked as they are.
    if args.answers is None:
        answers, validated, open_list = {}, None, []
    else:
        answers = read_json(args.answers)
        with input_file(args.answers):
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


def run_brief(command: TaskCommand) -> None:
    """The saved consultation, a board's pass, the whole scope or the rules of one pack."""
    args, task = command.args, command.task
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


def run_template(command: TaskCommand) -> None:
    """The review template as JSON."""
    task = command.task
    print_json(_read_consultation(task)["review_template"])


def run_deliberate(command: TaskCommand) -> None:
    """The objections between boards and the response template; without objection, that there is nothing to answer."""
    task = command.task
    request = deliberation_request(task)
    print_json(request)
    if not request["objections"]:
        print(f"OpenGuildKit: {nothing_to_deliberate(task['id'])}", file=sys.stderr)


def run_respond(command: TaskCommand) -> None:
    """Record the boards' answers to each other's objections."""
    args, state, task = command.args, command.state, command.task
    payload = read_json(args.file)
    with project_lock(state):
        current_task = read_task(state, args.id)
        if current_task != task:
            raise ValueError("The task changed while you were deliberating. Run task deliberate again.")
        with input_file(args.file):
            result = record_deliberation(current_task, payload)
        write_task(task_path(state, args.id), result)
    deliberation = result["deliberation"]
    print(f"{len(deliberation['agreed'])} resolved, {len(deliberation['open'])} open")
    print(RESOLUTION_RULE, file=sys.stderr)


def run_challenge(command: TaskCommand) -> None:
    """The decision brief and each board's challenge."""
    root, state, profile, task = command.root, command.state, command.profile, command.task
    recall = previous_round_line(task)
    if recall:
        print(recall)
    lines = (decision_text(task, profile, last_approval(state), load_register(state))
             if "review" in task else None)
    print(challenge_report(task, lines, root), end="")


def run_route(command: TaskCommand) -> None:
    """Preview the boards a consultation would select, and why."""
    args, state, profile, catalog, task = command.args, command.state, command.profile, command.catalog, command.task
    if short_lane.is_light(task):
        raise ValueError(short_lane.no_route_message(args.id))
    if args.answers is None and "answers" not in task:
        raise ValueError(f"Pass the answers: openguildkit task route {args.id} --answers FILE previews the boards "
                         f"before openguildkit task consult {args.id} --answers FILE records them.")
    if args.answers:
        with input_file(args.answers):
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


def run_consult(command: TaskCommand) -> None:
    """Record the answers and prepare the consultation of the boards, under the project lock."""
    args, root, state, profile, catalog, task = (command.args, command.root, command.state, command.profile,
                                                 command.catalog, command.task)
    # Only a consultation reads the reference library and the Storybook record: the other commands start without.
    from .alerts_cli import consultation_task
    from .references import load_references, with_pattern_references
    from .storybook import scope_entry as storybook_scope_entry

    if args.brief_file is not None:
        with input_file(args.brief_file):
            args.revised_brief = args.brief_file.read_text(encoding="utf-8-sig")
    if short_lane.is_light(task):
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
        with input_file(args.answers):
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
        registry = load_tools(state / "catalog" / "tools")
        knowledge = BriefKnowledge(catalog, families, active, context,
                                   lambda board_id: connected_tools(state, registry, board_id))
        result = record_consultation(consultation_task(state, current_task), answers, profile, catalog,
                                     _selection(args), controls, market, storybook_scope_entry(state), knowledge,
                                     connected_tools(state, registry), root,
                                     args.revised_brief)
        result.pop("dependency_alerts")
        if "dependency_alerts" in current_task:
            result["dependency_alerts"] = current_task["dependency_alerts"]
        write_task(task_path(state, args.id), result)
    if args.revised_brief is not None:
        warn_inputs(args.revised_brief.strip(), result["brief"], "revised brief")
    warn_inputs(answers, redact_data(answers), "task answers")
    print(result["consultation"]["markdown"])
    for line in board_replacements(catalog):
        print(f"OpenGuildKit: {line}", file=sys.stderr)


def _light_answers(args, task: dict, profile: dict) -> dict:
    """The answers of a short-lane task: the lane's own. The lane convenes one board and takes no answers of the
    requester's, so those options are refused, and a lane the profile no longer allows stops the consultation."""
    used = [option for option, given in (("--answers", args.answers), ("--add", args.add), ("--remove", args.remove)) if given]
    if used:
        raise ValueError(short_lane.options_message(args.id, used))
    problem = short_lane.lane_problem(task, profile)
    if problem:
        raise ValueError(problem)
    return short_lane.default_answers(task)


def _reused_answers(args, task: dict) -> dict:
    """The task's recorded answers for task consult --reuse-answers, those of --answers FILE replacing them, and
    concerns asked at a terminal when neither has it (a task consulted before the question was required). Without a
    terminal a missing concerns is answered unsure, which keeps every topic's rules open, and the command says so."""
    if "answers" not in task:
        raise ValueError(f"Task {task['id']} has no recorded answers to reuse: consult it with openguildkit task "
                         f"consult {task['id']} --answers FILE.")
    answers = dict(task["answers"])
    if args.answers is not None:
        with input_file(args.answers):
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


def run_review(command: TaskCommand) -> None:
    """Record the completed board reviews."""
    args, root, state, task = command.args, command.root, command.state, command.task
    review = read_json(args.file) if args.file else None
    with project_lock(state):
        current_task = read_task(state, args.id)
        if current_task != task:
            raise ValueError("The task changed while you were reviewing. Read the consultation and retry.")
        if review is not None:
            with input_file(args.file):
                result = record_review(current_task, review, root)
        else:
            result = assemble_review(current_task, args.summary)
        write_task(task_path(state, args.id), result)
    print(result["status"])
    for warning in result["review"].get("warnings", []):
        print(f"Warning: {warning}", file=sys.stderr)
    if review is not None:
        for warning in tool_evidence_warnings(root, state, result["review"]["boards"]):
            print(f"Warning: {warning}", file=sys.stderr)
    print(f"Next: openguildkit task deliberate {args.id} lists the objections between boards (skip it and task respond "
          f"when no board objects), then openguildkit task challenge {args.id} prints the decision brief to show the "
          "person.", file=sys.stderr)


def run_pass(command: TaskCommand) -> None:
    """Start one board's pass, or record its entry."""
    args, root, state = command.args, command.root, command.state
    action = args.action
    entry = read_json(args.file) if action == "submit" else {}
    with project_lock(state):
        current_task = read_task(state, args.id)
        if action == "pass":
            board_brief_problem(current_task, args.board)
            result = start_pass(current_task, args.board, args.mode or "sequential", args.again)
            submitted = result.pop("_submitted", False)
        else:
            with input_file(args.file):
                result = submit_pass(current_task, entry, args.mode, root)
        error = result.pop("_error", None)
        copied = result.pop("_warnings", [])
        write_task(task_path(state, args.id), result)
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


def run_progress(command: TaskCommand) -> None:
    """Which board passes are done, failed, started or missing."""
    args, task = command.args, command.task
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
