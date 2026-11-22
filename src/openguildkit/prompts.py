"""Ask questions to a person at a terminal: the setup questionnaire of init and the task questions of task consult."""

import sys

from .project import unsure_answers


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
            raise ValueError(f"Unknown choice: {item}")
    return selected if question.get("type") == "multi-select" else selected[0]


def prompt_questions(questions: list[dict], command: str) -> dict:
    """Ask each question in turn and return the answers; Enter keeps a default, ? applies the unsure answer."""
    if not sys.stdin.isatty():
        raise ValueError(f"{command} needs a terminal or --answers PATH.")
    answers = {}
    for question in questions:
        print(f"\n{question['prompt']}", file=sys.stderr)
        if question.get("help"):
            print(f"  ({question['help']})", file=sys.stderr)
        for index, choice in enumerate(question.get("choices", []), start=1):
            print(f"  {index}. {choice['label']} [{choice['id']}]", file=sys.stderr)
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
            shown = ", ".join(map(str, default)) if isinstance(default, list) else default
            print(f"  Default: {shown or 'none'}", file=sys.stderr)
        else:
            print("  No default: choose an answer.", file=sys.stderr)
        if "unsure" in question:
            print(f"  ? if you don't know: {question['unsure']}.", file=sys.stderr)
        while True:
            print("> ", end="", file=sys.stderr, flush=True)
            value = input().strip()
            if "unsure" in question and value.casefold() in ("?", "unsure", "i don't know", "je ne sais pas"):
                if any(choice["id"] == "unsure" for choice in question.get("choices", [])):
                    # A task question offers unsure as an answer of its own, which the task records.
                    answers[question["id"]] = ["unsure"] if kind == "multi-select" else "unsure"
                    print(f"  {question['unsure']}.", file=sys.stderr)
                    break
                resolved, notes = unsure_answers({question["id"]: "unsure"}, [question])
                answers.update(resolved)
                print(f"  {notes[0]}", file=sys.stderr)
                break
            if not value and "default" in question:
                answers[question["id"]] = question["default"]
                break
            if not value and kind in {"list", "multi-select"}:
                break
            if value == "-" and question["id"] in {"packs", "patterns"}:
                answers[question["id"]] = []
                if question["id"] == "packs":
                    answers["replace_default_packs"] = True
                break
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
            break
    return answers
