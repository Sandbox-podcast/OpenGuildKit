"""Command-line interface for OpenGuildKit."""

import argparse
import sys
from pathlib import Path

from .catalog import load_catalog
from .project import (
    check_instructions,
    init_questions,
    initialize,
    load_profile,
    project_root,
    state_path,
    sync_instructions,
    validate_profile,
)
from .storage import json_text, project_lock, read_json, write_json
from .tasks import (
    create_task,
    read_task,
    record_consultation,
    record_decision,
    record_review,
    require_current_scope,
    task_path,
)
from .workflow import handoff, task_questions


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openguildkit", description="Project rules and specialist reviews for AI-assisted work.")
    parser.add_argument("--project", type=Path, help="Project root (defaults to the closest configured ancestor).")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="List rule packs, boards and sectors.")
    catalog.add_argument("--json", action="store_true", help="Print the complete catalog as JSON.")
    init = commands.add_parser("init", help="Initialize a project profile and agent instructions.")
    init_mode = init.add_mutually_exclusive_group()
    init_mode.add_argument("--questions", action="store_true", help="Print the setup questionnaire as JSON.")
    init_mode.add_argument("--answers", type=Path, help="Read setup answers from a JSON file.")
    commands.add_parser("sync", help="Update the managed instructions from the project profile.")
    commands.add_parser("check", help="Check that the instructions match the project profile.")

    task = commands.add_parser("task", help="Frame a task, record advice and approve a handoff.")
    actions = task.add_subparsers(dest="action", required=True)
    new = actions.add_parser("new", help="Create a task draft.")
    new.add_argument("brief", nargs="?", help="Short description of the work.")
    new.add_argument("--file", type=Path, help="Read the brief from a UTF-8 Markdown or text file.")
    new.add_argument("--id", help="Use a readable lowercase task ID.")
    descriptions = {
        "questions": "Print the task questionnaire as JSON.",
        "consult": "Save task answers and prepare the board consultation.",
        "brief": "Print the saved consultation for the host agent.",
        "template": "Print the review template as JSON.",
        "review": "Record the completed board reviews.",
        "decide": "Record a human decision.",
        "handoff": "Print the approved implementation handoff.",
        "show": "Print the task record as JSON.",
    }
    for action, description in descriptions.items():
        command = actions.add_parser(action, help=description)
        command.add_argument("id", help="Task ID.")
        if action == "consult":
            command.add_argument("--answers", type=Path, help="Read task answers from a JSON file.")
        if action == "review":
            command.add_argument("--file", type=Path, required=True, help="Completed review JSON.")
        if action == "decide":
            outcome = command.add_mutually_exclusive_group(required=True)
            outcome.add_argument("--approve", action="store_true", help="Approve the reviewed scope in a terminal.")
            outcome.add_argument("--request-changes", action="store_true", help="Send the task back to consultation.")
            command.add_argument("--by", required=True, help="Decision owner's name.")
            command.add_argument("--reason", required=True, help="Reason for the decision.")
    return parser


def _print_json(data) -> None:
    print(json_text(data), end="")


def _prompt_choices(question: dict, value: str):
    choices = question["choices"]
    ids = [choice["id"] for choice in choices]
    raw = [item.strip() for item in value.split(",")] if question.get("type") == "multi-select" else [value]
    selected = []
    for item in raw:
        if item in ids:
            selected.append(item)
        elif item.isascii() and item.isdecimal() and 1 <= int(item) <= len(ids):
            selected.append(ids[int(item) - 1])
        else:
            raise ValueError(f"Unknown choice: {item}")
    return selected if question.get("type") == "multi-select" else selected[0]


def _prompt_questions(questions: list[dict], command: str) -> dict:
    if not sys.stdin.isatty():
        raise ValueError(f"{command} needs a terminal or --answers PATH.")
    answers = {}
    for question in questions:
        print(f"\n{question['prompt']}", file=sys.stderr)
        for index, choice in enumerate(question.get("choices", []), start=1):
            print(f"  {index}. {choice['label']} [{choice['id']}]", file=sys.stderr)
        kind = question.get("type", "select")
        if kind in {"list", "multi-select"}:
            print("  Separate multiple entries with commas.", file=sys.stderr)
        if question["id"] == "packs":
            print("  Enter '-' to use only the OpenGuildKit workflow pack.", file=sys.stderr)
        if "default" in question:
            print(f"  Default: {question['default']}", file=sys.stderr)
        while True:
            print("> ", end="", file=sys.stderr, flush=True)
            value = input().strip()
            if not value and "default" in question:
                answers[question["id"]] = question["default"]
                break
            if not value and kind in {"list", "multi-select"}:
                break
            if value == "-" and question["id"] == "packs":
                answers["packs"] = []
                break
            if not value:
                print("  Choose an answer.", file=sys.stderr)
                continue
            try:
                if "choices" in question:
                    answer = _prompt_choices(question, value)
                elif kind == "list":
                    answer = [item.strip() for item in value.split(",") if item.strip()]
                else:
                    answer = value
            except ValueError as error:
                print(f"  {error}", file=sys.stderr)
                continue
            answers[question["id"]] = answer
            break
    return answers


def _print_catalog(catalog: dict, as_json: bool) -> None:
    if as_json:
        _print_json(catalog)
        return
    for group in ("packs", "boards", "sectors"):
        print(group.capitalize())
        for entry in catalog[group].values():
            print(f"  {entry['id']:<24} {entry['title']}")


def _read_consultation(task: dict) -> dict:
    if "consultation" not in task:
        raise ValueError("Run task consult first.")
    return task["consultation"]


def _decide(args, root: Path, state: Path, task: dict) -> None:
    result = record_decision(task, args.approve, args.by, args.reason)
    if args.approve:
        if not sys.stdin.isatty():
            raise ValueError("Approval requires a person at an interactive terminal.")
        print(json_text({"brief": task["brief"], "review": task["review"]}), file=sys.stderr, end="")
        print(f"Type {args.id} to approve the reviewed scope: ", end="", file=sys.stderr, flush=True)
        if input().strip() != args.id:
            raise ValueError("Approval cancelled.")
    with project_lock(state):
        if read_task(state, args.id) != task:
            raise ValueError("The task changed while you were deciding. Review it and retry.")
        if args.approve:
            catalog = load_catalog(state / "catalog")
            profile = load_profile(state, catalog)
            require_current_scope(task, profile, catalog)
            check_instructions(root, profile, catalog)
        write_json(task_path(state, args.id), result)
    print(result["status"])


def _task_command(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    action = args.action
    if action == "new":
        if (args.brief is None) == (args.file is None):
            raise ValueError("Supply either a task brief or --file PATH.")
        brief = args.file.read_text(encoding="utf-8-sig") if args.file else args.brief
        check_instructions(root, profile, catalog)
        with project_lock(state):
            print(create_task(state, brief, args.id))
        return

    task = read_task(state, args.id)
    if action == "show":
        _print_json(task)
    elif action == "questions":
        _print_json(task_questions(task["brief"]))
    elif action == "brief":
        print(_read_consultation(task)["markdown"])
    elif action == "template":
        _print_json(_read_consultation(task)["review_template"])
    elif action == "consult":
        answers = (
            read_json(args.answers)
            if args.answers is not None
            else _prompt_questions(task_questions(task["brief"]), "task consult")
        )
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were answering. Review it and retry.")
            catalog = load_catalog(state / "catalog")
            profile = load_profile(state, catalog)
            check_instructions(root, profile, catalog)
            result = record_consultation(current_task, answers, profile, catalog)
            write_json(task_path(state, args.id), result)
        print(result["consultation"]["markdown"])
    elif action == "review":
        review = read_json(args.file)
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were reviewing. Read the consultation and retry.")
            result = record_review(current_task, review)
            write_json(task_path(state, args.id), result)
        print(result["status"])
    elif action == "decide":
        _decide(args, root, state, task)
    elif action == "handoff":
        output = handoff(task)
        require_current_scope(task, profile, catalog)
        check_instructions(root, profile, catalog)
        print(output)


def _run(args) -> None:
    root = project_root(args.project)
    state = state_path(root)
    catalog = load_catalog(state / "catalog")
    if args.command == "catalog":
        _print_catalog(catalog, args.json)
    elif args.command == "init":
        questions = init_questions(catalog, root.name or "Project")
        if args.questions:
            _print_json(questions)
            return
        if (state / "project.json").exists():
            raise ValueError("Project is already initialized. Edit .openguildkit/project.json and run openguildkit sync.")
        answers = read_json(args.answers) if args.answers else _prompt_questions(questions, "init")
        with project_lock(state):
            catalog = load_catalog(state / "catalog")
            initialize(root, state, validate_profile(answers, catalog), catalog)
        print(f"Initialized {root}")
    elif args.command == "sync":
        with project_lock(state):
            catalog = load_catalog(state / "catalog")
            sync_instructions(root, load_profile(state, catalog), catalog)
        print("OpenGuildKit instructions updated.")
    else:
        profile = load_profile(state, catalog)
        if args.command == "check":
            check_instructions(root, profile, catalog)
            print("OpenGuildKit instructions match the project profile.")
        elif args.command == "task":
            _task_command(args, root, state, profile, catalog)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        # Redirected output is consumed by agents and scripts on every platform.
        for stream in (sys.stdout, sys.stderr):
            if not stream.isatty() and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except (OSError, ValueError, EOFError) as error:
        print(f"OpenGuildKit: {error or 'Input ended before completion.'}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOpenGuildKit: Cancelled.", file=sys.stderr)
        return 130
    return 0
