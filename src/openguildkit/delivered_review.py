"""The boards' review of the delivered diff: after task result, before task complete.

Each board of the decision reads the diff between the approved revision and the delivered one, limited to the files of
the change, with what the decision asked (expected outcome, the board's recommendation, verdict and blockers,
disagreements left open, its decision criteria) and its own lens. It returns findings, each with a file, a line, a
severity and an action; task complete keeps a blocking finding, or one left to the person, as an open point. A task
whose diff no board reviewed closes as before.
"""

import json
from pathlib import Path

from . import clock, git, lazy_re
from .sensitive import redact_credentials
from .storage import print_json, project_lock, read_json, write_json
from .wording import plural
from .workflow import TaskStateError, blocker_list, is_decision_task

SEVERITIES = ("blocking", "important", "minor")
ACTIONS = ("fix", "defer", "decision")
# The diff printed in one brief. The rest is one git command away, which the brief prints.
DIFF_LIMIT = 6000
FINDINGS_GROUP = "Findings on the delivered diff"
_COMMIT = lazy_re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_HUNK = lazy_re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
HELP = "Have each board review the diff the task delivered, then record its findings."
FORMAT = {"board": "BOARD", "findings": [{"file": "path/of/the/change.py", "line": 42, "severity": "blocking",
                                          "action": "fix", "finding": "What is wrong, and where the diff shows it."}]}


def add_parser(actions) -> None:
    """The diff-review action of the task command."""
    command = actions.add_parser("diff-review", help=HELP)
    command.add_argument("id", help="Task ID.")
    shown = command.add_mutually_exclusive_group()
    shown.add_argument("--board", help="Print this board's brief: the diff, what the decision asked and its lens.")
    shown.add_argument("--submit", type=Path, metavar="FILE", help="Record one board's findings from a JSON file.")
    command.add_argument("--json", action="store_true", help="Print the brief or the review status as JSON.")


def _git(root: Path, *args: str) -> str | None:
    # A diff names its files as they are on disk, accents included.
    return git.text(root, "-c", "core.quotepath=off", *args)


def _short(revision: str) -> str:
    return revision[:12] if _COMMIT.fullmatch(revision) else revision


def require_reviewable(task: dict) -> None:
    """The delivered diff exists once the approved task records a result with its revision, in a Git repository."""
    if task["status"] != "approved":
        raise TaskStateError("The boards review the delivered diff of an approved task, after task result and before "
                             "task complete.")
    if is_decision_task(task):
        raise ValueError("A task of kind decision delivers no change to the project: there is no diff to review.")
    base = (task["decision"].get("base_revision") or {}).get("commit")
    if not base:
        raise ValueError("The approval names no Git revision (the project was not in Git when it was approved): there "
                         "is no delivered diff to compare with it.")
    if not (task.get("result") or {}).get("revision"):
        raise ValueError(f"Record the delivered revision first: openguildkit task verify {task['id']} reads it from "
                         f"Git, or task result {task['id']} --file FILE names it.")


def delivered_change(root: Path, task: dict) -> dict:
    """The files and the diff between the approved revision and the delivered one, the tool's state folder left out.

    A delivered revision that is not a commit of the repository (the working tree) is compared as the files are now,
    new files Git does not track yet included.
    """
    require_reviewable(task)
    base, revision = task["decision"]["base_revision"]["commit"], task["result"]["revision"]
    committed = bool(_COMMIT.fullmatch(revision)) and _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    spec = [base, revision] if committed else [base]
    names = git.names(root, "diff", "--name-only", "--no-renames", *spec, "--")
    if names is None:
        raise ValueError(f"Git could not compare the approved revision {_short(base)} with the delivered one: check "
                         "that both are in this repository (git fetch), then run the command again.")
    files = [name for name in names if not name.startswith(".openguildkit/")]
    untracked = [] if committed else [
        name for name in git.names(root, "ls-files", "--others", "--exclude-standard") or []
        if not name.startswith(".openguildkit/")]
    diff = _git(root, "diff", "--no-color", "--no-renames", *spec, "--", *files) if files else ""
    stats = {}
    for line in (_git(root, "diff", "--numstat", "--no-renames", *spec, "--", *files) or "").splitlines() if files else []:
        added, removed, name = line.split("\t", 2)
        stats[name] = f"+{added} -{removed}"
    return {"base": base, "revision": revision if committed else "working tree", "delivered": revision,
            "files": sorted(set(files) | set(untracked)), "untracked": sorted(untracked), "stats": stats,
            "diff": diff or "", "added": _added_lines(diff or "", root, untracked),
            "command": f"git diff {' '.join(_short(item) for item in spec)} -- {' '.join(files)}".rstrip(" -")}


def _added_lines(diff: str, root: Path, untracked: list[str]) -> dict[str, set[int]]:
    """The lines of each file that the change created, numbered in the delivered file."""
    added: dict[str, set[int]] = {}
    current, line = None, 0
    for text in diff.splitlines():
        if text.startswith("+++ "):
            current = text[6:] if text.startswith("+++ b/") else None
            continue
        match = _HUNK.match(text)
        if match:
            line = int(match.group(1))
        elif current and text.startswith("+"):
            added.setdefault(current, set()).add(line)
            line += 1
        elif current and text.startswith(" "):
            line += 1
    for name in untracked:
        try:
            count = len((root / name).read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            count = 0
        added[name] = set(range(1, count + 1))
    return added


def _board_ids(task: dict) -> list[str]:
    return [entry["id"] for entry in task["review"]["boards"]]


def _asked(task: dict, board_id: str) -> list[str]:
    """What the decision asked that this board reads the diff against."""
    entry = next(item for item in task["review"]["boards"] if item["id"] == board_id)
    challenge = entry.get("challenge", {})
    lines = []
    if task.get("answers", {}).get("outcome"):
        lines.append(f"Expected outcome: {task['answers']['outcome']}")
    decision = task["decision"]
    lines.append(f"Decision: approved by {decision['by']}: {decision['reason']}")
    lines.append(f"Your recommendation at approval: {entry['recommendation']}")
    if challenge.get("verdict"):
        failure = f"; failure mode: {challenge['failure_mode']}" if challenge.get("failure_mode") else ""
        lines.append(f"Your verdict at approval: {challenge['verdict']}{failure}")
    lines += [f"Question you left open: {question}" for question in entry.get("open_questions", [])]
    for item in blocker_list(task):
        if item["board"] == board_id:
            resolution = item["resolution"]
            state = f"{resolution['kind']} by {resolution['by']}" if resolution else "open"
            lines.append(f"Your blocker {item['id']} ({state}): {item['finding']}")
    deliberation = task.get("deliberation", {})
    objections = {item["id"]: item for item in deliberation.get("objections", [])}
    for item_id in deliberation.get("open", []):
        objection = objections.get(item_id)
        if objection and board_id in (objection["from"], objection["to"]):
            lines.append(f"Disagreement left open: {objection['from']} objects to {objection['to']}: "
                         f"{objection['point']}")
    return lines


def board_brief(task: dict, change: dict, board_id: str) -> dict:
    """One board's brief: the diff, what the decision asked, its lens and the format of its findings."""
    if board_id not in _board_ids(task):
        raise ValueError(f"Board {board_id} did not review this task. Its boards: {', '.join(_board_ids(task))}.")
    stored = task["consultation"].get("board_briefs", {}).get(board_id, {})
    diff = change["diff"]
    truncated = len(diff) > DIFF_LIMIT
    return {
        "task": task["id"], "board": board_id, "title": stored.get("title", board_id),
        "purpose": stored.get("purpose", ""), "base": change["base"], "revision": change["revision"],
        "files": change["files"], "untracked": change["untracked"], "asked": _asked(task, board_id),
        "decision_criteria": stored.get("decision_criteria", []),
        "lenses": [{"title": lens["title"], "focus": lens["focus"]} for lens in stored.get("lenses", [])],
        "diff": diff[:DIFF_LIMIT], "diff_truncated": truncated, "diff_command": change["command"],
        "format": {**FORMAT, "board": board_id},
        "submit": f"openguildkit task diff-review {task['id']} --submit FILE",
    }


def render_brief(brief: dict) -> str:
    revision = ("the working tree" if brief["revision"] == "working tree"
                else f"revision {_short(brief['revision'])}")
    lines = [f"# Delivered diff review: {brief['board']} ({brief['title']})", "",
             f"Task {brief['task']}: compare what was delivered with what the decision asked, through your lens only.",
             f"Approved revision {_short(brief['base'])}; delivered {revision}. Files of the change "
             f"({len(brief['files'])}): {', '.join(brief['files']) or 'none'}."]
    if brief["untracked"]:
        lines.append(f"New files Git does not track yet, not in the diff: read them in full: {', '.join(brief['untracked'])}.")
    lines += ["", "## What the decision asked", "", *(f"- {line}" for line in brief["asked"])]
    lines += [f"- Decision criterion: {line}" for line in brief["decision_criteria"]]
    lines += ["", "## Your lens", ""]
    if brief["purpose"]:
        lines.append(brief["purpose"])
    lines += [f"- {lens['title']}: {lens['focus']}" for lens in brief["lenses"]]
    lines += ["", "## The diff", "", "```diff", brief["diff"].rstrip("\n") or "(no change)", "```"]
    if brief["diff_truncated"]:
        lines.append(f"The diff is cut at {DIFF_LIMIT} characters: read the rest with {brief['diff_command']}")
    lines += ["", "## What to return", "",
              "Write your findings as JSON in a file, then record them: " + brief["submit"], "",
              json.dumps(brief["format"], indent=1, ensure_ascii=False), "",
              "- file and line: a file of the change and a line of its delivered version.",
              "- severity: blocking (must not ship as is), important or minor.",
              "- action: fix (now, before the closing), defer (to a later task; never for a line this change added, "
              "since a problem the change causes is not deferred) or decision (the person decides at the closing).",
              "- An empty findings list records that your board found nothing in the diff."]
    return "\n".join(lines)


def _problems(task: dict, change: dict, payload: object) -> tuple[str | None, list[dict], list[str]]:
    """The board, its findings and every problem of the file at once, as task submit reports them."""
    if not isinstance(payload, dict):
        return None, [], ["The file must be a JSON object with board and findings."]
    problems = []
    board = payload.get("board")
    boards = _board_ids(task)
    if not isinstance(board, str) or board.strip() not in boards:
        problems.append(f"board: got {board!r}; write one of the task's boards: {', '.join(boards)}.")
        board = None
    unknown = sorted(set(payload) - {"board", "findings"})
    if unknown:
        problems.append(f"unexpected {'field' if len(unknown) == 1 else 'fields'}: {', '.join(unknown)}; a file has board and findings only.")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return board, [], [*problems, "findings: expected a list, empty when the board found nothing."]
    recorded = []
    for index, item in enumerate(findings):
        where = f"findings[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: expected an object with file, line, severity, action and finding.")
            continue
        found = _finding_problems(item, where, change)
        problems += found
        if not found:
            recorded.append({"file": item["file"], "line": item["line"], "severity": item["severity"],
                             "action": item["action"], "finding": redact_credentials(" ".join(item["finding"].split()))})
    return (board.strip() if board else None), recorded, problems


def _finding_problems(item: dict, where: str, change: dict) -> list[str]:
    problems = []
    unknown = sorted(set(item) - {"file", "line", "severity", "action", "finding"})
    if unknown:
        problems.append(f"{where}: unexpected {'field' if len(unknown) == 1 else 'fields'} {', '.join(unknown)}.")
    file, line = item.get("file"), item.get("line")
    if not isinstance(file, str) or file not in change["files"]:
        problems.append(f"{where}.file: got {file!r}; name a file of the change: {', '.join(change['files']) or 'none'}.")
    if type(line) is not int or line < 1:
        problems.append(f"{where}.line: got {line!r}; give a line number of the delivered file, from 1.")
    if item.get("severity") not in SEVERITIES:
        problems.append(f"{where}.severity: got {item.get('severity')!r}; write {', '.join(SEVERITIES)}.")
    if item.get("action") not in ACTIONS:
        problems.append(f"{where}.action: got {item.get('action')!r}; write {', '.join(ACTIONS)}.")
    if not isinstance(item.get("finding"), str) or not item["finding"].strip():
        problems.append(f"{where}.finding: say what is wrong, in words.")
    if (item.get("action") == "defer" and isinstance(file, str) and type(line) is int
            and line in change["added"].get(file, set())):
        problems.append(f"{where}: {file}:{line} is a line this change added: a problem the change causes is not "
                        "deferred. Write action fix, or decision to leave it to the person.")
    return problems


def record_findings(task: dict, change: dict, payload: object) -> tuple[dict, str]:
    """The task with one board's findings on the delivered diff, which replace that board's earlier ones."""
    board, findings, problems = _problems(task, change, payload)
    if problems:
        raise ValueError("The findings cannot be recorded:\n- " + "\n- ".join(problems) + "\nFix them in the file and "
                         f"record it again: openguildkit task diff-review {task['id']} --submit FILE")
    review = task.get("delivered_review", {"boards": {}})
    entry = {"base": change["base"], "revision": change["delivered"], "at": clock.timestamp(), "findings": findings}
    return {**task, "delivered_review": {**review, "boards": {**review["boards"], board: entry}}}, board


def review_status(task: dict) -> dict:
    """Which boards reviewed the delivered revision, which reviewed an earlier one, and the findings that stay open."""
    boards = task["review"]["boards"] if "review" in task else []
    reviewed = task.get("delivered_review", {}).get("boards", {})
    delivered = (task.get("result") or {}).get("revision")
    rows = []
    for entry in boards:
        record = reviewed.get(entry["id"])
        row = {"board": entry["id"], "reviewed": record is not None}
        if record is not None:
            row.update(revision=record["revision"], stale=record["revision"] != delivered,
                       findings=len(record["findings"]),
                       blocking=[f"{item['file']}:{item['line']}" for item in record["findings"]
                                 if item["severity"] == "blocking"])
        rows.append(row)
    return {"boards": rows, "delivered": delivered}


def status_line(task: dict) -> str:
    """How many boards reviewed the diff, the blocking findings, and what comes next."""
    status = review_status(task)
    rows = status["boards"]
    done = [row for row in rows if row["reviewed"] and not row["stale"]]
    blocking = [f"{row['board']}, {where}" for row in rows if row["reviewed"] for where in row["blocking"]]
    line = f"{plural(len(done), 'board')} of {len(rows)} reviewed the delivered diff"
    line += f"; {plural(len(blocking), 'blocking finding')} ({'; '.join(blocking)})." if blocking else "; no blocking finding."
    stale = [row["board"] for row in rows if row["reviewed"] and row["stale"]]
    if stale:
        line += f" {', '.join(stale)} reviewed an earlier revision than the delivered one."
    left = [row["board"] for row in rows if not row["reviewed"] or row["stale"]]
    if left:
        return (line + f"\nNext: openguildkit task diff-review {task['id']} --board BOARD for "
                f"{', '.join(left)}, each in its own pass.")
    if blocking:
        return (line + f"\nNext: fix it, record the new revision with openguildkit task result {task['id']}, and "
                "have the board review again; or leave it to the person: task complete keeps it open.")
    return line + f"\nNext: openguildkit task complete {task['id']}."


def open_points(task: dict) -> list[str]:
    """What task complete keeps open: blocking findings, findings left to the person, and reviews of an earlier
    revision than the delivered one."""
    reviewed = task.get("delivered_review", {}).get("boards", {})
    delivered = (task.get("result") or {}).get("revision")
    points = []
    for board, record in sorted(reviewed.items()):
        if record["revision"] != delivered:
            points.append(f"{board} reviewed revision {_short(record['revision'])}, not the delivered "
                          f"{_short(delivered or 'none')}: its findings may be out of date")
        for item in record["findings"]:
            if item["severity"] == "blocking" or item["action"] == "decision":
                points.append(f"{board}: {item['severity']} finding at {item['file']}:{item['line']} "
                              f"({item['action']}): {item['finding']}")
    return points


def exported_review(task: dict) -> dict | None:
    """The findings as the shared decision record carries them, board by board."""
    reviewed = task.get("delivered_review", {}).get("boards")
    if not reviewed:
        return None
    return {board: {key: record[key] for key in ("revision", "at", "findings")} for board, record in sorted(reviewed.items())}


def run(args, root: Path, state: Path, task: dict) -> None:
    """Print the review status or one board's brief, or record one board's findings."""
    from .tasks import read_task, task_path

    change = delivered_change(root, task)
    if args.submit:
        payload = read_json(args.submit)
        with project_lock(state):
            if read_task(state, args.id) != task:
                raise ValueError("The task changed meanwhile. Retry.")
            try:
                updated, board = record_findings(task, change, payload)
            except ValueError as error:
                raise ValueError(f"{args.submit.as_posix()}: {error}") from None
            write_json(task_path(state, args.id), updated)
        findings = updated["delivered_review"]["boards"][board]["findings"]
        print(f"{board}: {plural(len(findings), 'finding')} recorded.")
        print(status_line(updated))
        return
    if args.board:
        brief = board_brief(task, change, args.board)
        print_json(brief) if args.json else print(render_brief(brief))
        return
    _print_overview(args, task, change)


def _print_overview(args, task: dict, change: dict) -> None:
    status = review_status(task)
    if args.json:
        print_json({"task": task["id"], "base": change["base"], "revision": change["revision"],
                    "files": change["files"], "stats": change["stats"], **status})
        return
    shown = ", ".join(f"{name} ({change['stats'][name]})" if name in change["stats"] else name
                      for name in change["files"][:20])
    more = f" and {len(change['files']) - 20} more" if len(change["files"]) > 20 else ""
    revision = "the working tree" if change["revision"] == "working tree" else _short(change["revision"])
    print(f"Delivered diff of task {task['id']}: approved revision {_short(change['base'])} to {revision}, "
          f"{plural(len(change['files']), 'file')}: {shown or 'none'}{more}.")
    print("Each board reads it in its own pass (a subagent when the host has them), with its brief:")
    for row in status["boards"]:
        state = ("not reviewed" if not row["reviewed"] else "reviewed an earlier revision" if row["stale"]
                 else f"reviewed, {plural(row['findings'], 'finding')}")
        print(f"  openguildkit task diff-review {task['id']} --board {row['board']}   [{state}]")
    print(status_line(task))
