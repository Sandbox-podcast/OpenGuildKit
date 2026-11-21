"""The `openguildkit alerts` commands and `task alerts`: one dependency alert register per project."""

import sys
from pathlib import Path

from .alerts import (
    REVIEW_STATUSES, STATUSES, accept_alert, find_alert, import_report, link_alert, load_register, migrate_task,
    needs_person, save_register, set_status, summary, task_alerts,
)
from .storage import json_text, project_lock, write_json
from .tasks import read_task, task_path

STATUS_CHOICES = (*REVIEW_STATUSES, "to-verify")


def add_parser(commands) -> None:
    alerts = commands.add_parser(
        "alerts", help="Import scanner reports into the project's dependency alert register and review the alerts.")
    actions = alerts.add_subparsers(dest="alerts_action", required=True)
    imported = actions.add_parser("import", help="Merge an npm audit, pip-audit, OSV-Scanner or Dependabot JSON report.")
    imported.add_argument("report", type=Path, help="The scanner's JSON report.")
    imported.add_argument("--task", help="Link the report's alerts to this task.")
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
    link = actions.add_parser("link", help="Link an alert to the task that handles it.")
    link.add_argument("alert", help="Alert ID.")
    link.add_argument("--task", required=True, help="Task ID.")


def _confirm_person(alert_id: str, what: str) -> None:
    """A person types the alert ID at an interactive terminal, as for a waiver."""
    if not sys.stdin.isatty():
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
        print(f"  [{alert['status']}] {alert['id']} {alert['severity']} {alert['version']}{fix}{accepted}{tasks}")


def _print_changes(changes: dict, as_json: bool) -> None:
    if as_json:
        print(json_text(changes), end="")
        return
    print(f"{changes['tool']}: {len(changes['reported'])} alert(s) reported, {len(changes['new'])} new, "
          f"{len(changes['reopened'])} reopened, {len(changes['resolved'])} resolved.")
    for key in ("new", "reopened", "resolved"):
        for alert_id in changes[key]:
            print(f"  {key}: {alert_id}")


def _review(register: dict, alert_id: str, status: str, by: str, reason: str) -> dict:
    alert = find_alert(register, alert_id)
    if needs_person(alert, status):
        _confirm_person(alert["id"], f"mark {status}")
    return set_status(register, alert_id, status, by, reason)


def run(args, state: Path) -> None:
    action = args.alerts_action
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
            register, changes = import_report(register, args.report, args.task)
        elif action == "set":
            register = _review(register, args.alert, args.status, args.by, args.reason)
        elif action == "accept":
            register = accept_alert(register, args.alert, args.by, args.reason)
            _confirm_person(find_alert(register, args.alert)["id"], "accept")
        else:
            read_task(state, args.task)
            register = link_alert(register, args.alert, args.task)
        save_register(state, register)
    if action == "import":
        _print_changes(changes, args.json)
        _consulted_note(state, args.task, args.json)
    else:
        alert = find_alert(register, args.alert)
        print(f"{alert['id']}: {alert['status']}" + (" (accepted)" if alert.get("accepted") else ""))


def _consulted_note(state: Path, task_id: str | None, as_json: bool) -> None:
    """The boards read the alerts of a task when it is consulted: say so when it already was."""
    if not task_id or as_json:
        return
    task = read_task(state, task_id)
    if "consultation" in task and task.get("status") != "done":
        print(f"{task_id} was already consulted: run openguildkit task consult {task_id} again so that the boards "
              "see these alerts.", file=sys.stderr)


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
    if args.import_file:
        _consulted_note(state, args.id, args.json)
    imports = register.get("imports", [])[-1:] if args.import_file else []
    _print_alerts(alerts, {"summary": summary(alerts, imports)} if args.json else {"imports": imports}, args.json)


def consultation_task(state: Path, task: dict) -> dict:
    """The task as a consultation sees it: only its open and confirmed alerts."""
    alerts = task_alerts(load_register(state), task)
    return {**task, "dependency_alerts": {"alerts": alerts}}
