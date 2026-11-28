"""The trace command: from a file to the exported decisions that cover it, and whether it changed since.

A reviewer, a security officer or an auditor asks which decision covers a file. The exported records list the files
of each change; this command reads them, says for each whether it still holds, and asks Git whether the file changed
after the last decision. It reads and writes nothing else: no task, no record, no Git index.
"""

import hashlib
import os
from pathlib import Path

from . import git
from .decisions import exported_records
from .guard import exported_decisions
from .lock import project_catalog
from .project import Fingerprints, load_profile
from .storage import print_json

_COMMIT = frozenset("0123456789abcdef")


def add_parser(commands) -> None:
    trace = commands.add_parser("trace", help="Show the exported decisions that cover a file, and whether it changed "
                                              "since the last one.")
    trace.add_argument("path", type=Path, help="File of the project, from the current folder or the project root.")
    trace.add_argument("--json", action="store_true", help="Print every decision with its checks and evidence as JSON.")


def run(args, root: Path, state: Path) -> int:
    catalog = project_catalog(args, state)
    profile = load_profile(state, catalog)
    relative = project_file(root, args.path)
    result = trace(root, state, profile, catalog, relative)
    if args.json:
        print_json(result)
    else:
        _print(result)
    return 0


def project_file(root: Path, path: Path) -> str:
    """The path as the records write it, relative to the project root with forward slashes. A relative path is read
    from the current folder when it is inside the project, from the project root otherwise."""
    base = Path.cwd().resolve()
    if not path.is_absolute() and not (base == root or root in base.parents):
        base = root
    target = Path(os.path.normpath(path if path.is_absolute() else base / path))
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise ValueError(f"{path} is outside the project {root.as_posix()}. Name a file inside it, or run the command "
                         "with --project set to the project that holds the file.") from None
    if not relative.parts:
        raise ValueError("Name a file of the project, not its root folder.")
    return relative.as_posix()


def trace(root: Path, state: Path, profile: dict, catalog: dict, relative: str) -> dict:
    """The decisions whose record lists the file, most recent first, the records that cannot be read, and the
    commits on the file after the last decision."""
    rows = {row["path"]: row for row in exported_decisions(root, state, profile, Fingerprints(profile, catalog))}
    decisions, unreadable = [], []
    for path, record in exported_records(state):
        shown = path.relative_to(root).as_posix()
        row = rows.get(shown) or {"status": "unreadable", "problem": None}
        files = record.get("files") if isinstance(record, dict) else None
        listed = isinstance(files, list) and all(isinstance(item, str) for item in files)
        if listed and relative not in files:
            continue
        if not listed or not isinstance(record.get("decision"), dict):
            # A file that is not a record, or a record without its file list: it may cover this file or not.
            if record is None or files is not None:
                message = row["problem"]["message"] if row.get("problem") else "it is not a decision record"
                for prefix in (f"{shown}: ", f"{shown} is ", f"{shown} "):
                    message = message.removeprefix(prefix)
                unreadable.append({"record": shown, "message": message})
            continue
        decisions.append(_decision(root, shown, record, row))
    decisions.sort(key=lambda item: (item["date"] or "", item["task"]), reverse=True)
    result = {"path": relative, "decisions": decisions, "unreadable": unreadable, "changed_since": None, "note": None}
    if decisions:
        result["changed_since"], result["note"] = _changed_since(root, relative, decisions[0])
        # task show prints the exported record of a task this copy does not hold, so the command fits both.
        result["next"] = f"openguildkit task show {decisions[0]['task']}"
    else:
        result["next"] = 'openguildkit task new "BRIEF"'
    return result


def initials(name: str) -> str:
    """CM for Camille Martin; a name already written as initials stays as it is."""
    words = name.split()
    if len(words) == 1 and words[0].isupper() and len(words[0]) <= 4:
        return words[0]
    return "".join(word[0].upper() for word in words[:3] if word[0].isalnum()) or "?"


def _decision(root: Path, shown: str, record: dict, row: dict) -> dict:
    decision = record["decision"]
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    checks = result.get("checks") if isinstance(result.get("checks"), dict) else {}
    by = str(decision.get("by", ""))
    problem = row.get("problem")
    withdrawn = record.get("withdrawn") if isinstance(record.get("withdrawn"), dict) else None
    if problem and problem.get("kind") == "withdrawn-here":
        withdrawn = withdrawn or {"by": "", "at": "", "reason": ""}
    return {
        "task": str(record.get("task")), "record": shown, "status": str(record.get("status", "approved")),
        "completed": bool(record.get("completed")), "date": str(decision.get("at", ""))[:10] or None,
        "by": by, "initials": initials(by), "reason": decision.get("reason"),
        "revision": result.get("revision"), "pull_request": result.get("pull_request"),
        "checks": {"passed": sorted(name for name, status in checks.items() if status == "passed"),
                   "failed": sorted(name for name, status in checks.items() if status == "failed"),
                   "other": sorted(name for name, status in checks.items() if status not in ("passed", "failed"))},
        "evidence_changed": _evidence_changed(root, result),
        "holds": row.get("status") != "unreadable" and problem is None,
        "problem": problem, "withdrawn": withdrawn, "local": bool(row.get("local")),
    }


def _evidence_changed(root: Path, result: dict) -> list[str]:
    """The checks whose journal is in this tree and no longer matches the sha256 the record holds."""
    changed = []
    for item in result.get("journals") if isinstance(result.get("journals"), list) else []:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("check", "evidence", "sha256")):
            continue
        path = root / item["evidence"]
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        except OSError:
            current = None
        if current is not None and current != item["sha256"]:
            changed.append(item["check"])
    return changed


def _git(root: Path, *args: str) -> list[str] | None:
    """The lines Git prints, or None when it fails or is not installed."""
    output = git.text(root, *args)
    return None if output is None else [line for line in output.splitlines() if line.strip()]


def _changed_since(root: Path, relative: str, latest: dict) -> tuple[dict | None, str | None]:
    """The commits on the file after the latest decision: after its delivered revision when Git has it, otherwise
    after the commit that last wrote its record."""
    if _git(root, "rev-parse", "--is-inside-work-tree") != ["true"]:
        return None, "The project is not a Git repository: whether the file changed since the decision is not checked."
    revision = latest["revision"] if isinstance(latest["revision"], str) else ""
    since = None
    if 7 <= len(revision) <= 64 and set(revision) <= _COMMIT \
            and _git(root, "merge-base", "--is-ancestor", revision, "HEAD") is not None:
        since = revision
    else:
        written = _git(root, "log", "-1", "--format=%H", "--", latest["record"])
        since = written[0] if written else None
    if since is None:
        return None, (f"{latest['record']} is not committed and names no delivered revision in this history: whether "
                      "the file changed since the decision is not checked.")
    commits = _git(root, "log", "--format=%H", f"{since}..HEAD", "--", relative) or []
    return {"since": since, "commit": commits[0] if commits else None, "commits": commits}, None


def _print(result: dict) -> None:
    path = result["path"]
    if not result["decisions"]:
        print(f"No exported decision covers {path}. Open a task before changing it: {result['next']}")
    for item in result["decisions"]:
        checks = item["checks"]
        counts = [f"{len(checks[key])} {key}" for key in ("passed", "failed") if checks[key]]
        if 0 < len(checks["failed"]) <= 3:
            counts[-1] += f" ({', '.join(checks['failed'])})"
        if checks["other"]:
            counts.append(f"{len(checks['other'])} skipped or not applicable")
        delivered = (item["revision"] or "")[:7] or item["pull_request"] or "not recorded"
        print(f"{item['task']} [{item['status']}, {item['date'] or 'no date'}, by {item['initials']}] "
              f"revision {delivered}; checks {', '.join(counts) or 'none recorded'}")
        notes = [item["record"], _standing(item)]
        if item["evidence_changed"]:
            notes.append(f"evidence changed since the export: {', '.join(item['evidence_changed'])}")
        print(f"    {'; '.join(notes)}")
    for item in result["unreadable"]:
        print(f"{item['record']} [unreadable]: {item['message']} It may cover {path}: fix or remove it, then trace again.")
    changed = result["changed_since"]
    if changed and changed["commit"]:
        print(f"Changed since the last decision (commit {changed['commit'][:7]}): no decision covers this change.")
    if result["note"]:
        print(result["note"])
    if result["decisions"]:
        print(f"Next: {result['next']}")


def _standing(item: dict) -> str:
    """Whether the decision still covers the file, in the words of task list --decisions."""
    withdrawn = item["withdrawn"]
    if withdrawn and withdrawn.get("by"):
        return (f"withdrawn by {initials(str(withdrawn['by']))} on {str(withdrawn.get('at', ''))[:10]}: "
                "the record covers nothing")
    problem = item["problem"]
    if problem is None:
        return "holds under the current rules"
    message = problem["message"].removeprefix(f"{item['record']}: ").removeprefix(f"{item['record']} ")
    if problem.get("kind") in ("withdrawn", "withdrawn-here"):
        return f"withdrawn, the record covers nothing: {message}"
    return f"{'history' if problem.get('severity') == 'note' else 'does not hold'}: {message}"
