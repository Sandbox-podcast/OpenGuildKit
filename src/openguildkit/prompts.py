"""Asks a person at a terminal the setup questions of `init` and the task questions of `task consult`.

Entry: prompt_choices, prompt_questions
Tests: tests/test_clean_errors.py, tests/test_first_run.py, tests/test_proportionate_setup.py
"""

import sys

from .errors import OgkError
from .project_setup import unsure_answers
from .terminal import interactive

# A list this long is read by no one and its answer is almost always Enter: only the choices the default keeps are printed.
LONG_LIST = 50


def _printed(question: dict) -> list[tuple[int, dict]]:
    """The choices to print with their number: all of them, or past LONG_LIST only those the default keeps."""
    numbered = list(enumerate(question.get("choices", []), start=1))
    if len(numbered) <= LONG_LIST:
        return numbered
    default = question.get("default")
    return [(number, choice) for number, choice in numbered if choice["id"] in (default if isinstance(default, list) else [default])]


def prompt_choices(question: dict, value: str):
    """The choice IDs an answer names, by ID or by number; several, separated by commas, for a multi-select."""
    choices = question["choices"]
    ids = [choice["id"] for choice in choices]
    raw = [item.strip() for item in value.split(",") if item.strip()] if question.get("type") == "multi-select" else [value]
    selected = []
    for item in raw:
        if item in ids:
            selected.append(item)
        elif item.isascii() and item.isdecimal() and 1 <= int(item) <= len(ids):
            selected.append(ids[int(item) - 1])
        else:
            raise OgkError("OGK-BOARD-028", f"Unknown choice: {item}")
    return selected if question.get("type") == "multi-select" else selected[0]


def _print_question(question: dict) -> tuple[int, str]:
    """Print a question with its help, its choices, how to answer it and its default: how many choices are hidden,
    and the question's type."""
    print(f"\n{question['prompt']}", file=sys.stderr)
    if question.get("help"):
        print(f"  ({question['help']})", file=sys.stderr)
    shown = _printed(question)
    for index, choice in shown:
        print(f"  {index}. {choice['label']} [{choice['id']}]", file=sys.stderr)
    hidden = len(question.get("choices", [])) - len(shown)
    if hidden:
        print(f"  Type list to show the {hidden} others, or type an ID or a number.", file=sys.stderr)
    kind = question.get("type", "select")
    if kind in {"list", "multi-select"}:
        print("  Separate multiple entries with commas.", file=sys.stderr)
    if question["id"] == "packs":
        print("  Enter '-' to replace the recommended packs: only the required workflow pack and the packs "
              "of the selected patterns apply.", file=sys.stderr)
    if question["id"] == "patterns":
        print("  Enter '-' to select none of these, or list all the IDs you want to apply.", file=sys.stderr)
    if "default_label" in question:
        print(f"  Default: {question['default_label']}", file=sys.stderr)
    elif "default" in question:
        default = question["default"]
        default_text = ", ".join(map(str, default)) if isinstance(default, list) else default
        print(f"  Default: {default_text or 'none'}", file=sys.stderr)
    else:
        print("  No default: choose an answer.", file=sys.stderr)
    if "unsure" in question:
        print(f"  ? if you don't know: {question['unsure']}.", file=sys.stderr)
    return hidden, kind


def _ask_until_answered(question: dict, kind: str, hidden: int, answers: dict) -> None:
    """Read answers at the prompt until one holds, and record it in answers; list shows every choice, ? applies the
    unsure answer."""
    while True:
        print("> ", end="", file=sys.stderr, flush=True)
        value = input().strip()
        if hidden and value.casefold() == "list":
            for index, choice in enumerate(question["choices"], start=1):
                print(f"  {index}. {choice['label']} [{choice['id']}]", file=sys.stderr)
            continue
        if "unsure" in question and value.casefold() in ("?", "unsure", "i don't know", "je ne sais pas"):
            if any(choice["id"] == "unsure" for choice in question.get("choices", [])):
                # A task question offers unsure as an answer of its own, which the task records.
                answers[question["id"]] = ["unsure"] if kind == "multi-select" else "unsure"
                print(f"  {question['unsure']}.", file=sys.stderr)
                return
            resolved, notes = unsure_answers({question["id"]: "unsure"}, [question])
            answers.update(resolved)
            print(f"  {notes[0]}", file=sys.stderr)
            return
        if not value and "default" in question:
            answers[question["id"]] = question["default"]
            return
        if not value and kind in {"list", "multi-select"}:
            return
        if value == "-" and question["id"] in {"packs", "patterns"}:
            answers[question["id"]] = []
            if question["id"] == "packs":
                answers["replace_default_packs"] = True
            return
        if not value:
            print("  Choose an answer.", file=sys.stderr)
            continue
        try:
            if "choices" in question:
                answer = prompt_choices(question, value)
            elif kind == "list":
                answer = [item.strip() for item in value.split(",") if item.strip()]
            else:
                answer = value
        except ValueError as error:
            print(f"  {error}", file=sys.stderr)
            continue
        answers[question["id"]] = answer
        return


def prompt_questions(questions: list[dict], command: str) -> dict:
    """Ask each question in turn and return the answers; Enter keeps a default, ? applies the unsure answer."""
    if not interactive():
        raise OgkError("OGK-BOARD-029", f"{command} needs a terminal or --answers PATH.")
    answers: dict = {}
    for question in questions:
        hidden, kind = _print_question(question)
        _ask_until_answered(question, kind, hidden, answers)
    return answers
