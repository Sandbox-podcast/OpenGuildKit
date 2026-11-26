"""The projects command: several OpenGuildKit projects at a glance, and a search across them.

A tech lead or a security officer who looks after several repositories sees where to act without opening each one.
The command takes the folders each time; it registers no project anywhere. It reads each project as its own
commands read it and writes nothing: a folder that is not a project, or a project that cannot be read, is named and
the others are listed.
"""

import contextlib
import io
import shlex
from collections import Counter
from pathlib import Path

from .alerts import LEGACY_STATUSES, load_register
from .decisions import exported_records
from .guard import guard_mode
from .lock import project_catalog
from .project import STATE_DIR, load_profile
from .storage import print_json, read_json
from .tasks import list_tasks, unresolved_blockers

SHOWN_MATCHES = 50
SHOWN_FOLDERS = 10


def add_parser(commands) -> None:
    projects = commands.add_parser("projects", help="Show several projects at a glance: guard, tasks, open points, "
                                                    "alerts and check. Reads only.")
    projects.add_argument("folders", nargs="*", type=Path, default=[Path(".")],
                          help="Project folders, or folders whose subfolders are projects (default: the current one).")
    projects.add_argument("--search", metavar="TEXT",
                          help="Find TEXT in the task briefs, decision reasons and rule IDs of every project.")
    projects.add_argument("--json", action="store_true", help="Print each project and each match as JSON.")


def run(args) -> int:
    folders, others = project_folders(args.folders)
    rows = [_project(args, folder) for folder in folders] + others
    result = {"projects": rows}
    if args.search is not None:
        if not args.search.strip():
            raise ValueError("--search needs some text to find.")
        result["matches"] = [match for folder in folders for match in _matches(folder, args.search)]
    if args.json:
        print_json(result)
    else:
        _print(result, args.search)
    return 0


def is_project(folder: Path) -> bool:
    return (folder / STATE_DIR / "project.json").is_file()


def project_folders(arguments: list[Path]) -> tuple[list[Path], list[dict]]:
    """The project folders the arguments name: a project itself, or the projects among a folder's subfolders.
    The others are rows of their own: a missing path, a folder that holds no project."""
    folders, others = [], []
    for argument in arguments:
        shown = argument.as_posix()
        if not argument.is_dir():
            others.append({"path": shown, "state": "missing" if not argument.exists() else "not-a-folder"})
        elif is_project(argument):
            folders.append(argument)
        else:
            children = sorted(child for child in argument.iterdir() if child.is_dir() and not child.name.startswith("."))
            found = [child for child in children if is_project(child)]
            folders += found
            outside = [child for child in children if child not in found] if found else [argument]
            others += [{"path": child.as_posix(), "state": "not-a-project"} for child in outside]
    return folders, others


def _project(args, folder: Path) -> dict:
    """One project's line: guard mode, approvals, tasks by status, open points, critical alerts and check."""
    row = {"path": folder.as_posix(), "state": "project"}
    try:
        root = folder.resolve(strict=True)
        state = root / STATE_DIR
        catalog = project_catalog(args, state)
        profile = load_profile(state, catalog)
        read = {}
        tasks = list_tasks(state, profile=profile, catalog=catalog, root=root, read=read)
        register = load_register(state)
    except Exception as error:  # Any project that cannot be read is named; the others are still listed.
        return {**row, "state": "unreadable", "message": str(error) or type(error).__name__}
    row.update(
        name=profile.get("name"), guard=guard_mode(profile),
        approvals="signed" if (profile.get("approval") or {}).get("mode") == "signed" else "local",
        tasks=dict(sorted(Counter(task["status"] for task in tasks).items())),
        attention=sum(1 for task in tasks if task["status"] == "unreadable" or task.get("severity") == "error"),
        open_points=sum(_open_points(task) for task in read.values()),
        critical_alerts=sum(1 for alert in register["alerts"] if alert.get("severity") == "critical"
                            and LEGACY_STATUSES.get(alert.get("status"), alert.get("status")) == "confirmed"),
        check=_check(root),
    )
    return row


def _open_points(task: dict) -> int:
    """The blockers a reviewed task still waits on, and the points a task closed with reservations left open."""
    if task["status"] == "reviewed":
        return len(unresolved_blockers(task))
    if task["status"] == "done-with-reservations":
        groups = task.get("result", {}).get("closing", {}).get("open_points", [])
        return sum(len(group.get("points", [])) for group in groups if isinstance(group, dict))
    return 0


def _check(root: Path) -> dict:
    """openguildkit check on the project, in this process, its output kept: whether it passes and, when it fails,
    the last line it printed."""
    from .cli import main  # The CLI imports this module: its entry point is reached when the command runs.

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--project", str(root), "check"])
    lines = [line.removeprefix("OpenGuildKit: ") for line in err.getvalue().splitlines() if line.strip()]
    return {"passes": code == 0, "code": code, "message": lines[-1] if code and lines else None}


def _matches(folder: Path, text: str) -> list[dict]:
    """Each task brief, decision reason and rule ID of the project that holds the text, case aside: the tasks of
    this copy, then the exported records of the tasks it does not hold."""
    wanted = text.casefold()
    matches, held = [], set()
    state = folder / STATE_DIR
    sources = []
    for path in sorted((state / "tasks").glob("*.json")):
        try:
            sources.append(read_json(path))
        except (OSError, ValueError):
            continue
    for _, record in exported_records(state):
        if record is not None:
            sources.append(record)
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("id", item.get("task")), str):
            continue
        task_id = item.get("id", item.get("task"))
        if task_id in held:
            continue
        held.add(task_id)
        decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        checks = result.get("checks")
        statuses = ({entry.get("check"): entry.get("status") for entry in checks if isinstance(entry, dict)}
                    if isinstance(checks, list) else checks if isinstance(checks, dict) else {})
        fields = [("brief", str(item.get("brief", "")).strip().splitlines()[0:1]),
                  ("decision reason", [str(decision.get("reason", ""))])]
        found = [(field, value) for field, values in fields for value in values if wanted in value.casefold()]
        found += [("rule", f"{rule} ({status})") for rule, status in sorted(statuses.items(), key=lambda pair: str(pair[0]))
                  if isinstance(rule, str) and rule.startswith("rule:") and wanted in rule.casefold()]
        matches += [{"project": folder.as_posix(), "task": task_id, "status": item.get("status"), "field": field,
                     "text": value[:120]} for field, value in found]
    return matches


def _summary(row: dict) -> str:
    if row["state"] == "unreadable":
        return f"{row['path']}: cannot be read: {row['message']}"
    if row["state"] in ("missing", "not-a-folder"):
        return f"{row['path']}: {'does not exist' if row['state'] == 'missing' else 'is not a folder'}"
    tasks = ", ".join(f"{count} {status}" for status, count in row["tasks"].items())
    parts = [f"guard {row['guard']}", "approvals signed" if row["approvals"] == "signed" else "approvals not signed",
             f"tasks {tasks}" if tasks else "no task"]
    if row["attention"]:
        parts.append(f"{row['attention']} approval(s) no longer hold")
    if row["open_points"]:
        parts.append(f"{row['open_points']} open point(s)")
    if row["critical_alerts"]:
        parts.append(f"{row['critical_alerts']} critical alert{'s' if row['critical_alerts'] > 1 else ''} confirmed")
    check = row["check"]
    parts.append("check passes" if check["passes"] else f"check fails: {(check['message'] or '')[:160]}")
    return f"{row['path']}: {'; '.join(parts)}"


def _print(result: dict, search: str | None) -> None:
    rows = result["projects"]
    outside = [row["path"] for row in rows if row["state"] == "not-a-project"]
    for row in rows:
        if row["state"] != "not-a-project":
            print(_summary(row))
    if outside:
        more = f" and {len(outside) - SHOWN_FOLDERS} more" if len(outside) > SHOWN_FOLDERS else ""
        print(f"Not OpenGuildKit projects ({len(outside)}): {', '.join(outside[:SHOWN_FOLDERS])}{more}. "
              "Run openguildkit init in a folder to set one up.")
    if not any(row["state"] == "project" or row["state"] == "unreadable" for row in rows):
        print("No OpenGuildKit project found: name project folders, or a folder whose subfolders are projects.")
    if search is not None:
        matches = result["matches"]
        for match in matches[:SHOWN_MATCHES]:
            print(f"{match['project']}: {match['task']} {match['field']}: {match['text']}")
        if len(matches) > SHOWN_MATCHES:
            print(f"{len(matches) - SHOWN_MATCHES} more matches: add --json for all of them.")
        if not matches:
            print(f"No task matches {search!r} in these projects.")
    failing = next((row for row in rows if row["state"] == "project" and not row["check"]["passes"]), None)
    if failing:
        print(f"Next: openguildkit --project {shlex.quote(failing['path'])} check")
