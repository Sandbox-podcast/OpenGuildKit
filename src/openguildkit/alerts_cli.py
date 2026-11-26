"""The `openguildkit alerts` commands and `task alerts`: one dependency alert register per project."""

import sys
from pathlib import Path

from . import requester
from .alerts import (
    REVIEW_STATUSES, SEVERITIES, STATUSES, accept_alert, alert_task_id, find_alert, import_report, link_alert,
    load_register, migrate_task, needs_person, save_register, set_severity, set_status, summary, task_alerts,
    task_brief, unhandled_alerts,
)
from .results import DONE_STATUSES
from .storage import json_text, project_lock, read_json, write_json
from .tasks import create_task, read_task, task_path
from .terminal import interactive

STATUS_CHOICES = (*REVIEW_STATUSES, "to-verify")


def add_parser(commands) -> None:
    alerts = commands.add_parser(
        "alerts", help="Import scanner reports into the project's dependency alert register and review the alerts.")
    actions = alerts.add_subparsers(dest="alerts_action", required=True)
    imported = actions.add_parser("import", help="Merge an npm audit, pip-audit, OSV-Scanner or Dependabot JSON report.")
    imported.add_argument("report", type=Path, help="The scanner's JSON report.")
    imported.add_argument("--task", help="Link the report's alerts to this task.")
    imported.add_argument("--scope", help="Name of the project part the report covers, such as front or services/api: "
                          "the import resolves only the alerts of that scope. Without it, only alerts without a scope.")
    imported.add_argument("--json", action="store_true", help="Print what changed as JSON.")
    listing = actions.add_parser("list", help="List the alerts of the register.")
    listing.add_argument("--status", action="append", choices=STATUSES, help="Only this status (repeatable).")
    listing.add_argument("--task", help="Only the alerts linked to this task.")
    listing.add_argument("--without-task", action="store_true", help="Only the alerts no task is linked to.")
    listing.add_argument("--json", action="store_true", help="Print the alerts as JSON.")
    review = actions.add_parser("set", help="Mark an alert open, confirmed, or dismissed with a reason.")
    review.add_argument("alert", help="Alert ID, or ecosystem:package:ADVISORY for any of its advisory IDs.")
    review.add_argument("--status", required=True, choices=STATUS_CHOICES, help="Review status.")
    review.add_argument("--by", required=True, help="Person who reviewed the alert.")
    review.add_argument("--reason", default="", help="Why; required to dismiss.")
    accept = actions.add_parser("accept", help="Record, at a terminal, why a person accepts a confirmed alert.")
    accept.add_argument("alert", help="Alert ID.")
    accept.add_argument("--by", required=True, help="Person who accepts the risk.")
    accept.add_argument("--reason", required=True, help="Why the risk is accepted.")
    severity = actions.add_parser(
        "severity", help="Set, at a terminal, the severity of an alert, such as one pip-audit reports without any.")
    severity.add_argument("alert", help="Alert ID.")
    severity.add_argument("--level", required=True, choices=SEVERITIES, help="The severity to record.")
    severity.add_argument("--by", required=True, help="Person who sets it.")
    severity.add_argument("--reason", required=True, help="Why, such as the advisory's CVSS score.")
    link = actions.add_parser("link", help="Link an alert to the task that handles it.")
    link.add_argument("alert", help="Alert ID.")
    link.add_argument("--task", required=True, help="Task ID.")
    tasks = actions.add_parser("tasks", help="List the confirmed alerts no task handles, with the task each one gets.")
    tasks.add_argument("--open", action="store_true", help="Open each task as a draft and link its alert to it.")
    tasks.add_argument("--json", action="store_true", help="Print the alerts and their tasks as JSON.")


def _confirm_person(alert_id: str, what: str) -> None:
    """A person types the alert ID at an interactive terminal, as for a waiver."""
    if not interactive():
        raise ValueError(f"To {what} {alert_id}, a person runs the command at an interactive terminal.")
    print(f"Type {alert_id} to {what} it: ", end="", file=sys.stderr, flush=True)
    if input().strip() != alert_id:
        raise ValueError("Cancelled.")


def _print_alerts(alerts: list[dict], data: dict, as_json: bool) -> None:
    if as_json:
        print(json_text({**data, "alerts": alerts}), end="")
        return
    for item in data.get("imports", []):
        print(f"Imported {item['alerts']} alert(s) from {item['tool']} ({item['file']}, sha256 {item['sha256'][:12]})")
    counts = summary(alerts, [])["by_status"]
    print(f"{len(alerts)} alert(s): " + ", ".join(f"{count} {status}" for status, count in counts.items()))
    for alert in alerts:
        fix = f" fix: {alert['fix']}" if alert.get("fix") else ""
        accepted = f" accepted by {alert['accepted']['by']}" if alert.get("accepted") else ""
        tasks = f" tasks: {', '.join(alert['tasks'])}" if alert.get("tasks") else ""
        scope = f" scope: {alert['scope']}" if alert.get("scope") else ""
        print(f"  [{alert['status']}] {alert['id']} {alert['severity']} {alert['version']}{scope}{fix}{accepted}{tasks}")


def _print_changes(changes: dict, as_json: bool) -> None:
    if as_json:
        print(json_text(changes), end="")
        return
    scope = f" (scope {changes['scope']})" if changes.get("scope") else ""
    print(f"{changes['tool']}{scope}: {len(changes['reported'])} alert(s) reported, {len(changes['new'])} new, "
          f"{len(changes['reopened'])} reopened, {len(changes['resolved'])} resolved.")
    if changes.get("nothing_analyzed"):
        print(f"  The report analyzed no dependency ({changes['nothing_analyzed']}): it resolves no alert.")
    if changes.get("previous_file"):
        print(f"  Warning: the previous {changes['tool']} import was the file {changes['previous_file']}, and this report "
              "resolves what that one listed. Import one full report per scanner: a report of another lockfile "
              "resolves the alerts of the first. Declare the scope of each report with --scope NAME (for example "
              "--scope front) so that a report resolves only the alerts of its own scope.")
    if changes.get("other_scopes"):
        print(f"  Alerts of the scope(s) {', '.join(changes['other_scopes'])} are left as they are: this import has no "
              "scope, so it concerns only the alerts without one.")
    for key in ("new", "reopened", "resolved"):
        for alert_id in changes[key]:
            print(f"  {key}: {alert_id}")
    for alert_id in changes["acceptance_removed"]:
        print(f"  acceptance removed: {alert_id} (reopened: it blocks its tasks again until a person accepts it again)")
    for alert_id in changes.get("unscoped", []):
        print(f"  kept without scope: {alert_id} (this report lists it, but it has no scope: a report with a scope "
              "neither resolves nor reopens it; an import without --scope does)")


def _review(register: dict, alert_id: str, status: str, by: str, reason: str) -> dict:
    alert = find_alert(register, alert_id)
    if needs_person(alert, status):
        _confirm_person(alert["id"], f"mark {status}")
    return set_status(register, alert_id, status, by, reason)


def _alert_requester(state: Path) -> str | None:
    """The requester of a task opened for an alert, when the profile separates the requester from the approver: the
    watch asked for it, not a person, so any person may approve it. None otherwise, so that the task is as before."""
    try:
        profile = read_json(state / "project.json")
    except (OSError, ValueError):
        return None
    return requester.ALERT_REQUESTER if isinstance(profile, dict) and requester.active(profile) else None


def _alert_tasks(args, state: Path) -> None:
    """One task per confirmed alert that no task handles: the same ID in every copy and every scheduled run, so the
    register links the alert to it as soon as the task is opened, here or by the scheduled watch."""
    rows = []
    with project_lock(state):
        register = load_register(state)
        for alert in unhandled_alerts(register):
            row = {"alert": alert["id"], "severity": alert["severity"], "task": alert_task_id(alert),
                   "brief": task_brief(alert)}
            if args.open:
                if not task_path(state, row["task"]).is_file():
                    create_task(state, row["brief"], row["task"], requested_by=_alert_requester(state))
                register = link_alert(register, alert["id"], row["task"])
            rows.append(row)
        if args.open and rows:
            save_register(state, register)
    if args.json:
        print(json_text(rows), end="")
    elif not rows:
        print("No confirmed alert waits for a task.")
    for row in [] if args.json else rows:
        print(f"{row['alert']} ({row['severity']}): task {row['task']}{' opened' if args.open else ''}")
    if rows and not args.open and not args.json:
        print("Open them with openguildkit alerts tasks --open, then consult each task.")


def run(args, state: Path) -> None:
    action = args.alerts_action
    if action == "tasks":
        _alert_tasks(args, state)
        return
    if action == "list":
        register = load_register(state)
        alerts = register["alerts"]
        if args.task:
            alerts = task_alerts(register, read_task(state, args.task), tuple(STATUSES))
        if args.without_task:
            alerts = [alert for alert in alerts if not alert.get("tasks")]
        if args.status:
            alerts = [alert for alert in alerts if alert["status"] in args.status]
        _print_alerts(alerts, {"summary": summary(alerts, [])}, args.json)
        return
    with project_lock(state):
        register = load_register(state)
        if action == "import":
            if args.task:
                read_task(state, args.task)
            register, changes = import_report(register, args.report, args.task, scope=args.scope)
        elif action == "set":
            register = _review(register, args.alert, args.status, args.by, args.reason)
        elif action == "severity":
            register = set_severity(register, args.alert, args.level, args.by, args.reason)
            _confirm_person(find_alert(register, args.alert)["id"], f"set the severity {args.level} of")
        elif action == "accept":
            register = accept_alert(register, args.alert, args.by, args.reason)
            _confirm_person(find_alert(register, args.alert)["id"], "accept")
        else:
            read_task(state, args.task)
            register = link_alert(register, args.alert, args.task)
        save_register(state, register)
    if action == "import":
        _print_changes(changes, args.json)
        if args.task:
            task = read_task(state, args.task)
            _consult_again_note(task, task_alerts(register, task), args.json)
    else:
        alert = find_alert(register, args.alert)
        severity = f", severity {alert['severity']}" if action == "severity" else ""
        print(f"{alert['id']}: {alert['status']}{severity}" + (" (accepted)" if alert.get("accepted") else ""))


def task_command(args, state: Path, task: dict) -> None:
    """`task alerts ID`: import, review or link alerts in the register for one task, then list them."""
    with project_lock(state):
        current = read_task(state, args.id)
        register, migrated = migrate_task(load_register(state), current)
        if args.import_file:
            register, _ = import_report(register, args.import_file, args.id)
        if args.link:
            register = link_alert(register, args.link, args.id)
        if args.alert_id:
            if not args.status:
                raise ValueError("Give --status with --set.")
            register = _review(register, args.alert_id, args.status, args.by or "", args.reason)
        if migrated != current or args.import_file or args.link or args.alert_id:
            save_register(state, register)
        if migrated != current:
            write_json(task_path(state, args.id), migrated)
    alerts = task_alerts(register, migrated, tuple(STATUSES))
    imports = register.get("imports", [])[-1:] if args.import_file else []
    _print_alerts(alerts, {"summary": summary(alerts, imports)} if args.json else {"imports": imports}, args.json)
    if args.import_file:
        _consult_again_note(migrated, task_alerts(register, migrated), args.json)


def _consult_again_note(task: dict, active: list[dict], as_json: bool) -> None:
    """The boards read a task's alerts when it is consulted: say so when its consultation lacks an active one."""
    held = {alert["id"] for alert in task.get("consultation", {}).get("scope", {}).get("dependency_alerts", [])}
    if "consultation" in task and task["status"] not in DONE_STATUSES and not as_json and any(
            alert["id"] not in held for alert in active):
        print(f"The task was consulted before this import: consult it again with openguildkit task consult "
              f"{task['id']} --reuse-answers so the boards see its alerts.")


def consultation_task(state: Path, task: dict) -> dict:
    """The task as a consultation sees it: only its open and confirmed alerts."""
    alerts = task_alerts(load_register(state), task)
    return {**task, "dependency_alerts": {"alerts": alerts}}
