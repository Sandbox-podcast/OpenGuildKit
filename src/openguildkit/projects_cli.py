"""The `projects` command: several projects at a glance and a search across them; a folder that is not a project, or a
project that cannot be read, is named and the others listed. Reads only.

A tech lead or a security officer who looks after several repositories sees where to act without opening each one.
The command takes the folders each time; it registers no project anywhere. It reads each project as its own
commands read it and writes nothing: a folder that is not a project, or a project that cannot be read, is named and
the others are listed.

Three options turn the list into an inventory of a fleet, each off by default (issue #479). --surfaces adds, for
every folder, what host scan finds there: the agent tools, the MCP servers and the permissive settings, so a
folder without a profile where agents already work is named. --policy FILE compares each project with the
minimum a JSON file describes, read and never written, and --strict ends in 1 when one falls short.
--format csv prints one line per folder under a header that does not change.

Entry: add_parser, run
Tests: tests/test_command_output_budget.py, tests/test_performance.py, tests/test_projects.py
"""

import csv
import sys
from collections import Counter
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from .alerts import LEGACY_STATUSES, load_register
from .check_cli import check_status
from .cli import command_parser
from .command import Command
from .decisions import exported_records
from .guard import guard_mode
from .lock import project_catalog, read_lock
from .project import STATE_DIR, load_profile
from .project_setup import GUARD_MODES
from .records import Profile, Task
from .shell import shell_word
from .storage import print_json, read_json
from .tasks import list_tasks
from .tasks_blockers import unresolved_blockers
from .tool_registry import load_tools
from .wording import plural

SHOWN_MATCHES = 50
SHOWN_FOLDERS = 10
POLICY_FIELDS = ("guard", "approvals", "separate_requester")
GUARD_RANK = {mode: rank for rank, mode in enumerate(GUARD_MODES)}
# The columns of --format csv, in this order, whatever the options: a cell is empty when its option was not given.
CSV_COLUMNS = ("path", "state", "name", "guard", "approvals", "tasks", "attention", "open_points", "critical_alerts",
               "check", "host", "hooks", "lock", "catalog_commit", "last_decision", "tools", "mcp_servers",
               "mcp_unpinned", "mcp_unlisted", "permissive", "drift")


def add_parser(commands) -> None:
    projects = commands.add_parser("projects", help="Show several projects at a glance: guard, tasks, open points, "
                                                    "alerts and check. Reads only.")
    projects.add_argument("folders", nargs="*", type=Path, default=[Path(".")],
                          help="Project folders, or folders whose subfolders are projects (default: the current one).")
    projects.add_argument("--search", metavar="TEXT",
                          help="Find TEXT in the task briefs, decision reasons and rule IDs of every project.")
    projects.add_argument("--json", action="store_true", help="Print each project and each match as JSON.")
    projects.add_argument("--surfaces", action="store_true",
                          help="Add what host scan finds in each folder, a project or not: agent tools, MCP servers, "
                               "permissive settings, hooks, lock version and last decision.")
    projects.add_argument("--policy", type=Path, metavar="FILE",
                          help="JSON file with the minimum each project must show (guard, approvals, "
                               "separate_requester); read only. Gaps are named; it reads the surfaces too.")
    projects.add_argument("--strict", action="store_true", help="With --policy: exit 1 when a folder falls short.")
    projects.add_argument("--format", choices=("text", "csv"), default="text",
                          help="csv prints one line per folder under a fixed header, for a spreadsheet.")


def run(command: Command) -> int:
    args = command.args
    policy = read_policy(args.policy) if args.policy is not None else None
    if args.strict and policy is None:
        raise ValueError("--strict compares each project with a policy: add --policy FILE.")
    if args.format == "csv" and (args.json or args.search is not None):
        raise ValueError("--format csv prints the projects only: use --json for the matches of --search, or for a program.")
    surfaces = args.surfaces or policy is not None
    folders, others = project_folders(args.folders)
    rows = [_project(args, folder, policy, surfaces) for folder in folders]
    rows += [_other(row, policy, surfaces) for row in others]
    result = {"projects": rows}
    if args.search is not None:
        if not args.search.strip():
            raise ValueError("--search needs some text to find.")
        result["matches"] = [match for folder in folders for match in _matches(folder, args.search)]
    if args.format == "csv":
        _print_csv(rows)
    elif args.json:
        print_json(result)
    else:
        _print(result, args.search, policy)
    short = sum(1 for row in rows if row.get("drift"))
    if args.strict and short:
        print(f"OpenGuildKit: {short} folder{'s' if short > 1 else ''} fall{'' if short > 1 else 's'} short of the policy.",
              file=sys.stderr)
    return int(args.strict and bool(short))


def read_policy(path: Path) -> dict:
    """The minimum a project must show, from a JSON file read and never written: guard (off, observe or enforce),
    approvals (signed) and separate_requester (true). Anything else is refused, so a typo is not a rule that never fires."""
    try:
        policy = read_json(path)
    except (OSError, ValueError) as error:
        raise ValueError(f"The policy file cannot be read: {error}") from None
    if not isinstance(policy, dict):
        raise ValueError(f"The policy file {path.name} must hold a JSON object.")
    unknown = sorted(str(name) for name in policy if name not in POLICY_FIELDS)
    if unknown:
        raise ValueError(f"The policy file {path.name} names {', '.join(unknown)}: a policy holds "
                         f"{', '.join(POLICY_FIELDS)}.")
    if "guard" in policy and policy["guard"] not in GUARD_RANK:
        raise ValueError(f"The guard of the policy must be {', '.join(list(GUARD_RANK)[:-1])} or {list(GUARD_RANK)[-1]}.")
    if "approvals" in policy and policy["approvals"] != "signed":
        raise ValueError('The approvals of the policy must be "signed".')
    if "separate_requester" in policy and policy["separate_requester"] is not True:
        raise ValueError("separate_requester in the policy must be true.")
    return policy


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


def _project(args, folder: Path, policy: dict | None, surfaces: bool) -> dict:
    """One project's line: guard mode, approvals, tasks by status, open points, critical alerts and check; with
    surfaces, what is found around them, and with a policy, how far it falls short."""
    row: dict = {"path": folder.as_posix(), "state": "project"}
    try:
        root = folder.resolve(strict=True)
        state = root / STATE_DIR
        catalog = project_catalog(args, state)
        profile = load_profile(state, catalog)
        read = {}
        tasks = list_tasks(state, profile=profile, catalog=catalog, root=root, read=read)
        register = load_register(state)
    except Exception as error:  # Any project that cannot be read is named; the others are still listed.
        return _other({**row, "state": "unreadable", "message": str(error) or type(error).__name__}, policy, surfaces)
    row.update(
        name=profile.get("name"), guard=guard_mode(profile),
        approvals="signed" if (profile.get("approval") or {}).get("mode") == "signed" else "local",
        tasks=dict(sorted(Counter(task["status"] for task in tasks).items())),
        attention=sum(1 for task in tasks if task["status"] == "unreadable" or task.get("severity") == "error"),
        open_points=sum(_open_points(task) for task in read.values()),
        critical_alerts=sum(1 for alert in register["alerts"] if alert.get("severity") == "critical"
                            and LEGACY_STATUSES.get(alert.get("status"), alert.get("status")) == "confirmed"),
        check=_check(root, read),
    )
    if surfaces:
        lock = read_lock(state) or {}
        own = state / "catalog" / "tools"
        row.update(_inventory(root, profile, load_tools(own) if own.is_dir() else _bundled_tools()),
                   lock=lock.get("generated_by"), catalog_commit=(lock.get("organization") or {}).get("commit"),
                   last_decision=_last_decision(read, state))
    if policy is not None:
        row["drift"] = _gaps(policy, row, profile)
    return row


@cache
def _bundled_tools() -> dict:
    return load_tools()


def _inventory(folder: Path, profile: Mapping[str, Any], tools: dict) -> dict:
    """What host scan finds in the folder, as the counts a fleet is read by: the agent tools, the MCP servers (all, those
    without a fixed version, those the registry does not know) and the permissive settings, and the state of the hooks of
    the profile's host."""
    from .surfaces import discover  # Only --surfaces and --policy read the folders' agent files.

    found = discover(folder, profile, tools)
    servers, host = found["mcp_servers"], profile.get("host")
    return {"host": host, "hooks": next((item["coverage"]["status"] for item in found["surfaces"] if item["id"] == host), None),
            "tools": [item["id"] for item in found["surfaces"]], "mcp_servers": len(servers),
            "mcp_unpinned": sum(item["pinned"] is False for item in servers),
            "mcp_unlisted": sum(item["registry"] is None for item in servers),
            "permissive": sum(item["code"] == "permissive-setting" for item in found["findings"])}


def _last_decision(read: dict, state: Path) -> str | None:
    """The day of the latest decision among the tasks of this copy and the exported records."""
    records = [*read.values(), *(record for _, record in exported_records(state) if record is not None)]
    days = [record["decision"]["at"][:10] for record in records if isinstance(record.get("decision"), dict)
            and isinstance(record["decision"].get("at"), str)]
    return max(days, default=None)


def _other(row: dict, policy: dict | None, surfaces: bool) -> dict:
    """The row of a folder that is not a readable project: with surfaces, the agents that work in it; under a policy,
    agents at work without a profile, or a project that cannot be read, is a gap."""
    if row["state"] not in ("unreadable", "not-a-project"):
        return row
    if surfaces:
        row.update(_inventory(Path(row["path"]), {}, _bundled_tools()))
    if policy is not None:
        gap = ({"field": "project", "policy": "readable", "found": "unreadable"} if row["state"] == "unreadable"
               else {"field": "project", "policy": "equipped", "found": "not-a-project"})
        row["drift"] = [gap] if row["state"] == "unreadable" or row["tools"] or row["mcp_servers"] else []
    return row


def _gaps(policy: dict, row: dict, profile: Profile) -> list[dict]:
    """Each field of the policy the project falls short of: the policy's value and the project's."""
    gaps = []
    if "guard" in policy and GUARD_RANK.get(row["guard"], -1) < GUARD_RANK[policy["guard"]]:
        gaps.append({"field": "guard", "policy": policy["guard"], "found": row["guard"]})
    if "approvals" in policy and row["approvals"] != policy["approvals"]:
        gaps.append({"field": "approvals", "policy": policy["approvals"], "found": row["approvals"]})
    if policy.get("separate_requester") and profile.get("separate_requester") is not True:
        gaps.append({"field": "separate_requester", "policy": True, "found": False})
    return gaps


def _open_points(task: Task) -> int:
    """The blockers a reviewed task still waits on, and the points a task closed with reservations left open."""
    if task["status"] == "reviewed":
        return len(unresolved_blockers(task))
    if task["status"] == "done-with-reservations":
        groups = task.get("result", {}).get("closing", {}).get("open_points", [])
        return sum(len(group.get("points", [])) for group in groups if isinstance(group, dict))
    return 0


def _check(root: Path, read: dict) -> dict:
    """openguildkit check on the project, in this process (check_cli.check_status): whether it passes and, when it
    fails, the line that says why. It is given the task records the project's line read, so that it reads none again;
    the rest runs as the CLI runs the command: its own options, catalog and profile."""
    return check_status(command_parser().parse_args(["--project", str(root), "check"]), root, read)


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


GAP_WORDS = {
    "guard": lambda gap: f"guard {gap['found']}, the policy asks for {gap['policy']}",
    "approvals": lambda gap: f"approvals not signed, the policy asks for {gap['policy']}",
    "separate_requester": lambda _gap: "requester not kept from approving, the policy asks for it",
    "project": lambda gap: "not an OpenGuildKit project, the policy asks for one" if gap["found"] == "not-a-project"
    else "cannot be read, the policy needs it read",
}


def _servers(row: dict) -> str:
    detail = ", ".join(text for text in (f"{row['mcp_unpinned']} not pinned" if row["mcp_unpinned"] else "",
                                         f"{row['mcp_unlisted']} not in the registry" if row["mcp_unlisted"] else "") if text)
    return plural(row["mcp_servers"], "MCP server") + (f" ({detail})" if detail else "")


def _surfaces_line(row: dict) -> str:
    """What --surfaces adds to a project's line, on a line of its own."""
    host = f"host {row['host'] or 'not set'}" + (f", hooks {row['hooks']}" if row["hooks"] else "")
    parts = [host, f"agent tools {', '.join(row['tools'])}" if row["tools"] else "no agent tool"]
    if row["mcp_servers"]:
        parts.append(_servers(row))
    if row["permissive"]:
        parts.append(plural(row["permissive"], "permissive setting"))
    parts += [f"lock {row['lock']}"] if row["lock"] else []
    parts += [f"organization catalog {row['catalog_commit'][:12]}"] if row["catalog_commit"] else []
    parts += [f"last decision {row['last_decision']}"] if row["last_decision"] else []
    return "    " + "; ".join(parts)


def _summary(row: dict) -> str:
    if row["state"] == "unreadable":
        return f"{row['path']}: cannot be read: {row['message']}"
    if row["state"] in ("missing", "not-a-folder"):
        return f"{row['path']}: {'does not exist' if row['state'] == 'missing' else 'is not a folder'}"
    tasks = ", ".join(f"{count} {status}" for status, count in row["tasks"].items())
    parts = [f"guard {row['guard']}", "approvals signed" if row["approvals"] == "signed" else "approvals not signed",
             f"tasks {tasks}" if tasks else "no task"]
    if row["attention"]:
        parts.append(f"{plural(row['attention'], 'approval')} no longer {'holds' if row['attention'] == 1 else 'hold'}")
    if row["open_points"]:
        parts.append(plural(row['open_points'], 'open point'))
    if row["critical_alerts"]:
        parts.append(f"{row['critical_alerts']} critical alert{'s' if row['critical_alerts'] > 1 else ''} confirmed")
    check = row["check"]
    parts.append("check passes" if check["passes"] else f"check fails: {(check['message'] or '')[:160]}")
    return f"{row['path']}: {'; '.join(parts)}"


def _gap_text(row: dict) -> str:
    return "policy gap: " + ", ".join(GAP_WORDS[gap["field"]](gap) for gap in row["drift"])


def _agents_at_work(row: dict) -> bool:
    return row["state"] == "not-a-project" and bool(row.get("tools") or row.get("mcp_servers"))


def _print(result: dict, search: str | None, policy: dict | None) -> None:
    rows = result["projects"]
    outside = [row["path"] for row in rows if row["state"] == "not-a-project" and not _agents_at_work(row)]
    for row in rows:
        if _agents_at_work(row):
            parts = [f"not an OpenGuildKit project; agents at work: {', '.join(row['tools']) or 'none seen'}"]
            parts += [_servers(row)] if row["mcp_servers"] else []
            parts += [_gap_text(row)] if row.get("drift") else []
            print(f"{row['path']}: {'; '.join(parts)}")
        elif row["state"] != "not-a-project":
            print(_summary(row) + (f"; {_gap_text(row)}" if row.get("drift") else ""))
            if "tools" in row and row["state"] == "project":
                print(_surfaces_line(row))
    if outside:
        more = f" and {len(outside) - SHOWN_FOLDERS} more" if len(outside) > SHOWN_FOLDERS else ""
        print(f"Not OpenGuildKit projects ({len(outside)}): {', '.join(outside[:SHOWN_FOLDERS])}{more}. "
              "Run openguildkit init in a folder to set one up.")
    if not any(row["state"] == "project" or row["state"] == "unreadable" or _agents_at_work(row) for row in rows):
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
        print(f"Next: openguildkit --project {shell_word(failing['path'])} check")
    if policy is not None:
        short = sum(1 for row in rows if row.get("drift"))
        print(f"Policy: {plural(short, 'folder')} fall{'s' if short == 1 else ''} short." if short
              else "Policy: no folder falls short.")


def _cell(value) -> str:
    """A cell of the CSV. A text that starts like a formula gets a quote before it, so that a spreadsheet shows it
    instead of running it: a project's name is typed by whoever owns the repository."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _print_csv(rows: list[dict]) -> None:
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        check, drift = row.get("check"), row.get("drift")
        cells = {**row, "tasks": ";".join(f"{status}:{count}" for status, count in row.get("tasks", {}).items()),
                 "check": "" if check is None else "passes" if check["passes"] else "fails",
                 "tools": ";".join(row.get("tools", [])),
                 "drift": "" if drift is None else ";".join(gap["field"] for gap in drift) or "none"}
        writer.writerow(_cell(cells.get(column)) for column in CSV_COLUMNS)
