"""Command-line interface for OpenGuildKit."""

import argparse
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from .catalog import load_catalog, undated_sources
from .ci import check_export, read_policy_pack
from .decisions import (
    DECISIONS_DIR,
    NAMESPACE,
    approval_policy,
    check_decision,
    decision_payload,
    exported_records,
    git_revision,
    ignored_by_git,
    payload_text,
    verify_signature,
)
from . import alerts_cli
from .alerts import blocking_alerts, load_register
from .deliverables import draft_problems, launch_notice, load_deliverables, new_draft, project_path, utm_link
from .brains import (
    brain_knowledge, brief_knowledge, consultation_context, knowledge_gaps, reading_list_note, write_brain_skeleton,
)
from .detect import components_for_profile, detect_stack, detected_project_name
from .project_checks import propose_checks
from .publishing import add_share, export_docs, project_overview, revoke_share, same_access, share_status
from . import profile_cli, tools_cli, webui
from .tools import connected_tools, load_tools, tool_evidence_warnings
from . import market_cli
from .market import load_dossier
from .market import scope_entry as market_scope_entry
from .storybook import STORYBOOK_VERSION
from .storybook import run as storybook_command
from .storybook import scope_entry as storybook_scope_entry
from .integrations import OTHER_HOST_NOTE, install_agent_files
from .guard import (
    NO_TASK, SCOPE_NOTE, STALE_DAYS, ci_guard, covering_approvals, export_decision, exported_decisions, guard_mode,
    record_of_another_task, run_hook,
)
from .relevance import changed_files, pack_relevance
from .results import (
    DONE_STATUSES, SUPPLY, SUPPLY_OR_NOT_APPLICABLE, asked_checks, chaosfolk_checks, compare_runs,
    completion_problems, criteria_summary, decision_changes, declared_cannot_run, keep_declarations, decision_revision_message, expected_checks, missing_scenarios, result_template,
    run_command_checks,
)
from .hosts import apply_host_settings, approval_warning, host_controls
from .lock import (
    package_version,
    apply_lock,
    build_lock,
    catalog_changes,
    installed_catalog_date,
    lock_is_current,
    read_lock,
    unshipped_records,
    update_target,
    write_lock,
)
from .patterns import patterns_to_review, role_choices
from .project import (
    RULES_NOTE,
    ALREADY_INITIALIZED,
    require_resolved_conflicts,
    unsure_answers,
    GUARD_MODES,
    STATE_DIR,
    check_instructions,
    complete_answers,
    init_questions,
    initialize,
    is_norm,
    load_profile,
    profile_recommendations,
    profile_fingerprint,
    project_root,
    resolved_profile,
    rule_conflicts,
    rule_plan,
    setup_profile,
    state_path,
    sync_instructions,
    task_scope_profile,
    validate_profile,
)
from .tools import HOSTS as TOOL_HOSTS
from .tools import detect_tools, load_tools, match_tools
from .references import english_title, find_references, load_references, with_pattern_references
from .sensitive import input_warnings, redact_credentials, redact_data
from .storage import json_text, project_lock, read_json, write_json
from .tasks import (
    SENSITIVE_GROUP,
    approval_problem,
    points_left_open,
    timestamp,
    cited_evidence,
    board_brief_problem,
    list_tasks,
    previous_round_line,
    tasks_touched,
    complete_task,
    defer_evidence,
    record_result,
    resolve_blocker,
    record_deliberation,
    assemble_review,
    pass_progress,
    start_pass,
    submit_pass,
    verification_blocker_problems,
    ACTIONS,
    record_authorization,
    create_task,
    read_task,
    record_consultation,
    decided_message,
    record_decision,
    record_review,
    require_current_scope,
    task_path,
)
from .workflow import RESOLUTION_RULE, trigger_matches, blocker_list, board_brief, challenge_report, decision_summary, deliberation_request, handoff, is_decision_task, open_points, pending_removals, select_boards, task_questions, validate_answers, validate_review, verdict_lines, review_lines, pack_rules


class _Version(argparse.Action):
    """Print the version and exit; reading the package metadata is slow, so only --version pays for it."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings, dest=dest, default=default, nargs=0,
                         help=help or "show program's version number and exit")

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"openguildkit {package_version()}")
        parser.exit()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openguildkit", description="Project rules and specialist reviews for AI-assisted work.")
    parser.add_argument("--version", action=_Version)
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
    guard.add_argument("--json", action="store_true", help="Print the result as JSON.")
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
    share.add_argument("share_action", choices=("add", "list", "revoke", "check"))
    share.add_argument("--deliverable", help="Page or folder shared (add).")
    share.add_argument("--recipient", action="append", default=[], help="Recipient email address (add, repeatable).")
    share.add_argument("--until", help="Last day of access, YYYY-MM-DD: a reminder, Documentalist keeps no end date (add).")
    share.add_argument("--portal", help="Address of the shared space's portal, https://HOST/p/SPACE; http only on this "
                                        "machine (add).")
    share.add_argument("--id", dest="share_id", help="Share ID (revoke).")
    share.add_argument("--by", help="Owner of the share (add, revoke).")
    share.add_argument("--json", action="store_true", help="Print the shares as JSON.")
    tools_cli.add_parser(commands)
    profile_cli.add_parser(commands)
    alerts_cli.add_parser(commands)
    market_cli.add_parser(commands)
    storybook = commands.add_parser(
        "storybook", help="Compose the company Storybook, record its stories and extract a design system.")
    storybook_actions = storybook.add_subparsers(dest="action", required=True)
    compose = storybook_actions.add_parser(
        "compose", help="Add a published Storybook to the refs file that .storybook/main imports.")
    compose.add_argument("ref", help="Ref ID, such as company; its stories are cited as storybook:REF_STORY_ID.")
    compose.add_argument("--url", help="URL of the published Storybook.")
    compose.add_argument("--title", help="Title shown in the Storybook sidebar.")
    compose.add_argument("--remove", action="store_true", help="Remove this ref from the refs file.")
    compose.add_argument("--config-dir", default=".storybook", help="Storybook configuration folder (default .storybook).")
    sb_import = storybook_actions.add_parser(
        "import", help="Compare Storybook index.json files, report what to map and record the known stories.")
    sb_import.add_argument("--project-index", type=Path,
                           help="The project's index.json or storybook-static folder (default storybook-static).")
    sb_import.add_argument("--company-index", type=Path, help="The company Storybook's index.json or static folder.")
    sb_import.add_argument("--ref", default="company", help="Ref ID of the company Storybook (default company).")
    sb_import.add_argument("--library", type=Path, help="package.json of the company component library.")
    sb_import.add_argument("--package", type=Path, help="The project's package.json (default package.json).")
    sb_extract = storybook_actions.add_parser(
        "extract", help="Inventory the components, variants and style tokens of an existing React application.",
        description="Inventory the components, variants and style tokens of an existing React application. "
                    "Supported: React function components (function declarations, arrow functions, forwardRef and "
                    "memo) in .tsx and .jsx files, their props, literal defaults and string-union prop types, the "
                    "export aliases and re-exports of .ts and .js index files, and CSS and SCSS stylesheets. "
                    "Not supported: class components, Vue, Angular and Svelte components, CSS-in-JS and utility "
                    "classes such as Tailwind's. The sources are read with text patterns, not a full parser: "
                    "check the inventory before proposing.")
    sb_extract.add_argument("--src", type=Path, action="append", required=True,
                         help="Source folder or file to scan, such as a screen; repeat to select several.")
    sb_extract.add_argument("--preview", type=Path, action="append", default=[],
                         help="Screenshot the team may reuse; recorded with its hash, never analyzed.")
    sb_extract.add_argument("--output", type=Path, help="Inventory file (default .openguildkit/storybook/inventory.json).")
    sb_propose = storybook_actions.add_parser(
        "propose", help="Write the proposals to validate from the inventory, keeping the decisions already made.")
    sb_propose.add_argument("--inventory", type=Path, help="Inventory file (default .openguildkit/storybook/inventory.json).")
    sb_propose.add_argument("--proposals", type=Path, help="Proposals file (default .openguildkit/storybook/proposals.json).")
    sb_generate = storybook_actions.add_parser(
        "generate", help="Write tokens, stories and an index for the validated proposals; never overwrite edits.")
    sb_generate.add_argument("--proposals", type=Path, help="Proposals file (default .openguildkit/storybook/proposals.json).")
    sb_generate.add_argument("--out", type=Path, help="Output folder (default src/design-system).")
    sb_generate.add_argument("--framework", help="Storybook framework package for the types (default: the one in "
                                                  "package.json, else @storybook/nextjs-vite for Next.js, "
                                                  "else @storybook/react-vite).")
    for storybook_action in (compose, sb_import, sb_extract, sb_propose, sb_generate):
        storybook_action.add_argument("--json", action="store_true", help="Print the result as JSON.")
    storybook.epilog = (f"Create the project Storybook with npm create storybook@{STORYBOOK_VERSION}. "
                        "storybook compose prints a minimal .storybook/main.ts when the project has none.")
    agent = commands.add_parser("integrations", help="Install the agent skill and subagent of this version.")
    agent.add_argument("--host", required=True, choices=("claude-code", "codex", "other"),
                       help="Agent to configure (other: the Agent Skills folder .agents/skills/).")
    agent.add_argument("--user", action="store_true", help="Install in the home folder for every project.")
    agent.add_argument("--force", action="store_true", help="Replace modified files, keeping a .previous copy.")
    host = commands.add_parser("host", help="Show or apply the rules the host agent can enforce.")
    host.add_argument("mode", choices=("check", "apply"), help="check reports each rule; apply writes the host settings.")
    host.add_argument("--json", action="store_true", help="Print the report as JSON.")
    update = commands.add_parser("update", help="Show what the installed catalog would change and adopt it.")
    update.add_argument("--apply", action="store_true", help="Adopt the installed catalog's records for this project.")
    update.add_argument("--json", action="store_true", help="Print the changes as JSON.")
    commands.add_parser("check", help="Check that the instructions match the project profile.")
    ui = commands.add_parser("ui", help="Open the web interface of this project on 127.0.0.1.")
    ui.add_argument("--port", type=int, default=webui.DEFAULT_PORT, help=f"Port (default {webui.DEFAULT_PORT}; 0 picks a free one).")
    ui.add_argument("--no-browser", action="store_true", help="Print the address without opening a browser.")
    ui.add_argument("--static", type=Path, help="Folder of a built front end (default: the one installed with the package).")
    ci = commands.add_parser("ci-check", help="Evaluate the central export rule on an exact Git commit.")
    ci.add_argument("--target-repo", type=Path, required=True, help="Local Git repository with the target commit.")
    ci.add_argument("--commit", required=True, help="Full Git SHA of the target commit.")

    task = commands.add_parser("task", help="Frame a task, record advice and approve a handoff.")
    actions = task.add_subparsers(dest="action", required=True)
    new = actions.add_parser("new", help="Create a task draft.")
    new.add_argument("brief", nargs="?", help="Short description of the work.")
    new.add_argument("--file", type=Path, help="Read the brief from a UTF-8 Markdown or text file.")
    new.add_argument("--id", help="Use a readable lowercase task ID.")
    new.add_argument("--follows", metavar="TASK", help="Link the task to an earlier task's decision.")
    listing = actions.add_parser("list", help="List the project's tasks with their status and next open point.")
    listing.add_argument("--status", help="Only tasks in this status.")
    listing.add_argument("--owner", help="Only tasks decided by this person.")
    listing.add_argument("--since", help="Created on or after YYYY-MM-DD.")
    listing.add_argument("--until", help="Created on or before YYYY-MM-DD.")
    listing.add_argument("--json", action="store_true", help="Print the tasks as JSON.")
    listing.add_argument("--decisions", action="store_true",
                         help="List the decisions exported to .openguildkit/decisions, teammates' included.")
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
        "blockers": "List the review's blockers and how each was resolved.",
        "clear": "Record the evidence that clears a blocker (the person, at a terminal or with a signature).",
        "waive": "Waive a blocker within the project's waiver policy (needs a terminal).",
        "respond": "Record the boards' answers to each other's objections.",
        "decide": "Record a human decision.",
        "handoff": "Print the approved implementation handoff, or the decision record of a decision task.",
        "decision-payload": "Print the exact decision an approver signs in a project that requires signed approvals.",
        "show": "Print the task record as JSON.",
        "checks": "List the checks the approved task must report.",
        "verify": "Run the project's check commands and the rules' machine checks, and record their results.",
        "result": "Record the delivered revision, criteria and check outcomes.",
        "complete": "Close the task: done, or done-with-reservations when points stay open.",
        "runs": "Compare the last two ChaosFolk replays of the task.",
        "alerts": "Import dependency alerts for the task into the project register and review them.",
        "export": "Write a shareable decision record to .openguildkit/decisions for the pull request.",
        "authorize": "Record a person's decision on an external action outside the authorized scope.",
    }
    for action, description in descriptions.items():
        command = actions.add_parser(action, help=description)
        command.add_argument("id", help="Task ID.")
        if action in ("consult", "questions", "route"):
            command.add_argument("--answers", type=Path, help="Read task answers from a JSON file.")
        if action == "consult":
            command.add_argument("--market", metavar="DOSSIER", help="Attach a market dossier from .openguildkit/market/.")
            revised = command.add_mutually_exclusive_group()
            revised.add_argument("--brief", dest="revised_brief", metavar="TEXT",
                                 help="Revise the brief when consulting again after a change request.")
            revised.add_argument("--brief-file", type=Path, metavar="FILE",
                                 help="Read the revised brief from a UTF-8 text file instead of --brief.")
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
            command.add_argument("--again", action="store_true",
                                 help="Redo a pass whose entry is already submitted; the entry is replaced at the next submit.")
        if action == "brief":
            shown = command.add_mutually_exclusive_group()
            shown.add_argument("--board", help="Print this board's pass again without starting it.")
            shown.add_argument("--scope", action="store_true", help="Print the whole project scope as JSON, rule texts included.")
            shown.add_argument("--pack", help="Print the rules of one pack in force for the task.")
        if action in ("pass", "submit"):
            command.add_argument("--mode", choices=("subagent", "sequential"), help="How the host runs this pass.")
        if action in ("clear", "waive"):
            command.add_argument("blocker", help="Blocker ID such as security:1 (see task blockers).")
            command.add_argument("--by", required=True, help="Person who resolves the blocker.")
        if action == "clear":
            command.add_argument("--evidence", required=True, help="Path, document or link that clears it.")
            command.add_argument("--supports", required=True, help="What the evidence establishes.")
            signing = command.add_mutually_exclusive_group()
            signing.add_argument("--payload", type=Path, help="Write the exact clearance payload to sign.")
            signing.add_argument("--signature", type=Path, help="SSH signature of the clearance payload.")
            command.add_argument("--signer", help="Approver principal used to sign the clearance.")
        if action == "waive":
            command.add_argument("--reason", required=True, help="Why the risk is accepted.")
            command.add_argument("--scope", required=True, help="What the waiver covers.")
            command.add_argument("--until", required=True, help="Last day of the waiver, YYYY-MM-DD.")
        if action == "blockers":
            command.add_argument("--json", action="store_true", help="Print the blockers as JSON.")
        if action == "export":
            command.add_argument("--output", type=Path, help="Write the shareable record to this file instead.")
        if action == "checks":
            command.add_argument("--json", action="store_true", help="Print the checks as JSON.")
        if action in ("checks", "result"):
            command.add_argument("--all", action="store_true",
                                 help="Ask every rule of the active packs, including those that do not concern the task.")
        if action == "result":
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--file", type=Path, help="Result JSON.")
            source.add_argument("--template", action="store_true", help="Print a result file to fill in.")
        if action == "complete":
            command.add_argument("--by", help="Person who closes the task over skipped sensitive rules or deferred "
                                              "evidence (needs a terminal).")
            command.add_argument("--defer", action="append", default=[], metavar="EVIDENCE=TASK",
                                 help="Hand an awaited named evidence to a follow-up task (with --by).")
        if action == "verify":
            command.add_argument("--chaosfolk", type=Path, metavar="SUMMARY",
                                 help="Record a ChaosFolk regression summary.json instead of running the check commands.")
            command.add_argument("--tool-version", help="ChaosFolk version or commit that produced the summary.")
            command.add_argument("--cannot-run", metavar="COMMAND_CHECK",
                                 help="Record that a check command such as command:1 cannot run in this environment "
                                      "(with --by and --reason, at a terminal); the task then closes with that reservation.")
            command.add_argument("--withdraw", metavar="COMMAND_CHECK",
                                 help="Withdraw a declaration that a command cannot run (with --by, at a terminal): "
                                      "the command runs and its outcome is recorded.")
            command.add_argument("--by", help="Person who records or withdraws that the command cannot run.")
            command.add_argument("--reason", help="Why the command cannot run here.")
        if action == "alerts":
            command.add_argument("--import", dest="import_file", type=Path, metavar="REPORT",
                                 help="npm audit, pip-audit, OSV-Scanner or Dependabot JSON report.")
            command.add_argument("--set", dest="alert_id", metavar="ALERT", help="Alert ID to review.")
            command.add_argument("--link", metavar="ALERT", help="Link an alert of the register to the task.")
            command.add_argument("--status", choices=alerts_cli.STATUS_CHOICES, help="Review status for --set.")
            command.add_argument("--by", help="Reviewer's name for --set.")
            command.add_argument("--reason", default="", help="Reason, required to dismiss.")
            command.add_argument("--json", action="store_true", help="Print the alerts as JSON.")
        if action == "runs":
            command.add_argument("--json", action="store_true", help="Print the comparison as JSON.")
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
            command.add_argument("--signature", type=Path, help="SSH signature of task decision-payload (signed projects).")
            command.add_argument("--signer", help="Principal in the allowed signers file (signed projects).")
        if action == "decision-payload":
            command.add_argument("--by", required=True, help="Decision owner's name.")
            command.add_argument("--reason", required=True, help="Reason for the decision.")
            command.add_argument("--output", type=Path, help="Write the exact bytes to sign to this file.")
    return parser


def _print_json(data) -> None:
    print(json_text(data), end="")


@contextmanager
def _input_file(path: Path):
    """Name the file a refusal comes from, so the person knows which file to correct."""
    try:
        yield
    except ValueError as error:
        raise ValueError(f"{path.as_posix()}: {error}") from error


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


LOCK_OLDER = (
    "The instructions follow a newer catalog than the project's lock. Run openguildkit update to review the changes "
    "and the tasks they touch, then openguildkit update --apply. openguildkit sync would rewrite the instructions from "
    "the lock's earlier rules and leave the lock as it is."
)


def _require_instructions(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    """Refuse out-of-date instructions, naming update rather than sync when they follow a newer installed catalog."""
    try:
        check_instructions(root, profile, catalog)
    except ValueError:
        lock = read_lock(state)
        if lock is not None and _instructions_match(root, profile, update_target(_installed_catalog(args, state)[0], lock)):
            raise ValueError(LOCK_OLDER) from None
        raise


def _instructions_match(root: Path, profile: dict, catalog: dict) -> bool:
    try:
        check_instructions(root, profile, catalog)
    except ValueError:
        return False
    return True


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


def _print_touched(tasks: list[dict], before: bool = False) -> None:
    """The tasks a change of rules touches, in the same words for update, update --apply and sync."""
    if not tasks:
        return
    print("Tasks this change touches:" if before else "Tasks consulted under the previous rules:")
    for task in tasks:
        print(f"  {task['id']} ({task['status']}): {task['step']}.")


def _show_exported(root: Path, state: Path, profile: dict, catalog: dict, task_id: str) -> None:
    """Show a task known here only by its exported record, with whether that record still holds."""
    row = next(item for item in exported_decisions(root, state, profile, profile_fingerprint(profile, catalog))
               if item["path"].endswith(f"/{task_id}.json"))
    print(f"OpenGuildKit: task {task_id} exists here only as the exported record {row['path']}.", file=sys.stderr)
    if row["problem"]:
        print(f"OpenGuildKit: {row['problem']['message']}", file=sys.stderr)
    _print_json(read_json(root / row["path"]))


def _print_decision_rows(rows: list[dict]) -> None:
    if not rows:
        print(f"No exported decision in .openguildkit/{DECISIONS_DIR}.")
    for row in rows:
        if row["status"] == "unreadable":
            print(f"{row['path']} [unreadable]: {row['problem']['message']}")
            continue
        state = "completed" if row["completed"] else "not completed"
        print(f"{row['task']} [{row['status']} by {row['by']}, {state}] {row['brief']}")
        message = row["problem"]["message"].removeprefix(f"{row['path']}: ").removeprefix(f"{row['path']} ") if row["problem"] else ""
        notes = [row["path"], message or "holds under the current rules"]
        if not row["local"]:
            notes.append("no local task record (a teammate's task, or a deleted tasks folder)")
        print(f"    {'; '.join(notes)}")


def _sharing_warnings(root: Path, state: Path, records: list[dict]) -> list[str]:
    """What git will not carry to a teammate: tasks named only by exported records, evidence left out of the repository."""
    warnings = []
    absent = sorted({row["task"] for row in records if row["status"] != "unreadable" and not row["local"]})
    if absent:
        warnings.append(
            f"exported decisions name tasks absent from this copy: {', '.join(absent)}. That is normal for a teammate's "
            "task; if the tasks folder was deleted, these records are what remains (openguildkit task list --decisions)."
        )
    warnings += [_clash_message(task_id, path) for task_id, path in _id_clashes(root, state).items()]
    cited = {row["id"]: cited_evidence(read_task(state, row["id"])) for row in list_tasks(state)
             if row["status"] != "unreadable"}
    return warnings + _unshared_evidence(root, cited)


def _id_clashes(root: Path, state: Path) -> dict[str, str]:
    """Local tasks whose ID an exported record of another task uses, such as a teammate's taken in a merge.

    Only the tasks that share an ID with an exported record are read, so a project with many tasks and few
    records lists its tasks as fast as before.
    """
    clashes = {}
    for record in sorted((state / DECISIONS_DIR).glob("*.json")):
        try:
            if not task_path(state, record.stem).is_file():
                continue
            task = read_task(state, record.stem)
        except ValueError:
            continue
        path = record_of_another_task(state, task)
        if path is not None:
            clashes[record.stem] = path.relative_to(root).as_posix()
    return clashes


def _clash_message(task_id: str, path: str) -> str:
    return (f"task {task_id} of this copy and the exported decision {path} are different tasks with the same ID. "
            "Leave the record as it is and open your work under another ID with openguildkit task new \"BRIEF\" --id "
            "NEW-ID (see docs/workflow.md, \"When two copies use the same task ID\").")


def _unshared_evidence(root: Path, cited: dict[str, list[str]]) -> list[str]:
    """Evidence a reviewer cannot open from the repository: ignored by git or kept under .openguildkit/tasks/."""
    warnings = []
    ignored = ignored_by_git(root, sorted({path for paths in cited.values() for path in paths}))
    local_only = f"{STATE_DIR}/tasks/"
    for task_id, paths in cited.items():
        unshared = [path for path in paths if path in ignored or path.replace("\\", "/").startswith(local_only)]
        if unshared:
            warnings.append(
                f"task {task_id} cites evidence a reviewer cannot open from the repository (ignored by git or kept under "
                f"{local_only}): {', '.join(unshared)}. Move it to a committed folder and record it again."
            )
    return warnings


def _undated_project_sources(state: Path, live: dict) -> list[str]:
    """Project records that cite a source without a checked date; bundled sources always carry one."""
    project = state / "catalog"
    references = {
        "references": {record["id"]: record for family in load_references(project / "references").values()
                       for record in family["references"]},
        "deliverables": load_deliverables(live, project / "deliverables"),
    }
    return undated_sources({**live, **references})


def _update_catalog(args, root: Path, state: Path) -> None:
    with project_lock(state):
        live, bundled = _installed_catalog(args, state)
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
        _print_json(result)
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
        _print_touched(result["stale_tasks"], before=True)
        print("Nothing changed. Run openguildkit update --apply to adopt these rules.")
        return
    print("Applied. The next consultations use these rules.")
    _print_touched(result["stale_tasks"])


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


def _prompt_task_questions(brief: str) -> dict:
    """Ask the base questions, then the follow-ups that the first answers call for."""
    base = [question for question in task_questions(brief) if question["id"] != "context"]
    answers = _prompt_questions(base, "task consult")
    follow_ups = [question for question in task_questions(brief, answers) if question["id"] not in answers]
    answers.update(_prompt_questions(follow_ups, "task consult"))
    for point in open_points(brief, validate_answers(answers)):
        print(f"  Open point: {point}", file=sys.stderr)
    return answers


def _interactive_init(questions: list[dict], catalog: dict, registry: dict | None = None) -> dict:
    """Ask the setup questions in order; each norm is confirmed on its own, with the reason it is proposed."""
    by_id = {question["id"]: question for question in questions}
    answers = _prompt_questions([by_id["name"], by_id["sector"]], "init")
    components = _prompt_components(by_id["components"])
    if components:
        answers["components"] = components
    else:
        answers.update(_prompt_questions([by_id["stack"]], "init"))
    answers.update(_prompt_questions([by_id["roles"], by_id["personal_data"]], "init"))
    answers["personal_data"] = answers["personal_data"] == "yes"
    if answers["personal_data"]:
        answers.update(_prompt_questions([by_id["people_decisions"]], "init"))
    plan = profile_recommendations(answers, catalog)
    _print_plan_notes(plan)
    kept, declined = _prompt_norms(plan, catalog)
    answers["norms"] = {**dict.fromkeys(kept, "yes"), **declined}
    _print_preselection(plan, catalog)
    patterns = _patterns_question(by_id["patterns"], plan, catalog)
    answers.update(_prompt_questions([patterns], "init"))
    answers["patterns"] = [*kept, *_scoped_patterns(answers.get("patterns", []), plan)]
    recommended = [pack["id"] for pack in rule_plan(setup_profile(answers, catalog, questions)[0], catalog)["packs"]]
    packs = {**by_id["packs"], "default_label": f"none beyond the recommended packs: {', '.join(recommended)}"}
    answers.update(_prompt_questions([packs, by_id["boards"]], "init"))
    answers.update(_prompt_tools(by_id["tools"], load_tools() if registry is None else registry))
    rest = [by_id[question_id] for question_id in ("host", "guard", "research", "conventions")]
    answers.update(_prompt_questions(rest, "init"))
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
    extra = _prompt_questions([{key: value for key, value in others.items() if key != "proposed"}], "init")
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
        while True:
            print("> ", end="", file=sys.stderr, flush=True)
            value = input().strip().casefold()
            if value in ("", "y", "yes", "o", "oui", "n", "no", "non"):
                break
            print("  Answer y or n.", file=sys.stderr)
        if value in ("", "y", "yes", "o", "oui"):
            kept.append(pattern["id"])
            continue
        decider = decider or _prompt_line("  Your name, recorded with the decline: ")
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
    answers = _prompt_questions([question], "init")
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
    "claude-code and codex. The rules above stay with the AGENTS.md instructions and the CI check. To install "
    "the settings and hooks for one of these agents, run openguildkit profile set host claude-code (or codex) "
    "--by NAME --reason WHY, then openguildkit host apply."
)


def _detected_host(root: Path) -> str | None:
    """The agent host whose files the repository already has, offered as the default answer."""
    if (root / ".claude").is_dir() or (root / "CLAUDE.md").is_file():
        return "claude-code"
    if (root / ".codex").is_dir():
        return "codex"
    return None


def _setup_questions(root: Path, state: Path, catalog: dict) -> tuple[list[dict], dict]:
    """The questionnaire with the defaults this repository shows: components, tools and host."""
    registry = load_tools(state / "catalog" / "tools")
    found = detect_stack(root)
    questions = init_questions(catalog, detected_project_name(root), components_for_profile(found),
                               detect_tools(root, registry), _detected_host(root), propose_checks(root, found))
    return questions, registry


def _print_setup_notes(profile: dict, left_aside: list[dict], registry: dict, proposed: list[dict]) -> None:
    """After init: what the guard lets the agent do, the components left aside and the next steps that apply."""
    mode = profile.get("guard", "off")
    host = profile.get("host", "other")
    print(f"Board guard: {GUARD_MODES[mode]}")
    if mode != "off" and host not in ("claude-code", "codex"):
        print("  This host has no hook: the reminder is the AGENTS.md instruction, and the CI check catches the rest.")
    print("  To change it: openguildkit profile set guard off|observe|enforce --by NAME --reason WHY "
          "(lowering it is typed by the person at a terminal).")
    if left_aside:
        names = "; ".join(f"{item['id']} ({item.get('path', '.')}): {', '.join(item['stack'])}" for item in left_aside)
        print(f"OpenGuildKit: the answers give no components, so these detected ones are left aside: {names}. "
              'Add them under "components" to scope the rules to them.', file=sys.stderr)
    known, unknown = match_tools(profile.get("tools", []), registry)
    steps = []
    if host in ("claude-code", "codex"):
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
              "task verify runs only the project's checks (docs/workflow.md#project-checks).")
    elif not profile["checks"]:
        print("No project check: task verify runs no test command (docs/workflow.md#project-checks).")


def _print_catalog(catalog: dict, as_json: bool) -> None:
    groups = ("packs", "boards", "sectors")
    if as_json:
        _print_json({group: catalog[group] for group in groups})
        return
    for group in groups:
        print(group.capitalize())
        for entry in catalog[group].values():
            preselected = _sector_packs(catalog, entry["id"]) if group == "sectors" else []
            suffix = f" (preselects {', '.join(preselected)})" if preselected else ""
            print(f"  {entry['id']:<24} {entry['title']}{suffix}")


def _sector_packs(catalog: dict, sector_id: str) -> list[str]:
    """The packs of the patterns that a sector preselects without a stack."""
    return [
        pack_id
        for pattern in catalog["patterns"].values()
        if sector_id in pattern.get("match", {}).get("sectors", []) and not pattern["match"].get("stack")
        for pack_id in pattern["packs"]
    ]


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


def _print_recommendations(plan: dict, as_json: bool) -> None:
    if as_json:
        _print_json(plan)
        return
    print("Preselected patterns, confirm or remove them")
    for pattern in plan["matched"]:
        where = f" [{', '.join(pattern['components'])}]" if pattern.get("components") else ""
        print(f"  {pattern['id']}{where}: {'; '.join(pattern['reasons'])} ({pattern['rules']} rules)")
        if pattern.get("version_unknown"):
            print(f"    version unknown, confirm {', '.join(pattern['version_unknown'])}")
    if plan.get("excluded"):
        print("Not applicable because of a version")
        for item in plan["excluded"]:
            where = f" [{item['component']}]" if item["component"] else ""
            print(f"  {item['id']}{where}: {'; '.join(item['reasons'])}")
    print("Suggested, not selected: add one only if the team uses it")
    for pattern in plan["suggested"]:
        reason = "choose one overlapping pattern" if pattern.get("choice_required") else "; ".join(pattern["reasons"])
        print(f"  {pattern['id']}: {reason} ({pattern['rules']} rules)")
    print(f"Recommended packs: {', '.join(plan['recommended_packs'])} ({plan['rule_count']} rules in all)")
    print(RULES_NOTE)
    if plan.get("declined"):
        print("Declined in the profile, not proposed again (openguildkit profile adopt brings one back)")
        for entry in plan["declined"]:
            who = f" by {entry['by']} on {entry['on']}: {entry['reason']}" if isinstance(entry, dict) else ""
            print(f"  {entry['id'] if isinstance(entry, dict) else entry}{who}")
    if plan.get("review"):
        print("Selected patterns to review")
        for item in plan["review"]:
            print(f"  {item['id']}: {'; '.join(item['reasons'])}")


def _print_rule_plan(plan: dict, as_json: bool, file=None) -> None:
    file = file or sys.stdout
    if as_json:
        print(json_text(plan), end="", file=file)
        return
    if plan["patterns"]:
        print("Patterns, with why they apply and their rules", file=file)
        for pattern in plan["patterns"]:
            print(f"  {pattern['id']} ({pattern['rules']} rules): {pattern['reason']}", file=file)
        print(f"  {RULES_NOTE}", file=file)
    for regulation in plan["regulations"]:
        print(f"  {regulation['id']} asks: {regulation['asks']}", file=file)
    for entry in plan["declined"]:
        who = f" by {entry['by']} on {entry['on']}: {entry['reason']}" if "by" in entry else ""
        print(f"  Declined, not active: {entry['id']}{who}", file=file)
    print(f"{plan['rule_count']} rules in force; a task is asked only those that concern it.", file=file)
    if plan["rule_warning"]:
        print(f"Warning: {plan['rule_warning']}", file=file)
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
            version = item["version"] or item.get("note") or "version unknown"
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


def _guard_hook(args) -> int:
    """Run as a host hook: in enforce mode, an edit the guard cannot check is refused."""
    try:
        raw = "" if sys.stdin.isatty() else sys.stdin.read()
    except (OSError, UnicodeError):
        raw = None

    def load():
        root = project_root(args.project)
        state = state_path(root)
        catalog = _load_project_catalog(args, state)
        return root, state, load_profile(state, catalog), catalog

    code, out, err = run_hook(args.hook, raw, args.project, load)
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    return code


def _guard(args, root: Path, state: Path) -> int:
    if args.ci:
        result = ci_guard(root, args.base, lambda base_state: _load_project_catalog(args, base_state),
                          require_signed=args.require_signed)
        if args.json:
            _print_json(result)
        else:
            print(f"Guard mode on {args.base}: {result['mode']}. {result['changed']} changed file(s).")
            for task_id in result["decisions"]:
                # A valid record covers the change only when nothing else is wrong, such as a file it does not list.
                where = f".openguildkit/decisions/{task_id}.json"
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
    catalog = _load_project_catalog(args, state)
    profile = load_profile(state, catalog)
    approvals = covering_approvals(root, state, profile, catalog)
    result = {"mode": guard_mode(profile), "covered_by": [item["task"] for item in approvals], "approvals": approvals,
              # Committed decisions show what the repository carries; only a local approved task covers new edits.
              "exported_decisions": [row["task"] for row in exported_decisions(
                  root, state, profile, profile_fingerprint(profile, catalog)) if not row["problem"]]}
    if args.json:
        _print_json(result)
    elif not approvals:
        print(NO_TASK)
    else:
        print("Approved task(s) in progress:")
        for item in approvals:
            stale = f" (approved more than {STALE_DAYS} days ago: confirm it still applies)" if item["stale"] else ""
            print(f"  {item['task']}: {item['brief']}{stale}")
        print(SCOPE_NOTE)
    return 0


def _deliverable(args, root: Path, state: Path, profile: dict, catalog: dict) -> int:
    templates = load_deliverables(catalog, state / "catalog" / "deliverables")
    action = args.deliverable_action
    if action == "list":
        for template in templates.values():
            method = f" (method {template['method']})" if template.get("method") else ""
            print(f"{template['id']:<24} {template['title']}{method} [{', '.join(template['brains'])}]")
        return 0
    if action == "utm":
        names = ("source", "medium", "campaign", "content", "term")
        print(utm_link(args.url, {name: getattr(args, name) for name in names}))
        return 0
    if action == "check":
        path = project_path(root, state, args.path, "deliverable check")
        text = path.read_text(encoding="utf-8")
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
        raise ValueError(f"Unknown deliverable {args.id}. Run openguildkit deliverable list.")
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
        return 0
    if args.share_action == "add":
        if not (args.deliverable and args.until and args.portal and args.by):
            raise ValueError("docs share add needs --deliverable, --recipient, --until, --portal and --by.")
        share = add_share(state, args.deliverable, args.recipient, args.until, args.portal, args.by)
        _print_share_added(share)
        for other in same_access(state, share, running=True):
            for recipient in sorted(set(share["recipients"]) & set(other["recipients"])):
                print(f"OpenGuildKit: {recipient} already has access to space {share['space']} through share {other['id']} "
                      f"(until {other['until']}). Documentalist keeps one access per address and space: removing it there "
                      "ends both shares, so revoke them together.", file=sys.stderr)
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
            shared = sorted({recipient for other in others for recipient in other["recipients"]} & set(share["recipients"]))
            print(f"Other shares give {', '.join(shared)} the same space: if you removed that access there, they lost it "
                  "too. Record each one:")
            for other in others:
                print(f"  openguildkit docs share revoke --id {other['id']} --by NAME   "
                      f"# {', '.join(other['recipients'])}, {other['deliverable']}, until {other['until']}")
        return 0
    rows = share_status(state)
    if args.json:
        _print_json(rows)
    else:
        for row in rows:
            _print_share_row(row)
    expired = [row for row in rows if row["state"].startswith("expired")]
    return 1 if args.share_action == "check" and expired else 0


def _print_share_added(share: dict) -> None:
    """Say what the recipients really get and that the end date is the owner's to keep."""
    print(f"Share {share['id']} recorded. Its perimeter is the whole space {share['space']}: Documentalist shows the "
          f"recipients every published page of that space, not only {share['deliverable']}. Publish the deliverable in a "
          "space that holds only it, or hide the other pages.")
    print("Invite the recipients now in that space's reader settings (magic link mode).")
    print(f"Documentalist keeps no end date: the access lasts until you remove it. After {share['until']}, remove it there "
          f"(\"Retirer l'accès\"), then run openguildkit docs share revoke --id {share['id']} --by NAME. "
          "openguildkit docs share check lists it from the next day.")


def _print_share_row(row: dict) -> None:
    """One share with its perimeter and state; one past its last day says which access to remove and which to keep."""
    space = row["space"] or "unknown: the portal address names no /p/SPACE"
    print(f"{row['id']} {row['deliverable']} (whole space {space}) until {row['until']} "
          f"({len(row['recipients'])} recipient(s)): {row['state']}")
    for recipient in row["remove"]:
        print(f"  remove {recipient} from space {space} in Documentalist (\"Retirer l'accès\")")
    for recipient, other in sorted(row["kept"].items()):
        print(f"  keep {recipient}: share {other['share']} gives the same space until {other['until']}")
    if row["remove"]:
        print(f"  then record it: openguildkit docs share revoke --id {row['id']} --by NAME")


def _read_consultation(task: dict) -> dict:
    if "consultation" not in task:
        raise ValueError("Run task consult first.")
    return task["consultation"]


def _print_brains(args, catalog: dict, families: dict) -> int:
    boards = catalog["boards"]
    if args.id and args.id not in boards:
        raise ValueError(f"Unknown brain: {args.id}. Run openguildkit brains.")
    if args.check:
        gaps = knowledge_gaps(catalog, families)
        for gap in gaps:
            print(f"- {gap}")
        print(f"{len(boards)} brains, {len(gaps)} gap(s).")
        return 1 if gaps else 0
    if args.json:
        if args.id:
            _print_json({**boards[args.id], "knowledge": brain_knowledge(args.id, catalog, families)})
        else:
            _print_json(boards)
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
        for board in boards.values():
            reviewers = board.get("review", {}).get("specialists", [])
            count = f" ({len(reviewers)} specialists)" if reviewers else ""
            print(f"  {board['id']:<23} {board['title']}{count}")
    return 0


def _new_brain(args, state: Path, catalog: dict) -> int:
    """Write a project brain's skeleton and say which tasks the new brain makes stale."""
    with project_lock(state):
        written = write_brain_skeleton(state / "catalog", args.new, catalog)
        updated = _load_project_catalog(args, state)
    for path in written:
        print(f"Wrote {path.as_posix()}")
    print("Replace each TODO, then run openguildkit brains --check and openguildkit sync.")
    if not (state / "project.json").is_file():
        return 0
    profile = load_profile(state, catalog)
    if profile["boards"]:
        print(f"The profile lists its boards: openguildkit profile add board {args.new} --by NAME --reason WHY "
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


def _decide(args, root: Path, state: Path, task: dict, profile: dict) -> None:
    policy = approval_policy(profile)
    base = git_revision(root) if args.approve else None
    signature = None
    if args.approve and policy["mode"] == "signed":
        if not args.signature or not args.signer:
            raise ValueError(
                "This project requires a signed approval: run task decision-payload, sign it with ssh-keygen -Y sign "
                f"-n {NAMESPACE}, then pass --signature FILE --signer PRINCIPAL."
            )
        text = args.signature.read_text(encoding="utf-8")
        verify_signature(root, policy, decision_payload(task, args.by, args.reason, base), text, args.signer)
        signature = {"signer": args.signer, "text": text}
    blocking = blocking_alerts(load_register(state), task) if args.approve else []
    if blocking:
        raise ValueError("Approval is blocked:\n- " + "\n- ".join(blocking))
    removals = pending_removals(task) if args.approve else []
    result = record_decision(task, args.approve, args.by, args.reason, base, signature, removals)
    if args.approve and (signature is None or removals):
        if not sys.stdin.isatty():
            raise ValueError("Approval requires a person at an interactive terminal.")
        recall = previous_round_line(task)
        if recall:
            print(recall, file=sys.stderr)
        print("\n".join(decision_summary(task)), file=sys.stderr)
        if signature is None:
            review = validate_review(task["consultation"], task["review"])
            print("\n".join(["", f"Brief: {task['brief'].strip()}", "", review["summary"], *review_lines(review),
                             "", f"Full decision brief, with each board's evidence: openguildkit task challenge "
                             f"{args.id}", *verdict_lines(review, task.get("deliberation"), is_decision_task(task))]),
                  file=sys.stderr)
            print(f"Type {args.id} to approve the reviewed scope: ", end="", file=sys.stderr, flush=True)
            if input().strip() != args.id:
                raise ValueError("Approval cancelled.")
        for board in removals:
            print(f"The agent removed the {board} board, which the data answer selected. "
                  f"Type {board} to confirm the removal: ", end="", file=sys.stderr, flush=True)
            if input().strip() != board:
                raise ValueError(
                    f"Approval cancelled: the removal of the {board} board was not confirmed. "
                    "Request changes and consult again with it."
                )
    with project_lock(state):
        if read_task(state, args.id) != task:
            raise ValueError("The task changed while you were deciding. Review it and retry.")
        if args.approve:
            catalog = _load_project_catalog(args, state)
            profile = load_profile(state, catalog)
            require_current_scope(task, profile, catalog)
            _require_instructions(args, root, state, profile, catalog)
        write_json(task_path(state, args.id), result)
    print(result["status"])


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
    answers_file = _shell_word(answers_path.as_posix()) if answers_path else "FILE"
    print(f"Change the boards: openguildkit task route {task_id} --answers {answers_file} --add BOARD --remove BOARD "
          "--reason TEXT to preview.")
    options = [*(f"--add {_shell_word(board_id)}" for board_id in selection.get("add") or []),
               *(f"--remove {_shell_word(board_id)}" for board_id in selection.get("remove") or []),
               *(f"--delegate {_shell_word(f'{board_id}={name}')}" for board_id, name in (selection.get("delegate") or {}).items())]
    if options:
        options.append(f"--reason {_shell_word(selection.get('reason') or '')}")
    print(f"Apply: openguildkit task consult {task_id} --answers {answers_file}{''.join(' ' + item for item in options)}")


def _shell_word(value: str) -> str:
    """A command-line word as typed: quoted only when it holds a space or a character a shell reads. A tilde
    inside a word, as in a Windows short path (RUNNER~1), is read by no shell; only a leading one is."""
    if re.fullmatch(r"[\w@%+=:,./-][\w@%+=:,./~-]*", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
            print(f"  {name} ({count} check(s)): {reason}")


def _closing(args, state: Path, task: dict, profile: dict, relevance: dict, root: Path, changed: list[str]) -> dict:
    """The closed task. Deferring evidence or naming who closes needs the person at a terminal."""
    blocking = blocking_alerts(load_register(state), task)
    if blocking:
        raise ValueError("The task cannot be declared done:\n- " + "\n- ".join(blocking))
    if args.defer and not args.by:
        raise ValueError("Name the person who hands the evidence to a follow-up task: --by NAME.")
    deferrals = []
    for item in args.defer:
        check_id, _, follow_up = item.rpartition("=")
        if not check_id or not follow_up:
            raise ValueError("Write --defer EVIDENCE=TASK, for example --defer evidence:gdpr/x/y=privacy-record.")
        deferrals.append((check_id, read_task(state, follow_up)))
    current = defer_evidence(task, profile, deferrals, args.by.strip(), relevance) if deferrals else task
    closed = complete_task(current, profile, root, relevance, args.by, changed=changed)
    if args.by:
        if not sys.stdin.isatty():
            raise ValueError("Closing a task with --by needs the person at an interactive terminal.")
        for group in closed["result"]["closing"]["open_points"]:
            print(f"{group['group']}:", file=sys.stderr)
            for point in group["points"]:
                print(f"  - {point}", file=sys.stderr)
        print(f"Type {args.id} to close it as {closed['status']}: ", end="", file=sys.stderr, flush=True)
        if input().strip() != args.id:
            raise ValueError("Closing cancelled.")
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
        print(f"{count} open point(s), listed above and kept in task show {task['id']} (result.closing).")
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


def _declaration_checks(args, task: dict, profile: dict, check_id: str) -> dict:
    """The task's check commands; a declaration names one of them and the person, at a terminal."""
    commands = {check["id"]: check["command"] for check in expected_checks(task, profile) if check["kind"] == "command"}
    if check_id not in commands:
        raise ValueError(f"{check_id} is not a check command of the task: {', '.join(commands) or 'none'}.")
    if not (args.by or "").strip():
        raise ValueError("Name the person with --by NAME.")
    if not sys.stdin.isatty():
        raise ValueError("Declaring whether a command can run needs the person at an interactive terminal.")
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
    print(f"Type {args.id} to record that {args.cannot_run} (`{commands[args.cannot_run]}`) cannot run here: ",
          end="", file=sys.stderr, flush=True)
    if input().strip() != args.id:
        raise ValueError("Cancelled.")
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


NO_CHECK_COMMAND = (
    "No project check command is configured: task verify ran no test. To have it run one: openguildkit profile add "
    "check \"COMMAND\" --by NAME --reason WHY (docs/workflow.md#project-checks); the change applies to tasks "
    "consulted after it."
)


def _print_remaining(args, task: dict, profile: dict, relevance: dict, root: Path, state: Path,
                     changed: list[str], held: list[str]) -> int:
    """Every point that keeps the task from being done, one per line, then their count.

    The exit status is 1 when task verify finds a mandatory check command failed, so a script or a CI
    job can tell; points that only need answers keep it at 0.
    """
    if args.action == "verify" and not task["consultation"]["scope"].get("checks") and not is_decision_task(task):
        print(NO_CHECK_COMMAND)
    problems = (completion_problems(task, profile, relevance, changed=changed)
                + blocking_alerts(load_register(state), task) + verification_blocker_problems(task, profile, root))
    for problem in problems:
        print(f"- {problem}")
    if problems:
        print(f"{len(problems)} point(s) before the task can be done.")
    elif held:
        print("Nothing else is missing, but some answers were not recorded (above): fix them, or run task complete "
              "with the answers already recorded.")
    elif any(group["group"] == SENSITIVE_GROUP for group in points_left_open(task, profile, relevance)):
        # task complete refuses these without the person: say so now rather than at the closing.
        print(f"Ready to close with the person at a terminal: a data protection, security or AI point stays open, "
              f"so they run openguildkit task complete {args.id} --by NAME.")
    else:
        print("Ready: run task complete.")
    failed = [item for item in task["result"]["checks"]
              if item["check"].startswith("command:") and item["status"] == "failed"]
    return 1 if args.action == "verify" and failed else 0


def _warn_inputs(original: object, recorded: object, label: str) -> None:
    for warning in input_warnings(original, recorded, label):
        print(warning, file=sys.stderr)


def _task_command(args, root: Path, state: Path, profile: dict, catalog: dict) -> int | None:
    action = args.action
    if action == "new":
        if (args.brief is None) == (args.file is None):
            raise ValueError("Supply either a task brief or --file PATH.")
        brief = args.file.read_text(encoding="utf-8-sig") if args.file else args.brief
        _require_instructions(args, root, state, profile, catalog)
        with project_lock(state):
            record = state / DECISIONS_DIR / f"{args.id}.json" if args.id else None
            if record is not None and record.is_file() and not task_path(state, args.id).is_file():
                raise ValueError(f"Task ID {args.id} is already used by the exported decision "
                                 f"{record.relative_to(root).as_posix()}, a teammate's task or an earlier one: read it "
                                 f"with openguildkit task show {args.id}, and choose another ID.")
            print(create_task(state, brief, args.id, args.follows))
        _warn_inputs(brief.strip(), redact_credentials(brief.strip()), "task brief")
        return
    if action == "list" and args.decisions:
        rows = exported_decisions(root, state, profile, profile_fingerprint(profile, catalog))
        if args.json:
            _print_json(rows)
        else:
            _print_decision_rows(rows)
        return
    if action == "list":
        rows = list_tasks(state, args.status, args.owner, args.since, args.until,
                          current_fingerprint=profile_fingerprint(profile, catalog), profile=profile, catalog=catalog)
        clashes = _id_clashes(root, state)
        for row in rows:
            if row["id"] in clashes:
                row["id_used_by_record"] = clashes[row["id"]]
                if not args.json:
                    print(f"OpenGuildKit: {_clash_message(row['id'], clashes[row['id']])}", file=sys.stderr)
        if args.json:
            _print_json(rows)
        elif not rows:
            shared = len(exported_records(state))
            print("No task matches." + (f" {shared} exported decision(s) of the repository, teammates' included: "
                                        "openguildkit task list --decisions" if shared else ""))
        else:
            for row in rows:
                owner = f", approved by {row['owner']}" if row.get("owner") else ""
                if row.get("closed_by"):
                    owner += f", closed by {row['closed_by']}"
                follows = f" (follows {row['follows']})" if row.get("follows") else ""
                print(f"{row['id']} [{row['status']}{owner}] {row.get('brief', '')}{follows}")
                print(f"    next: {row['next']}")
        return

    record = state / DECISIONS_DIR / f"{args.id}.json"
    if not task_path(state, args.id).is_file() and record.is_file():
        if action == "show":
            _show_exported(root, state, profile, catalog, args.id)
            return
        raise ValueError(f"Task {args.id} exists here only as the exported record {record.relative_to(root).as_posix()}, "
                         f"a teammate's task or an earlier one: read it with openguildkit task show {args.id} or "
                         "openguildkit task list --decisions.")
    task = read_task(state, args.id)
    if action in ("show", "checks", "handoff", "export", "verify", "result", "complete"):
        # One answer for every reader: an error stops the action; a note (a completed task's history) is shown.
        problem = approval_problem(task, profile_fingerprint(profile, catalog), profile, catalog)
        if problem and problem["severity"] == "error" and action not in ("show", "checks"):
            raise ValueError(problem["message"])
        if problem and action in ("show", "checks", "export"):
            print(f"OpenGuildKit: {problem['message']}", file=sys.stderr)
        elif problem:
            raise ValueError(problem["message"])
    if action == "show":
        _print_json(task)
    elif action == "questions":
        # One shape with or without answers: the follow-ups carry their prompt, so they can be asked as they are.
        if args.answers is None:
            answers, validated, open_list = {}, None, []
        else:
            answers = read_json(args.answers)
            with _input_file(args.answers):
                validated = validate_answers(answers)
            open_list = open_points(task["brief"], validated)
        questions = task_questions(task["brief"], validated)
        _print_json({
            "questions": questions,
            "follow_ups": sorted(({"id": question["id"], "prompt": question["prompt"]} for question in questions
                                  if question.get("essential") is not None and question["id"] not in answers),
                                 key=lambda item: item["id"]),
            "open_points": open_list,
        })
    elif action == "brief":
        consultation = _read_consultation(task)
        if args.scope:
            _print_json(consultation["scope"])
        elif args.pack:
            print(pack_rules(consultation, args.pack), end="")
        elif args.board:
            board_brief_problem(task, args.board)
            print(board_brief(consultation, args.board))
        else:
            print(consultation["markdown"])
    elif action == "template":
        _print_json(_read_consultation(task)["review_template"])
    elif action == "blockers":
        items = blocker_list(task)
        if args.json:
            _print_json(items)
        elif not items:
            print("No blockers.")
        else:
            for item in items:
                resolution = item["resolution"]
                state = f"{resolution['kind']} by {resolution['by']}" if resolution else "open"
                phase = " (due at verification)" if item.get("phase") == "verification" else ""
                print(f"{item['id']} [{state}]{phase} {item['finding']}")
                if item.get("owner"):
                    print(f"    owner: {item['owner']}; clears when: {item['clears_when']}")
                if resolution and resolution["kind"] == "cleared":
                    print(f"    evidence: {resolution['evidence']}; supports: {resolution['supports']}")
                if resolution and resolution.get("recorded_from") == "no terminal":
                    print("    recorded without a terminal")
    elif action in ("clear", "waive"):
        if task["status"] == "approved":
            require_current_scope(task, profile, catalog)
            check_decision(task, root, profile)
        if action == "waive":
            if not sys.stdin.isatty():
                raise ValueError("A waiver needs a person at an interactive terminal.")
            details = {"kind": "waived", "by": args.by, "reason": args.reason, "scope": args.scope, "until": args.until}
        else:
            details = {"kind": "cleared", "by": args.by, "evidence": args.evidence, "supports": args.supports}
            if (args.signature is None) != (args.signer is None):
                raise ValueError("Pass --signature and --signer together.")
            if args.payload:
                payload = resolve_blocker(task, args.blocker, details, profile, root, signing_payload=True)
                args.payload.write_bytes(payload_text(payload).encode("utf-8"))
                print(args.payload)
                return
            if args.signature:
                if approval_policy(profile)["mode"] != "signed":
                    raise ValueError("A clearance signature is only used in a project with signed approvals.")
                details.update(signature=args.signature.read_text(encoding="utf-8"), signer=args.signer)
        details["terminal"] = sys.stdin.isatty()
        result = resolve_blocker(task, args.blocker, details, profile, root)
        # A signed clearance is the person's act through their key; otherwise the person types the task ID.
        if action == "clear" and "signature" not in details:
            if not details["terminal"]:
                raise ValueError(
                    "Clearing a blocker is the person's act: show them the evidence, and they run task clear in "
                    "their own terminal."
                )
            print(f"Type {args.id} to clear {args.blocker} with {args.evidence}: ", end="", file=sys.stderr,
                  flush=True)
            if input().strip() != args.id:
                raise ValueError("Clearing cancelled.")
        if action == "waive":
            print(f"Type {args.id} to waive {args.blocker} until {args.until}: ", end="", file=sys.stderr, flush=True)
            if input().strip() != args.id:
                raise ValueError("Waiver cancelled.")
        with project_lock(state):
            if read_task(state, args.id) != task:
                raise ValueError("The task changed while you were deciding. Review it and retry.")
            write_json(task_path(state, args.id), result)
        print(details["kind"])
    elif action == "checks":
        if task["status"] not in ("approved", *DONE_STATUSES):
            raise ValueError("Checks belong to an approved task.")
        relevance = _relevance(root, task, profile, catalog, args.all)
        checks = expected_checks(task, profile, relevance)
        reported = {item["check"]: item for item in task.get("result", {}).get("checks", [])}
        if args.json:
            _print_json([{**check, "result": reported.get(check["id"])} for check in checks])
        else:
            _print_checks(checks, reported, task["id"])
    elif action == "result" and args.template:
        if task["status"] != "approved":
            raise ValueError("Results belong to an approved task that is not done yet.")
        relevance = _relevance(root, task, profile, catalog, args.all)
        changed = decision_changes(root, task)
        _print_json(result_template(task, profile, relevance, changed=changed))
        if changed:
            print(decision_revision_message(changed), file=sys.stderr)
    elif action in ("verify", "result", "complete"):
        if task["status"] != "approved":
            raise ValueError("Run checks for an approved task that is not done yet." if action == "verify"
                             else "Results belong to an approved task that is not done yet.")
        check_decision(task, root, profile)
        decision = is_decision_task(task)
        changed = decision_changes(root, task)
        relevance = _relevance(root, task, profile, catalog, getattr(args, "all", False))
        notes = []
        if action == "verify":
            payload = {}
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
        elif action == "complete":
            closing = _closing(args, state, task, profile, relevance, root, changed)
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed meanwhile. Retry.")
            if action == "verify":
                result = record_result(current_task, profile, payload, "verify", relevance, root)
            elif action == "result":
                with _input_file(args.file):
                    result = record_result(current_task, profile, read_json(args.file), "report", relevance, root,
                                           changed=changed)
            else:
                result = closing
            held = result.pop("_held", [])
            write_json(task_path(state, args.id), result)
        for warning in _unshared_evidence(root, {args.id: cited_evidence(result)}):
            print(f"OpenGuildKit: {warning}", file=sys.stderr)
        if action == "complete":
            _print_closing(result, listed=bool(args.by))
            exported = (state / DECISIONS_DIR / f"{args.id}.json").is_file()
            print(f"OpenGuildKit: {'export the decision record again' if exported else 'export the decision record'} "
                  f"so it says the task is completed, and commit it: openguildkit task export {args.id}. guard --ci "
                  "accepts it with the work, or in a pull request of its own once the approval's record is merged: the "
                  "same approval, with its completion added.", file=sys.stderr)
            return
        for line in notes:
            print(line)
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
                  f"{item['why']}). Ask them for it, or hand it to a follow-up task: task complete {args.id} "
                  f"--defer {item['check']}=FOLLOW-UP --by NAME.")
        if criteria_summary(result["result"]):
            print(criteria_summary(result["result"]))
        for warning in result["result"].get("warnings", []):
            print(f"Warning: {warning}")
        return _print_remaining(args, result, profile, relevance, root, state, changed, held)
    elif action == "alerts":
        alerts_cli.task_command(args, state, task)
    elif action == "runs":
        comparison = compare_runs(task)
        if comparison is None:
            raise ValueError("The task has fewer than two ChaosFolk replays to compare.")
        if args.json:
            _print_json(comparison)
        else:
            for name, (before, after) in comparison["changed"].items():
                print(f"{name}: {before or 'absent'} -> {after or 'absent'}")
            print(f"{len(comparison['unchanged'])} scenario(s) unchanged")
    elif action == "export":
        path = export_decision(root, state, task, profile, args.output).resolve()
        print(path.relative_to(root).as_posix() if root in path.parents else str(path))
        if "completed_at" not in task:
            print(f"OpenGuildKit: task {args.id} is not completed yet and the record says so. It lists the files Git "
                  "tracks that changed since the approval, which guard --ci compares with the pull request: export it "
                  "again once the work is committed, and after task complete, and commit it.", file=sys.stderr)
    elif action == "deliberate":
        _print_json(deliberation_request(task))
    elif action == "respond":
        payload = read_json(args.file)
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were deliberating. Run task deliberate again.")
            with _input_file(args.file):
                result = record_deliberation(current_task, payload)
            write_json(task_path(state, args.id), result)
        deliberation = result["deliberation"]
        print(f"{len(deliberation['agreed'])} resolved, {len(deliberation['open'])} open")
        print(RESOLUTION_RULE, file=sys.stderr)
    elif action == "challenge":
        recall = previous_round_line(task)
        if recall:
            print(recall)
        print(challenge_report(task), end="")
    elif action == "route":
        if args.answers is None and "answers" not in task:
            raise ValueError("Pass --answers FILE, or consult the task first.")
        if args.answers:
            with _input_file(args.answers):
                answers = validate_answers(read_json(args.answers))
        else:
            answers = validate_answers(task["answers"])
        selected = select_boards(
            task_scope_profile(profile, catalog, answers.get("components", [])),
            catalog, {**task, "answers": answers}, answers, _selection(args)
        )
        if args.json:
            _print_json(selected)
        else:
            _print_route(state, task, answers, profile, selected, _selection(args), args.answers)
    elif action == "consult":
        if args.brief_file is not None:
            with _input_file(args.brief_file):
                args.revised_brief = args.brief_file.read_text(encoding="utf-8-sig")
        answers = (
            read_json(args.answers)
            if args.answers is not None
            else _prompt_task_questions(args.revised_brief or task["brief"])
        )
        if args.answers is not None:
            with _input_file(args.answers):
                validate_answers(answers)
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were answering. Review it and retry.")
            catalog = _load_project_catalog(args, state)
            profile = load_profile(state, catalog)
            _require_instructions(args, root, state, profile, catalog)
            controls = host_controls(root, profile)
            market = None
            if args.market:
                research = "public-sources" if profile.get("research") == "public-sources" and answers.get("research") == "public" else "local-only"
                market = market_scope_entry(load_dossier(state, args.market), research, brief=" ".join(
                    [args.revised_brief or current_task["brief"], answers.get("context") or ""]))
            families = with_pattern_references(load_references(state / "catalog" / "references"), catalog["patterns"])
            scoped_profile = task_scope_profile(profile, catalog, answers.get("components", []))
            active = set(scoped_profile["packs"])
            context = consultation_context(current_task, answers, scoped_profile, catalog)
            knowledge = {board_id: brief_knowledge(board_id, catalog, families, active, context)
                         for board_id in catalog["boards"]}
            registry = load_tools(state / "catalog" / "tools")
            for board_id in catalog["boards"]:
                usable = connected_tools(state, registry, board_id)
                if usable:
                    knowledge[board_id]["tools"] = usable
            result = record_consultation(alerts_cli.consultation_task(state, current_task), answers, profile, catalog,
                                         _selection(args), controls, market, storybook_scope_entry(state), knowledge,
                                         connected_tools(state, registry), root,
                                         args.revised_brief)
            result.pop("dependency_alerts")
            if "dependency_alerts" in current_task:
                result["dependency_alerts"] = current_task["dependency_alerts"]
            write_json(task_path(state, args.id), result)
        if args.revised_brief is not None:
            _warn_inputs(args.revised_brief.strip(), result["brief"], "revised brief")
        _warn_inputs(answers, redact_data(answers), "task answers")
        print(result["consultation"]["markdown"])
    elif action == "review":
        review = read_json(args.file) if args.file else None
        with project_lock(state):
            current_task = read_task(state, args.id)
            if current_task != task:
                raise ValueError("The task changed while you were reviewing. Read the consultation and retry.")
            if review is not None:
                with _input_file(args.file):
                    result = record_review(current_task, review, root)
            else:
                result = assemble_review(current_task, args.summary)
            write_json(task_path(state, args.id), result)
        print(result["status"])
        if review is not None:
            for warning in tool_evidence_warnings(root, state, result["review"]["boards"]):
                print(f"Warning: {warning}", file=sys.stderr)
    elif action in ("pass", "submit"):
        entry = read_json(args.file) if action == "submit" else None
        with project_lock(state):
            current_task = read_task(state, args.id)
            if action == "pass":
                board_brief_problem(current_task, args.board)
                result = start_pass(current_task, args.board, args.mode or "sequential", args.again)
                submitted = result.pop("_submitted", False)
            else:
                with _input_file(args.file):
                    result = submit_pass(current_task, entry, args.mode, root)
            error = result.pop("_error", None)
            write_json(task_path(state, args.id), result)
        if action == "pass":
            print(board_brief(result["consultation"], args.board))
            if submitted:
                print(f"The {args.board} pass is already submitted; to redo it on purpose, run openguildkit task pass "
                      f"{args.id} {args.board} --again. This copy is for reading only.", file=sys.stderr)
        elif error:
            raise ValueError(f"{args.file.as_posix()}: the pass is recorded as failed. {error}\nFix these points in the "
                             f"file and send it again: openguildkit task submit {args.id} --file {args.file.as_posix()}")
        else:
            print("done")
            saved_entry = result["passes"]["boards"][entry["id"].strip()]["entry"]
            for warning in tool_evidence_warnings(root, state, [saved_entry]):
                print(f"Warning: {warning}", file=sys.stderr)
    elif action == "progress":
        if "consultation" not in task:
            raise ValueError("Run task consult first.")
        progress = pass_progress(task)
        if args.json:
            _print_json(progress)
        else:
            for item in progress:
                details = ", ".join(f"{key} {item[key]}" for key in ("mode", "attempts", "in") if key in item)
                print(f"{item['board']}: {item['status']}{f' ({details})' if details else ''}")
                if "error" in item:
                    print(f"    {item['error']}")
    elif action == "decide":
        _decide(args, root, state, task, profile)
    elif action == "decision-payload":
        if task["status"] != "reviewed":
            raise ValueError(decided_message(task) or "Record the boards' review before preparing a decision.")
        text = payload_text(decision_payload(task, args.by, args.reason, git_revision(root)))
        if args.output:
            # Exact UTF-8 bytes with LF line endings: a shell redirect could change the encoding.
            args.output.write_bytes(text.encode("utf-8"))
            print(args.output)
        else:
            print(text, end="")
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
        evidence = []
        if task.get("status") == "approved":
            evidence = [check for check in asked_checks(task, profile, _relevance(root, task, profile, catalog))
                        if check["kind"] == "evidence"]
        output = handoff(task, evidence)
        check_decision(task, root, profile)
        _require_instructions(args, root, state, profile, catalog)
        print(output)


def _warn_unsigned(profile: dict) -> None:
    """Say once per setup or check command, not on every command, that local approvals can be forged."""
    warning = approval_warning(profile)
    if warning:
        print(warning, file=sys.stderr)


def _run(args) -> int | None:
    if args.command == "guard" and args.hook:
        return _guard_hook(args)
    root = project_root(args.project)
    state = state_path(root)
    if args.command == "guard":
        return _guard(args, root, state)
    if args.command == "ui":
        return webui.serve(root, args.port, args.static, not args.no_browser)
    catalog = _load_project_catalog(args, state)
    if args.command == "references":
        _print_references(args, state, catalog)
    elif args.command == "patterns":
        _print_patterns(args, catalog["patterns"])
    elif args.command == "brains":
        if args.new:
            return _new_brain(args, state, catalog)
        families = with_pattern_references(load_references(state / "catalog" / "references"), catalog["patterns"])
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
        _print_rule_plan(rule_plan(profile, catalog), args.json)
    elif args.command == "recommend":
        if args.answers:
            questions = _setup_questions(root, state, catalog)[0]
            plan = profile_recommendations(complete_answers(read_json(args.answers), questions, catalog)[0], catalog)
        else:
            profile = load_profile(state, catalog)
            plan = {**profile_recommendations(profile, catalog), "review": patterns_to_review(profile, catalog)}
        _print_recommendations(plan, args.json)
    elif args.command == "catalog":
        _print_catalog(catalog, args.json)
    elif args.command == "profile":
        return profile_cli.run(args, root, state, _installed_catalog, _print_touched)
    elif args.command == "tools":
        return tools_cli.run(args, root, state, catalog, load_profile)
    elif args.command == "alerts":
        return alerts_cli.run(args, state)
    elif args.command == "init":
        questions, registry = _setup_questions(root, state, catalog)
        if args.questions:
            _print_json(questions)
            return
        if (state / "project.json").exists():
            raise ValueError(ALREADY_INITIALIZED)
        answers = read_json(args.answers) if args.answers else _interactive_init(questions, catalog, registry)
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
            live, bundled = _installed_catalog(args, state)
            profile, left_aside = setup_profile(answers, live, questions)
            initialize(root, state, profile, live)
            write_lock(state, build_lock(profile, live, bundled))
        print(f"Initialized {root}")
        print("Wrote AGENTS.md, the project rules every agent reads, and CLAUDE.md, one line that imports "
              "AGENTS.md for Claude Code. Delete CLAUDE.md if nobody uses Claude Code: check does not require it.")
        proposed = next(question for question in questions if question["id"] == "checks").get("proposed", [])
        _print_setup_notes(profile, left_aside if args.answers else [], registry, proposed)
        _warn_unsigned(profile)
    elif args.command == "update":
        _update_catalog(args, root, state)
    elif args.command == "sync":
        with project_lock(state):
            live, bundled = _installed_catalog(args, state)
            lock = read_lock(state)
            catalog = apply_lock(live, lock)
            profile = load_profile(state, catalog)
            replaced = sync_instructions(root, profile, catalog)
            lock = build_lock(profile, catalog, bundled, lock)
            write_lock(state, lock)
        print("OpenGuildKit instructions updated.")
        if replaced:
            print(f"Replaced {len(replaced)} line(s) edited by hand in the managed block of AGENTS.md; keep your own "
                  "text outside the markers:")
            for line in replaced[:5]:
                print(f"  - {line[:100]}")
        for record in unshipped_records(lock, bundled):
            print(f"OpenGuildKit: {record} is no longer shipped; it is kept from the catalog lock until you remove it "
                  "from .openguildkit/project.json.", file=sys.stderr)
        _print_touched(tasks_touched(state, profile, catalog))
        pending = _pending_catalog_changes(lock, live, profile, bundled)
        if pending:
            print(f"OpenGuildKit: sync keeps the rules of the catalog lock; the installed catalog changes "
                  f"{len(pending)} of its records ({', '.join(pending)}). Run openguildkit update to review them.",
                  file=sys.stderr)
        for item in patterns_to_review(profile, catalog):
            print(f"OpenGuildKit: review pattern {item['id']}: {'; '.join(item['reasons'])}", file=sys.stderr)
    else:
        profile = load_profile(state, catalog)
        if args.command == "deliverable":
            return _deliverable(args, root, state, profile, catalog)
        if args.command == "docs":
            return _docs(args, root, state, profile, catalog)
        if args.command == "market":
            return market_cli.run(args, state, profile)
        if args.command == "storybook":
            return storybook_command(args, root, state)
        if args.command == "host":
            if args.mode == "check":
                _warn_unsigned(profile)
            controls = host_controls(root, profile)
            written = None
            if args.mode == "apply":
                written = apply_host_settings(root, profile)
                for path in written:
                    print(f"Wrote {path}", file=sys.stderr)
                if not written and profile.get("host", "other") not in ("claude-code", "codex"):
                    print(f"OpenGuildKit: {NO_HOST_SETTINGS}", file=sys.stderr)
                controls = host_controls(root, profile)
            missing = [control for control in controls if control["status"] == "missing"]
            if args.json:
                _print_json(controls)
            else:
                for control in controls:
                    print(f"[{HOST_STATUS_LABELS.get(control['status'], control['status'])}] {control['title']}"
                          f"\n    {control['detail']}")
                if missing:
                    print(f"{len(missing)} setting(s) missing. Run openguildkit host apply, then openguildkit host check.")
                else:
                    print("Nothing missing. A rule marked 'by instruction' or 'by a person' is left to the agent's "
                          "instructions or to a person on purpose: no setting of this host can enforce it.")
            # host apply that writes nothing for the host other has done nothing the person asked for.
            wrote_nothing = written == [] and profile.get("host", "other") not in ("claude-code", "codex")
            return 1 if (missing and args.mode == "check") or wrote_nothing else 0
        if args.command == "check":
            _warn_unsigned(profile)
            fingerprint = profile_fingerprint(profile, catalog)
            # An approval that no longer holds is an error until the task is consulted again; a completed task
            # whose rules changed afterwards is history and stays quiet here (task list shows it).
            failing = [f"{row['id']}: {row['next']}" for row in list_tasks(state, current_fingerprint=fingerprint,
                                                                         profile=profile, catalog=catalog)
                       if row["status"] == "unreadable" or row.get("severity") == "error"]
            records = exported_decisions(root, state, profile, fingerprint)
            failing += [row["problem"]["message"] for row in records
                        if row["problem"] and row["problem"]["severity"] == "error"]
            for line in failing:
                print(f"OpenGuildKit: {line}", file=sys.stderr)
            live, bundled = _installed_catalog(args, state)
            lock = read_lock(state)
            _require_instructions(args, root, state, profile, catalog)
            missing = [control["title"] for control in host_controls(root, profile) if control["status"] == "missing"]
            if missing:
                raise ValueError(f"The host settings do not enforce: {'; '.join(missing)}. "
                                 "Run openguildkit host check for the cause, then openguildkit host apply.")
            if not lock_is_current(lock, profile, catalog, bundled):
                raise ValueError("The catalog lock does not match the profile. Run openguildkit sync.")
            if not failing:
                print("OpenGuildKit instructions match the project profile.")
            pending = _pending_catalog_changes(lock, live, profile, bundled)
            if pending:
                print(f"OpenGuildKit: the installed catalog changes the rules of {len(pending)} locked "
                      f"{'record' if len(pending) == 1 else 'records'} ({', '.join(pending)}). The project keeps its "
                      "locked rules: run openguildkit update to review the changes.", file=sys.stderr)
            undated = _undated_project_sources(state, live)
            if undated:
                print(f"OpenGuildKit: date the sources of {len(undated)} project "
                      f"{'record' if len(undated) == 1 else 'records'}: {', '.join(undated)}. Open each page, then "
                      'add "checked": "YYYY-MM-DD" after its url with that day\'s date (see docs/catalog-format.md).',
                      file=sys.stderr)
            for warning in _sharing_warnings(root, state, records):
                print(f"OpenGuildKit: {warning}", file=sys.stderr)
            if failing:
                raise ValueError(f"The instructions match the project profile, but {len(failing)} "
                                 f"{'approval no longer holds' if len(failing) == 1 else 'approvals no longer hold'}: "
                                 "each line above gives the command to run.")
        elif args.command == "ci-check":
            result = check_export(profile, catalog, args.target_repo, args.commit)
            _print_json(result)
            return 0 if result["status"] == "success" else 1
        elif args.command == "task":
            return _task_command(args, root, state, profile, catalog)


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
    args = _parser().parse_args(argv)
    if getattr(args, "project", None) is not None and not args.project.is_dir():
        what = "is not a folder" if args.project.exists() else "does not exist"
        print(f"OpenGuildKit: The project folder {args.project.as_posix()} {what}. Check --project, or create the "
              "folder and run openguildkit init in it.", file=sys.stderr)
        return 2 if args.command == "ci-check" else 1
    try:
        code = _run(args) or 0
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        return _reader_closed()
    except (OSError, ValueError, EOFError) as error:
        print(f"OpenGuildKit: {str(error) or 'Input ended before completion.'}", file=sys.stderr)
        return 2 if args.command == "ci-check" else 1
    except KeyboardInterrupt:
        print("\nOpenGuildKit: Cancelled.", file=sys.stderr)
        return 130
