"""Command-line interface for OpenGuildKit."""

import argparse
import sys
from pathlib import Path

from .catalog import load_catalog
from .ci import check_export, read_policy_pack
from .detect import components_for_profile, detect_stack
from .hosts import apply_host_settings, host_controls
from .lock import (
    apply_lock,
    build_lock,
    catalog_changes,
    lock_is_current,
    read_lock,
    update_target,
    write_lock,
)
from .patterns import patterns_to_review, role_choices
from .project import (
    check_instructions,
    init_questions,
    initialize,
    load_profile,
    profile_recommendations,
    profile_fingerprint,
    project_root,
    resolved_profile,
    rule_conflicts,
    rule_plan,
    state_path,
    sync_instructions,
    validate_profile,
)
from .references import find_references, load_references, with_pattern_references
from .storage import json_text, project_lock, read_json, write_json
from .tasks import (
    record_deliberation,
    assemble_review,
    pass_progress,
    start_pass,
    submit_pass,
    ACTIONS,
    record_authorization,
    create_task,
    read_task,
    record_consultation,
    record_decision,
    record_review,
    require_current_scope,
    task_path,
)
from .workflow import board_brief, challenge_report, deliberation_request, handoff, open_points, select_boards, task_questions, validate_answers


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openguildkit", description="Project rules and specialist reviews for AI-assisted work.")
    parser.add_argument("--project", type=Path, help="Project root (defaults to the closest configured ancestor).")
    parser.add_argument("--policy-repo", type=Path, help="Local Git repository with the central export rule.")
    parser.add_argument("--policy-commit", help="Full Git SHA of the central policy commit.")
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="List rule packs, boards and sectors.")
    catalog.add_argument("--json", action="store_true", help="Print the complete catalog as JSON.")
    references = commands.add_parser("references", help="Browse the reference library.")
    references.add_argument("query", nargs="?", help="Search reference names and descriptions.")
    references.add_argument("--family", help="Show references from one family ID.")
    references.add_argument("--id", help="Show one reference and its sources.")
    references.add_argument("--json", action="store_true", help="Print matching references as JSON.")
    patterns = commands.add_parser("patterns", help="List stack patterns and work methods.")
    patterns.add_argument("--role", help="Filter by role ID.")
    patterns.add_argument("--id", help="Show a pattern, its match and its rule packs.")
    patterns.add_argument("--json", action="store_true", help="Print matching patterns as JSON.")
    preview = commands.add_parser("preview", help="Show the rule packs, their origin and scope before writing them.")
    preview.add_argument("--answers", type=Path, help="Preview setup answers instead of the saved profile.")
    preview.add_argument("--json", action="store_true", help="Print the plan as JSON.")
    detect = commands.add_parser("detect", help="Propose components and technologies from the repository's manifests.")
    detect.add_argument("--json", action="store_true", help="Print the components and their evidence as JSON.")
    recommend = commands.add_parser("recommend", help="Preview patterns for a project context.")
    recommend.add_argument("--answers", type=Path, help="Read sector, stack and roles from a JSON file.")
    recommend.add_argument("--json", action="store_true", help="Print matches and suggestions as JSON.")
    brains = commands.add_parser("brains", help="List the specialist review boards.")
    brains.add_argument("--id", help="Show a brain's specialist lenses and review criteria.")
    brains.add_argument("--json", action="store_true", help="Print the board definitions as JSON.")
    init = commands.add_parser("init", help="Initialize a project profile and agent instructions.")
    init_mode = init.add_mutually_exclusive_group()
    init_mode.add_argument("--questions", action="store_true", help="Print the setup questionnaire as JSON.")
    init_mode.add_argument("--answers", type=Path, help="Read setup answers from a JSON file.")
    commands.add_parser("sync", help="Update the managed instructions from the project profile.")
    host = commands.add_parser("host", help="Show or apply the rules the host agent can enforce.")
    host.add_argument("mode", choices=("check", "apply"), help="check reports each rule; apply writes the host settings.")
    host.add_argument("--json", action="store_true", help="Print the report as JSON.")
    update = commands.add_parser("update", help="Show what the installed catalog would change and adopt it.")
    update.add_argument("--apply", action="store_true", help="Adopt the installed catalog's records for this project.")
    update.add_argument("--json", action="store_true", help="Print the changes as JSON.")
    commands.add_parser("check", help="Check that the instructions match the project profile.")
    ci = commands.add_parser("ci-check", help="Evaluate the central export rule on an exact Git commit.")
    ci.add_argument("--target-repo", type=Path, required=True, help="Local Git repository with the target commit.")
    ci.add_argument("--commit", required=True, help="Full Git SHA of the target commit.")

    task = commands.add_parser("task", help="Frame a task, record advice and approve a handoff.")
    actions = task.add_subparsers(dest="action", required=True)
    new = actions.add_parser("new", help="Create a task draft.")
    new.add_argument("brief", nargs="?", help="Short description of the work.")
    new.add_argument("--file", type=Path, help="Read the brief from a UTF-8 Markdown or text file.")
    new.add_argument("--id", help="Use a readable lowercase task ID.")
    descriptions = {
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
        "respond": "Record the boards' answers to each other's objections.",
        "decide": "Record a human decision.",
        "handoff": "Print the approved implementation handoff, or the decision record of a decision task.",
        "show": "Print the task record as JSON.",
        "authorize": "Record a person's decision on an external action outside the authorized scope.",
    }
    for action, description in descriptions.items():
        command = actions.add_parser(action, help=description)
        command.add_argument("id", help="Task ID.")
        if action in ("consult", "questions", "route"):
            command.add_argument("--answers", type=Path, help="Read task answers from a JSON file.")
        if action in ("consult", "route"):
            command.add_argument("--add", action="append", default=[], metavar="BOARD", help="Add a board to the consultation.")
            command.add_argument("--remove", action="append", default=[], metavar="BOARD", help="Remove a proposed board.")
            command.add_argument("--reason", help="Why the boards were added or removed.")
            command.add_argument("--delegate", action="append", default=[], metavar="BOARD=NAME",
                                 help="Name the person who reviews a required board the project has not enabled.")
        if action == "route":
            command.add_argument("--json", action="store_true", help="Print the selection as JSON.")
        if action == "review":
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--file", type=Path, help="Completed review JSON.")
            source.add_argument("--summary", help="Assemble the review from completed board passes with this summary.")
        if action == "pass":
            command.add_argument("board", help="Board ID.")
        if action in ("pass", "submit"):
            command.add_argument("--mode", choices=("subagent", "sequential"), help="How the host runs this pass.")
        if action == "respond":
            command.add_argument("--file", type=Path, required=True, help="Completed deliberation JSON.")
        if action == "submit":
            command.add_argument("--file", type=Path, required=True, help="The board's filled-in JSON entry.")
        if action == "progress":
            command.add_argument("--json", action="store_true", help="Print the progress as JSON.")
        if action == "authorize":
            command.add_argument("--action", dest="external_action", required=True, choices=ACTIONS,
                                 help="Kind of external action.")
            command.add_argument("--target", required=True, help="Host or tool name, without query or private details.")
            outcome = command.add_mutually_exclusive_group(required=True)
            outcome.add_argument("--allow", action="store_true", help="Allow the action (needs a terminal).")
            outcome.add_argument("--deny", action="store_true", help="Refuse the action.")
            command.add_argument("--by", required=True, help="Decision owner's name.")
            command.add_argument("--reason", required=True, help="Reason for the decision.")
        if action == "decide":
            outcome = command.add_mutually_exclusive_group(required=True)
            outcome.add_argument("--approve", action="store_true", help="Approve the reviewed scope in a terminal.")
            outcome.add_argument("--request-changes", action="store_true", help="Send the task back to consultation.")
            command.add_argument("--by", required=True, help="Decision owner's name.")
            command.add_argument("--reason", required=True, help="Reason for the decision.")
    return parser


def _print_json(data) -> None:
    print(json_text(data), end="")


def _installed_catalog(args, state: Path) -> tuple[dict, dict[str, set[str]]]:
    """The installed catalog with project additions, and the IDs that ship with OpenGuildKit."""
    if (args.policy_repo is None) != (args.policy_commit is None):
        raise ValueError("Supply --policy-repo and --policy-commit together.")
    policy = None
    if args.policy_repo is not None:
        policy = (args.policy_commit, read_policy_pack(args.policy_repo, args.policy_commit))
    live = load_catalog(state / "catalog", central_policy=policy)
    bundled = {collection: set(entries) for collection, entries in load_catalog().items()}
    return live, bundled


def _load_project_catalog(args, state: Path) -> dict:
    """The catalog in force for the project: locked records take precedence over installed ones."""
    live, _ = _installed_catalog(args, state)
    return apply_lock(live, read_lock(state))


def _stale_tasks(state: Path, profile: dict, catalog: dict) -> list[dict]:
    stale = []
    directory = state / "tasks"
    if not directory.is_dir():
        return stale
    for path in sorted(directory.glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError:
            continue
        if task.get("profile_fingerprint") and task["profile_fingerprint"] != profile_fingerprint(profile, catalog):
            stale.append({"id": task["id"], "status": task["status"]})
    return stale


def _update_catalog(args, root: Path, state: Path) -> None:
    with project_lock(state):
        live, bundled = _installed_catalog(args, state)
        lock = read_lock(state)
        if lock is None:
            catalog = live
            profile = load_profile(state, catalog)
            if args.apply:
                write_lock(state, build_lock(profile, catalog, bundled))
            result = {"changes": [], "conflicts": [], "applied": args.apply, "stale_tasks": [],
                      "note": "The project had no catalog lock. It now pins the installed catalog." if args.apply
                      else "The project has no catalog lock yet. Run openguildkit update --apply or sync to create one."}
        else:
            current = apply_lock(live, lock)
            profile = load_profile(state, current)
            target = update_target(live, lock)
            changes = catalog_changes(lock, live, target, profile, bundled)
            conflicts = [conflict for conflict in rule_conflicts(profile, target) if conflict["resolution"] is None]
            result = {"changes": changes, "conflicts": conflicts, "applied": False, "stale_tasks": []}
            if args.apply and changes:
                sync_instructions(root, profile, target)
                write_lock(state, build_lock(profile, target, bundled))
                result["applied"] = True
                result["stale_tasks"] = _stale_tasks(state, profile, target)
    _print_update(result, args.json)


def _print_update(result: dict, as_json: bool) -> None:
    if as_json:
        _print_json(result)
        return
    if result.get("note"):
        print(result["note"])
        return
    if not result["changes"]:
        print("The project's rules match the installed catalog.")
        return
    for change in result["changes"]:
        label = f"{change['collection']}/{change['id']}"
        if change["status"] == "added":
            print(f"+ {label} {change.get('version') or ''}".rstrip())
            continue
        if change["status"] != "changed":
            print(f"- {label}: {change['status']}, kept from the lock")
            continue
        version = f" {change['version'][0]} -> {change['version'][1]}" if "version" in change else ""
        print(f"~ {label}{version} ({', '.join(change['fields'])})")
        for rule in change.get("rules", {}).get("added", []):
            print(f"    + rule {rule['id']}: {rule['text']}")
        for rule_id in change.get("rules", {}).get("removed", []):
            print(f"    - rule {rule_id}")
        for rule in change.get("rules", {}).get("changed", []):
            print(f"    ~ rule {rule['id']}: {rule['after']}")
        for url in change["sources"]["added"]:
            print(f"    + source {url}")
        for url in change["sources"]["removed"]:
            print(f"    - source {url}")
    for conflict in result["conflicts"]:
        print(f"! {' and '.join(conflict['packs'])} conflict: record a resolution before applying.")
    if not result["applied"]:
        print("Nothing changed. Run openguildkit update --apply to adopt these rules.")
        return
    print("Applied. The next consultations use these rules.")
    for task in result["stale_tasks"]:
        print(f"  Task {task['id']} ({task['status']}) was consulted under the previous rules: review it again.")


def _prompt_choices(question: dict, value: str):
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
            print("  Enter '-' for the required workflow pack and any selected pattern packs.", file=sys.stderr)
        if question["id"] == "patterns":
            print("  Enter '-' to skip patterns, or select all the IDs you want to apply.", file=sys.stderr)
        if "default" in question:
            default = question["default"]
            shown = ", ".join(map(str, default)) if isinstance(default, list) else default
            print(f"  Default: {shown or 'none'}", file=sys.stderr)
        while True:
            print("> ", end="", file=sys.stderr, flush=True)
            value = input().strip()
            if not value and "default" in question:
                answers[question["id"]] = question["default"]
                break
            if not value and kind in {"list", "multi-select"}:
                break
            if value == "-" and question["id"] in {"packs", "patterns"}:
                answers[question["id"]] = []
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


def _prompt_components(question: dict) -> list[dict]:
    """Show the detected components and let the person keep them or describe the stack instead."""
    detected = question.get("default") or []
    if not detected:
        return []
    print(f"\n{question['prompt']}", file=sys.stderr)
    for component in detected:
        print(f"  {component['id']} ({component['path']}): {', '.join(component['stack'])}", file=sys.stderr)
    print("  Keep these components? [Y/n] (edit .openguildkit/project.json later to correct them)", file=sys.stderr)
    while True:
        print("> ", end="", file=sys.stderr, flush=True)
        value = input().strip().casefold()
        if value in ("", "y", "yes", "o", "oui"):
            return detected
        if value in ("n", "no", "non"):
            return []
        print("  Answer y or n.", file=sys.stderr)


def _scoped_patterns(selected: list, plan: dict) -> list:
    """Keep the components on which each chosen stack pattern matched."""
    scopes = {pattern["id"]: pattern.get("components") for pattern in [*plan["matched"], *plan["suggested"]]}
    return [
        {"id": pattern_id, "components": scopes[pattern_id]}
        if isinstance(pattern_id, str) and scopes.get(pattern_id) else pattern_id
        for pattern_id in selected
    ]


def _print_plan_notes(plan: dict) -> None:
    for pattern in plan["matched"]:
        if pattern.get("version_unknown"):
            print(f"  {pattern['id']}: confirm {', '.join(pattern['version_unknown'])}", file=sys.stderr)
    for item in plan.get("excluded", []):
        where = f" in {item['component']}" if item["component"] else ""
        print(f"  {item['id']} does not apply{where}: {'; '.join(item['reasons'])}", file=sys.stderr)


def _prompt_task_questions(brief: str) -> dict:
    """Ask the base questions, then the follow-ups that the first answers call for."""
    base = [question for question in task_questions(brief) if question["id"] != "context"]
    answers = _prompt_questions(base, "task consult")
    follow_ups = [question for question in task_questions(brief, answers) if question["id"] not in answers]
    answers.update(_prompt_questions(follow_ups, "task consult"))
    for point in open_points(brief, validate_answers(answers)):
        print(f"  Open point: {point}", file=sys.stderr)
    return answers


def _interactive_init(questions: list[dict], catalog: dict) -> dict:
    by_id = {question["id"]: question for question in questions}
    answers = _prompt_questions([by_id["name"], by_id["sector"]], "init")
    components = _prompt_components(by_id["components"])
    if components:
        answers["components"] = components
    else:
        answers.update(_prompt_questions([by_id["stack"]], "init"))
    answers.update(_prompt_questions([by_id["roles"]], "init"))
    asked = {"name", "sector", "stack", "components", "roles"}
    pending = [question for question in questions if question["id"] not in asked]
    plan = profile_recommendations(answers, catalog)
    _print_plan_notes(plan)
    matched = [pattern["id"] for pattern in plan["matched"]]
    suggested = [pattern["id"] for pattern in plan["suggested"]]
    if suggested:
        print(f"\nMethods and alternatives to consider: {', '.join(suggested)}", file=sys.stderr)
    for question in pending:
        if question["id"] == "patterns":
            question["default"] = matched
            position = {pattern_id: index for index, pattern_id in enumerate([*matched, *suggested])}
            question["choices"].sort(key=lambda choice: position.get(choice["id"], len(position)))
    answers.update(_prompt_questions(pending, "init"))
    if "patterns" in answers:
        answers["patterns"] = _scoped_patterns(answers["patterns"], plan)
    return answers


def _print_catalog(catalog: dict, as_json: bool) -> None:
    groups = ("packs", "boards", "sectors")
    if as_json:
        _print_json({group: catalog[group] for group in groups})
        return
    for group in groups:
        print(group.capitalize())
        for entry in catalog[group].values():
            print(f"  {entry['id']:<24} {entry['title']}")


def _print_references(args, state: Path, catalog: dict) -> None:
    families = with_pattern_references(load_references(state / "catalog" / "references"), catalog["patterns"])
    if not args.json and all(value is None for value in (args.query, args.family, args.id)):
        print(f"{sum(len(family['references']) for family in families.values())} references")
        for family in families.values():
            print(f"  {family['id']:<14} {family['title']} ({len(family['references'])})")
        return
    matches = find_references(families, family_id=args.family, query=args.query, record_id=args.id)
    if args.json:
        _print_json(matches)
    elif args.id:
        reference = matches[0]
        print(f"{reference['title']} [{reference['id']}]")
        print(f"{reference['family_title']} / {reference['category']} / {reference['kind']}")
        print(f"\n{reference['summary']}\n{reference['applies_when']}\n")
        for source in reference["sources"]:
            print(f"- {source['title']}: {source['url']}")
    elif matches:
        for reference in matches:
            print(f"  {reference['id']:<34} {reference['title']} [{reference['family']}]")
    else:
        print("No references matched.")


def _print_patterns(args, patterns: dict) -> None:
    roles = role_choices(patterns)
    if args.role and args.role not in roles:
        raise ValueError(f"Unknown role: {args.role}. Available roles: {', '.join(roles)}.")
    matches = [
        pattern for pattern in patterns.values()
        if (not args.role or args.role in pattern["roles"]) and (not args.id or args.id == pattern["id"])
    ]
    if args.id and not matches:
        raise ValueError(f"No pattern matched {args.id!r}.")
    if args.json:
        _print_json(matches)
        return
    if args.id:
        pattern = matches[0]
        print(f"{pattern['title']} [{pattern['id']}]")
        print(pattern["description"])
        print(f"Roles: {', '.join(pattern['roles'])}")
        print(f"Packs: {', '.join(pattern['packs'])}")
        if "match" in pattern:
            requirements = [" / ".join(group) for group in pattern["match"]["stack"]]
            print(f"Stack requirements: {' + '.join(requirements)}")
            if pattern["match"].get("sectors"):
                print(f"Sectors: {', '.join(pattern['match']['sectors'])}")
        for source in pattern["sources"]:
            print(f"- {source['title']}: {source['url']}")
        return
    print(f"{len(matches)} patterns")
    for pattern in matches:
        print(f"  {pattern['id']:<33} {pattern['title']} [{', '.join(pattern['roles'])}]")


def _print_recommendations(plan: dict, as_json: bool) -> None:
    if as_json:
        _print_json(plan)
        return
    print("Matched stack patterns")
    for pattern in plan["matched"]:
        where = f" [{', '.join(pattern['components'])}]" if pattern.get("components") else ""
        print(f"  {pattern['id']}{where}: {', '.join(pattern['matched_stack'])}")
        if pattern.get("version_unknown"):
            print(f"    version unknown, confirm {', '.join(pattern['version_unknown'])}")
    if plan.get("excluded"):
        print("Not applicable because of a version")
        for item in plan["excluded"]:
            where = f" [{item['component']}]" if item["component"] else ""
            print(f"  {item['id']}{where}: {'; '.join(item['reasons'])}")
    print("Methods and alternatives to consider")
    for pattern in plan["suggested"]:
        reason = ", ".join(pattern.get("matched_roles", [])) or "choose one overlapping pattern"
        print(f"  {pattern['id']}: {reason}")
    print(f"Recommended packs: {', '.join(plan['recommended_packs'])}")
    if plan.get("review"):
        print("Selected patterns to review")
        for item in plan["review"]:
            print(f"  {item['id']}: {'; '.join(item['reasons'])}")


def _print_rule_plan(plan: dict, as_json: bool, file=sys.stdout) -> None:
    if as_json:
        print(json_text(plan), end="", file=file)
        return
    print("Rule packs, in the order AGENTS.md lists them", file=file)
    for pack in plan["packs"]:
        scope = f" [{', '.join(pack['scope'])}]" if pack["scope"] else ""
        print(f"  {pack['id']}@{pack['version']}{scope}: {'; '.join(pack['provenance'])}", file=file)
    for pack_id in plan["excluded"]:
        print(f"  {pack_id}: not applied, see the rule decisions", file=file)
    if plan["conflicts"]:
        print("Conflicting packs", file=file)
        for conflict in plan["conflicts"]:
            where = f" in {', '.join(conflict['scope'])}" if conflict["scope"] else ""
            resolution = conflict["resolution"]
            outcome = (
                f"keep {', '.join(resolution['keep'])} ({resolution['reason']})" if resolution
                else "unresolved: add a resolution to the profile"
            )
            print(f"  {' / '.join(conflict['packs'])}{where}: {outcome}", file=file)
    for title, field in (("Team conventions", "conventions"), ("Project checks", "checks")):
        if plan[field]:
            print(title, file=file)
            for item in plan[field]:
                print(f"  - {item}", file=file)


def _confirm_rule_plan(plan: dict) -> None:
    print("", file=sys.stderr)
    _print_rule_plan(plan, False, file=sys.stderr)
    print("Write this profile and these rules? [Y/n]", file=sys.stderr)
    print("> ", end="", file=sys.stderr, flush=True)
    if input().strip().casefold() not in ("", "y", "yes", "o", "oui"):
        raise ValueError("Setup cancelled. Nothing was written.")


def _print_detection(detected: dict, as_json: bool) -> None:
    if as_json:
        _print_json(detected)
        return
    if not detected["components"]:
        print("No known manifest found. Describe the stack during init.")
        return
    for component in detected["components"]:
        print(f"{component['id']} ({component['path']})")
        for item in component["evidence"]:
            version = item["version"] or "version unknown"
            note = ", inferred from a client library" if item["inferred"] else ""
            print(f"  {item['name']}: {version} [{item['evidence']}{note}]")


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
        raise ValueError("Run task consult first.")
    return task["consultation"]


def _print_brains(args, catalog: dict) -> None:
    boards = catalog["boards"]
    if args.id and args.id not in boards:
        raise ValueError(f"Unknown brain: {args.id}. Run openguildkit brains.")
    if args.json:
        _print_json(boards[args.id] if args.id else boards)
    elif args.id:
        board = boards[args.id]
        print(f"{board['title']} [{board['id']}]")
        print(board["description"])
        if "review" in board:
            plan = board["review"]
            for specialist in plan["specialists"]:
                print(f"  {specialist['title']}: {specialist['focus']}")
            for heading, key in (
                ("Evidence to inspect", "evidence"),
                ("Challenge questions", "challenge"),
                ("Decision criteria", "decision_criteria"),
            ):
                print(f"\n{heading}")
                for question in plan[key]:
                    print(f"  - {question}")
    else:
        for board in boards.values():
            reviewers = board.get("review", {}).get("specialists", [])
            count = f" ({len(reviewers)} specialists)" if reviewers else ""
            print(f"  {board['id']:<23} {board['title']}{count}")


def _decide(args, root: Path, state: Path, task: dict) -> None:
    result = record_decision(task, args.approve, args.by, args.reason)
    if args.approve:
        if not sys.stdin.isatty():
            raise ValueError("Approval requires a person at an interactive terminal.")
        print(
            json_text({"brief": task["brief"], "answers": task["answers"], "review": task["review"]}),
            file=sys.stderr,
            end="",
        )
        if any(entry.get("challenge", {}).get("blockers") for entry in task["review"]["boards"]):
            print("The review flags blockers. Record how the decision addresses them.", file=sys.stderr)
        print(f"Type {args.id} to approve the reviewed scope: ", end="", file=sys.stderr, flush=True)
        if input().strip() != args.id:
            raise ValueError("Approval cancelled.")
    with project_lock(state):
        if read_task(state, args.id) != task:
            raise ValueError("The task changed while you were deciding. Review it and retry.")
        if args.approve:
            catalog = _load_project_catalog(args, state)
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
        if args.answers is None:
            _print_json(task_questions(task["brief"]))
        else:
            answers = read_json(args.answers)
            questions = task_questions(task["brief"], answers)
            asked = {question["id"] for question in questions if question.get("essential") is not None}
            _print_json({
                "questions": questions,
                "follow_ups": sorted(asked - answers.keys()),
                "open_points": open_points(task["brief"], validate_answers(answers)),
            })
    elif action == "brief":
        print(_read_consultation(task)["markdown"])
    elif action == "template":
        _print_json(_read_consultation(task)["review_template"])
    elif action == "deliberate":
        _print_json(deliberation_request(task))
    elif action == "respond":
        payload = read_json(args.file)
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were deliberating. Run task deliberate again.")
            result = record_deliberation(current_task, payload)
            write_json(task_path(state, args.id), result)
        deliberation = result["deliberation"]
        print(f"{len(deliberation['agreed'])} resolved, {len(deliberation['open'])} open")
    elif action == "challenge":
        print(challenge_report(task), end="")
    elif action == "route":
        if args.answers is None and "answers" not in task:
            raise ValueError("Pass --answers FILE, or consult the task first.")
        answers = validate_answers(read_json(args.answers) if args.answers else task["answers"])
        selected = select_boards(
            resolved_profile(profile, catalog), catalog, {**task, "answers": answers}, answers, _selection(args)
        )
        if args.json:
            _print_json(selected)
        else:
            for board_id, reasons in selected["routing"].items():
                print(f"{board_id}: {'; '.join(reasons)}")
            for item in selected["adjustments"]:
                print(f"  {item['action']} {item['board']}: {item['reason']}")
    elif action == "consult":
        answers = (
            read_json(args.answers)
            if args.answers is not None
            else _prompt_task_questions(task["brief"])
        )
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were answering. Review it and retry.")
            catalog = _load_project_catalog(args, state)
            profile = load_profile(state, catalog)
            check_instructions(root, profile, catalog)
            controls = host_controls(root, profile)
            result = record_consultation(current_task, answers, profile, catalog, _selection(args), controls)
            write_json(task_path(state, args.id), result)
        print(result["consultation"]["markdown"])
    elif action == "review":
        review = read_json(args.file) if args.file else None
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were reviewing. Read the consultation and retry.")
            result = record_review(current_task, review) if review is not None else assemble_review(current_task, args.summary)
            write_json(task_path(state, args.id), result)
        print(result["status"])
    elif action in ("pass", "submit"):
        entry = read_json(args.file) if action == "submit" else None
        with project_lock(state):
            current_task = read_task(state, args.id)
            if action == "pass":
                result = start_pass(current_task, args.board, args.mode or "sequential")
            else:
                result = submit_pass(current_task, entry, args.mode)
            error = result.pop("_error", None)
            write_json(task_path(state, args.id), result)
        if action == "pass":
            print(board_brief(result["consultation"], args.board))
        elif error:
            raise ValueError(f"The pass is recorded as failed: {error} Start it again with task pass.")
        else:
            print("done")
    elif action == "progress":
        if "consultation" not in task:
            raise ValueError("Run task consult first.")
        progress = pass_progress(task)
        if args.json:
            _print_json(progress)
        else:
            for item in progress:
                details = ", ".join(f"{key} {item[key]}" for key in ("mode", "attempts") if key in item)
                print(f"{item['board']}: {item['status']}{f' ({details})' if details else ''}")
                if "error" in item:
                    print(f"    {item['error']}")
    elif action == "decide":
        _decide(args, root, state, task)
    elif action == "authorize":
        if args.allow and not sys.stdin.isatty():
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
    elif action == "handoff":
        output = handoff(task)
        require_current_scope(task, profile, catalog)
        check_instructions(root, profile, catalog)
        print(output)


def _run(args) -> int | None:
    root = project_root(args.project)
    state = state_path(root)
    catalog = _load_project_catalog(args, state)
    if args.command == "references":
        _print_references(args, state, catalog)
    elif args.command == "patterns":
        _print_patterns(args, catalog["patterns"])
    elif args.command == "brains":
        _print_brains(args, catalog)
    elif args.command == "detect":
        _print_detection(detect_stack(root), args.json)
    elif args.command == "preview":
        profile = validate_profile(read_json(args.answers), catalog) if args.answers else load_profile(state, catalog)
        _print_rule_plan(rule_plan(profile, catalog), args.json)
    elif args.command == "recommend":
        if args.answers:
            plan = profile_recommendations(read_json(args.answers), catalog)
        else:
            profile = load_profile(state, catalog)
            plan = {**profile_recommendations(profile, catalog), "review": patterns_to_review(profile, catalog)}
        _print_recommendations(plan, args.json)
    elif args.command == "catalog":
        _print_catalog(catalog, args.json)
    elif args.command == "init":
        detected = components_for_profile(detect_stack(root))
        questions = init_questions(catalog, root.name or "Project", detected)
        if args.questions:
            _print_json(questions)
            return
        if (state / "project.json").exists():
            raise ValueError("Project is already initialized. Edit .openguildkit/project.json and run openguildkit sync.")
        answers = read_json(args.answers) if args.answers else _interactive_init(questions, catalog)
        if not args.answers:
            _confirm_rule_plan(rule_plan(validate_profile(answers, catalog), catalog))
        with project_lock(state):
            live, bundled = _installed_catalog(args, state)
            profile = validate_profile(answers, live)
            initialize(root, state, profile, live)
            write_lock(state, build_lock(profile, live, bundled))
        print(f"Initialized {root}")
    elif args.command == "update":
        _update_catalog(args, root, state)
    elif args.command == "sync":
        with project_lock(state):
            live, bundled = _installed_catalog(args, state)
            catalog = apply_lock(live, read_lock(state))
            profile = load_profile(state, catalog)
            sync_instructions(root, profile, catalog)
            write_lock(state, build_lock(profile, catalog, bundled))
        print("OpenGuildKit instructions updated.")
        for item in patterns_to_review(profile, catalog):
            print(f"OpenGuildKit: review pattern {item['id']}: {'; '.join(item['reasons'])}", file=sys.stderr)
    else:
        profile = load_profile(state, catalog)
        if args.command == "host":
            controls = host_controls(root, profile)
            if args.mode == "apply":
                for path in apply_host_settings(root, profile):
                    print(f"Wrote {path}", file=sys.stderr)
                controls = host_controls(root, profile)
            if args.json:
                _print_json(controls)
            else:
                for control in controls:
                    print(f"[{control['status']}] {control['title']}\n    {control['detail']}")
            return
        if args.command == "check":
            check_instructions(root, profile, catalog)
            missing = [control["title"] for control in host_controls(root, profile) if control["status"] == "missing"]
            if missing:
                raise ValueError(f"The host settings do not enforce: {'; '.join(missing)}. Run openguildkit host apply.")
            _, bundled = _installed_catalog(args, state)
            if not lock_is_current(read_lock(state), profile, catalog, bundled):
                raise ValueError("The catalog lock does not match the profile. Run openguildkit sync.")
            print("OpenGuildKit instructions match the project profile.")
        elif args.command == "ci-check":
            result = check_export(profile, catalog, args.target_repo, args.commit)
            _print_json(result)
            return 0 if result["status"] == "success" else 1
        elif args.command == "task":
            _task_command(args, root, state, profile, catalog)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        # Redirected output is consumed by agents and scripts on every platform.
        for stream in (sys.stdout, sys.stderr):
            if not stream.isatty() and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="backslashreplace")
    args = _parser().parse_args(argv)
    try:
        return _run(args) or 0
    except (OSError, ValueError, EOFError) as error:
        print(f"OpenGuildKit: {str(error) or 'Input ended before completion.'}", file=sys.stderr)
        return 2 if args.command == "ci-check" else 1
    except KeyboardInterrupt:
        print("\nOpenGuildKit: Cancelled.", file=sys.stderr)
        return 130
