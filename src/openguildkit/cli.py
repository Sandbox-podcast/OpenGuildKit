"""Command-line interface for OpenGuildKit."""

import argparse
import os
import re
import sys
from functools import cache
from importlib import import_module
from pathlib import Path

from . import (
    audit_cli,
    cli_surface,
    completion_cli,
    evidence_cli,
    features_cli,
    managed,
    org_catalog_cli,
    profile_cli,
    projects_cli,
    tasks_cli,
    trace_cli,
)
from .brains import brain_knowledge, knowledge_gaps, reading_list_note, write_brain_skeleton
from .catalog import replaced_boards, undated_sources
from .ci import check_export
from .cli_errors import error_message, print_trace
from .cli_surface import VersionAction, add_by, format_option, hoist_global_options, polish, take_by_warning
from .detect import components_for_profile, detect_stack, detected_project_name
from .doc_links import doc_link
from .errors import unknown
from .guard import (
    NO_TASK,
    approval_text,
    ci_guard,
    covering_approvals,
    exported_decisions,
    guard_mode,
    hook_command,
    scope_note,
)
from .hosts import HOOK_HOSTS, HOSTS, OFF_PATH, apply_host_settings, approval_warning, host_controls
from .integrations import OTHER_HOST_NOTE, install_agent_files
from .lock import (
    LOCK_FILE,
    apply_lock,
    build_lock,
    catalog_changes,
    installed_catalog,
    installed_catalog_date,
    lock_is_current,
    package_version,
    project_catalog,
    read_lock,
    require_instructions,
    unshipped_records,
    update_target,
    write_lock,
)
from .patterns import patterns_to_review, role_choices
from .profile_cli import print_touched
from .project import (
    ALREADY_INITIALIZED,
    GUARD_MODES,
    RULES_NOTE,
    STATE_DIR,
    Fingerprints,
    RuleError,
    complete_answers,
    init_questions,
    initialize,
    is_norm,
    load_profile,
    profile_recommendations,
    project_root,
    require_resolved_conflicts,
    rule_conflicts,
    rule_plan,
    setup_profile,
    state_path,
    sync_instructions,
    unsure_answers,
)
from .project_checks import propose_checks
from .prompts import prompt_questions
from .rule_plan_text import print_recommendations, print_rule_plan
from .storage import print_json, project_lock, read_json, write_json
from .tasks import list_tasks, read_task, task_path, tasks_touched
from .tasks_cli import sharing_issues
from .terminal import interactive
from .tools import detect_tools, load_tools, match_tools
from .wording import plural


def _on_first_call(module: str, name: str):
    """A function of a module that few commands use, imported when it is first called, so that the other commands
    start without that module (the web server alone added about 30 ms to every command, the edit hook included)."""
    def call(*args, **kwargs):
        return getattr(import_module(f"{__package__}.{module}"), name)(*args, **kwargs)

    call.__name__ = call.__qualname__ = name
    return call


draft_problems, launch_notice, load_deliverables, new_draft, project_path, utm_link = (
    _on_first_call("deliverables", name)
    for name in ("draft_problems", "launch_notice", "load_deliverables", "new_draft", "project_path", "utm_link"))
add_share, export_docs, project_overview, revoke_share, same_access, share_status, shared_addresses, space_neighbours = (
    _on_first_call("publishing", name)
    for name in ("add_share", "export_docs", "project_overview", "revoke_share", "same_access", "share_status",
                 "shared_addresses", "space_neighbours"))
render_scan, scan_exit_code, scan_report, scan_sarif = (
    _on_first_call("surfaces", name) for name in ("render_scan", "scan_exit_code", "scan_report", "scan_sarif"))
alerts_run, market_run, storybook_run, tools_run = (_on_first_call(f"{name}_cli", "run")
                                                   for name in ("alerts", "market", "storybook", "tools"))
english_title, find_references, load_references, with_pattern_references = (
    _on_first_call("references", name)
    for name in ("english_title", "find_references", "load_references", "with_pattern_references"))
# The port of openguildkit ui, here so that the help does not import the web server; webui.DEFAULT_PORT is the
# same number (tests/test_performance.py compares the help with it).
UI_PORT = 7311


@cache
def command_parser(left_out: frozenset[str] = frozenset()) -> argparse.ArgumentParser:
    """The CLI's argument parser, built once per process: building it costs more than parsing a command, and the
    web server parses one command after another. The commands of the modules left_out (cli_surface.deferred_modules)
    get their line of the root's help and no options."""
    parser = argparse.ArgumentParser(prog="openguildkit", description="Project rules and specialist reviews for AI-assisted work.")
    parser.add_argument("--version", action=VersionAction)
    parser.add_argument("--project", type=Path, help="Project root (defaults to the closest configured ancestor). "
                                                     "It may also follow the command.")
    policy = parser.add_argument_group("central policy", "Where the central export-link-expiry rule is read from (ci-check).")
    policy.add_argument("--policy-repo", type=Path, help="Local Git repository with the central export rule.")
    policy.add_argument("--policy-commit", help="Full Git SHA of the central policy commit.")
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
    brains.add_argument("--check", action="store_true", help="Fail when a brain has no method or no reference.")
    brains.add_argument("--new", metavar="ID", help="Write the skeleton of a project brain in .openguildkit/catalog.")
    init = commands.add_parser("init", help="Initialize a project profile and agent instructions.")
    init_mode = init.add_mutually_exclusive_group()
    init_mode.add_argument("--questions", action="store_true", help="Print the setup questionnaire as JSON.")
    init_mode.add_argument("--answers", type=Path, help="Read setup answers from a JSON file.")
    commands.add_parser("sync", help="Update the managed instructions from the project profile.")
    guard = commands.add_parser("guard", help="Say whether an approved task covers the work, for hooks and CI.")
    guard_mode = guard.add_mutually_exclusive_group()
    guard_mode.add_argument("--hook", choices=("prompt", "pre-edit"), help="Run as a host hook; reads the hook input on stdin.")
    guard_mode.add_argument("--ci", action="store_true", help="Check the decisions exported for the changes since --base.")
    guard.add_argument("--base", default="origin/main", help="Base revision for --ci (default origin/main).")
    guard.add_argument("--require-signed", action="store_true",
                       help="With --ci, fail while the base revision's approvals are local and cannot be verified.")
    guard.add_argument("--org-catalog", action="append", metavar="NAME=PATH",
                       help="With --ci, the copy of the organization catalog that the lock calls NAME.")
    guard.add_argument("--json", action="store_true", help="Print the result as JSON.")
    format_option(guard, "With --ci, print the problems")
    deliverable = commands.add_parser("deliverable", help="Start and check a business deliverable from an approved task.")
    deliverable_actions = deliverable.add_subparsers(dest="deliverable_action", required=True)
    deliverable_actions.add_parser("list", help="List the deliverable templates.")
    show_deliverable = deliverable_actions.add_parser("show", help="Show a template: inputs, approvals and checks.")
    show_deliverable.add_argument("id")
    new_deliverable = deliverable_actions.add_parser("new", help="Write a draft for an approved task.")
    new_deliverable.add_argument("id")
    new_deliverable.add_argument("--task", required=True, help="Approved task the deliverable comes from.")
    new_deliverable.add_argument("--tool", help="Tool the team will use, from the profile's approved tools (optional).")
    new_deliverable.add_argument("--output", type=Path, required=True, help="Markdown file to write.")
    check_deliverable = deliverable_actions.add_parser("check", help="List what keeps a draft from review.")
    check_deliverable.add_argument("path", type=Path)
    utm = deliverable_actions.add_parser("utm", help="Print a landing URL tagged with the campaign's UTM parameters.")
    utm.add_argument("--url", required=True, help="https address of the landing page.")
    for name in ("campaign", "source", "medium"):
        utm.add_argument(f"--{name}", required=True, help=f"utm_{name} value agreed with the analytics owner.")
    utm.add_argument("--content", help="utm_content value, to tell links of the same campaign apart.")
    utm.add_argument("--term", help="utm_term value, for paid search keywords.")
    docs = commands.add_parser("docs", help="Export documentation of completed tasks and track who it is shared with.")
    docs_actions = docs.add_subparsers(dest="docs_action", required=True)
    export = docs_actions.add_parser("export", help="Write Reference, Learn and Blog pages for Documentalist.")
    export.add_argument("--tasks", required=True, help="Comma-separated IDs of completed tasks to document.")
    export.add_argument("--output", type=Path, required=True, help="Folder to write, for example docs-site.")
    export.add_argument("--version", dest="doc_version", required=True, help="Project version the pages describe.")
    export.add_argument("--sections", default="project,reference,learn,blog", help="Sections to write.")
    export.add_argument("--openapi", type=Path, help="OpenAPI file to place next to the pages.")
    share = docs_actions.add_parser("share", help="Record, list, revoke or check the shares of a deliverable.")
    share.add_argument("share_action", choices=("add", "list", "revoke", "check", "verify"))
    share.add_argument("--deliverable", help="Page or folder shared (add).")
    share.add_argument("--recipient", action="append", default=[], help="Recipient email address (add, repeatable).")
    share.add_argument("--until", help="Last day of access, YYYY-MM-DD; set it in the portal too (add).")
    share.add_argument("--portal", help="Address of the shared space's portal, https://HOST/p/SPACE; http only on this "
                                        "machine (add, verify).")
    share.add_argument("--id", dest="share_id", help="Share ID (revoke).")
    add_by(share)
    share.add_argument("--dedicated-space", action="store_true",
                       help="Record the space as holding this deliverable only: another deliverable is refused in it (add).")
    share.add_argument("--user", help="Documentalist editor account email (verify; password is prompted at the terminal).")
    share.add_argument("--json", action="store_true", help="Print the shares as JSON.")
    cli_surface.add_module_parsers(commands, left_out, ("tools_cli", "features_cli", "profile_cli", "alerts_cli", "market_cli",
        "storybook_cli", "trace_cli", "projects_cli", "org_catalog_cli", "audit_cli", "evidence_cli", "completion_cli"))
    agent = commands.add_parser("integrations", help="Install the agent skill and subagent of this version.")
    agent.add_argument("--host", required=True, choices=HOSTS,
                       help="Agent to configure (other: the Agent Skills folder .agents/skills/).")
    agent.add_argument("--user", action="store_true", help="Install in the home folder for every project.")
    agent.add_argument("--force", action="store_true", help="Replace modified files, keeping a .previous copy.")
    _host_parser(commands)
    update = commands.add_parser("update", help="Show what the installed catalog would change and adopt it.")
    update.add_argument("--apply", action="store_true", help="Adopt the installed catalog's records for this project.")
    update.add_argument("--json", action="store_true", help="Print the changes as JSON.")
    check = commands.add_parser("check", help="Check that the instructions match the project profile.")
    format_option(check, "Print the problems")
    commands.add_parser("mcp", help="Serve read-only project metadata to a local MCP client. Requires --project.")
    ui = commands.add_parser("ui", help="Open the web interface of this project on 127.0.0.1.")
    ui.add_argument("--port", type=int, default=UI_PORT, help=f"Port (default {UI_PORT}; 0 picks a free one).")
    ui.add_argument("--no-browser", action="store_true", help="Print the address without opening a browser.")
    ui.add_argument("--static", type=Path, help="Folder of a built front end (default: the one installed with the package).")
    ui.add_argument("--stable-address", action="store_true", help="Keep the host name from one launch to the next, so the browser keeps the page's preferences. It comes from the project's path, which another local program can compute.")
    ci = commands.add_parser("ci-check", help="Evaluate the central export rule on an exact Git commit.")
    ci.add_argument("--target-repo", type=Path, required=True, help="Local Git repository with the target commit.")
    ci.add_argument("--commit", required=True, help="Full Git SHA of the target commit.")

    tasks_cli.add_parser(commands)
    polish(parser)
    return parser


def _host_parser(commands) -> None:
    """The host command: check, apply, scan and managed, with their options."""
    host = commands.add_parser("host", help="Show or apply the rules the host agent can enforce, or scan its files.")
    host.add_argument("mode", choices=("check", "apply", "scan", "managed"),
                      help="check reports each rule; apply writes the host settings; scan reads the instruction files "
                           "and agent settings for hidden characters, phrases that cancel the rules and risky commands; "
                           "managed prints the settings file an administrator deploys by MDM for one host.")
    host.add_argument("--json", action="store_true", help="Print the report as JSON.")
    host.add_argument("--strict", action="store_true", help="With scan: exit 1 on any finding, not only an error.")
    format_option(host, "With scan, print the findings")
    managed.add_options(host)


def _pending_catalog_changes(lock: dict | None, live: dict, profile: dict, bundled: dict) -> list[str]:
    """Locked records whose rules the installed catalog changes; a source checked again changes no rule."""
    if lock is None:
        return []
    changes = catalog_changes(lock, live, update_target(live, lock), profile, bundled)
    return [
        f"{change['collection']}/{change['id']}" for change in changes
        if change["status"] != "changed" or set(change["fields"]) != {"sources"}
        or change["sources"]["added"] or change["sources"]["removed"]
    ]


def _undated_project_sources(state: Path, live: dict) -> list[str]:
    """Project records that cite a source without a checked date; bundled sources always carry one. The project's
    references are read with the catalog it uses, so a pack or a brain they name that does not exist stops check."""
    project = state / "catalog"
    in_use = apply_lock(live, read_lock(state))
    references = {
        "references": {record["id"]: record for family in load_references(project / "references", in_use).values()
                       for record in family["references"]},
        "deliverables": load_deliverables(live, project / "deliverables"),
    }
    return undated_sources({**live, **references})


def _update_catalog(args, root: Path, state: Path) -> None:
    with project_lock(state):
        load_tools(state / "catalog" / "tools")
        live, bundled = installed_catalog(args, state)
        lock = read_lock(state)
        if lock is None:
            catalog = live
            profile = load_profile(state, catalog)
            if args.apply:
                sync_instructions(root, profile, catalog)
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
            # The tasks are named before --apply, and sync names the same ones afterwards.
            touched = tasks_touched(state, profile, target) if changes else []
            result = {"changes": changes, "conflicts": conflicts, "applied": False, "stale_tasks": touched}
            if args.apply and changes:
                sync_instructions(root, profile, target)
                write_lock(state, build_lock(profile, target, bundled, lock))
                result["applied"] = True
        result["catalog_date"] = installed_catalog_date()
    _print_update(result, args.json)


def _print_update(result: dict, as_json: bool) -> None:
    if as_json:
        print_json(result)
        return
    date = result.get("catalog_date") or "unknown"
    if result.get("note"):
        print(f"Installed catalog: sources checked up to {date}.")
        print(result["note"])
        return
    count = len(result["changes"])
    print(f"Installed catalog: sources checked up to {date}. "
          f"{count} {'record' if count == 1 else 'records'} changed since the project's lock.")
    if not result["changes"]:
        print("The project's rules match the installed catalog.")
        return
    for change in result["changes"]:
        label = f"{change['collection']}/{change['id']}"
        if change["status"] == "added":
            print(f"+ {label} {change.get('version') or ''}".rstrip())
            continue
        if change["status"] != "changed":
            print(f"- {label}: {change['status']}, kept from the lock until you remove it from .openguildkit/project.json")
            continue
        version = f" {change['version'][0]} -> {change['version'][1]}" if "version" in change else ""
        print(f"~ {label}{version} ({', '.join(change['fields'])})")
        for rule in change.get("rules", {}).get("added", []):
            print(f"    + rule {rule['id']}: {rule['text']}")
        for rule_id in change.get("rules", {}).get("removed", []):
            print(f"    - rule {rule_id}")
        for rule in change.get("rules", {}).get("changed", []):
            print(f"    ~ rule {rule['id']}")
            print(f"        before: {rule['before']}")
            print(f"        after:  {rule['after']}")
        for url in change["sources"]["added"]:
            print(f"    + source {url}")
        for url in change["sources"]["removed"]:
            print(f"    - source {url}")
        redated = change["sources"].get("redated", [])
        if redated:
            latest = max((item["checked"][1] or "" for item in redated), default="")
            print(f"    ~ {len(redated)} {'source' if len(redated) == 1 else 'sources'} checked again, latest {latest}")
    for conflict in result["conflicts"]:
        print(f"! {' and '.join(conflict['packs'])} conflict: record a resolution before applying.")
    if not result["applied"]:
        print_touched(result["stale_tasks"], before=True)
        print("Nothing changed. Run openguildkit update --apply to adopt these rules.")
        return
    print("Applied. The next consultations use these rules.")
    print_touched(result["stale_tasks"])


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


HOST_STATUS_LABELS = {"instruction": "by instruction", "human": "by a person"}
NO_HOST_SETTINGS = (
    "the project's host is other, so host apply wrote nothing: OpenGuildKit writes host settings only for "
    "claude-code, codex and gemini-cli. The rules above stay with the AGENTS.md instructions and the CI check. To "
    "install the settings and hooks for one of these agents, run openguildkit profile set host claude-code (or codex) "
    "--by INITIALS --reason WHY, then openguildkit host apply. For Gemini CLI, set the host to gemini-cli."
)


def _detected_host(root: Path) -> str | None:
    """The agent host whose files the repository already has, offered as the default answer."""
    if (root / ".claude").is_dir() or (root / "CLAUDE.md").is_file():
        return "claude-code"
    if (root / ".codex").is_dir():
        return "codex"
    if (root / ".gemini").is_dir() or (root / "GEMINI.md").is_file():
        return "gemini-cli"
    return None


def _setup_questions(root: Path, state: Path, catalog: dict) -> tuple[list[dict], dict]:
    """The questionnaire with the defaults this repository shows: components, tools and host."""
    registry = load_tools(state / "catalog" / "tools")
    listings = {}  # The folders detection walks, so that the proposed checks need no second walk.
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


def _print_catalog(catalog: dict, as_json: bool) -> None:
    groups = ("packs", "boards", "sectors")
    if as_json:
        print_json({group: catalog[group] for group in groups})
        return
    width = max(len(entry["id"]) for group in groups for entry in catalog[group].values())
    for group in groups:
        print(group.capitalize())
        for entry in catalog[group].values():
            preselected = _sector_packs(catalog, entry["id"]) if group == "sectors" else []
            suffix = f" (preselects {', '.join(preselected)})" if preselected else ""
            print(f"  {entry['id']:<{width}} {entry['title']}{suffix}")


def _sector_packs(catalog: dict, sector_id: str) -> list[str]:
    """The packs of the patterns that a sector preselects without a stack."""
    return [
        pack_id
        for pattern in catalog["patterns"].values()
        if sector_id in pattern.get("match", {}).get("sectors", []) and not pattern["match"].get("stack")
        for pack_id in pattern["packs"]
    ]


def _print_references(args, state: Path, catalog: dict) -> None:
    families = with_pattern_references(load_references(state / "catalog" / "references", catalog), catalog["patterns"])
    if not args.json and all(value is None for value in (args.query, args.family, args.id)):
        print(f"{sum(len(family['references']) for family in families.values())} references")
        for family in families.values():
            print(f"  {family['id']:<14} {family['title']} ({len(family['references'])})")
        return
    matches = find_references(families, family_id=args.family, query=args.query, record_id=args.id)
    if args.json:
        print_json(matches)
    elif args.id:
        reference = matches[0]
        print(f"{english_title(reference)} [{reference['id']}]")
        if english_title(reference) != reference["title"]:
            print(f"Original title: {reference['title']}")
        print(f"{reference['family_title']} / {reference['category']} / {reference['kind']}")
        if reference.get("edition"):
            print(f"Edition: {reference['edition']}")
        print(f"\n{reference['summary']}\n{reference['applies_when']}\n")
        if reference.get("pattern"):
            print(f"Pattern: openguildkit patterns --id {reference['pattern']}")
        packs = [catalog["packs"][pack_id] for pack_id in reference.get("packs", []) if pack_id in catalog["packs"]]
        for pack in packs:
            print(f"Pack {pack['id']}@{pack['version']}: {', '.join(rule['id'] for rule in pack['rules'])}")
        if not packs:
            print("Status: documentary reference. No pack turns it into rules yet.")
        print()
        for source in reference["sources"]:
            print(_source_line(source))
    elif matches:
        for reference in matches:
            print(f"  {reference['id']:<34} {english_title(reference)} [{reference['family']}]")
    else:
        print("No references matched.")


def _source_line(source: dict) -> str:
    """A source as printed for a person, with the day its page was last checked."""
    checked = f" (checked {source['checked']})" if "checked" in source else ""
    return f"- {source['title']}: {source['url']}{checked}"


def _print_patterns(args, patterns: dict) -> None:
    roles = role_choices(patterns)
    if args.role and args.role not in roles:
        raise ValueError(f"Unknown role: {args.role}. Available roles: {', '.join(roles)}.")
    matches = [
        pattern for pattern in patterns.values()
        if (not args.role or args.role in pattern["roles"]) and (not args.id or args.id == pattern["id"])
    ]
    if args.id and not matches:
        raise ValueError(unknown("pattern", args.id, "patterns"))
    if args.json:
        print_json(matches)
        return
    if args.id:
        pattern = matches[0]
        print(f"{pattern['title']} [{pattern['id']}]")
        print(pattern["description"])
        print(f"Roles: {', '.join(pattern['roles'])}")
        print(f"Packs: {', '.join(pattern['packs'])}")
        match = pattern.get("match", {})
        if match.get("stack"):
            requirements = [" / ".join(group) for group in match["stack"]]
            print(f"Stack requirements: {' + '.join(requirements)}")
        if match.get("sectors"):
            print(f"Sectors: {', '.join(match['sectors'])}")
        if match.get("personal_data"):
            print("Preselected when the project processes personal data")
        for source in pattern["sources"]:
            print(_source_line(source))
        return
    print(f"{len(matches)} patterns")
    for pattern in matches:
        print(f"  {pattern['id']:<33} {pattern['title']} [{', '.join(pattern['roles'])}]")


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


def _print_detection(detected: dict, as_json: bool) -> None:
    if as_json:
        print_json(detected)
        return
    if not detected["components"]:
        print("No known manifest found. Describe the stack during init.")
        return
    for component in detected["components"]:
        print(f"{component['id']} ({component['path']})")
        for item in component["evidence"]:
            version = item["version"] or item.get("note") or "version unknown"
            note = ", inferred from a client library" if item["inferred"] else ""
            print(f"  {item['name']}: {version} [{item['evidence']}{note}]")


def _guard_hook(args) -> int:
    """Run as a host hook: in enforce mode, an edit the guard cannot check is refused.

    Hosts reach guard.hook_command through __main__ without this module; this path serves --policy-repo and the
    tests that call main().
    """
    return hook_command(args.hook, args.project, lambda state: project_catalog(args, state))


def _print_guard_sarif(root: Path, found: list[dict], mode: str) -> None:
    from .check_findings import Report

    report = Report(True)
    report.guard(found, mode)
    print(report.text(root), end="")


def _require_sarif_options(args) -> None:
    """--format sarif belongs to check, to guard --ci and to host scan, and it does not go with --json: both print on
    the standard output, so say which one to type."""
    if args.command == "host" and args.format == "sarif":
        if args.mode != "scan":
            raise ValueError("--format sarif writes the findings of the scan: type openguildkit host scan --format sarif.")
        if args.json:
            raise ValueError("--format sarif and --json both print the result on the standard output: use one of them. "
                             "Type openguildkit host scan --format sarif for code scanning, or openguildkit host scan "
                             "--json for a program.")
    if args.command == "guard" and args.format == "sarif":
        if not args.ci:
            raise ValueError("--format sarif writes the result of the CI check: type openguildkit guard --ci "
                             "--format sarif.")
        if args.json:
            raise ValueError("--format sarif and --json both print the result on the standard output: use one of them. "
                             "Type openguildkit guard --ci --format sarif for code scanning, or openguildkit guard --ci "
                             "--json for a program.")


def _guard(args, root: Path, state: Path) -> int:
    if args.ci:
        found: list[dict] = []
        result = ci_guard(root, args.base, lambda base_state: project_catalog(args, base_state),
                          require_signed=args.require_signed, findings=found, org_catalog=args.org_catalog)
        if args.format == "sarif":
            _print_guard_sarif(root, found, result["mode"])
        elif args.json:
            print_json(result)
        else:
            print(f"Guard mode on {args.base}: {result['mode']}. {plural(result['changed'], 'changed file')}.")
            for task_id in result["decisions"]:
                # A valid record covers the change only when nothing else is wrong, such as a file it does not list.
                where = result["records"][task_id]
                print(f"  Covered by the decision of task {task_id} ({where})." if result["ok"]
                      else f"  Valid decision of task {task_id} ({where}), but the check fails:")
            for problem in result["problems"]:
                print(f"  {problem}")
            for note in result["notes"]:
                print(f"  Note: {note}")
            if not result["ok"] and result["mode"] != "enforce":
                print(f"  Flagged, not blocking. Not enforced: the guard mode of {args.base} is {result['mode']}, so "
                      "this job passes; set \"guard\": \"enforce\" in the profile to fail it.")
        if result["ok"] or result["mode"] != "enforce":
            return 0
        return 1
    catalog = project_catalog(args, state)
    profile = load_profile(state, catalog)
    approvals = covering_approvals(root, state, profile, catalog)
    result = {"mode": guard_mode(profile), "covered_by": [item["task"] for item in approvals], "approvals": approvals,
              # Committed decisions show what the repository carries; only a local approved task covers new edits.
              "exported_decisions": [row["task"] for row in exported_decisions(
                  root, state, profile, Fingerprints(profile, catalog)) if not row["problem"]]}
    if args.json:
        print_json(result)
    elif not approvals:
        print(NO_TASK)
    else:
        print("Approved task in progress:" if len(approvals) == 1 else "Approved tasks in progress:")
        for item in approvals:
            print(f"  {approval_text(item)}")
        print(scope_note(approvals))
    return 0


def _deliverable(args, root: Path, state: Path, profile: dict, catalog: dict) -> int:
    templates = load_deliverables(catalog, state / "catalog" / "deliverables")
    action = args.deliverable_action
    if action == "list":
        width = max((len(key) for key in templates), default=0)
        for template in templates.values():
            method = f" (method {template['method']})" if template.get("method") else ""
            print(f"{template['id']:<{width}} {template['title']}{method} [{', '.join(template['brains'])}]")
        return 0
    if action == "utm":
        names = ("source", "medium", "campaign", "content", "term")
        print(utm_link(args.url, {name: getattr(args, name) for name in names}))
        return 0
    if action == "check":
        path = project_path(root, state, args.path, "deliverable check")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeError as error:
            raise ValueError(f"{args.path} is not UTF-8 text ({error}): save the draft as UTF-8.") from error
        match = re.search(r'^deliverable: "([a-z0-9-]+)"$', text, re.MULTILINE)
        if not match or match.group(1) not in templates:
            raise ValueError(f"{args.path} is not a draft written by openguildkit deliverable new.")
        problems = draft_problems(templates[match.group(1)], text)
        for problem in problems:
            print(f"- {problem}")
        if not problems:
            print("Ready for review by " + ", ".join(templates[match.group(1)]["brains"]))
        return 1 if problems else 0
    if args.id not in templates:
        raise ValueError(unknown("deliverable", args.id, "deliverable list"))
    template = templates[args.id]
    if action == "show":
        print(f"{template['title']} [{template['id']}]\n{template['description']}\nBefore starting the tool:")
        for line in launch_notice(template):
            print(f"  - {line}")
        print("Checks:")
        for check in template["checks"]:
            print(f"  - {check['id']}: {check['verification']}")
        return 0
    task = read_task(state, args.task)
    output = project_path(root, state, args.output, "--output")
    entry = new_draft(template, task, args.tool, profile.get("tools", []), output)
    with project_lock(state):
        current = read_task(state, args.task)
        write_json(task_path(state, args.task), {**current, "deliverables": [*current.get("deliverables", []), entry]})
    print("Before starting the tool:")
    for line in launch_notice(template):
        print(f"  - {line}")
    print(f"Draft written to {args.output.as_posix()}")
    return 0


def _docs(args, root: Path, state: Path, profile: dict, catalog: dict) -> int:
    if args.docs_action == "export":
        tasks = [item.strip() for item in args.tasks.split(",") if item.strip()]
        sections = tuple(item.strip() for item in args.sections.split(",") if item.strip())
        output = project_path(root, state, args.output, "--output")
        openapi = project_path(root, state, args.openapi, "--openapi") if args.openapi else None
        result = export_docs(state, tasks, output, args.doc_version, sections, openapi, profile["name"],
                             project_overview(profile, catalog))
        for path in result["written"]:
            print(f"wrote {path}")
        for path in result["removed"]:
            print(f"removed {path}")
        for path in result["kept"]:
            print(f"kept {path}: not a page this export wrote inside {args.output.as_posix()}, left in place")
        for warning in result["warnings"]:
            print(f"OpenGuildKit: {warning}", file=sys.stderr)
        return 0
    if args.share_action == "add":
        if not (args.deliverable and args.until and args.portal and args.by):
            raise ValueError("docs share add needs --deliverable, --recipient, --until, --portal and --by.")
        share = add_share(state, args.deliverable, args.recipient, args.until, args.portal, args.by, args.dedicated_space)
        _print_share_added(share)
        for given in dict.fromkeys(args.recipient):
            if given not in share["recipients"]:
                kept = shared_addresses(share, {"recipients": [given]})[0]
                print(f"OpenGuildKit: {given} and {kept} differ only in case, so they are one reader: the share records "
                      f"{kept}.", file=sys.stderr)
        for other in space_neighbours(state, share):
            print(f"OpenGuildKit: space {share['space']} also carries {other['deliverable']} (share {other['id']}): the "
                  f"recipients of each share can read both deliverables. To share {share['deliverable']} on its own, "
                  "publish it in a space of its own and record it with --dedicated-space.", file=sys.stderr)
        for other in same_access(state, share, running=True):
            for recipient in shared_addresses(share, other):
                print(f"OpenGuildKit: {recipient} already has access to space {share['space']} through share {other['id']} "
                      f"(until {other['until']}). Documentalist keeps one access per address and space: give it the later "
                      f"last day, {max(share['until'], other['until'])}, in the portal; removing it there ends both shares, "
                      "so revoke them together.", file=sys.stderr)
        return 0
    if args.share_action == "revoke":
        if not args.share_id or not args.by:
            raise ValueError("docs share revoke needs --id and --by.")
        share = revoke_share(state, args.share_id, args.by)
        print("revoked")
        space = share["space"] or f"of the portal {share['portal']}"
        print(f"\"Retirer l'accès\" in Documentalist removes an address from the whole space {space}, not only from "
              f"{share['deliverable']}.")
        others = same_access(state, share)
        if others:
            shared = sorted({recipient for other in others for recipient in shared_addresses(share, other)})
            print(f"Other shares give {', '.join(shared)} the same space: if you removed that access there, they lost it "
                  "too. Record each one:")
            for other in others:
                print(f"  openguildkit docs share revoke --id {other['id']} --by INITIALS   "
                      f"# {', '.join(other['recipients'])}, {other['deliverable']}, until {other['until']}")
        return 0
    if args.share_action == "verify":
        if not args.portal or not args.user:
            raise ValueError("docs share verify needs --portal and --user; the password is requested at the terminal.")
        from .portal_verification import verify_portal
        report = verify_portal(state, args.portal, args.user)
        if args.json:
            print_json(report)
        else:
            print(f"{report['space']}: {report['source']} at {report['checked_at']}")
            print(report["scope"])
            if report["problem"]:
                print(report["problem"])
            for item in report["rows"]:
                print(f"  {item['recipient']}: register until {item['register_until'] or 'no running share'}; "
                      f"portal {_portal_state(item)}; {item['status']}")
                if item.get("action"):
                    print(f"    {item['action']}")
        return 0 if report["source"] == "documentalist-api" and all(row["status"] == "matches" for row in report["rows"]) else 1
    rows = share_status(state)
    if args.json:
        print_json(rows)
    elif not rows:
        print("No share recorded.")
    else:
        for row in rows:
            _print_share_row(row)
    expired = [row for row in rows if row["state"].startswith("expired")]
    # A dedicated space that carries another deliverable no longer isolates it: the register was edited by hand.
    breached = [row for row in rows if row["dedicated"] and row["also_in_space"]]
    return 1 if args.share_action == "check" and (expired or breached) else 0


def _print_share_added(share: dict) -> None:
    """Say what the recipients really get and that the end date is the owner's to keep."""
    print(f"Share {share['id']} recorded. Its perimeter is the whole space {share['space']}: Documentalist shows the "
          f"recipients every published page of that space, not only {share['deliverable']}. Publish the deliverable in a "
          "space that holds only it, or hide the other pages.")
    if share.get("dedicated"):
        print(f"Space {share['space']} is recorded as dedicated to {share['deliverable']}: the register refuses another "
              "deliverable in it. OpenGuildKit cannot see what the space publishes: check from a reader session that "
              "its navigation and search show only this deliverable.")
    print("Invite the recipients now in that space's reader settings (magic link mode).")
    print(f"Set the last day {share['until']} in Documentalist if supported. On older versions remove access there "
          f"after that day, then run openguildkit docs share revoke --id {share['id']} --by INITIALS. "
          "The local check is a reminder; it does not contact the portal.")


def _portal_state(item: dict) -> str:
    """What the portal's invitation settings said for one recipient of docs share verify."""
    if item.get("source") != "documentalist-api":
        return "not verified"
    if not item.get("invited"):
        return "not invited"
    state = "open" if item.get("policy_active") else "ended"
    return f"until {item['portal_until']} ({state})" if item.get("portal_until") else "invited with no end date (open)"


def _print_share_row(row: dict) -> None:
    """One share with its perimeter and state; one past its last day says which access to remove and which to keep."""
    space = row["space"] or "unknown: the portal address names no /p/SPACE"
    print(f"{row['id']} {row['deliverable']} (whole space {space}) until {row['until']} "
          f"({plural(len(row['recipients']), 'recipient')}): {row['state']}")
    if row["also_in_space"]:
        dedicated = " although the space is recorded as dedicated to this deliverable" if row["dedicated"] else ""
        print(f"  its recipients can also read {', '.join(row['also_in_space'])}, shared through the same space{dedicated}")
    if row.get("portal_observation"):
        observed = row["portal_observation"]
        print(f"  last portal observation: {observed['source']} at {observed['checked_at']} (may be outdated)")
        for item in observed["rows"]:
            print(f"    {item.get('recipient')}: {item.get('status')}, portal {_portal_state(item)}")
    for recipient in row["remove"]:
        print(f"  remove {recipient} from space {space} in Documentalist (\"Retirer l'accès\")")
    for recipient, other in sorted(row["kept"].items()):
        print(f"  keep {recipient}: share {other['share']} gives the same space until {other['until']}")
    if row["remove"]:
        print(f"  then record it: openguildkit docs share revoke --id {row['id']} --by INITIALS")


def _print_brains(args, catalog: dict, families: dict) -> int:
    boards = catalog["boards"]
    if args.id and args.id not in boards:
        raise ValueError(f"Unknown brain: {args.id}. Run openguildkit brains.")
    if args.check:
        gaps = knowledge_gaps(catalog, families)
        for gap in gaps:
            print(f"- {gap}")
        print(f"{len(boards)} brains, {plural(len(gaps), 'gap')}.")
        return 1 if gaps else 0
    if args.json:
        if args.id:
            print_json({**boards[args.id], "knowledge": brain_knowledge(args.id, catalog, families)})
        else:
            print_json(boards)
    elif args.id:
        board = boards[args.id]
        print(f"{board['title']} [{board['id']}]")
        print(board["description"])
        if "review" in board:
            plan = board["review"]
            for specialist in plan["specialists"]:
                print(f"  {specialist['title']}: {specialist['focus']}")
                for check in specialist.get("checks", []):
                    print(f"    - {check}")
            for heading, key in (
                ("Evidence to inspect", "evidence"),
                ("Challenge questions", "challenge"),
                ("Decision criteria", "decision_criteria"),
            ):
                print(f"\n{heading}")
                for question in plan[key]:
                    print(f"  - {question}")
        knowledge = brain_knowledge(args.id, catalog, families)
        print("\nMethods")
        for item in knowledge["methods"]:
            print(f"  - {item['title']} [{item['id']}]")
        print("\nRule packs")
        for item in knowledge["packs"]:
            print(f"  - {item['title']} [{item['id']}@{item['version']}]")
        print("\nReferences and standards")
        print(f"  {reading_list_note(len(knowledge['references']))}")
        for item in knowledge["references"]:
            edition = f" ({item['edition']})" if item.get("edition") else ""
            print(f"  - {item['title']}{edition}: {item['url']}")
        used = [tool["title"] for tool in load_tools().values() if args.id in tool["brains"]]
        print(f"\nTools this brain can use ({len(used)}): {', '.join(used)}")
        print(f"  Details: openguildkit tools list --brain {args.id}")
    else:
        width = max(len(board_id) for board_id in boards)
        for board in boards.values():
            reviewers = board.get("review", {}).get("specialists", [])
            count = f" ({len(reviewers)} specialists)" if reviewers else ""
            print(f"  {board['id']:<{width}} {board['title']}{count}")
    return 0


def _new_brain(args, state: Path, catalog: dict) -> int:
    """Write a project brain's skeleton and say which tasks the new brain makes stale."""
    with project_lock(state):
        written = write_brain_skeleton(state / "catalog", args.new, catalog)
        updated = project_catalog(args, state)
    for path in written:
        print(f"Wrote {path.as_posix()}")
    print("Replace each TODO, then run openguildkit brains --check and openguildkit sync.")
    if not (state / "project.json").is_file():
        return 0
    profile = load_profile(state, catalog)
    if profile["boards"]:
        print(f"The profile lists its boards: openguildkit profile add board {args.new} --by INITIALS --reason WHY "
              "lets it review tasks.")
        return 0
    already = {task["id"] for task in tasks_touched(state, profile, catalog)}
    stale = [task for task in tasks_touched(state, profile, updated) if task["id"] not in already]
    for task in stale:
        print(f"Task {task['id']} ({task['status']}) was consulted without {args.new}: once you sync, "
              "it needs a new review before work continues.")
    if not stale:
        print(f"No task was reviewed under the previous board. New tasks will be routed to {args.new} by its triggers.")
    return 0


def _warn_unsigned(profile: dict, report=None) -> None:
    """Say once per setup or check command, not on every command, that local approvals can be forged."""
    warning = approval_warning(profile)
    if warning:
        print(warning, file=sys.stderr)
        if report is not None:
            report.add("approvals-not-signed", "warning", warning.removeprefix("OpenGuildKit: "))


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


def _init(args, root: Path, state: Path, catalog: dict) -> None:
    """Print the setup questionnaire, or write the profile, the instructions and the catalog lock from the answers."""
    questions, registry = _setup_questions(root, state, catalog)
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
    _warn_unsigned(profile)


def _sync(args, root: Path, state: Path) -> None:
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
    pending = _pending_catalog_changes(lock, live, profile, bundled)
    if pending:
        print(f"OpenGuildKit: sync keeps the rules of the catalog lock; the installed catalog changes "
              f"{len(pending)} of its records ({', '.join(pending)}). Run openguildkit update to review them.",
              file=sys.stderr)
    for item in patterns_to_review(profile, catalog):
        print(f"OpenGuildKit: review pattern {item['id']}: {'; '.join(item['reasons'])}", file=sys.stderr)


def _host(args, root: Path, profile: dict) -> int:
    """Report the rules the host agent enforces (host check), or write its settings and hooks (host apply)."""
    if args.mode == "check":
        _warn_unsigned(profile)
    controls = host_controls(root, profile)
    written = None
    if args.mode == "apply":
        written = apply_host_settings(root, profile)
        for path in written:
            print(f"Wrote {path}")
        if not written and profile.get("host", "other") not in HOOK_HOSTS:
            print(f"OpenGuildKit: {NO_HOST_SETTINGS}", file=sys.stderr)
        controls = host_controls(root, profile)
    missing = [control for control in controls if control["status"] == "missing"]
    if args.json:
        print_json(controls)
    else:
        for control in controls:
            print(f"[{HOST_STATUS_LABELS.get(control['status'], control['status'])}] {control['title']}"
                  f"\n    {control['detail']}")
        settings = [control for control in missing if control.get("cause") != "path"]
        if settings:
            print(f"{plural(len(settings), 'setting')} missing. Run openguildkit host apply, then openguildkit host check.")
        if not missing:
            print("Nothing missing. A rule marked 'by instruction' or 'by a person' is left to the agent's "
                  "instructions or to a person on purpose: no setting of this host can enforce it.")
    # host apply that writes nothing for the host other has done nothing the person asked for, and one that leaves a
    # setting missing has not done it either.
    wrote_nothing = written == [] and profile.get("host", "other") not in HOOK_HOSTS
    return 1 if missing or wrote_nothing else 0


def _host_scan(args, root: Path, state: Path) -> int:
    """Read the instruction files and settings of the project, list its agent tools and MCP servers, and report what
    could mislead an agent. The profile, when there is one, gives the guard; the project's own tools join the registry."""
    profile = load_profile(state, project_catalog(args, state)) if (state / "project.json").is_file() else {}
    result = scan_report(root, profile, load_tools(state / "catalog" / "tools"), args.allow)
    if args.format == "sarif":
        print(scan_sarif(result, root), end="")
    elif args.json:
        print_json(result)
    else:
        print(render_scan(result))
    return scan_exit_code(result, args.strict)


def check(args, root: Path, state: Path, profile: dict, catalog: dict, read: dict | None = None) -> int:
    """`check`, in text or, with --format sarif, as the SARIF document of its problems on the standard output.

    The command stops where it stopped: a problem that ends it (instructions, host settings, catalog lock, approvals
    that no longer hold) ends it in SARIF too, with the findings gathered up to there and the same exit code. A failure
    that is not a problem of the project, such as a profile that cannot be read, prints no file. read holds the task
    records a caller already read, by ID (projects), which are not read again."""
    from .check_findings import Report

    report = Report(args.format == "sarif")
    code = 0
    try:
        _check_project(args, root, state, profile, catalog, report, {} if read is None else read)
    except RuleError as problem:
        if not report.active:
            raise
        report.blocked(problem)
        print(f"OpenGuildKit: {problem}", file=sys.stderr)
        code = 1
    if report.active:
        print(report.text(root), end="")
    return code


def _check_project(args, root: Path, state: Path, profile: dict, catalog: dict, report, read: dict) -> None:
    """Check that the instructions, the host settings and the catalog lock match the profile, and that every
    approval still holds; warn about what git will not carry to a teammate. Each problem and warning goes to the
    report too, when it gathers them. read receives the task records, by ID, and each is read once."""
    load_tools(state / "catalog" / "tools")
    _warn_unsigned(profile, report)
    # An approval that no longer holds is an error until the task is consulted again; a completed task
    # whose rules changed afterwards is history and stays quiet here (task list shows it).
    rows = list_tasks(state, profile=profile, catalog=catalog, root=root, read=read)
    failing = [f"{row['id']}: {row['next']}" for row in rows
               if row["status"] == "unreadable" or row.get("severity") == "error"]
    report.tasks(rows)
    # An approval that holds through the signers of the revision it was signed at: said, never failed.
    for row in rows:
        if row.get("note"):
            print(f"OpenGuildKit: {row['id']}: {row['note']}", file=sys.stderr)
    records = exported_decisions(root, state, profile, Fingerprints(profile, catalog), read)
    failing += [row["problem"]["message"] for row in records
                if row["problem"] and row["problem"]["severity"] == "error"]
    report.records(records)
    replaced = {**replaced_boards(catalog), **org_catalog_cli.unaccepted_replacements(catalog, read_lock(state))}
    report.boards(replaced)
    for line in failing + list(replaced.values()):
        print(f"OpenGuildKit: {line}", file=sys.stderr)
    live, bundled = installed_catalog(args, state)
    lock = read_lock(state)
    require_instructions(args, root, state, profile, catalog)
    missing = [control for control in host_controls(root, profile) if control["status"] == "missing"]
    settings = [control["title"] for control in missing if control.get("cause") != "path"]
    if missing:
        raise RuleError(" ".join(
            ([f"The host settings do not enforce: {'; '.join(settings)}. Run openguildkit host check for the cause, "
              "then openguildkit host apply."] if settings else [])
            + ([OFF_PATH] if len(settings) < len(missing) else [])), "host-settings-missing")
    if not lock_is_current(lock, profile, catalog, bundled):
        raise RuleError("The catalog lock does not match the profile. Run openguildkit sync.", "catalog-lock-stale",
                        [f"{STATE_DIR}/{LOCK_FILE}"])
    if not failing and not report.active:
        print("OpenGuildKit instructions match the project profile.")
    pending = _pending_catalog_changes(lock, live, profile, bundled)
    if pending:
        message = (f"the installed catalog changes the rules of {len(pending)} locked "
                   f"{'record' if len(pending) == 1 else 'records'} ({', '.join(pending)}). The project keeps its "
                   "locked rules: run openguildkit update to review the changes.")
        print(f"OpenGuildKit: {message}", file=sys.stderr)
        report.add("catalog-update-pending", "warning", message, f"{STATE_DIR}/{LOCK_FILE}")
    undated = _undated_project_sources(state, live)
    if undated:
        message = (f"date the sources of {len(undated)} project "
                   f"{'record' if len(undated) == 1 else 'records'}: {', '.join(undated)}. Open each page, then "
                   f'add "checked": "YYYY-MM-DD" after its url with that day\'s date (see {doc_link("docs/catalog-format.md")}).')
        print(f"OpenGuildKit: {message}", file=sys.stderr)
        report.add("source-undated", "warning", message)
    issues = sharing_issues(root, state, records, read)
    for _, message, _ in issues:
        print(f"OpenGuildKit: {message}", file=sys.stderr)
    report.sharing(issues)
    if failing:
        raise RuleError(f"The instructions match the project profile, but {len(failing)} "
                        f"{'approval no longer holds' if len(failing) == 1 else 'approvals no longer hold'}: "
                        "each line above gives the command to run.", None)


def _run(args) -> int | None:
    if args.command == "completion":  # Before the project: a script to load is asked for anywhere.
        completion_cli.run(args)
        return None
    _require_sarif_options(args)
    if args.command == "guard" and args.hook:
        return _guard_hook(args)
    if args.command == "host" and (args.strict or args.allow) and args.mode != "scan":
        raise ValueError(f"{'--strict' if args.strict else '--allow'} is an option of openguildkit host scan.")
    if args.command == "mcp" and args.project is None:
        raise ValueError("Supply --project PATH to open a project MCP server.")
    root = project_root(args.project)
    state = state_path(root)
    if args.command in ("trace", "projects"):
        return trace_cli.run(args, root, state) if args.command == "trace" else projects_cli.run(args)
    if args.command == "audit":
        return audit_cli.run(args, root)
    if args.command == "org-catalog":  # Before the catalog in force, which an unreadable organization copy stops.
        return org_catalog_cli.run(args, root, state)
    if args.command == "evidence":
        return evidence_cli.run(args, root, state)
    if args.command == "mcp":
        if args.policy_repo is not None or args.policy_commit is not None:
            raise ValueError("The MCP server reads the project catalog in force without policy overrides.")
        from .project_mcp import serve_project

        return serve_project(state)
    if args.command == "guard":
        return _guard(args, root, state)
    if args.command == "ui":
        from . import webui  # Only this command serves pages; every other one starts without the web server.

        return webui.serve(root, args.port, args.static, not args.no_browser, stable_address=args.stable_address)
    if args.command == "host" and args.mode in ("scan", "managed"):  # managed needs no project: an administrator's machine
        return managed.run(args) if args.mode == "managed" else _host_scan(args, root, state)
    catalog = project_catalog(args, state)
    if args.command == "references":
        _print_references(args, state, catalog)
    elif args.command == "patterns":
        _print_patterns(args, catalog["patterns"])
    elif args.command == "brains":
        if args.new:
            return _new_brain(args, state, catalog)
        families = with_pattern_references(load_references(state / "catalog" / "references", catalog), catalog["patterns"])
        return _print_brains(args, catalog, families)
    elif args.command == "integrations":
        base = Path.home() if args.user else root
        for item in install_agent_files(base, args.host, args.force):
            print(f"{Path(item['file']).as_posix()}: {item['action']} (openguildkit {package_version()})")
        if args.host == "other":
            print(OTHER_HOST_NOTE)
    elif args.command == "detect":
        _print_detection(detect_stack(root), args.json)
    elif args.command == "preview":
        if args.answers:
            profile = setup_profile(read_json(args.answers), catalog, _setup_questions(root, state, catalog)[0])[0]
        else:
            profile = load_profile(state, catalog)
        print_rule_plan(rule_plan(profile, catalog), args.json)
    elif args.command == "recommend":
        if args.answers:
            questions = _setup_questions(root, state, catalog)[0]
            plan = profile_recommendations(complete_answers(read_json(args.answers), questions, catalog)[0], catalog)
        else:
            profile = load_profile(state, catalog)
            plan = {**profile_recommendations(profile, catalog), "review": patterns_to_review(profile, catalog)}
        print_recommendations(plan, args.json)
    elif args.command == "catalog":
        _print_catalog(catalog, args.json)
    elif args.command == "profile":
        return profile_cli.run(args, root, state)
    elif args.command == "tools":
        return tools_run(args, root, state, catalog)
    elif args.command == "features":
        return features_cli.run(args, root, state, catalog)
    elif args.command == "alerts":
        return alerts_run(args, state)
    elif args.command == "init":
        _init(args, root, state, catalog)
    elif args.command == "update":
        _update_catalog(args, root, state)
    elif args.command == "sync":
        _sync(args, root, state)
    else:
        return _project_command(args, root, state, catalog)
    return None


def _project_command(args, root: Path, state: Path, catalog: dict) -> int | None:
    """The commands that need the project's profile."""
    profile = load_profile(state, catalog)
    if args.command == "deliverable":
        return _deliverable(args, root, state, profile, catalog)
    if args.command == "docs":
        return _docs(args, root, state, profile, catalog)
    if args.command == "market":
        return market_run(args, state, profile)
    if args.command == "storybook":
        return storybook_run(args, root, state)
    if args.command == "host":
        return _host(args, root, profile)
    if args.command == "check":
        return check(args, root, state, profile, catalog)
    if args.command == "ci-check":
        result = check_export(profile, catalog, args.target_repo, args.commit)
        print_json(result)
        return 0 if result["status"] == "success" else 1
    if args.command == "task":
        return tasks_cli.run(args, root, state, profile, catalog)
    return None


def _reader_closed() -> int:
    """The reader of the output stopped early, as `| head` does: end quietly, like a command that finished.

    Standard output then points at the null device, so the interpreter's last flush cannot fail again.
    """
    try:
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, sys.stdout.fileno())
        os.close(null)
    except (OSError, ValueError, AttributeError):
        pass  # Not a real file descriptor, as when a test captures the output: nothing is flushed at exit.
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        # Redirected output is consumed by agents and scripts on every platform.
        for stream in (sys.stdout, sys.stderr):
            if not stream.isatty() and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="backslashreplace")
    argv = hoist_global_options(sys.argv[1:] if argv is None else argv)
    parser = command_parser(cli_surface.deferred_modules(argv))
    if not argv:
        parser.print_help()
        return 0
    take_by_warning()  # A line left by a parse that failed in this process is not this run's.
    args = parser.parse_args(argv)
    by_warning = take_by_warning()
    if getattr(args, "project", None) is not None and not args.project.is_dir():
        what = "is not a folder" if args.project.exists() else "does not exist"
        print(f"OpenGuildKit: The project folder {args.project.as_posix()} {what}. Check --project, or create the "
              "folder and run openguildkit init in it.", file=sys.stderr)
        return 2 if args.command == "ci-check" else 1
    try:
        code = _run(args) or 0
        if by_warning:
            print(by_warning, file=sys.stderr)
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        return _reader_closed()
    except (OSError, ValueError, EOFError) as error:
        print_trace()
        print(f"OpenGuildKit: {error_message(error, parser, args)}", file=sys.stderr)
        return 2 if args.command == "ci-check" else 1
    except KeyboardInterrupt:
        print("\nOpenGuildKit: Cancelled.", file=sys.stderr)
        return 130
