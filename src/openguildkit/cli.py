"""Command-line interface for OpenGuildKit."""

import argparse
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
    host_coverage,
    managed,
    org_catalog_cli,
    org_policy_cli,
    profile_cli,
    projects_cli,
    tasks_cli,
    trace_cli,
)
from .catalog_cli import (
    new_brain,
    print_brains,
    print_catalog,
    print_detection,
    print_patterns,
    print_references,
    update_catalog,
)
from .check_cli import check, guard, guard_hook, host, host_scan, require_sarif_options
from .ci import check_export
from .cli_errors import error_message, print_trace, reader_closed
from .cli_surface import VersionAction, add_by, format_option, hoist_global_options, polish, take_by_warning
from .detect import detect_stack
from .docs_cli import deliverable, docs
from .hosts import HOSTS
from .init_cli import init, setup_questions, sync
from .integrations import OTHER_HOST_NOTE, install_agent_files
from .lock import package_version, project_catalog
from .patterns import patterns_to_review
from .project import (
    complete_answers,
    load_profile,
    profile_recommendations,
    project_root,
    rule_plan,
    setup_profile,
    state_path,
)
from .rule_plan_text import print_recommendations, print_rule_plan
from .storage import print_json, read_json


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
alerts_run, market_run, storybook_run, tools_run = (_on_first_call(module, "run")
                                                   for module in ("alerts_cli", "market_cli", "storybook_cli", "tools_cli"))
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
    # No abbreviations: Python 3.11 read `projects --policy` as an ambiguous prefix of --policy-repo (#479).
    parser = argparse.ArgumentParser(prog="openguildkit", allow_abbrev=False,
                                     description="Project rules and specialist reviews for AI-assisted work.")
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
    org_policy_cli.add_guard_options(guard)
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
    host_coverage.add_options(host)


def _run(args) -> int | None:
    if args.command == "completion":  # Before the project: a script to load is asked for anywhere.
        completion_cli.run(args)
        return None
    require_sarif_options(args)
    if args.command == "guard" and args.hook:
        return guard_hook(args)
    if args.command == "host" and (args.strict and args.mode != "scan" or args.allow and args.mode not in ("scan", "managed")):
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
        return guard(args, root, state)
    if args.command == "ui":
        from . import webui  # Only this command serves pages; every other one starts without the web server.

        return webui.serve(root, args.port, args.static, not args.no_browser, stable_address=args.stable_address)
    if args.command == "host" and args.matrix:  # The coverage of every host, from the tables of the code: no project.
        return host_coverage.run(args)
    if args.command == "host" and args.mode in ("scan", "managed"):  # managed needs no project: an administrator's machine
        return managed.run(args) if args.mode == "managed" else host_scan(args, root, state)
    catalog = project_catalog(args, state)
    if args.command == "references":
        print_references(args, state, catalog)
    elif args.command == "patterns":
        print_patterns(args, catalog["patterns"])
    elif args.command == "brains":
        if args.new:
            return new_brain(args, state, catalog)
        families = with_pattern_references(load_references(state / "catalog" / "references", catalog), catalog["patterns"])
        return print_brains(args, catalog, families)
    elif args.command == "integrations":
        base = Path.home() if args.user else root
        for item in install_agent_files(base, args.host, args.force):
            print(f"{Path(item['file']).as_posix()}: {item['action']} (openguildkit {package_version()})")
        if args.host == "other":
            print(OTHER_HOST_NOTE)
    elif args.command == "detect":
        print_detection(detect_stack(root), args.json)
    elif args.command == "preview":
        if args.answers:
            profile = setup_profile(read_json(args.answers), catalog, setup_questions(root, state, catalog)[0])[0]
        else:
            profile = load_profile(state, catalog)
        print_rule_plan(rule_plan(profile, catalog), args.json)
    elif args.command == "recommend":
        if args.answers:
            questions = setup_questions(root, state, catalog)[0]
            plan = profile_recommendations(complete_answers(read_json(args.answers), questions, catalog)[0], catalog)
        else:
            profile = load_profile(state, catalog)
            plan = {**profile_recommendations(profile, catalog), "review": patterns_to_review(profile, catalog)}
        print_recommendations(plan, args.json)
    elif args.command == "catalog":
        print_catalog(catalog, args.json)
    elif args.command == "profile":
        return profile_cli.run(args, root, state)
    elif args.command == "tools":
        return tools_run(args, root, state, catalog)
    elif args.command == "features":
        return features_cli.run(args, root, state, catalog)
    elif args.command == "alerts":
        return alerts_run(args, state)
    elif args.command == "init":
        init(args, root, state, catalog)
    elif args.command == "update":
        update_catalog(args, root, state)
    elif args.command == "sync":
        sync(args, root, state)
    else:
        return _project_command(args, root, state, catalog)
    return None


def _project_command(args, root: Path, state: Path, catalog: dict) -> int | None:
    """The commands that need the project's profile."""
    profile = load_profile(state, catalog)
    if args.command == "deliverable":
        return deliverable(args, root, state, profile, catalog)
    if args.command == "docs":
        return docs(args, root, state, profile, catalog)
    if args.command == "market":
        return market_run(args, state, profile)
    if args.command == "storybook":
        return storybook_run(args, root, state)
    if args.command == "host":
        return host(args, root, profile)
    if args.command == "check":
        return check(args, root, state, profile, catalog)
    if args.command == "ci-check":
        result = check_export(profile, catalog, args.target_repo, args.commit)
        print_json(result)
        return 0 if result["status"] == "success" else 1
    if args.command == "task":
        return tasks_cli.run(args, root, state, profile, catalog)
    return None


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
        return reader_closed()
    except (OSError, ValueError, EOFError) as error:
        print_trace()
        print(f"OpenGuildKit: {error_message(error, parser, args)}", file=sys.stderr)
        return 2 if args.command == "ci-check" else 1
    except KeyboardInterrupt:
        print("\nOpenGuildKit: Cancelled.", file=sys.stderr)
        return 130
