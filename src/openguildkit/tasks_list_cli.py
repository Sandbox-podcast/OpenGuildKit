"""The task actions that read the tasks: list, show and retro, with the exported records of a teammate and the
warnings on what the team does not share."""

import sys
from pathlib import Path

from .approval_check import DONE_STATUSES
from .clock import today
from .decisions import DECISIONS_DIR, export_digest, exported_records, ignored_by_git
from .doc_links import doc_link
from .guard_export import record_of_another_task
from .guard_records import exported_decisions
from .project import STATE_DIR
from .project_rules import Fingerprints
from .retro import (
    DEFAULT_MINIMUM,
    draft_pack,
    facts_of_record,
    facts_of_task,
    project_summary,
    render_draft,
    render_project,
    render_task,
    task_retro,
    write_draft,
)
from .storage import print_json, read_json
from .tasks import list_tasks, read_task, task_path
from .tasks_command import TaskCommand
from .tasks_review import cited_evidence
from .tasks_status import decision_words, next_step, state_refusal
from .wording import plural
from .workflow import TaskStateError


def show_exported(root: Path, state: Path, profile: dict, catalog: dict, task_id: str, closing: bool = False) -> None:
    """Show a task known here only by its exported record, with whether that record still holds."""
    row = next(item for item in exported_decisions(root, state, profile, Fingerprints(profile, catalog))
               if item["path"].endswith(f"/{task_id}.json"))
    print(f"OpenGuildKit: task {task_id} exists here only as the exported record {row['path']}.", file=sys.stderr)
    if row["problem"]:
        print(f"OpenGuildKit: {row['problem']['message']}", file=sys.stderr)
    record = read_json(root / row["path"])
    if closing and not isinstance((record.get("result") or {}).get("closing"), dict):
        raise ValueError(f"The exported record of {task_id} has no closing: the task was not completed when it was "
                         "exported.")
    print_json(_closing_points(record, task_id) if closing else record)


def _closing_points(task: dict, task_id: str) -> dict:
    """What a completed task left open, without the rest of its record: task list points here for a task done with
    reservations, whose whole record can weigh a hundred kilobytes."""
    closing = (task.get("result") or {}).get("closing")
    if not isinstance(closing, dict):
        raise TaskStateError("Only a completed task has a closing with its open points.")
    return {"id": task_id, "status": task.get("status"),
            **{key: closing[key] for key in ("by", "verification", "open_points") if key in closing}}


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


def sharing_issues(root: Path, state: Path, records: list[dict], tasks: dict | None = None) -> list[tuple[str, str, str | None]]:
    """What git will not carry to a teammate: tasks named only by exported records, evidence left out of the repository.

    Each issue is its kind (task-absent, task-id-clash or evidence-unshared), the line check prints and the file it is
    about, None when it names none. tasks holds the task records the caller already read, by ID; without it they are
    read here."""
    issues: list[tuple[str, str, str | None]] = []
    absent = sorted({row["task"] for row in records if row["status"] != "unreadable" and not row["local"]})
    if absent:
        issues.append((
            "task-absent",
            f"exported decisions name tasks absent from this copy: {', '.join(absent)}. That is normal for a teammate's "
            "task; if the tasks folder was deleted, these records are what remains (openguildkit task list --decisions).",
            None,
        ))
    issues += [("task-id-clash", _clash_message(task_id, path), path)
               for task_id, path in _id_clashes(root, state, tasks).items()]
    cited = {}
    if tasks is not None:
        cited = {task_id: cited_evidence(task) for task_id, task in sorted(tasks.items())}
    else:
        for path in sorted((state / "tasks").glob("*.json")):  # An unreadable record is reported by check already.
            try:
                cited[path.stem] = cited_evidence(read_task(state, path.stem))
            except ValueError:
                continue
    return issues + unshared_evidence(root, cited)


def _id_clashes(root: Path, state: Path, tasks: dict | None = None) -> dict[str, str]:
    """Local tasks whose ID an exported record of another task uses, such as a teammate's taken in a merge.

    Only the tasks that share an ID with an exported record are read, so a project with many tasks and few
    records lists its tasks as fast as before. tasks holds the task records the caller already read, by ID: then
    only those are compared, and none is read again.
    """
    clashes = {}
    for record in sorted((state / DECISIONS_DIR).glob("*.json")):
        if tasks is not None:
            task = tasks.get(record.stem)
        else:
            try:
                task = read_task(state, record.stem) if task_path(state, record.stem).is_file() else None
            except ValueError:
                task = None
        path = record_of_another_task(state, task) if task is not None else None
        if path is not None:
            clashes[record.stem] = path.relative_to(root).as_posix()
    return clashes


def _clash_message(task_id: str, path: str) -> str:
    return (f"task {task_id} of this copy and the exported decision {path} are different tasks with the same ID. "
            "Leave the record as it is and open your work under another ID with openguildkit task new \"BRIEF\" --id "
            f"NEW-ID (see {doc_link('docs/workflow.md', 'when-two-copies-use-the-same-task-id')}).")


def unshared_evidence(root: Path, cited: dict[str, list[str]]) -> list[tuple[str, str, str | None]]:
    """Evidence a reviewer cannot open from the repository: ignored by git or kept under .openguildkit/tasks/."""
    issues: list[tuple[str, str, str | None]] = []
    ignored = ignored_by_git(root, sorted({path for paths in cited.values() for path in paths}))
    local_only = f"{STATE_DIR}/tasks/"
    for task_id, paths in cited.items():
        unshared = [path for path in paths if path in ignored or path.replace("\\", "/").startswith(local_only)]
        if unshared:
            issues.append((
                "evidence-unshared",
                f"task {task_id} cites evidence a reviewer cannot open from the repository (ignored by git or kept under "
                f"{local_only}): {', '.join(unshared)}. Move it to a committed folder and record it again.",
                f"{STATE_DIR}/tasks/{task_id}.json",
            ))
    return issues


def run_list(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    """The project's tasks with their status and next open point, or the exported decisions."""
    if args.decisions:
        rows = exported_decisions(root, state, profile, Fingerprints(profile, catalog))
        if args.json:
            print_json(rows)
        else:
            _print_decision_rows(rows)
        return
    read: dict = {}
    rows = list_tasks(state, args.status, args.owner, args.since, args.until, profile=profile, catalog=catalog,
                      root=root, read=read, skip=DONE_STATUSES if args.ready else (), indexed=True)
    if args.ready:
        rows = [row for row in rows if row["status"] not in (*DONE_STATUSES, "unreadable") and not row.get("waiting_for")]
    # A task listed from the line the index keeps is not in read: that line holds only while the exported record of
    # its ID is its own, or there is none (tasks_status.kept_line).
    clashes = _id_clashes(root, state, read)
    for row in rows:
        if row["id"] in clashes:
            row["id_used_by_record"] = clashes[row["id"]]
            if not args.json:
                print(f"OpenGuildKit: {_clash_message(row['id'], clashes[row['id']])}", file=sys.stderr)
    if args.json:
        print_json(rows)
    elif not rows:
        shared = len(exported_records(state))
        print("No task matches." + (f" {plural(shared, 'exported decision')} of the repository, teammates' included: "
                                    "openguildkit task list --decisions" if shared else ""))
    else:
        for row in rows:
            owner = f", {row['decided']}" if row.get("decided") else ""
            if row.get("closed_by"):
                owner += f", closed by {row['closed_by']}"
            follows = f" (follows {row['follows']})" if row.get("follows") else ""
            lane = f" (short lane: {', '.join(row['paths'])})" if row.get("lane") else ""
            print(f"{row['id']} [{row['status']}{owner}] {row.get('brief', '')}{lane}{follows}")
            print(f"    next: {row['next']}")
            if row.get("note"):
                print(f"    note: {row['note']}")
            for line in row.get("evidence_changed", []):
                print(f"    changed evidence: {line}")
            if row.get("waiting_for"):
                print(f"    waits for: {', '.join(item['task'] + ' (' + item['status'] + ')' for item in row['waiting_for'])}")


def _retro_record(root: Path, state: Path, task_id: str) -> dict:
    """The facts of a closed task known here only by its exported record, or why the record cannot be read."""
    path = state / DECISIONS_DIR / f"{task_id}.json"
    record = read_json(path)
    where = path.relative_to(root).as_posix()
    if not isinstance(record, dict) or record.get("record_sha256") != export_digest(record):
        raise ValueError(f"The exported record {where} does not match its digest: it was changed after it was "
                         "exported. Restore it from git, or run openguildkit check to see what it reports.")
    try:
        return facts_of_record(record)
    except ValueError:
        raise ValueError(f"The exported record {where} was written before task {task_id} was completed, so it has no "
                         "closing to read. Look at it with openguildkit task list --decisions; once the task is "
                         f"closed, openguildkit task export {task_id} writes it.") from None


def _closed_facts(state: Path) -> tuple[list[dict], dict]:
    """The facts of every closed task of the project, the task records first and the exported records of the others,
    and how many records were left out. A task record read here is the one its exported record repeats."""
    facts, held, ignored = [], set(), {"unreadable_task_records": 0, "exported_records_not_holding": 0}
    for path in sorted((state / "tasks").glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError:
            ignored["unreadable_task_records"] += 1
            continue
        held.add((task["id"], task["created_at"]))
        if task["status"] in DONE_STATUSES:
            facts.append(facts_of_task(task))
    for _, record in exported_records(state):
        if record is None:
            ignored["exported_records_not_holding"] += 1
        elif record.get("completed") is True and record.get("status") in DONE_STATUSES:
            if record.get("record_sha256") != export_digest(record):
                ignored["exported_records_not_holding"] += 1
            elif (record["task"], record.get("task_created_at") or "") not in held:
                facts.append(facts_of_record(record))
    return facts, ignored


def run_retro(args, root: Path, state: Path, profile: dict, catalog: dict) -> None:
    """The retrospective of one closed task, or with --all of the project: read from the records, never written."""
    if bool(args.id) == args.all:
        raise ValueError("Name the closed task to read, openguildkit task retro ID, or count the whole project with "
                         "openguildkit task retro --all (task retro ID reads one task and --all counts them all)."
                         if not args.id else
                         "task retro ID reads one task and --all counts the project: give one of them.")
    if args.minimum is not None and not args.all:
        raise ValueError("--min counts tasks across the project: use it with openguildkit task retro --all.")
    if args.draft_rules is not None and not args.all:
        raise ValueError("--draft-rules drafts rules from what comes back across the project: use it with openguildkit "
                         "task retro --all.")
    minimum = DEFAULT_MINIMUM if args.minimum is None else args.minimum
    if minimum < 1:
        raise ValueError("--min counts tasks: give a number of 1 or more.")
    if args.all:
        facts, ignored = _closed_facts(state)
        summary = project_summary(facts, minimum, profile, catalog, ignored)
        lines = []
        if args.draft_rules is not None:
            pack = draft_pack(summary["recurrences"], today().isoformat())
            summary["draft"] = pack and {"path": write_draft(root, state, args.draft_rules, pack), "pack": pack["id"],
                                         "rules": len(pack["rules"])}
            lines = render_draft(summary["draft"], minimum)
        if args.json:
            print_json(summary)
        else:
            print("\n".join([*render_project(summary), *lines]))
        return
    if task_path(state, args.id).is_file():
        task = read_task(state, args.id)
        if task["status"] not in DONE_STATUSES:
            # Said without judging the approval, which would ask Git: the retrospective starts no process.
            raise ValueError(state_refusal(task, "Only a closed task has a retrospective."))
        record = facts_of_task(task)
    elif (state / DECISIONS_DIR / f"{args.id}.json").is_file():
        record = _retro_record(root, state, args.id)
    else:
        read_task(state, args.id)  # says the task is unknown, with the closest ID and the command that lists them
    retro = task_retro(record)
    if args.json:
        print_json(retro)
    else:
        print("\n".join(render_task(retro)))


def _summary(task: dict, profile: dict) -> str:
    """What task show --summary prints: a screen, whatever the size of the record."""
    decided = decision_words(task)
    lines = [f"{task['id']} [{task['status']}{', ' + decided if decided else ''}] {task['brief'].splitlines()[0][:100]}",
             f"  created: {task['created_at'][:10]}"]
    if task.get("consultation"):
        lines.append(f"  boards: {', '.join(task['consultation']['boards'])}")
    result = task.get("result")
    if result:
        met = sum(item["status"] == "met" for item in result.get("criteria", []))
        passed = sum(item["status"] == "passed" for item in result.get("checks", []))
        lines.append(f"  result: {met} of {len(result.get('criteria', []))} criteria met, "
                     f"{passed} of {len(result.get('checks', []))} checks passed")
    lines += [f"  next: {next_step(task, profile)}", f"  all of it: openguildkit task show {task['id']} --json"]
    return "\n".join(lines)


def run_show(command: TaskCommand) -> None:
    """The task record as JSON, only the open points its closing left, or a summary."""
    args, profile, task = command.args, command.profile, command.task
    if args.summary and args.json:
        raise ValueError("--summary and --json exclude each other: one is a screen, the other the whole record.")
    if args.summary:
        print(_summary(task, profile))
    else:
        print_json(_closing_points(task, args.id) if args.closing else task)
