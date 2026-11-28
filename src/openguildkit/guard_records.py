"""Checks the decision records a project exports: their shape, their seal, their history and the conflicts between them."""

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from . import lazy_re
from .decisions import (
    DECISIONS_DIR,
    approval_policy,
    date_moved,
    export_digest,
    exported_records,
    history_message,
    outside_history_message,
    seal,
    shared_digest,
    stale_approval_message,
    verify_recorded_signature,
    verify_signature,
)
from .guard import read_task_lazily
from .guard_export import RECORD_VERSION, conflict_message, record_shape, withdrawal_of

if TYPE_CHECKING:
    from .project_rules import Fingerprints


def record_check(record: dict, relative: str, fingerprint: "str | Fingerprints", policy: dict, base_root: Path,
                  earlier: dict, *, extracted: bool = False, history: Path | None = None) -> tuple[str, str, str] | None:
    """The kind of problem a decision record has, its message and the code of its rule (docs/sarif.md), or None when
    it holds.

    extracted says that base_root holds files copied from a Git revision (CI) rather than a working copy; history is
    then the repository whose history holds the signers of an approval the base revision already carries.
    """
    found = _record_fault(record, relative, fingerprint, policy, base_root, earlier, extracted=extracted, history=history)
    if found is None:
        return None
    code, message = found
    if code == "decision-stale":
        return "earlier-rules", f"{relative}: {stale_approval_message(record['task'])}", code
    if code == "decision-record-unverified":
        return "earlier-record", (f"{relative} was exported by an earlier release, before records carried a digest: its "
                                  f"content is not verified. Export it again with openguildkit task export {record['task']}."), code
    if code == "decision-withdrawn":
        withdrawn = record.get("withdrawn") or earlier[record["task"]]["withdrawn"]
        return "withdrawn", (f"{relative}: the approval of {record['task']} was withdrawn by {withdrawn['by']} on "
                             f"{withdrawn['at'][:10]} ({withdrawn['reason']}): the record covers no change. Open a new task "
                             "for this work."), code
    return "invalid-record", message, code


_COMMIT = lazy_re.compile(r"[0-9a-f]{7,64}")


def in_history(history: Path, commit: object) -> bool:
    """Whether HEAD of the repository contains the commit: a commit git does not have, or one HEAD does not reach,
    is outside its history."""
    from . import git

    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        return False
    return git.text(history, "merge-base", "--is-ancestor", commit, "HEAD") is not None


def _earlier_withdrawal(earlier: dict, task_id: str) -> bool:
    before = earlier.get(task_id)
    return isinstance(before, dict) and isinstance(before.get("withdrawn"), dict) and all(
        isinstance(before["withdrawn"].get(key), str) for key in ("by", "reason", "at"))


def _rules_hold(fingerprint: "str | Fingerprints", recorded: str) -> bool:
    """Whether a record was approved under the current rules; a Fingerprints also accepts the fingerprint that an
    earlier release recorded for the same rules, so that an upgrade does not turn every record into earlier rules."""
    from .project_rules import Fingerprints

    return fingerprint.holds(recorded) if isinstance(fingerprint, Fingerprints) else recorded == fingerprint


def _payload_fault(record: dict, relative: str, payload: dict | None, export_again: str) -> tuple[str, str] | None:
    """A record whose approval payload is missing, or whose seal, file name, lane, requester or shown review does not
    match what was approved."""
    decision = record["decision"]
    if payload is None:
        return "decision-record-invalid", f"{relative} carries no approval payload. {export_again}"
    expected = {"task": record["task"], "outcome": "approved", "profile_fingerprint": record["profile_fingerprint"],
                "by": decision["by"], "reason": decision["reason"]}
    if any(payload.get(key) != value for key, value in expected.items()) or seal(payload) != decision["seal"] \
            or date_moved(decision, payload):  # A local approval dated by the audit log keeps the date it was sealed at.
        return "decision-record-invalid", f"{relative}: the seal does not match the approval it records. {export_again}"
    if PurePosixPath(relative).parent.name == DECISIONS_DIR and PurePosixPath(relative).stem != record["task"]:
        return "decision-record-invalid", (
            f"{relative} names task {record['task']}: each record belongs in the file of its own task. {export_again}")
    if (record.get("lane"), record.get("paths")) != (payload.get("lane"), payload.get("paths")):
        return "decision-record-invalid", (f"{relative}: the lane or the paths of the record are not those that were "
                                           f"approved. {export_again}")
    if record.get("requested_by") != payload.get("requested_by"):
        return "decision-record-invalid", (f"{relative}: the requester of the record is not the one that was approved. "
                                           f"{export_again}")
    shown = shared_digest(record.get("brief"), record.get("summary"), record.get("boards"), record.get("rounds", []))
    if "shared_sha256" in payload and payload["shared_sha256"] != shown:
        return "decision-record-invalid", (
            f"{relative}: what the record shows (brief, summary, board verdicts and recommendations, earlier "
            f"rounds) does not match what was approved. {export_again}")
    return None


def _signature_fault(record: dict, relative: str, payload: dict, policy: dict, base_root: Path, earlier: dict,
                     extracted: bool, history: Path | None) -> tuple[str, str] | None:
    """Under signed approvals: a decision with no signature, or one the allowed signers do not verify."""
    decision = record["decision"]
    if not isinstance(decision.get("signature"), str) or not isinstance(decision.get("signer"), str):
        return "decision-unsigned", f"{relative}: the project requires signed approvals and this decision is not signed."
    try:
        # An approval the base revision already carries may come from an approver who has left since; a new one
        # must come from a current approver.
        if record["task"] in earlier or not extracted:
            verify_recorded_signature(base_root, policy, payload, decision["signature"], decision["signer"],
                                      committed=not extracted, history=history)
        else:
            verify_signature(base_root, policy, payload, decision["signature"], decision["signer"], committed=False,
                             at_signing=True)
    except ValueError as error:
        return "decision-signature-invalid", f"{relative}: {error}"
    return None


def _record_fault(record: dict, relative: str, fingerprint: "str | Fingerprints", policy: dict, base_root: Path, earlier: dict,
                  *, extracted: bool = False, history: Path | None = None) -> tuple[str, str] | None:
    """What is wrong with a record: the code of its rule (docs/sarif.md) and a message, which record_check writes
    for the codes decision-stale, decision-record-unverified and decision-withdrawn; None when it holds.

    Records written from RECORD_VERSION on carry two digests: the approval's seal covers what the record shows of
    the approval, and record_sha256 the whole record. A record that has neither was exported by an earlier release.
    """
    decision = record["decision"]
    payload = decision.get("payload")
    export_again = f"Export it again with openguildkit task export {record['task']}, or restore the file from git."
    if _earlier_withdrawal(earlier, record["task"]) and _same_approval(earlier[record["task"]], record):
        return "decision-withdrawn", ""
    if record["task"] in earlier and not _same_approval(earlier[record["task"]], record):
        return "decision-superseded", (
            f"{relative}: task {record['task']} already had another approval on the base revision; open a new task "
            "for new work. A record of the same approval (same seal, same consultation) may add its completion.")
    fault = _payload_fault(record, relative, payload, export_again)
    if fault:
        return fault
    current = record.get("schema_version", 1) >= RECORD_VERSION or "shared_sha256" in payload or "record_sha256" in record
    if current and record.get("record_sha256") != export_digest(record):
        return "decision-record-invalid", f"{relative} was changed after it was exported. {export_again}"
    inconsistent = _completion_problem(record) if current else None
    if inconsistent:
        return "decision-record-invalid", (
            f"{relative}: its completion is not consistent ({inconsistent}): a record that says completed carries "
            f"the closing that task complete writes, and a record that does not carries none. {export_again}")
    if record.get("withdrawn"):
        return "decision-withdrawn", ""
    if not _rules_hold(fingerprint, record["profile_fingerprint"]):
        return "decision-stale", ""
    if not current:
        return "decision-record-unverified", ""
    # In CI, a new approval must have been given on a revision of this change's history, as task list requires
    # locally: a record approved on an abandoned branch and copied into another pull request covers nothing.
    commit = (payload.get("base_revision") or {}).get("commit") if isinstance(payload.get("base_revision"), dict) else None
    if extracted and history is not None and record["task"] not in earlier and commit is not None \
            and not in_history(history, commit):
        return "decision-outside-history", f"{relative}: {outside_history_message(record['task'], str(commit))}"
    if policy["mode"] == "signed":
        return _signature_fault(record, relative, payload, policy, base_root, earlier, extracted, history)
    return None


def _same_approval(earlier: object, record: dict) -> bool:
    """Whether a record carries the approval the base revision's record of the same task carried: the same seal over
    the same consultation, re-exported with its completion or its files, never a new approval under that ID."""
    before = earlier.get("decision") if isinstance(earlier, dict) else None
    if not isinstance(before, dict) or before.get("seal") != record["decision"]["seal"]:
        return False
    payload = before.get("payload") if isinstance(before.get("payload"), dict) else {}
    return payload.get("consultation_id") == record["decision"].get("payload", {}).get("consultation_id")


def _completion_problem(record: dict) -> str | None:
    """Whether a record's completion agrees with what task complete writes. No person seals a completion, so
    this is consistency, not proof: the record's own digest can be recomputed by whoever edits it."""
    from .approval_check import DONE_STATUSES
    from .wording import plural

    status, completed = record.get("status"), record.get("completed")
    if status not in ("approved", *DONE_STATUSES):
        return f"status {status!r} is not a status a task is exported with"
    if completed is not (status in DONE_STATUSES):
        return f"completed is {completed!r} while the status is {status}"
    closing = record.get("result", {}).get("closing") if isinstance(record.get("result"), dict) else None
    if not completed:
        return "a closing or a completion time without completion" if closing is not None or "completed_at" in record else None
    if not isinstance(record.get("completed_at"), str):
        return "no completion time"
    if not isinstance(closing, dict) or not isinstance(closing.get("open_points"), list):
        return "no closing with its open points"
    if (status == "done-with-reservations") != bool(closing["open_points"]):
        return f"the status is {status} while the closing lists {plural(len(closing['open_points']), 'group')} of open points"
    return None


def _has_local_task(state: Path, task_id: str) -> bool:
    from .tasks import task_path

    try:
        return task_path(state, task_id).is_file()
    except ValueError:
        return False


def exported_decisions(root: Path, state: Path, profile: dict, fingerprint: "str | Fingerprints",
                       tasks: dict | None = None) -> list[dict]:
    """Every exported decision of the repository, teammates' included, and whether it still holds.

    The record's twin of approval_check.approval_problem: the same wording, an error for an approval not yet completed
    and a note for a completed one, whose record is history. tasks holds the task records the caller already read,
    by ID; a local task it lacks is read here.
    """
    rows = []
    policy = approval_policy(profile)
    for path, record in exported_records(state):
        relative = path.relative_to(root).as_posix()
        row = {"task": path.stem, "path": relative, "status": "unreadable", "problem": None}
        try:
            if record is None:
                raise ValueError(conflict_message(path, relative) or (
                    f"{relative} is not a decision record written by openguildkit task export. "
                    "Export the decision again or remove the file."))
            record_shape(record, relative)
            found = record_check(record, relative, fingerprint, policy, root, {})
        except (OSError, ValueError) as error:
            row["problem"] = {"kind": "invalid-record", "severity": "error", "message": str(error),
                              "code": "decision-record-invalid"}
            rows.append(row)
            continue
        brief = str(record.get("brief", "")).strip().splitlines()
        # Records exported before the completed field said it through their status.
        completed = bool(record.get("completed", record.get("status") == "done"))
        row.update(task=record["task"], status=record.get("status", "approved"), completed=completed,
                   by=record["decision"]["by"], brief=brief[0][:80] if brief else "",
                   local=_has_local_task(state, record["task"]))
        if found:
            kind, message, code = found
            if kind == "earlier-rules" and completed:
                message = f"{relative}: {history_message(record['task'])}"
            # A record that carries its withdrawal is history: it covers nothing and says so.
            note = kind in ("earlier-record", "withdrawn") or (kind == "earlier-rules" and completed)
            row["problem"] = {"kind": kind, "severity": "note" if note else "error",
                              "message": message, "code": code}
        elif row["local"] and (withdrawn := _withdrawn_here(state, record, tasks)):
            row["problem"] = {"kind": "withdrawn-here", "severity": "error", "message": (
                f"{relative}: the approval of {record['task']} was withdrawn in this copy by {withdrawn['by']} on "
                f"{withdrawn['at'][:10]}, and the record still says it is approved, so guard --ci keeps accepting it. "
                f"Write the withdrawal into it with openguildkit task export {record['task']}, and commit it."),
                "code": "decision-withdrawn-here"}
        rows.append(row)
    return rows


def _withdrawn_here(state: Path, record: dict, tasks: dict | None = None) -> dict | None:
    """The withdrawal the local task records for the approval an exported record carries, if any."""
    task = (tasks or {}).get(record["task"])
    if task is None:
        try:
            task = read_task_lazily(state, record["task"])
        except Exception:  # An unreadable task record is reported by task list and check.
            return None
    return withdrawal_of(task, record)
