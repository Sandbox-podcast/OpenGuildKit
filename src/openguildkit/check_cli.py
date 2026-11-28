"""The commands that check a project against its profile: check, guard and host.

Entry: run, check, warn_unsigned, pending_catalog_changes.
Tests: tests/test_guard.py, tests/test_sarif_commands.py, tests/test_hosts.py, tests/test_host_scan.py.
"""

import sys
from pathlib import Path

from . import host_coverage, managed, org_catalog_cli, org_policy_cli
from .catalog import replaced_boards, undated_sources
from .command import Command
from .doc_links import doc_link
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
from .hosts import HOOK_HOSTS, OFF_PATH, apply_host_settings, approval_warning, host_controls
from .lock import (
    LOCK_FILE,
    apply_lock,
    catalog_changes,
    installed_catalog,
    lock_is_current,
    project_catalog,
    read_lock,
    require_instructions,
    update_target,
)
from .project import STATE_DIR, Fingerprints, RuleError, load_profile
from .references import load_references
from .storage import print_json
from .tasks import list_tasks
from .tasks_cli import sharing_issues
from .tools import load_tools
from .wording import plural

HOST_STATUS_LABELS = {"instruction": "by instruction", "human": "by a person"}
NO_HOST_SETTINGS = (
    "the project's host is other, so host apply wrote nothing: OpenGuildKit writes host settings only for "
    "claude-code, codex and gemini-cli. The rules above stay with the AGENTS.md instructions and the CI check. To "
    "install the settings and hooks for one of these agents, run openguildkit profile set host claude-code (or codex) "
    "--by INITIALS --reason WHY, then openguildkit host apply. For Gemini CLI, set the host to gemini-cli."
)


def pending_catalog_changes(lock: dict | None, live: dict, profile: dict, bundled: dict) -> list[str]:
    """Locked records whose rules the installed catalog changes; a source checked again changes no rule."""
    if lock is None:
        return []
    changes = catalog_changes(lock, live, update_target(live, lock), profile, bundled)
    return [
        f"{change['collection']}/{change['id']}" for change in changes
        if change["status"] != "changed" or set(change["fields"]) != {"sources"}
        or change["sources"]["added"] or change["sources"]["removed"]
    ]


def undated_project_sources(state: Path, live: dict) -> list[str]:
    """Project records that cite a source without a checked date; bundled sources always carry one. The project's
    references are read with the catalog it uses, so a pack or a brain they name that does not exist stops check."""
    from .deliverables import load_deliverables  # Kept off the start of sync and init, which import this module.

    project = state / "catalog"
    in_use = apply_lock(live, read_lock(state))
    references = {
        "references": {record["id"]: record for family in load_references(project / "references", in_use).values()
                       for record in family["references"]},
        "deliverables": load_deliverables(live, project / "deliverables"),
    }
    return undated_sources({**live, **references})


def warn_unsigned(profile: dict, report=None) -> None:
    """Say once per setup or check command, not on every command, that local approvals can be forged."""
    warning = approval_warning(profile)
    if warning:
        print(warning, file=sys.stderr)
        if report is not None:
            report.add("approvals-not-signed", "warning", warning.removeprefix("OpenGuildKit: "))


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


def _guard(command: Command) -> int:
    args = command.args
    _require_sarif_options(args)
    if args.hook:
        return _guard_hook(args)
    root, state = command.root, command.state
    if args.ci:
        found: list[dict] = []
        result = ci_guard(root, args.base, lambda base_state: project_catalog(args, base_state),
                          require_signed=args.require_signed, findings=found, org_catalog=args.org_catalog,
                          org_policy_copy=org_policy_cli.ci_copy(args))
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


def _host(command: Command) -> int:
    """Report the rules the host agent enforces (host check), or write its settings and hooks (host apply); scan,
    managed and --matrix go to their own functions."""
    args = command.args
    _require_sarif_options(args)
    if args.strict and args.mode != "scan" or args.allow and args.mode not in ("scan", "managed"):
        raise ValueError(f"{'--strict' if args.strict else '--allow'} is an option of openguildkit host scan.")
    root, state = command.root, command.state
    if args.matrix:  # The coverage of every host, from the tables of the code: no project.
        return host_coverage.run(args)
    if args.mode in ("scan", "managed"):  # managed needs no project: an administrator's machine
        return managed.run(args) if args.mode == "managed" else _host_scan(args, root, state)
    profile = command.profile
    if args.mode == "check":
        warn_unsigned(profile)
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
    from .surfaces import render_scan, scan_exit_code, scan_report, scan_sarif  # 11 ms that only host scan needs.

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
    warn_unsigned(profile, report)
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
    pending = pending_catalog_changes(lock, live, profile, bundled)
    if pending:
        message = (f"the installed catalog changes the rules of {len(pending)} locked "
                   f"{'record' if len(pending) == 1 else 'records'} ({', '.join(pending)}). The project keeps its "
                   "locked rules: run openguildkit update to review the changes.")
        print(f"OpenGuildKit: {message}", file=sys.stderr)
        report.add("catalog-update-pending", "warning", message, f"{STATE_DIR}/{LOCK_FILE}")
    undated = undated_project_sources(state, live)
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
    org_policy_cli.check(state, profile, catalog, report)
    if failing:
        raise RuleError(f"The instructions match the project profile, but {len(failing)} "
                        f"{'approval no longer holds' if len(failing) == 1 else 'approvals no longer hold'}: "
                        "each line above gives the command to run.", None)


HANDLERS = {
    "guard": _guard,
    "host": _host,
    "check": lambda command: check(command.args, command.root, command.state, command.profile, command.catalog),
}


def run(command: Command) -> int:
    return HANDLERS[command.args.command](command)
