"""The commands that set a project up: init, with its questions at a terminal, and sync.

Entry: run, setup_questions.
Tests: tests/test_setup_questionnaire.py, tests/test_first_run.py, tests/test_proportionate_setup.py.
"""

import sys
from pathlib import Path

from .check_cli import pending_catalog_changes, warn_unsigned
from .command import Command
from .detect import components_for_profile, detect_stack, detected_project_name
from .doc_links import doc_link
from .hosts import HOOK_HOSTS
from .lock import apply_lock, build_lock, installed_catalog, read_lock, unshipped_records, write_lock
from .patterns import patterns_to_review
from .profile_changes import print_touched
from .project import RULES_NOTE, load_profile, profile_recommendations
from .project_checks import propose_checks
from .project_instructions import ALREADY_INITIALIZED, initialize, sync_instructions
from .project_rules import require_resolved_conflicts, rule_plan
from .project_setup import GUARD_MODES, init_questions, is_norm, setup_profile, unsure_answers
from .prompts import prompt_questions
from .rule_plan_text import print_rule_plan
from .storage import print_json, project_lock, read_json
from .tasks import tasks_touched
from .terminal import interactive
from .tool_registry import load_tools
from .tools import detect_tools, match_tools
from .wording import plural


def _prompt_components(question: dict) -> list[dict]:
    """Show the detected components and let the person keep them or describe the stack instead."""
    detected = question.get("default") or []
    if not detected:
        return []
    print(f"\n{question['prompt']}", file=sys.stderr)
    for component in detected:
        print(f"  {component['id']} ({component['path']}): {', '.join(component['stack'])}", file=sys.stderr)
    print("  Keep these components? [Y/n/e] (e corrects a component's stack and versions)", file=sys.stderr)
    while True:
        print("> ", end="", file=sys.stderr, flush=True)
        value = input().strip().casefold()
        if value in ("", "y", "yes", "o", "oui"):
            return detected
        if value in ("n", "no", "non"):
            return []
        if value in ("e", "edit"):
            return _edit_components(detected)
        print("  Answer y, n or e.", file=sys.stderr)


def _edit_components(detected: list[dict]) -> list[dict]:
    """Ask for each component's stack, Enter keeping the detected one, so one wrong version costs one line."""
    edited = []
    for component in detected:
        print(f"  {component['id']}: {', '.join(component['stack'])}", file=sys.stderr)
        print("  Enter to keep, or the corrected stack separated by commas (for example PostgreSQL 16).", file=sys.stderr)
        print("> ", end="", file=sys.stderr, flush=True)
        value = input().strip()
        stack = [item.strip() for item in value.split(",") if item.strip()]
        edited.append({**component, "stack": stack or component["stack"]})
    return edited


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


def _interactive_init(questions: list[dict], catalog: dict, registry: dict | None = None) -> dict:
    """Ask the setup questions in order; each norm is confirmed on its own, with the reason it is proposed."""
    by_id = {question["id"]: question for question in questions}
    answers = prompt_questions([by_id["name"], by_id["sector"]], "init")
    components = _prompt_components(by_id["components"])
    if components:
        answers["components"] = components
    else:
        answers.update(prompt_questions([by_id["stack"]], "init"))
    answers.update(prompt_questions([by_id["roles"], by_id["personal_data"]], "init"))
    answers["personal_data"] = answers["personal_data"] == "yes"
    if answers["personal_data"]:
        answers.update(prompt_questions([by_id["people_decisions"]], "init"))
    plan = profile_recommendations(answers, catalog)
    _print_plan_notes(plan)
    kept, declined = _prompt_norms(plan, catalog)
    answers["norms"] = {**dict.fromkeys(kept, "yes"), **declined}
    _print_preselection(plan, catalog)
    patterns = _patterns_question(by_id["patterns"], plan, catalog)
    answers.update(prompt_questions([patterns], "init"))
    answers["patterns"] = [*kept, *_scoped_patterns(answers.get("patterns", []), plan)]
    recommended = [pack["id"] for pack in rule_plan(setup_profile(answers, catalog, questions)[0], catalog)["packs"]]
    packs = {**by_id["packs"], "default_label": f"none beyond the recommended packs: {', '.join(recommended)}"}
    answers.update(prompt_questions([packs, by_id["boards"]], "init"))
    answers.update(_prompt_tools(by_id["tools"], load_tools() if registry is None else registry))
    rest = [by_id[question_id] for question_id in ("host", "guard", "research", "conventions")]
    answers.update(prompt_questions(rest, "init"))
    answers["checks"] = _prompt_checks(by_id["checks"])
    return answers


def _prompt_checks(question: dict) -> list[str]:
    """Offer each test command the repository shows, kept only on a yes, then ask for other checks."""
    kept = []
    proposed = question.get("proposed", [])
    if proposed:
        print("\nTest commands found in the repository. task verify runs each kept command, and a task cannot be "
              "done while one fails: keep a command only if it passes on a workstation with the dependencies "
              "installed. [y/N]", file=sys.stderr)
    for item in proposed:
        print(f"  {item['command']}  ({item['evidence']}). Keep it? [y/N]", file=sys.stderr)
        print("> ", end="", file=sys.stderr, flush=True)
        if input().strip().casefold() in ("y", "yes", "o", "oui"):
            kept.append(item["command"])
    others = {**question, "prompt": "Other project checks to run, if any?"} if proposed else question
    extra = prompt_questions([{key: value for key, value in others.items() if key != "proposed"}], "init")
    return list(dict.fromkeys([*kept, *extra.get("checks", [])]))


def _prompt_norms(plan: dict, catalog: dict) -> tuple[list[str], dict[str, dict]]:
    """Ask, one norm at a time, whether each regulation the project's answers propose applies; a no asks who
    decides (once) and why, recorded with the decline."""
    norms = [pattern for pattern in plan["matched"] if is_norm(catalog["patterns"][pattern["id"]])]
    kept, declined, decider = [], {}, None
    if norms:
        print("\nNorms proposed for this project. Enter keeps a norm; n declines it and it is not proposed again.",
              file=sys.stderr)
    for pattern in norms:
        print(f"  {pattern['id']}: {'; '.join(pattern['reasons'])} ({pattern['title']}). Does it apply? [Y/n]",
              file=sys.stderr)
        print(f"    {pattern['description']}", file=sys.stderr)
        while True:
            print("> ", end="", file=sys.stderr, flush=True)
            value = input().strip().casefold()
            if value in ("", "y", "yes", "o", "oui", "n", "no", "non"):
                break
            print("  Answer y or n.", file=sys.stderr)
        if value in ("", "y", "yes", "o", "oui"):
            kept.append(pattern["id"])
            continue
        decider = decider or _prompt_line("  Your initials or team handle, recorded with the decline: ")
        reason = _prompt_line("  Why does it not apply, in one line? ")
        declined[pattern["id"]] = {"answer": "no", "by": decider, "reason": reason}
    if declined:
        print(f"  Declined, not proposed again: {', '.join(declined)}", file=sys.stderr)
    return kept, declined


def _prompt_line(prompt: str) -> str:
    """Ask until the person types a non-empty line."""
    while True:
        print(prompt, end="", file=sys.stderr, flush=True)
        value = input().strip()
        if value:
            return value


def _patterns_question(question: dict, plan: dict, catalog: dict) -> dict:
    """The patterns question with the preselected stack and role patterns as its default, listed first."""
    matched = [pattern["id"] for pattern in plan["matched"] if not is_norm(catalog["patterns"][pattern["id"]])]
    suggested = [pattern["id"] for pattern in plan["suggested"]]
    position = {pattern_id: index for index, pattern_id in enumerate([*matched, *suggested])}
    choices = sorted(question["choices"], key=lambda choice: position.get(choice["id"], len(position)))
    question = {key: value for key, value in question.items() if key != "default_label"}
    return {**question, "choices": choices, "default": matched}


def _prompt_tools(question: dict, registry: dict) -> dict:
    """Ask for the team's tools, then say which ones the registry knows and which are kept as written."""
    print(f"\nThe registry knows {len(registry)} tools: openguildkit tools list shows them.", file=sys.stderr)
    for item in question.get("detected", []):
        print(f"  The repository shows signs of {item['tool']}: {', '.join(item['signals'])}", file=sys.stderr)
    answers = prompt_questions([question], "init")
    known, unknown = match_tools(answers.get("tools", []), registry)
    if known:
        print(f"  Known to the registry: {', '.join(known)}", file=sys.stderr)
    if unknown:
        print(f"  Not in the registry, kept as written: {', '.join(unknown)}", file=sys.stderr)
    return answers


def _print_preselection(plan: dict, catalog: dict) -> None:
    """Show the other preselected patterns and why, so the person can keep or remove each one."""
    others = [pattern for pattern in plan["matched"] if not is_norm(catalog["patterns"][pattern["id"]])]
    if others:
        print("\nPreselected patterns, keep or remove them at the next question:", file=sys.stderr)
        for pattern in others:
            print(f"  {pattern['id']}: {'; '.join(pattern['reasons'])} ({pattern['rules']} rules)", file=sys.stderr)
        print(f"  {RULES_NOTE}", file=sys.stderr)
    regulations = [pattern["id"] for pattern in plan["suggested"] if pattern.get("kind") == "regulation"]
    methods = [pattern["id"] for pattern in plan["suggested"] if pattern.get("kind") != "regulation"]
    if regulations:
        print(f"Regulations to consider for your roles: {', '.join(regulations)}", file=sys.stderr)
    if methods:
        counted = [f"{pattern['id']} ({pattern['rules']} rules)" for pattern in plan["suggested"]
                   if pattern.get("kind") != "regulation"]
        print(f"Methods and alternatives to consider: {', '.join(counted)}", file=sys.stderr)


def _detected_host(root: Path) -> str | None:
    """The agent host whose files the repository already has, offered as the default answer."""
    if (root / ".claude").is_dir() or (root / "CLAUDE.md").is_file():
        return "claude-code"
    if (root / ".codex").is_dir():
        return "codex"
    if (root / ".gemini").is_dir() or (root / "GEMINI.md").is_file():
        return "gemini-cli"
    return None


def setup_questions(root: Path, state: Path, catalog: dict) -> tuple[list[dict], dict]:
    """The questionnaire with the defaults this repository shows: components, tools and host."""
    registry = load_tools(state / "catalog" / "tools")
    listings: dict[str, set[str]] = {}  # The folders detection walks, so that the proposed checks need no second walk.
    found = detect_stack(root, listings)
    questions = init_questions(catalog, detected_project_name(root), components_for_profile(found),
                               detect_tools(root, registry), _detected_host(root), propose_checks(root, found, listings))
    return questions, registry


def _print_setup_notes(profile: dict, left_aside: list[dict], registry: dict, proposed: list[dict]) -> None:
    """After init: what the guard lets the agent do, the components left aside and the next steps that apply."""
    mode = profile.get("guard", "off")
    host = profile.get("host", "other")
    print(f"Board guard: {GUARD_MODES[mode]}")
    if mode != "off" and host not in HOOK_HOSTS:
        print("  This host has no hook: the reminder is the AGENTS.md instruction, and the CI check catches the rest.")
    print("  To change it: openguildkit profile set guard off|observe|enforce --by INITIALS --reason WHY "
          "(lowering it is typed by the person at a terminal).")
    if mode != "off" and (profile.get("approval") or {}).get("mode") != "signed":
        print("  Approvals are sealed locally: a seal catches an accidental edit, not an agent that writes files. "
              f"To require signed ones: openguildkit profile set approval signed ({doc_link('docs/workflow.md', 'signed-approvals')}).")
    if left_aside:
        names = "; ".join(f"{item['id']} ({item.get('path', '.')}): {', '.join(item['stack'])}" for item in left_aside)
        print(f"OpenGuildKit: the answers give no components, so these detected ones are left aside: {names}. "
              'Add them under "components" to scope the rules to them.', file=sys.stderr)
    known, unknown = match_tools(profile.get("tools", []), registry)
    steps = []
    if host in HOOK_HOSTS:
        steps.append(f"openguildkit host apply    install the {host} settings and hooks, then openguildkit host check")
    if known:
        steps.append(f"openguildkit tools plan {' '.join(known)}    see the MCP servers for the team's tools")
    if steps:
        print("Next steps:")
        for step in steps:
            print(f"  {step}")
    if unknown:
        print(f"Tools not in the registry, kept in the profile: {', '.join(unknown)}. "
              "Describe them in .openguildkit/catalog/tools/ or connect them yourself.")
    _print_check_notes(profile, proposed)


def _print_check_notes(profile: dict, proposed: list[dict]) -> None:
    """Say which checks task verify will run, and the test commands the repository shows that were left out."""
    if profile["checks"]:
        print(f"Project checks run by task verify: {'; '.join(profile['checks'])}. Install the project's "
              "dependencies first: a check that cannot run fails with its cause.")
    left = [item["command"] for item in proposed if item["command"] not in profile["checks"]]
    if left:
        print(f"Test commands found but not kept as project checks: {'; '.join(left)}. "
              f"task verify runs only the project's checks ({doc_link('docs/workflow.md', 'project-checks')}).")
    elif not profile["checks"]:
        print(f"No project check: task verify runs no test command ({doc_link('docs/workflow.md', 'project-checks')}).")


def _print_selection(plan: dict) -> None:
    """Before init --answers writes: each pattern with its reason and rules, so the person sees what the
    answers they confirmed with preview bring."""
    print("Writing these patterns (openguildkit profile decline removes one later):", file=sys.stderr)
    for pattern in plan["patterns"]:
        print(f"  {pattern['id']} ({pattern['rules']} rules): {pattern['reason']}", file=sys.stderr)
    print(f"{plan['rule_count']} rules in force; a task is asked only those that concern it. {RULES_NOTE}",
          file=sys.stderr)
    if plan["rule_warning"]:
        print(f"Warning: {plan['rule_warning']}", file=sys.stderr)


def _confirm_rule_plan(plan: dict) -> None:
    print("", file=sys.stderr)
    print_rule_plan(plan, False, file=sys.stderr)
    print("Write this profile and these rules? [Y/n]", file=sys.stderr)
    print("> ", end="", file=sys.stderr, flush=True)
    if input().strip().casefold() not in ("", "y", "yes", "o", "oui"):
        raise ValueError("Setup cancelled. Nothing was written.")


def _require_answers(answers: dict, questions: list[dict]) -> None:
    """The questions an answers file cannot leave out: those without a default, such as personal data, which
    decides whether the laws on personal data are proposed."""
    missing = [question for question in questions if question.get("required") and question["id"] not in answers]
    if missing:
        lines = "\n".join(f"- {question['id']}: {question['prompt']} Answer "
                          f"{', '.join(choice['id'] for choice in question.get('choices', []))} or unsure "
                          f"({question['unsure']})." for question in missing)
        raise ValueError(f"The setup answers leave out {plural(len(missing), 'question')} that {'needs' if len(missing) == 1 else 'need'} an answer. Nothing was "
                         f"written.\n{lines}")


def init(args, root: Path, state: Path, catalog: dict) -> None:
    """Print the setup questionnaire, or write the profile, the instructions and the catalog lock from the answers."""
    questions, registry = setup_questions(root, state, catalog)
    if args.questions:
        print_json(questions)
        return
    if (state / "project.json").exists():
        raise ValueError(ALREADY_INITIALIZED)
    if not args.answers and not interactive():
        raise ValueError("init needs a terminal for its questions. Without one, print them with openguildkit init "
                         "--questions, save the answers as JSON, then run openguildkit init --answers PATH.")
    answers = read_json(args.answers) if args.answers else _interactive_init(questions, catalog, registry)
    if args.answers and isinstance(answers, dict):
        _require_answers(answers, questions)
    if isinstance(answers, dict):
        for note in unsure_answers(answers, questions)[1]:
            print(f"OpenGuildKit: {note}", file=sys.stderr)
    if not args.answers:
        _confirm_rule_plan(rule_plan(setup_profile(answers, catalog, questions)[0], catalog))
    else:
        planned = setup_profile(answers, catalog, questions)[0]
        require_resolved_conflicts(planned, catalog)
        _print_selection(rule_plan(planned, catalog))
    with project_lock(state):
        live, bundled = installed_catalog(args, state)
        profile, left_aside = setup_profile(answers, live, questions)
        initialize(root, state, profile, live)
        write_lock(state, build_lock(profile, live, bundled, read_lock(state)))
    print(f"Initialized {root}")
    print("Wrote AGENTS.md, the project rules every agent reads, and CLAUDE.md, one line that imports "
          "AGENTS.md for Claude Code. Delete CLAUDE.md if nobody uses Claude Code: check does not require it.")
    if profile.get("host") == "gemini-cli":
        print("Wrote GEMINI.md, one line that imports AGENTS.md for Gemini CLI, which reads GEMINI.md and not AGENTS.md.")
    proposed = next(question for question in questions if question["id"] == "checks").get("proposed", [])
    _print_setup_notes(profile, left_aside if args.answers else [], registry, proposed)
    warn_unsigned(profile)


def sync(args, root: Path, state: Path) -> None:
    """Rewrite the managed instructions and the catalog lock from the profile, and say what that touches."""
    with project_lock(state):
        live, bundled = installed_catalog(args, state)
        lock = read_lock(state)
        catalog = apply_lock(live, lock)
        profile = load_profile(state, catalog)
        replaced = sync_instructions(root, profile, catalog)
        lock = build_lock(profile, catalog, bundled, lock)
        write_lock(state, lock)
    print("OpenGuildKit instructions updated.")
    if replaced:
        print(f"Replaced {plural(len(replaced), 'line')} edited by hand in the managed block of AGENTS.md; keep your own "
              "text outside the markers:")
        for line in replaced[:5]:
            print(f"  - {line[:100]}")
    for record in unshipped_records(lock, bundled):
        print(f"OpenGuildKit: {record} is no longer shipped; it is kept from the catalog lock until you remove it "
              "from .openguildkit/project.json.", file=sys.stderr)
    print_touched(tasks_touched(state, profile, catalog))
    pending = pending_catalog_changes(lock, live, profile, bundled)
    if pending:
        print(f"OpenGuildKit: sync keeps the rules of the catalog lock; the installed catalog changes "
              f"{len(pending)} of its records ({', '.join(pending)}). Run openguildkit update to review them.",
              file=sys.stderr)
    for item in patterns_to_review(profile, catalog):
        print(f"OpenGuildKit: review pattern {item['id']}: {'; '.join(item['reasons'])}", file=sys.stderr)


HANDLERS = {
    "init": lambda command: init(command.args, command.root, command.state, command.catalog),
    "sync": lambda command: sync(command.args, command.root, command.state),
}


def run(command: Command) -> None:
    HANDLERS[command.args.command](command)
