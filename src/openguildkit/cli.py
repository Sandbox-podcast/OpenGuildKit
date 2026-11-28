"""Parses commands and runs each one through one table, `COMMANDS`: the module whose `run(command)` runs it, imported
for that command only, and what is read before it runs.

Entry: command_parser, main, COMMANDS
Tests: tests/e2e/test_admin_guide.py, tests/e2e/test_board_passes.py, tests/e2e/test_campaign_links.py,
tests/e2e/test_catalog_lock.py, tests/e2e/test_cli_flow.py, tests/e2e/test_export_ci.py, tests/e2e/test_field_kit.py,
tests/e2e/test_host_rehearsal.py, tests/test_ci_jobs.py, tests/test_dead_code.py, tests/test_detect_versions.py,
tests/test_determinism.py, tests/test_doc_examples.py, tests/test_gemini_host.py, tests/test_host_scan.py,
tests/test_host_surfaces.py, tests/test_install_script.py, tests/test_org_catalog.py, tests/test_product_docs.py,
tests/test_rule_checks.py, tests/test_sample_project.py, tests/test_test_suite.py, tests/test_upgrade.py,
tests/test_upgrades.py, tests/test_workflows.py
"""

import argparse
import sys
from functools import cache
from importlib import import_module
from pathlib import Path

from . import cli_surface, host_coverage, managed, org_policy_cli, tasks_cli
from .cli_errors import command_words, error_message, json_error, print_trace
from .cli_surface import VersionAction, add_by, format_option, hoist_global_options, polish, take_by_warning
from .command import Command
from .errors import OgkError, error_line, file_error
from .hosts import HOSTS
from .storage import answering, json_text
from .terminal import reader_closed, utf8_streams, warn

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
    format_option(check, "Print the problems", "Print whether the check passes and its findings as JSON.")
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


# Each command, the module whose run(command) runs it, and what is read before it runs (command.NEEDS): the module
# is imported only for its command, so that the others, the help and the edit hook start without it.
COMMANDS = {
    "completion": ("completion_cli", "args"),  # A script to load is asked for anywhere, before the project.
    "guard": ("check_cli", "args"),  # guard --hook reads its own project.
    "host": ("check_cli", "args"),  # Its options are checked before the project.
    "mcp": ("connect_cli", "args"),  # --project is required before the project.
    "trace": ("trace_cli", "root"),
    "projects": ("projects_cli", "root"),
    "audit": ("audit_cli", "root"),
    "org-catalog": ("org_catalog_cli", "root"),  # Before the catalog in force, which an unreadable copy stops.
    "evidence": ("evidence_cli", "root"),
    "ui": ("connect_cli", "root"),
    **dict.fromkeys(("references", "patterns", "brains", "detect", "preview", "recommend", "catalog", "update"),
                    ("catalog_cli", "catalog")),
    "integrations": ("connect_cli", "catalog"),
    "profile": ("profile_cli", "catalog"),
    "tools": ("tools_cli", "catalog"),
    "features": ("features_cli", "catalog"),
    "alerts": ("alerts_cli", "catalog"),
    "init": ("init_cli", "catalog"),
    "sync": ("init_cli", "catalog"),
    "deliverable": ("docs_cli", "profile"),
    "docs": ("docs_cli", "profile"),
    "market": ("market_cli", "profile"),
    "storybook": ("storybook_cli", "profile"),
    "check": ("check_cli", "profile"),
    "ci-check": ("connect_cli", "profile"),
    "task": ("tasks_cli", "profile"),
}


def _run(args) -> int | None:
    module, needs = COMMANDS[args.command]
    command = Command(args)
    command.read(needs)
    return import_module(f"{__package__}.{module}").run(command)


def _failed(args, answer: str | None, error: BaseException, text: str) -> int:
    """End on an error: its line on standard error and, under --json, the same error as JSON on standard output (#484),
    with the exit code of an error, 2 for ci-check."""
    if answer is not None:
        print(json_text(json_error(error, text)), end="")
    print(error_line(error, text), file=sys.stderr)
    return 2 if args.command == "ci-check" else 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        utf8_streams()  # Redirected output is consumed by agents and scripts on every platform.
    argv = hoist_global_options(sys.argv[1:] if argv is None else argv)
    parser = command_parser(cli_surface.deferred_modules(argv))
    if not argv:
        parser.print_help()
        return 0
    take_by_warning()  # A line left by a parse that failed in this process is not this run's.
    args = parser.parse_args(argv)
    by_warning = take_by_warning()
    answer = command_words(parser, args) if getattr(args, "json", False) else None
    if getattr(args, "project", None) is not None and not args.project.is_dir():
        exists = args.project.exists()
        text = (f"The project folder {args.project.as_posix()} {'is not a folder' if exists else 'does not exist'}. "
                "Check --project, or create the folder and run openguildkit init in it.")
        return _failed(args, answer, OgkError("OGK-CLI-002", text) if exists else OgkError("OGK-CLI-001", text), text)
    try:
        with answering(answer):
            code = _run(args) or 0
        if by_warning:
            print(by_warning, file=sys.stderr)
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        return reader_closed()
    except (OSError, ValueError, EOFError) as error:
        print_trace()
        text = error_message(error, parser, args)
        return _failed(args, answer, file_error(error, text) if isinstance(error, OSError) else error, text)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        warn("Cancelled.")
        return 130
