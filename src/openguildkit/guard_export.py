"""Exports an approval decision and its withdrawal as a signed record, and names the conflicts between records."""

import json
import re
from pathlib import Path

from . import lazy_re
from .decisions import (
    DECISIONS_DIR,
    changed_paths_since,
    check_decision,
    check_decision_seal,
    export_digest,
    exported_boards,
    exported_rounds,
)
from .project import STATE_DIR
from .storage import read_json, write_json


def export_decision(root: Path, state: Path, task: dict, profile: dict, output: Path | None = None) -> Path:
    """Write a shareable record of an approved decision: no evidence details, no internal notes.

    The record carries the approval payload, and its signature when there is one, so CI can recompute the seal.
    """
    from .delivered_review import exported_review
    from .results import verification_of
    from .tasks_closing import evidence_states
    from .workflow import TaskStateError, exported_blockers, mock_evidence

    if task["status"] not in ("approved", "done", "done-with-reservations"):
        raise TaskStateError("Only an approved or completed task can be exported.")
    check_decision(task, root, profile)
    path = output if output is not None else state / DECISIONS_DIR / f"{task['id']}.json"
    _refuse_foreign_record(root, path, task)
    decision = task["decision"]
    record = {
        "schema_version": RECORD_VERSION,
        "task": task["id"],
        "brief": task["brief"],
        **({"requested_by": task["requested_by"]} if "requested_by" in task else {}),
        "status": task["status"],
        **({"waiting_for": task["waiting_for"]} if task.get("waiting_for") else {}),
        "profile_fingerprint": task["profile_fingerprint"],
        "task_created_at": task["created_at"],
        "summary": task["review"]["summary"],
        "boards": exported_boards(task["review"]),
        # Evidence read from a mock is synthetic: the record says so to anyone who reads it later.
        **({"mock_evidence": mock_evidence(task)} if mock_evidence(task) else {}),
        "decision": {key: decision[key] for key in ("by", "reason", "at", "seal", "base_revision", "separate_requester")
                     if key in decision},
        # A record exported before completion says so; task complete asks for a new export.
        "completed": "completed_at" in task,
    }
    if "completed_at" in task:
        record["completed_at"] = task["completed_at"]
    if task.get("lane"):
        record.update(lane=task["lane"], paths=task["paths"])
    # What the change touches, so that CI can tell this record from a copy brought with another change.
    record["files"] = changed_files(root, decision.get("base_revision"))
    record["decision"]["payload"] = check_decision_seal(task)
    for key in ("signer", "signature"):
        if key in decision:
            record["decision"][key] = decision[key]
    if task.get("rounds"):
        record["rounds"] = exported_rounds(task)
    if task.get("result"):
        # A decision task closes without a result file: its result holds only the closing.
        checks = task["result"].get("checks", [])
        record["result"] = {
            key: task["result"][key] for key in ("revision", "pull_request") if key in task["result"]
        }
        record["result"]["checks"] = {item["check"]: item["status"] for item in checks}
        journals = [
            {"check": item["check"], "evidence": item["evidence"], "sha256": item["sha256"]}
            for item in checks
            if item.get("journal") is True and isinstance(item.get("sha256"), str) and isinstance(item.get("evidence"), str)
        ]
        if journals:
            record["result"]["journals"] = journals
        record["result"]["check_exceptions"] = [
            {key: item[key] for key in ("check", "status", "reason", "owner") if key in item}
            for item in checks if item["status"] in ("skipped", "not-applicable")
        ]
        # A reviewer sees which named evidence was declared not applicable, by whom and why.
        record["result"]["evidence_not_applicable"] = [
            {key: item[key] for key in ("check", "reason", "owner")} for item in checks
            if item["check"].startswith("evidence:") and item["status"] == "not-applicable"
        ]
        # The tool checks that a named evidence exists, never what it says: the record names who confirmed it.
        supplied = [{"check": item["check"], "evidence": item["evidence"], "confirmed_by": item.get("owner")}
                    for item in checks
                    if item["check"].startswith("evidence:") and item["status"] == "passed"]
        if supplied:
            record["result"]["evidence_supplied"] = supplied
            record["result"]["evidence_note"] = "OpenGuildKit checked that each path exists; it did not read the documents."
        record["result"]["criteria"] = [
            {"criterion": item["criterion"], "status": item["status"],
             "verified_by": verification_of(item, task["result"])}
            for item in task["result"].get("criteria", [])
        ]
        for key in ("packs", "warnings", "deferred"):
            if task["result"].get(key):
                record["result"][key] = task["result"][key]
        if "closing" in task["result"]:
            record["result"]["closing"] = task["result"]["closing"]
    blockers = exported_blockers(task)
    if blockers:
        record["blockers"] = blockers
    # The state of each evidence at the export, once one has a fingerprint (task clear, task result).
    states = evidence_states(task, root)
    if states:
        record["evidence_states"] = states
    if task.get("follows"):
        record["follows"] = task["follows"]["task"]
    # The regulations and patterns the profile declined when the task was consulted, with who, when and why.
    declined = task.get("consultation", {}).get("scope", {}).get("declined")
    if declined:
        record["declined"] = declined
    # The boards' findings on the delivered diff, when they reviewed it (task diff-review).
    findings = exported_review(task)
    if findings:
        record["delivered_review"] = findings
    # What was added after the approval (completion, result) is covered by a digest of the whole record.
    record["record_sha256"] = export_digest(record)
    write_json(path, record)
    return path


RECORD_VERSION = 2


def changed_files(root: Path, base_revision: dict | None) -> list[str] | None:
    """The files Git tracks that changed since the approved revision, committed or not, decision records left out.

    None when the approval named no revision (a project outside Git): such a record covers no change in CI.
    """
    if not base_revision or not base_revision.get("commit"):
        return None
    prefix = f"{STATE_DIR}/{DECISIONS_DIR}/"
    return sorted({path for path in changed_paths_since(root, base_revision["commit"]) if not path.startswith(prefix)})


def _same_task(record: object, task: dict) -> bool:
    """Whether an existing record is this task's own earlier export: same ID, same creation time when the record
    names it, and an approval of one of this task's consultations (each has its own random ID)."""
    if not isinstance(record, dict) or record.get("task") != task["id"]:
        return False
    if record.get("task_created_at", task["created_at"]) != task["created_at"]:
        return False
    payload = record.get("decision", {}).get("payload") if isinstance(record.get("decision"), dict) else None
    ids = {task.get("consultation", {}).get("id"), *(item.get("consultation", {}).get("id") for item in task["rounds"])}
    ids.discard(None)
    consultation = payload.get("consultation_id") if isinstance(payload, dict) else None
    return isinstance(consultation, str) and consultation in ids


def record_of_another_task(state: Path, task: dict) -> Path | None:
    """The exported record that uses this local task's ID while it belongs to another task, if any."""
    path = state / DECISIONS_DIR / f"{task['id']}.json"
    if not path.is_file():
        return None
    try:
        record = read_json(path)
    except (OSError, ValueError):
        return path
    return None if _same_task(record, task) else path


def _refuse_foreign_record(root: Path, path: Path, task: dict) -> None:
    """Never replace a record that another task wrote, such as a teammate's decision with the same ID.

    Only a regular file can hold a record: a device such as /dev/null, given with --output, receives it as is.
    """
    if not path.is_file():
        return
    try:
        existing = read_json(path)
    except (OSError, ValueError):
        existing = None
    if not _same_task(existing, task):
        shown = path.resolve().relative_to(root.resolve()).as_posix() if root.resolve() in path.resolve().parents else str(path)
        conflict = conflict_message(path, shown) if existing is None else None
        if conflict:
            raise ValueError(conflict)
        raise ValueError(f"{shown} holds a decision record of another task, such as a teammate's task with the same ID: "
                         f"it is left as it is. Read it with openguildkit task list --decisions; export this task "
                         "with --output to another file, or open it again under another ID.")


def record_shape(record: dict, relative: str) -> None:
    """Refuse a record that openguildkit task export could not have written."""
    decision = record.get("decision")
    problem = None
    if not isinstance(record.get("task"), str) or not isinstance(record.get("profile_fingerprint"), str):
        problem = "task and profile_fingerprint must be text"
    elif not isinstance(decision, dict):
        problem = "decision must be an object"
    elif not all(isinstance(decision.get(key), str) for key in ("seal", "by", "reason")):
        problem = "decision.seal, decision.by and decision.reason must be text"
    elif not isinstance(decision.get("payload", {}), dict):
        problem = "decision.payload must be an object"
    elif not isinstance(decision.get("payload", {}).get("consultation_id", ""), str):
        problem = "decision.payload.consultation_id must be text"
    elif isinstance(record.get("schema_version", 1), bool) or not isinstance(record.get("schema_version", 1), int):
        problem = "schema_version must be a whole number"
    elif "result" in record and not isinstance(record["result"], dict):
        problem = "result must be an object"
    elif record.get("files") is not None and (not isinstance(record["files"], list)
                                              or not all(isinstance(item, str) for item in record["files"])):
        problem = "files must be a list of paths"
    elif ("lane" in record or "paths" in record) and (record.get("lane") != "light" or not isinstance(record.get("paths"), list)
                                                      or not all(isinstance(item, str) for item in record["paths"])):
        problem = "lane and paths go together: the lane is light and paths a list of paths"
    elif "requested_by" in record and not isinstance(record["requested_by"], str):
        problem = "requested_by must be text"
    elif "withdrawn" in record and (not isinstance(record["withdrawn"], dict) or not all(
            isinstance(record["withdrawn"].get(key), str) for key in ("by", "reason", "at"))):
        problem = "withdrawn must name who withdrew the approval, why and when (by, reason, at)"
    if problem:
        raise ValueError(f"{relative} is not a decision record written by openguildkit task export: {problem}. "
                         "Export the decision again or remove the file.")


_CONFLICT_START = lazy_re.compile(r"^<<<<<<< ?(.*)$", re.MULTILINE)


_CONFLICT_END = lazy_re.compile(r"^>>>>>>> ?(.*)$", re.MULTILINE)


_APPROVER = lazy_re.compile(r'"by"\s*:\s*"((?:[^"\\]|\\.)*)"')


def conflict_message(path: Path, relative: str) -> str | None:
    """Name a decision record left with git conflict markers, and whose each side is when the text says it."""
    from .doc_links import doc_link

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    start, end = _CONFLICT_START.search(text), _CONFLICT_END.search(text)
    if not start or not end or "\n=======" not in text:
        return None
    ours = text[start.end():text.index("\n=======", start.end())]
    theirs = text[text.index("\n=======", start.end()):end.start()]
    sides = []
    for label, side in ((start.group(1).strip() or "ours", ours), (end.group(1).strip() or "theirs", theirs)):
        approver = _APPROVER.search(side)
        name = label.split()[0] + (" (this copy)" if label.split()[0] == "HEAD" else "")
        sides.append(f"{name} approved by {json.loads(chr(34) + approver.group(1) + chr(34))}" if approver else name)
    return (f"{relative} holds a git merge conflict: two copies exported a decision for task {path.stem} ("
            f"{'; '.join(sides)}). Two tasks used the same ID: keep the teammate's record, open your work under "
            f"another ID, and export it again (see {doc_link('docs/workflow.md', 'when-two-copies-use-the-same-task-id')}).")


def withdrawal_of(task: dict, record: dict) -> dict | None:
    """Who withdrew, why and when, from the round of the task that holds the approval the record carries."""
    for previous in task.get("rounds", []):
        if isinstance(previous.get("revoked"), dict) and \
                previous.get("decision", {}).get("seal") == record["decision"].get("seal"):
            return {key: previous["revoked"][key] for key in ("by", "reason", "at")}
    return None


def export_withdrawal(root: Path, state: Path, task: dict, output: Path | None = None) -> Path:
    """Write the withdrawal of an approval into the record that task export wrote of it, so that CI refuses it.

    The record keeps the approval as it was, with who withdrew it, why and when; its digest is computed again.
    """
    from .workflow import TaskStateError

    path = output if output is not None else state / DECISIONS_DIR / f"{task['id']}.json"
    shown = path.resolve().relative_to(root.resolve()).as_posix() if root.resolve() in path.resolve().parents else str(path)
    if not any(isinstance(item.get("revoked"), dict) for item in task.get("rounds", [])):
        raise TaskStateError("Only an approved or completed task can be exported, or one whose approval was withdrawn.")
    if not path.is_file():
        raise ValueError(f"The approval of {task['id']} was withdrawn and {shown} does not exist: there is no exported "
                         "record to write the withdrawal into, and nothing for guard --ci to accept.")
    _refuse_foreign_record(root, path, task)
    record = read_json(path)
    record_shape(record, shown)
    withdrawn = withdrawal_of(task, record)
    if withdrawn is None:
        raise ValueError(f"{shown} holds an approval of {task['id']} that was not withdrawn: it is left as it is.")
    record = {key: value for key, value in record.items() if key != "record_sha256"}
    record["withdrawn"] = withdrawn
    record["record_sha256"] = export_digest(record)
    write_json(path, record)
    return path


def untracked_files(root: Path) -> list[str]:
    """The new files Git does not track yet, ignored files and decision records left out: no record lists them."""
    from . import git

    prefix = f"{STATE_DIR}/{DECISIONS_DIR}/"
    return sorted(path for path in git.names(root, "ls-files", "--others", "--exclude-standard", "--full-name") or []
                  if not path.startswith(prefix))


def changes_since_approval(root: Path, task: dict) -> list[str] | None:
    """The files Git tracks that changed since the task's approval, committed or not, and the new files it does not
    track yet (the decision records left out); None when the approval named no Git revision."""
    files = changed_files(root, (task.get("decision") or {}).get("base_revision"))
    return None if files is None else sorted({*files, *untracked_files(root)})
