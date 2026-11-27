"""Track task consultations and decisions in the project."""

import contextlib
import difflib
import hashlib
import json
import marshal
import os
import re
import time
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timezone
from functools import cache
from pathlib import Path

from . import clock, delivered_review, light_lane, requester, task_index
from .decisions import (
    DECISIONS_DIR, EARLIER_SIGNERS, approval_policy, base_commit, check_decision_seal, decision_payload,
    history_message, reconsult_command, revisions_outside_history, seal, signature_or_history_problem,
    stale_approval_message, verify_signature,
)
from .project import Fingerprints, fingerprint_holds, profile_fingerprint, rules_in_force, task_scope_profile
from .relevance import sensitive_area
from .sensitive import redact_credentials, redact_data
from .results import (
    DONE_STATUSES, asked_checks, completion_problems, evidence_fingerprint, evidence_state, merge_results,
    not_concerned, outcomes, result_warnings, validate_result, waiting_evidence,
)
from .storage import file_signature, read_json, write_text
from .alerts import resolution_line, resolved_by_import
from .consultation import code_not_found, consult, profile_settings
from .questionnaire import validate_answers
from .workflow import (
    RESOLUTION_FIELDS, TaskStateError, blocker_list, blocker_resolutions, decision_summary, is_decision_task,
    pending_removals, resolution_field, review_warnings, validate_board_entry, validate_deliberation, validate_review,
)

ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WINDOWS_RESERVED_NAMES = {"con", "prn", "aux", "nul"} | {
    f"{prefix}{digit}" for prefix in ("com", "lpt") for digit in range(1, 10)
}


def timestamp() -> str:
    return clock.timestamp()


def write_task(path: Path, task: dict) -> None:
    """Write a task record without indentation, which made 29 % of a closed task's weight: git ignores the records
    and only the commands read them. Nothing compares their bytes (seals and digests hash the parsed fields), and any
    JSON reader, an earlier release's included, reads the same fields."""
    write_text(path, json.dumps(task, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def task_path(state: Path, task_id: str) -> Path:
    if task_id in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{task_id} is a reserved file name on Windows. Choose another task ID.")
    if len(task_id) > 64 or not ID_PATTERN.fullmatch(task_id):
        raise ValueError("Use a task ID of up to 64 lowercase letters, digits and separating hyphens.")
    path = state / "tasks" / f"{task_id}.json"
    if path.resolve() != path:
        raise ValueError(f"Task records must stay inside their project: {path}")
    return path


def _unknown_task(state: Path, task_id: str) -> str:
    """The error for a task ID with no record, with the closest existing ID when one is near."""
    known = sorted(path.stem for path in (state / "tasks").glob("*.json")) if (state / "tasks").is_dir() else []
    close = difflib.get_close_matches(task_id, known, n=1)
    hint = f"Did you mean {close[0]}? " if close else ""
    return f"Unknown task: {task_id}. {hint}Run openguildkit task list to see the tasks."


class KeptRecords:
    """The task records a process that outlives its commands (openguildkit ui) has read, by file signature, so that
    listing the tasks again after nothing changed reads none. A record is kept serialized and handed out as a new
    copy, because commands change what they read. What would pass the limit in bytes is read as it always was."""

    def __init__(self, limit: int = 256 * 1024 * 1024):
        self.limit = limit
        self.size = 0
        self.entries: dict[Path, tuple[tuple, bytes]] = {}

    def get(self, path: Path, signature: tuple | None) -> dict | None:
        kept = self.entries.get(path)
        return marshal.loads(kept[1]) if kept is not None and signature is not None and kept[0] == signature else None

    def put(self, path: Path, signature: tuple | None, record: dict) -> None:
        if signature is None:
            return
        blob = marshal.dumps(record)
        before = self.entries.pop(path, None)
        self.size -= len(before[1]) if before else 0
        if self.size + len(blob) <= self.limit:
            self.entries[path] = (signature, blob)
            self.size += len(blob)


# Where records are kept: only inside keeping_records. A command that runs once reads each record once.
_KEPT: KeptRecords | None = None


@contextlib.contextmanager
def keeping_records(kept: KeptRecords):
    """Inside the block, read_task serves the records of `kept` while their file is as it was, and adds the others."""
    global _KEPT
    before, _KEPT = _KEPT, kept
    try:
        yield
    finally:
        _KEPT = before


def read_task(state: Path, task_id: str) -> dict:
    path = task_path(state, task_id)
    if not path.is_file():
        raise ValueError(_unknown_task(state, task_id))
    kept = _KEPT
    if kept is None:
        return _validated_task(state, path, task_id)
    # The signature is taken before the read: a file that changes in between is read again next time.
    signature = file_signature(path, content=True)
    task = kept.get(path, signature)
    if task is None:
        task = _validated_task(state, path, task_id)
        kept.put(path, signature, task)
    return task


def _validated_task(state: Path, path: Path, task_id: str) -> dict:
    task = read_json(path)
    if task.get("schema_version") != 1 or task.get("id") != task_id:
        raise ValueError(f"Unsupported or mismatched task record: {path}")
    problem = _record_problem(task)
    if problem:
        # Task records are not under version control (.openguildkit/.gitignore lists tasks/).
        raise ValueError(
            f"Task record {task_id} is damaged: {problem}. Restore {path.relative_to(state.parent).as_posix()} from a "
            "backup, or delete that file and open a new task with openguildkit task new."
        )
    return task


STATUSES = {
    "draft": (),
    "consulting": ("answers", "consultation", "profile_fingerprint"),
    "reviewed": ("answers", "consultation", "profile_fingerprint", "review"),
    "changes-requested": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
    "approved": ("answers", "consultation", "profile_fingerprint", "review", "decision"),
    "done": ("answers", "consultation", "profile_fingerprint", "review", "decision", "result"),
    # Closed with points left open: skipped rules, deferred evidence, open disagreements, waivers.
    "done-with-reservations": ("answers", "consultation", "profile_fingerprint", "review", "decision", "result"),
}

# The shape of every field the commands read, checked once when a record is loaded. A type is a
# type, [shape] a list of that shape, a dict an object whose keys ending in "?" are optional and
# whose "*" gives the shape of every value, a tuple one of several shapes, a frozenset the values allowed.
_DECISION = {"outcome": str, "by": str, "reason": str, "at": str}
_TEMPLATE_BOARD = {"id": str, "challenge?": {"specialists": [{"id": str}]}}
# A rule states its text, or declares a machine check that stands in for it; either can name evidence.
_EVIDENCE = [{"id": str, "title": str}]
_RULE = (
    {"id": str, "instruction": str, "verification": str, "check?": dict, "evidence?": _EVIDENCE},
    {"id": str, "check": dict, "evidence?": _EVIDENCE},
)
_SCOPE = {
    "open_points?": [str],
    "checks?": [str],
    "code_not_found?": [str],
    "packs?": [{"id": str, "rules": [_RULE]}],
    "market?": {"id": str, "observations": [{"id": str}], "changes?": [dict]},
    "tools?": [{"id": str}],
    "storybook?": {"indexes": [{"ref": str, "stories": [str]}]},
    "host_controls?": [{"id": str, "status": str}],
}
_CONSULTATION = {
    "id": str, "boards": [str], "routing": {"*": [str]}, "scope": _SCOPE, "markdown": str,
    "review_template": {"boards": [_TEMPLATE_BOARD]},
    "adjustments?": [{"board": str, "action": str, "reason": str}],
    "delegations?": {"*": str},
    "domains?": {"*": [str]},
    # Checked when a pass is printed (board_brief_problem), so that listing tasks stays fast.
    "board_briefs?": {"*": dict},
}
_BOARD_BRIEF = {
    "title": str, "purpose": str, "routing": [str], "questions": [str],
    "lenses": [{"id": str, "title": str, "focus": str, "checks?": [str]}],
    "lenses_not_concerned": [{"id": str, "applies_to": [str]}],
    "evidence": [str], "challenge": [str], "decision_criteria": [str],
    "source_leads": [{"title": str, "url": str}], "methods": [str], "other_methods": int,
    "rules": [{"pack": str, "title": str, "rules": [{"id": str, "instruction": str}]}],
    "unprinted_packs?": [str], "not_concerned?": [{"reason": str, "items": [str]}], "other_packs": int,
    "references": [{"title": str, "url": str}],
    "tools?": [{"title": str, "server": str, "mode": str}], "reviewer?": str, "stories?": [str],
}
_CHALLENGE = {
    "verdict": str,
    "specialists": [{"id": str, "basis": str, "evidence_refs": [int], "finding": str}],
    "blockers": [({"finding": str, "phase?": frozenset({"approval", "verification"})}, str)],
}
_REVIEW = {
    "consultation_id": str, "summary": str, "warnings?": [str],
    "boards": [{"id": str, "recommendation": str, "evidence": [(str, {"source": str, "ref": str})],
                "open_questions": [str], "challenge?": _CHALLENGE}],
}
_RESOLUTION = {"kind": frozenset({"cleared", "waived"}), "by": str, "evidence?": str, "supports?": str, "fingerprint?": str,
               "reason?": str, "scope?": str, "until?": str, "signer?": str, "signature?": str}
_RECORD = {
    "created_at": str,
    "lane?": frozenset({light_lane.LANE}),
    "paths?": [str],
    "completed_at?": str,
    "profile_fingerprint?": str,
    "answers?": {"*": (str, [str])},
    "consultation?": _CONSULTATION,
    "review?": _REVIEW,
    "decision?": {**_DECISION, "confirmed_removals?": [str]},
    "passes?": {"consultation_id": str, "boards": {"*": {"status": str, "mode?": str, "attempts?": int, "error?": str}}},
    "deliberation?": {
        "objections": [{"id": str, "from": str, "to": str, "point": str}],
        "responses": [{"objection": str, "board": str}],
        "agreed": [str], "open": [str], "decision_needed": str,
    },
    "blocker_resolutions?": {"*": _RESOLUTION},
    "verification_blocker_resolutions?": {"*": _RESOLUTION},
    "result?": {
        "revision?": str, "pull_request?": str,
        "criteria?": [{"criterion": str, "status": str}],
        "checks?": [{"check": str, "status": str}],
        "runs?": [{"tool": str, "outcomes": {"*": str}}],
    },
    "follows?": {"task": str, "brief": str, "status": str, "decision": _DECISION},
    "after?": [str],
    "authorizations?": [{"action": str, "target": str, "decision": str, "by": str, "reason": str}],
    "dependency_alerts?": {"alerts?": [dict]},
    "delivered_review?": {"boards": {"*": {
        "base": str, "revision": str, "at": str,
        "findings": [{"file": str, "line": int, "severity": frozenset(delivered_review.SEVERITIES),
                      "action": frozenset(delivered_review.ACTIONS), "finding": str}]}}},
}
_RESOLUTION_FIELDS = {"cleared": ("evidence", "supports"), "waived": ("reason", "scope", "until")}


def _shape_problem(value: object, shape: object, field: str) -> str | None:
    """Where value departs from shape (see _RECORD), named by its path such as review.boards[0].challenge."""
    if isinstance(shape, tuple):
        problems = [_shape_problem(value, option, field) for option in shape]
        return None if None in problems else problems[-1]
    if isinstance(shape, frozenset):
        return None if value in shape else f"{field} must be one of {', '.join(sorted(shape))}"
    if isinstance(shape, list):
        if not isinstance(value, list):
            return f"{field} must be a list"
        problems = (_shape_problem(item, shape[0], f"{field}[{index}]") for index, item in enumerate(value))
        return next((problem for problem in problems if problem), None)
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return f"{field} must be an object"
        for key, inner in shape.items():
            if key == "*":
                problems = (_shape_problem(item, inner, f"{field}.{name}") for name, item in value.items())
            else:
                name = key.rstrip("?")
                if name not in value:
                    if key.endswith("?"):
                        continue
                    return f"{field}.{name} is missing" if field else f"{name} is missing"
                problems = iter([_shape_problem(value[name], inner, f"{field}.{name}" if field else name)])
            problem = next((problem for problem in problems if problem), None)
            if problem:
                return problem
        return None
    if shape is int:
        return None if type(value) is int else f"{field} must be a whole number"
    if shape is str:
        return None if isinstance(value, str) else f"{field} must be text"
    return None if isinstance(value, shape) else f"{field} must be {'an object' if shape is dict else 'a list'}"


def _record_problem(task: dict) -> str | None:
    """Describe the first field of a task record that the commands could not use, if any."""
    if not isinstance(task.get("brief"), str) or not task["brief"].strip():
        return "brief must be text"
    status = task.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        return f"status must be one of {', '.join(STATUSES)}"
    rounds = task.get("rounds")
    if not isinstance(rounds, list) or any(not isinstance(entry, dict) for entry in rounds):
        return "rounds must be a list of objects"
    for field in STATUSES[status]:
        if field not in task:
            return f"{'an' if status[0] in 'aeiou' else 'a'} {status} task needs {field}"
    problem = _shape_problem(task, _RECORD, "")
    if problem:
        return problem
    if ("lane" in task) != bool(task.get("paths")):
        return "lane and paths go together: a short-lane task names the paths it may change"
    for field in RESOLUTION_FIELDS:
        for blocker, resolution in task.get(field, {}).items():
            missing = [key for key in _RESOLUTION_FIELDS[resolution["kind"]] if key not in resolution]
            if missing:
                return f"{field}.{blocker}.{missing[0]} is missing"
    return None


def board_brief_problem(task: dict, board_id: str) -> None:
    """Refuse to print a pass from a damaged stored brief, with the field to restore."""
    stored = task.get("consultation", {}).get("board_briefs", {}).get(board_id)
    problem = _shape_problem(stored, _BOARD_BRIEF, f"consultation.board_briefs.{board_id}") if stored is not None else None
    if problem:
        raise ValueError(f"Task record {task['id']} is damaged: {problem}. Restore it from a backup or consult again.")


def validate_brief(brief: str) -> str:
    """The brief as recorded: one check for a new task and for a brief revised at a new consultation.

    A credential is replaced by a placeholder before anything is written; the rest of the words are kept.
    """
    brief = brief.strip()
    if not brief:
        raise ValueError("Supply a task brief.")
    return redact_credentials(brief)


def _dependency_cycle(state: Path, task_id: str, after: list[str]) -> list[str] | None:
    """The chain of --after links that would lead from a new task back to itself, if any: a task can only wait for
    one that is gone and whose ID is taken again."""
    def walk(current: str, path: list[str]) -> list[str] | None:
        if current == task_id:
            return path
        if current in seen:
            return None
        seen.add(current)
        try:
            waits = read_task(state, current).get("after", [])
        except ValueError:
            return None
        return next((found for name in waits if (found := walk(name, [*path, name]))), None)
    seen: set[str] = set()
    return next((found for name in after if (found := walk(name, [task_id, name]))), None)


def dependencies(state: Path, task_id: str, after: list[str]) -> dict[str, str]:
    """The tasks a new task waits for, with their status; an unknown ID, the task itself or a cycle is refused."""
    found = {}
    for name in dict.fromkeys(after):
        if name == task_id:
            raise ValueError(f"A task cannot wait for itself: {task_id}.")
        found[name] = read_task(state, name)["status"]
    cycle = _dependency_cycle(state, task_id, list(found))
    if cycle:
        raise ValueError(f"Task {task_id} cannot wait for {cycle[1]}: that would close a cycle "
                         f"({' -> '.join(cycle)}). Remove that --after.")
    return found


def waiting_for(task: dict, statuses: dict[str, str]) -> list[dict]:
    """The tasks this one waits for that are not done yet, with their status; one that no longer exists still holds
    it back, as unknown."""
    return [{"task": name, "status": statuses.get(name, "unknown")} for name in task.get("after", [])
            if statuses.get(name) not in DONE_STATUSES]


def waits_line(waiting: list[dict]) -> str:
    """auth-flow (draft) and api-schema (approved)."""
    names = [f"{item['task']} ({item['status']})" for item in waiting]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def create_task(state: Path, brief: str, task_id: str | None, follows: str | None = None,
                lane: dict | None = None, after: list[str] | None = None, requested_by: str | None = None) -> str:
    brief = validate_brief(brief)
    if task_id is not None and not task_id.strip():
        raise ValueError("The task ID is empty. Omit --id to generate one.")
    task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
    path = task_path(state, task_id)
    if path.exists():
        raise ValueError(f"Task already exists: {task_id}")
    record = {
        "schema_version": 1,
        "id": task_id,
        "brief": brief,
        "created_at": timestamp(),
        "status": "draft",
        "rounds": [],
        **(lane or {}),
        # Who asked for the work (requester.py): written only when named, so a task without one is as before.
        **({"requested_by": requested_by} if requested_by is not None else {}),
    }
    if after:
        record["after"] = list(dependencies(state, task_id, after))
    if follows is not None:
        previous = read_task(state, follows)
        if "decision" not in previous:
            raise ValueError(f"Task {follows} has no recorded decision to follow.")
        record["follows"] = {
            "task": follows,
            "brief": previous["brief"],
            "status": previous["status"],
            "decision": {key: previous["decision"][key] for key in ("outcome", "by", "reason", "at")},
        }
    write_task(path, record)
    return task_id


def next_step(task: dict, profile: dict | None = None) -> str:
    """The open point that keeps a task from moving on; with the profile, whether a waiver can still close it."""
    status = task["status"]
    if status == "draft":
        return ("Consult the boards: the short lane asks no questions." if light_lane.is_light(task)
                else "Answer the questionnaire and consult the boards.")
    if status == "consulting":
        progress = pass_progress(task)
        waiting = [item["board"] + (" (failed)" if item["status"] == "failed" else "") for item in progress
                   if item["status"] in ("missing", "failed")]
        started = [item["board"] for item in progress if item["status"] == "started"]
        if not waiting and not started:
            return "Write the summary and record the review."
        # A started pass is under way, not pending: it waits for its entry.
        parts = [f"Board reviews pending: {', '.join(waiting)}"] if waiting else []
        if started:
            parts.append(f"{'p' if waiting else 'P'}asses started, waiting for their entry: {', '.join(started)}")
        return "; ".join(parts) + "."
    if status == "reviewed":
        blockers = unresolved_blockers(task)
        return f"Resolve blockers {', '.join(blockers)}." if blockers else "Waiting for the person's decision."
    if status == "changes-requested":
        return f"Consult again: {task['decision']['reason']}"
    if status == "approved":
        return _approved_step(task) + _conditions_step(task, profile) + _abandoned_step(task)
    if status == "done-with-reservations":
        return f"Done with reservations: see the open points with openguildkit task show {task['id']} --closing."
    return "Done."


# How a refusal names a status that has no decision yet.
_STATUS_WORDS = {"draft": "a draft, not consulted yet", "consulting": "being consulted",
                 "reviewed": "reviewed and waits for the person's decision"}


def next_command(task: dict) -> str:
    """The command that moves a task on from its status, said to the agent: a refusal ends with it, so that a refused
    command leads to one that runs."""
    task_id, status = task["id"], task["status"]
    if status == "draft" and light_lane.is_light(task):
        return (f"consult the one board its paths call for with openguildkit task consult {task_id}: the short lane asks "
                "no questions")
    if status == "draft":
        return (f"read the questions with openguildkit task questions {task_id}, then consult the boards with "
                f"openguildkit task consult {task_id} --answers FILE")
    if status == "consulting":
        progress = pass_progress(task)
        review = f"openguildkit task review {task_id} --summary TEXT"
        to_run = [item["board"] for item in progress if item["status"] in ("missing", "failed")]
        started = [item["board"] for item in progress if item["status"] == "started"]
        steps = [f"run the passes of {', '.join(to_run)} (openguildkit task pass {task_id} BOARD)"] if to_run else []
        if started:
            steps.append(f"submit the entries of {', '.join(started)} (openguildkit task submit {task_id} --file ENTRY)")
        return f"{'; '.join(steps)}; then {review}" if steps else f"every pass is done: {review}"
    if status == "reviewed":
        decide = (f"the person decides at their terminal: openguildkit task decide {task_id} --approve (or "
                  "--request-changes) --by NAME --reason TEXT")
        blockers = unresolved_blockers(task)
        if blockers:
            return (f"the person clears {', '.join(blockers)} at their terminal (openguildkit task clear {task_id} "
                    f"BLOCKER --evidence PATH --supports TEXT --by NAME) or requests changes, then {decide}")
        return decide
    if status == "changes-requested":
        return f"consult again: {reconsult_command(task_id)} (--answers FILE to change the answers)"
    if status == "approved":
        if is_decision_task(task):
            return f"close the decision with openguildkit task complete {task_id}"
        if not task.get("result"):
            return f"implement the handoff (openguildkit task handoff {task_id}), then openguildkit task verify {task_id}"
        return f"openguildkit task verify {task_id}, then openguildkit task complete {task_id}"
    return f'open a follow-up task: openguildkit task new "BRIEF" --follows {task_id}'


def passes_left(task: dict) -> str:
    """After an entry is recorded: how many passes are left and the command that comes next."""
    left = [item for item in pass_progress(task) if item["status"] != "done"]
    if not left:
        return f"Every pass is done: write the summary and run openguildkit task review {task['id']} --summary TEXT."
    return f"{len(left)} {'pass' if len(left) == 1 else 'passes'} left: {next_command(task)}."


def state_refusal(task: dict, refused: str, problem: dict | None = None) -> str:
    """A refused action on a task whose status it does not fit: what is refused, then the status and the next
    command that runs. A decided task says who decided and what fits next (decided_message, with the task's
    approval_problem when an approval no longer holds)."""
    decided = decided_message(task, problem)
    if decided:
        return f"{refused} {decided}"
    words = _STATUS_WORDS.get(task["status"], task["status"])
    return f"{refused} Task {task['id']} is {words}: next, {next_command(task)}."


def _setting_change(name: str, before, after) -> str:
    """One setting's change in words, such as "required boards changed (none -> legal)"."""
    if isinstance(after, list):
        return f"{name} changed ({', '.join(before or []) or 'none'} -> {', '.join(after) or 'none'})"
    return f"{name} {'unset' if before is None else before} -> {'unset' if after is None else after}"


def rule_changes(task: dict, profile: dict, catalog: dict) -> list[str]:
    """What changed, pack by pack and rule by rule, in the rules the task was consulted under."""
    scope = task["consultation"]["scope"]
    try:
        current = task_scope_profile(profile, catalog, task.get("answers", {}).get("components", []))
    except ValueError:
        return ["the task's components changed"]
    before = {pack["id"]: pack for pack in scope.get("packs", [])}
    after = {pack_id: rules_in_force(catalog["packs"][pack_id], current) for pack_id in current["packs"]}
    changes = [f"pack {pack_id} added" for pack_id in after if pack_id not in before]
    changes += [f"pack {pack_id} removed" for pack_id in before if pack_id not in after]
    for pack_id in [pack_id for pack_id in after if pack_id in before]:
        old = {rule["id"]: rule for rule in before[pack_id]["rules"]}
        new = {rule["id"]: rule for rule in after[pack_id]["rules"]}
        changes += [f"rule {pack_id}/{rule_id} added" for rule_id in new if rule_id not in old]
        changes += [f"rule {pack_id}/{rule_id} changed" for rule_id in new if rule_id in old and old[rule_id] != new[rule_id]]
        changes += [f"rule {pack_id}/{rule_id} removed" for rule_id in old if rule_id not in new]
    if scope.get("sector", {}).get("id") != current["sector"]:
        changes.append("sector changed")
    # Only what voids an approval is named: conventions, tools and the guard, host or research settings do not.
    changes += [f"{field} changed" for field in ("stack", "checks") if scope.get(field, []) != current.get(field, [])]
    # The consultation recorded the settings of the resolved profile (every board when none is listed).
    settings, stored = profile_settings(current), scope.get("settings", {})
    changes += [_setting_change(name, stored[name], value) for name, value in settings.items()
                if name in stored and stored[name] != value]
    if not changes and settings.keys() <= stored.keys():
        return ["a board's definition changed: openguildkit update shows the catalog changes"]
    if not changes:
        # A task consulted before these settings were recorded: name what may have changed.
        return [f"a project setting changed ({', '.join(settings)}), or a board's definition; "
                "openguildkit preview shows the profile"]
    return changes[:6] + ([f"{len(changes) - 6} more changes: openguildkit update shows them"] if len(changes) > 6 else [])


# An approval older than this, with nothing recorded since, may be abandoned: task list and the guard say so.
STALE_DAYS = 14


def revoke_command(task_id: str) -> str:
    """The person's command that withdraws an approval, the same in every message that names it."""
    return f"openguildkit task revoke {task_id} --by NAME --reason TEXT"


def days_since(moment: str | None) -> int | None:
    """Whole days since a recorded time; None when the time cannot be read."""
    try:
        then = datetime.fromisoformat(moment)
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (clock.real_now() - then).days


def _conditions_step(task: dict, profile: dict | None) -> str:
    """The conditions of approval still open and, without a waiver policy, the way out if one cannot be met; then the
    waivers that expired since, each with what the person can do."""
    waiting = [item["id"] for item in blocker_list(task)
               if item.get("phase") == "verification" and not item["resolution"]]
    expired = "".join(f" {expired_waiver_step(task, item)}" for item in expired_waivers(blocker_list(task)))
    if not waiting:
        return expired
    text = (f" Condition(s) of approval still open: {', '.join(waiting)}. The person clears each with its evidence at "
            f"their terminal: openguildkit task clear {task['id']} BLOCKER --evidence PATH --supports TEXT --by NAME.")
    if profile is not None and not waiver_policy(profile):
        text += (" The project allows no waiver, so the task cannot complete while one is open: if one cannot be met, "
                 f"the person withdraws the approval at their terminal: {revoke_command(task['id'])}.")
    return text + expired


def _abandoned_step(task: dict) -> str:
    """An old approval with nothing recorded since still lets every edit through the guard: name the way to end it."""
    age = days_since(task["decision"].get("at"))
    if task.get("result") or is_decision_task(task) or age is None or age <= STALE_DAYS:
        return ""
    return (f" Approved {age} days ago with no result recorded, and the guard lets every edit through while it is "
            f"approved: if the work is abandoned, the person withdraws the approval: {revoke_command(task['id'])}.")


def _approved_step(task: dict) -> str:
    """The next step of an approved task, from what its result already holds."""
    task_id = task["id"]
    if is_decision_task(task):
        if task.get("answers", {}).get("outcome") and not (task.get("result") or {}).get("criteria"):
            return (f"Decision recorded: report its acceptance criterion with task result {task_id} --template, "
                    f"then task complete {task_id}, then open a follow-up task to act on it.")
        return f"Decision recorded: close it with task complete {task_id}, then open a follow-up task to act on it."
    result = task.get("result")
    if not result:
        return (f"Implement, then record the results: task verify {task_id} and task result {task_id}, "
                f"then task complete {task_id}.")
    commands = task["consultation"]["scope"].get("checks", [])
    failed = sorted((item for item in result.get("checks", []) if item["status"] == "failed"),
                    key=lambda item: not item["check"].startswith("command:"))
    if failed:
        item = failed[0]
        index = int(item["check"].split(":")[1]) - 1 if item["check"].startswith("command:") else None
        what = f" (`{commands[index]}`)" if index is not None and index < len(commands) else ""
        cause = f": {item['message']}" if item.get("message") else ""
        more = f" and {len(failed) - 1} other check(s)" if len(failed) > 1 else ""
        return f"{item['check']}{what} failed{cause}{more}. Fix it, then run task verify {task_id}."
    waiting = result.get("waiting_for", [])
    if waiting:
        return "Waiting for evidence: " + "; ".join(f"{item['title']} from {item['owner']}" for item in waiting) + "."
    return f"Result recorded: run task verify {task_id} to list what remains, then task complete {task_id}."


def approval_problem(task: dict, profile: dict, catalog: dict, root: Path | None = None, *,
                     fingerprints: Fingerprints | None = None, outside: set[str] | None = None,
                     explain: bool = True) -> dict | None:
    """Whether a task's approval still holds: its seal intact, its rules, checks and boards current, its signature
    valid and the revision it was approved at still in the project history.

    Every reader asks this one function and prints its message: task list, check, task consult (which reopens the
    task under the same ID), handoff, verify, result, complete, export and the guard. An error blocks the work; a note
    marks a completed task, whose record is history. Without the project root, the signature and the history are not
    read. outside and fingerprints let a reader of many tasks ask git and hash the profile once (covering_approvals);
    explain names what changed in the rules, which the guard does not need.
    """
    decision = task.get("decision")
    if not decision or decision.get("outcome") != "approved":
        return None
    completed = task["status"] in DONE_STATUSES
    try:
        payload = check_decision_seal(task)
    except ValueError as error:
        if completed and "seal" not in decision:
            return {"kind": "no-seal", "severity": "note", "message": history_message(task["id"], sealed=False)}
        return {"kind": "invalid-seal" if "seal" in decision else "no-seal", "severity": "error", "message": str(error)}
    fingerprints = fingerprints or Fingerprints(profile, catalog)
    if not fingerprints.holds(task.get("profile_fingerprint")):
        changes = rule_changes(task, profile, catalog) if explain else None
        if completed:
            return {"kind": "earlier-rules", "severity": "note", "message": history_message(task["id"], changes)}
        return {"kind": "earlier-rules", "severity": "error", "message": stale_approval_message(task["id"], changes)}
    # A completed task's record is history: a squash merge is expected to take its revision out of the history.
    found = None if completed or root is None else signature_or_history_problem(task, root, profile, payload, outside)
    if not found:
        return None
    return {"kind": found[0], "severity": "note" if found[0] == EARLIER_SIGNERS else "error", "message": found[1]}


def require_approval(task: dict, profile: dict, catalog: dict, root: Path | None = None) -> None:
    """Refuse to act on an approved task whose approval no longer holds, with the one message every reader prints."""
    problem = approval_problem(task, profile, catalog, root)
    if problem and problem["severity"] == "error":
        raise ValueError(problem["message"])


def _period_day(value: str | None, option: str) -> str | None:
    """The day a period option names, written YYYY-MM-DD and a real date."""
    if value is None:
        return None
    try:
        if not _DAY.fullmatch(value):
            raise ValueError
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"{option}: {value!r} is not a real date. Write it YYYY-MM-DD.") from None


def list_tasks(state: Path, status: str | None = None, owner: str | None = None,
               since: str | None = None, until: str | None = None, *, profile: dict | None = None,
               catalog: dict | None = None, root: Path | None = None, read: dict | None = None,
               skip: Iterable[str] = (), indexed: bool = False) -> list[dict]:
    """Every task of the project with its status, decision owner and next open point.

    With the profile and the catalog, each approval is judged by approval_problem, and with the project root its
    signature and revision too (one git call for every approval). A dict given as read receives every task record
    read, by ID, so that a caller that needs them too does not read them again; a record it already holds is not
    read again either. skip leaves out tasks of those statuses, as status leaves out the others.

    indexed reads the status index first (task_index.py) and writes back what the reads taught it: a record read
    whole at its current signature is not read again when its status is left out, nor when it is a closed task whose
    line the index keeps (_kept_line), which read then does not receive. The index only saves reads: missing, stale
    or corrupt, it gives the same list.
    """
    since, until = _period_day(since, "--since"), _period_day(until, "--until")
    directory = state / "tasks"
    rows = []
    if not directory.is_dir():
        return rows
    judged = profile is not None and catalog is not None
    fingerprints = Fingerprints(profile, catalog) if judged else None
    skip = {*skip, *(set(STATUSES) - {status} if status else ())}
    index = task_index.entries(state) if indexed else {}
    entries, statuses, learnt = [], {}, False

    def in_period(day: str) -> bool:
        return not ((since and day < since) or (until and day > until))

    for path in sorted(directory.glob("*.json")):
        known = index.get(path.name, {})
        if known.get("checked") is True and known.get("status") in skip:
            statuses[path.stem] = known["status"]
            continue
        line = _kept_line(state, known, path.stem, fingerprints)
        if line:
            statuses[path.stem] = known["status"]
            if in_period(line["row"]["created"]):
                entries.append((None, dict(line["row"])))
            continue
        try:
            task = (read or {}).get(path.stem) or read_task(state, path.stem)
        except ValueError as error:
            entries.append((None, {"id": path.stem, "status": "unreadable", "next": str(error)}))
            continue
        if "stamp" in known and (known.get("checked"), known.get("status")) != (True, task["status"]):
            index[path.name], learnt = {"status": task["status"], "stamp": known["stamp"], "checked": True}, True
        statuses[task["id"]] = task["status"]
        if read is not None:
            read[task["id"]] = task
        if task["status"] not in skip and in_period(task["created_at"][:10]):
            entries.append((task, None))
    approved = [base_commit(task) for task, _ in entries if task and task["status"] == "approved"]
    outside = revisions_outside_history(root, approved) if judged and root is not None else None
    for task, row in entries:
        if task is not None:
            problem = (approval_problem(task, profile, catalog, root, fingerprints=fingerprints, outside=outside)
                       if judged else None)
            row = _task_row(task, problem, profile, fingerprints, root)
            name = f"{task['id']}.json"
            if index.get(name, {}).get("checked") is True:
                line = _line_to_keep(state, task, row, problem, fingerprints)
                if line and index[name].get("line") != line:
                    index[name], learnt = {**index[name], "line": line}, True
        elif row["status"] == "unreadable":
            rows.append(row)
            continue
        # owner is who took the task's current decision: the approval, the change request or the withdrawal.
        if owner and (row["owner"] or "").casefold() != owner.casefold():
            continue
        waiting = waiting_for(row, statuses)
        if waiting:
            row["waiting_for"] = waiting
        rows.append(row)
    if learnt:
        task_index.save(state, index)
    return rows


def _task_row(task: dict, problem: dict | None, profile: dict | None, fingerprints: Fingerprints | None,
              root: Path | None) -> dict:
    """A task's line of task list, but for the tasks it waits for, which depend on the others; problem is its
    approval_problem, fingerprints those of the profile when the approval is judged."""
    # An approval that holds through the signers of the revision it was signed at keeps its next step.
    note = problem if problem and problem["kind"] == EARLIER_SIGNERS else None
    row = {"id": task["id"], "status": task["status"], "created": task["created_at"][:10],
           "owner": None if problem and problem["kind"] == "invalid-seal" else task.get("decision", {}).get("by"),
           "brief": task["brief"].splitlines()[0][:80],
           "next": problem["message"] if problem and not note else next_step(task, profile)}
    if fingerprints is not None and task["status"] == "reviewed" and \
            not fingerprints.holds(task.get("profile_fingerprint")):
        row["next"] = stale_review_message(task["id"])
    decided = decision_words(task, problem)
    if decided:
        row["decided"] = decided
    if note:
        row["note"] = note["message"]
    if problem:
        row.update(approval_problem=problem["kind"], severity=problem["severity"])
    closed_by = task.get("result", {}).get("closing", {}).get("by")
    if closed_by:
        row["closed_by"] = closed_by
    if task.get("follows"):
        row["follows"] = task["follows"]["task"]
    if light_lane.is_light(task):
        row.update(lane=task["lane"], paths=task["paths"])
    changed = changed_evidence(task, root) if root is not None else []
    if changed:
        row["evidence_changed"] = changed
    if task.get("after"):
        row["after"] = task["after"]
    return row


# The line of a closed task the status index keeps (_line_to_keep), checked again when it is read back (_kept_line).
_LINE_ROW = {"id": str, "status": str, "created": str, "owner": (str, type(None)), "brief": str, "next": str,
             "decided?": str, "closed_by?": str, "follows?": str, "lane?": str, "paths?": [str], "after?": [str]}
_LINE_FIELDS = {key.rstrip("?") for key in _LINE_ROW}
_LINE = {"code": str, "fingerprint": str, "row": _LINE_ROW, "export": ([int], type(None))}


@cache
def _code_stamp() -> str | None:
    """What changes with the code that writes the lines the status index keeps: the name, size and modification time
    of each module of the package, so that another release or an edited checkout reads the records again."""
    try:
        modules = sorted((item.name, item.stat().st_size, item.stat().st_mtime_ns)
                         for item in os.scandir(Path(__file__).parent) if item.name.endswith(".py"))
    except OSError:
        return None
    return hashlib.sha256(repr(modules).encode()).hexdigest()


def _line_to_keep(state: Path, task: dict, row: dict, problem: dict | None,
                  fingerprints: Fingerprints | None) -> dict | None:
    """What the status index keeps of a closed task's line: the row, the fingerprint of the rules it was approved
    under and the signature of its exported record (None without one). None when the line depends on more than the
    record and the rules: an approval that does not hold, evidence whose file may change, an exported record of
    another task under its ID, which task list names at each run."""
    from .guard import record_of_another_task  # The guard reads task records: it is loaded once this module is.

    code = _code_stamp()
    if task["status"] not in DONE_STATUSES or problem or fingerprints is None or code is None or \
            any(fingerprint for _, _, fingerprint in _accepted_evidence(task)):
        return None
    # Taken before the record is read, and not trusted just after a write: as for the index, a second write within
    # the same clock tick could keep the signature.
    export = file_signature(state / DECISIONS_DIR / f"{task['id']}.json")
    if (export and export[1] + task_index.RACY_NANOSECONDS >= time.time_ns()) or record_of_another_task(state, task):
        return None
    return {"code": code, "fingerprint": task["profile_fingerprint"], "row": dict(row),
            "export": list(export) if export else None}


def _kept_line(state: Path, entry: dict, task_id: str, fingerprints: Fingerprints | None) -> dict | None:
    """The line the status index keeps for a closed task while its record, its exported record, the code that wrote
    the line and the rules it was approved under all hold; None otherwise, and the record is read."""
    line = entry.get("line")
    if entry.get("checked") is not True or fingerprints is None or not isinstance(line, dict) or \
            _shape_problem(line, _LINE, "line"):
        return None
    row, export = line["row"], file_signature(state / DECISIONS_DIR / f"{task_id}.json")
    if (line["code"], row["id"], row["status"], line["export"]) != \
            (_code_stamp(), task_id, entry.get("status"), list(export) if export else None) or \
            row["status"] not in DONE_STATUSES or not set(row) <= _LINE_FIELDS:
        return None
    return line if fingerprints.holds(line["fingerprint"]) else None


def decision_words(task: dict, problem: dict | None = None) -> str | None:
    """Who took the task's current decision, in the words task list prints: "approved by X", "changes requested by
    X", "withdrawn by X (approved by Y)", or that the approval no longer holds (problem is its approval_problem)."""
    decision = task.get("decision")
    if not decision:
        return None
    by = decision["by"]
    if decision["outcome"] == "changes-requested":
        if decision.get("withdraws"):
            approver = next((entry["decision"]["by"] for entry in reversed(task["rounds"]) if entry.get("revoked")), None)
            return f"withdrawn by {by}" + (f" (approved by {approver})" if approver else "")
        return f"changes requested by {by}"
    if problem and problem["severity"] == "error":
        # A broken seal means the name itself may have been edited.
        return ("approval no longer holds" if problem["kind"] == "invalid-seal"
                else f"approved by {by}, approval no longer holds")
    return f"approved by {by}"


# What a change of rules means for a task in each status; a completed task keeps its record as history.
_TOUCHED_STEP = {
    "consulting": "consult it again",
    "reviewed": "request changes and consult it again",
    "approved": "consult it again (openguildkit task consult ID --reuse-answers), which keeps the passes of unchanged "
                "boards, or open a linked task with --follows",
}
# An approval without a seal, written by a release older than sealed decisions, or with a broken one keeps no pass.
_UNSEALED_STEP = ("consult it again (openguildkit task consult ID --reuse-answers): its approval has no valid seal, so "
                  "every board reviews again and check fails on it until then; or open a linked task with --follows")


def _seal_holds(task: dict) -> bool:
    try:
        check_decision_seal(task)
    except ValueError:
        return False
    return True


def tasks_touched(state: Path, profile: dict, catalog: dict) -> list[dict]:
    """The open tasks consulted under other rules, checks or boards than this profile's, each with what to do.

    update, sync and the profile commands name the same: given the profile about to be written, these are the tasks
    whose consultation or approval the change voids (a change of a neutral field, APPROVAL_NEUTRAL_FIELDS, voids none).
    """
    fingerprints = Fingerprints(profile, catalog)
    touched = []
    for path in sorted((state / "tasks").glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError:
            continue
        step = _TOUCHED_STEP.get(task["status"])
        if task["status"] == "approved" and not _seal_holds(task):
            step = _UNSEALED_STEP
        if step and not fingerprints.holds(task.get("profile_fingerprint")):
            touched.append({"id": task["id"], "status": task["status"], "step": step.replace("ID", task["id"])})
    return touched


def cited_evidence(task: dict) -> list[str]:
    """The project paths a task names as evidence for a reviewer: named evidence, rule and pack answers,
    acceptance criteria and blocker clearings.

    Free text ("Tried by hand.") is not a path and is left out, and so are the logs task verify writes for
    the check commands under .openguildkit/tasks/: they are the tool's own record, not evidence to share.
    """
    result = task.get("result", {})
    paths = [item.get("evidence") for item in result.get("checks", []) if "exit_code" not in item]
    paths += [item.get("evidence") for item in result.get("packs", [])]
    for criterion in result.get("criteria", []):
        paths += [criterion.get("evidence"), criterion.get("verified_by")]
    paths += [item["evidence"] for item in blocker_resolutions(task).values() if item["kind"] == "cleared"]
    logs = f".openguildkit/tasks/{task['id']}-checks/"
    return [path for path in dict.fromkeys(paths)
            if isinstance(path, str) and path and not path.startswith(("https://", "command:", logs))
            and not any(character.isspace() for character in path)]


def record_consultation(
    task: dict, answers: dict, profile: dict, catalog: dict, selection: dict | None = None,
    host_controls: list[dict] | None = None, market: dict | None = None, storybook: dict | None = None,
    knowledge: dict | None = None, tools: list[dict] | None = None, root: Path | None = None,
    brief: str | None = None,
) -> dict:
    """Record a consultation. With the project root, a bug brief's files and functions are looked for in it.

    A brief can be revised at any consultation, the passes then start over; after a change request, the earlier round
    is kept. An approval that no longer holds (earlier rules, a revision a rebase replaced, a seal or a signature that
    fails) is consulted again under the same ID: it is kept in rounds with the reason, and the passes of the boards
    whose brief did not change are kept.
    """
    reopened = None
    if task["status"] == "approved":
        reopened = approval_problem(task, profile, catalog, root)
        if not reopened or reopened["severity"] != "error":
            raise ValueError(decided_message(task))
    elif task["status"] == "reviewed" and not fingerprint_holds(task.get("profile_fingerprint"), profile, catalog):
        raise ValueError(stale_review_message(task["id"]))
    elif task["status"] not in {"draft", "consulting", "changes-requested"}:
        raise ValueError(decided_message(task) or (
            f"The review of {task['id']} is recorded and waits for the person's decision: they approve it or request "
            f"changes at their terminal (openguildkit task decide {task['id']}), and you consult again after a change "
            "request."))
    rounds = list(task["rounds"])
    # A withdrawn approval went to the rounds when the person withdrew it.
    if task["status"] in {"changes-requested", "approved"} and not task["decision"].get("withdraws"):
        archived = archived_round(task)
        if reopened:
            archived["reopened"] = reopened["message"]
        rounds.append(archived)
    validated = validate_answers(redact_data(answers))
    result = {**task, "answers": validated, "rounds": rounds}
    if brief is not None:
        result["brief"] = validate_brief(brief)
    missing = None
    if root is not None and validated["kind"] == "bug":
        missing = code_not_found(" ".join([result["brief"], validated.get("context", "")]), root)
    result.update(
        status="consulting",
        consultation=consult(
            task_scope_profile(profile, catalog, validated.get("components", [])),
            catalog, result, selection, host_controls, market, storybook,
            knowledge, tools, missing,
        ),
        profile_fingerprint=profile_fingerprint(profile, catalog),
    )
    for key in ("review", "decision", "passes", "deliberation", *RESOLUTION_FIELDS, "result", "waiting_for"):
        result.pop(key, None)
    # A broken seal means the review itself may have been edited: every board reviews again.
    if reopened and reopened["kind"] not in ("invalid-seal", "no-seal"):
        kept = kept_passes(task, result["consultation"])
        if kept["boards"]:
            result["passes"] = kept
            left = [board_id for board_id in result["consultation"]["boards"] if board_id not in kept["boards"]]
            result["consultation"]["markdown"] += kept_passes_note(task["id"], sorted(kept["boards"]), left)
    return result


# Each round of a task keeps these fields of the record it closes, the clearances of both phases included.
ROUND_FIELDS = ("brief", "answers", "consultation", "review", "decision", "profile_fingerprint", "deliberation",
                *RESOLUTION_FIELDS, "result")


def archived_round(task: dict) -> dict:
    """The record of a round as the rounds keep it, when the task is consulted again or its approval withdrawn."""
    return {key: task[key] for key in ROUND_FIELDS if key in task}


def kept_passes(task: dict, consultation: dict) -> dict:
    """The passes of the approved round whose board brief and entry template did not change: same board, same rules,
    same questions. The person approves again over them; task pass BOARD --again redoes one."""
    previous = task["consultation"]
    entries = {entry["id"]: entry for entry in task["review"]["boards"]}
    templates = [{item["id"]: item for item in source["review_template"]["boards"]}
                 for source in (previous, consultation)]
    mode = "subagent" if task["review"].get("execution") == "subagents" else "sequential"
    boards = {}
    for board_id in consultation["boards"]:
        before = previous.get("board_briefs", {}).get(board_id)
        unchanged = before is not None and before == consultation.get("board_briefs", {}).get(board_id)
        if board_id in entries and unchanged and templates[0].get(board_id) == templates[1].get(board_id):
            boards[board_id] = {"status": "done", "mode": mode, "entry": entries[board_id], "at": timestamp(),
                                "attempts": 0, "kept_from": previous["id"]}
    return {"consultation_id": consultation["id"], "boards": boards}


def kept_passes_note(task_id: str, kept: list[str], left: list[str]) -> str:
    """The consultation's note on the passes kept from the approved round, and what remains before the decision."""
    remaining = (f"Run the passes of {', '.join(left)} (openguildkit task pass {task_id} BOARD), then" if left
                 else "Every pass is kept: run")
    return (f"\n\n## Passes kept from the approved round\n\nThe brief, the rules and the entry template of these "
            f"boards did not change, so their passes are kept as done: {', '.join(kept)}. {remaining} openguildkit "
            f"task review {task_id} --summary TEXT; the person approves again. To redo a kept pass: openguildkit "
            f"task pass {task_id} BOARD --again.\n")


def previous_round_line(task: dict) -> str | None:
    """One line recalling the previous round's decision and its reason, for the next round's decision."""
    if not task.get("rounds"):
        return None
    earlier = task["rounds"][-1]
    decision = earlier["decision"]
    outcome = "changes requested" if decision["outcome"] == "changes-requested" else decision["outcome"]
    revised = " The brief was revised since." if earlier.get("brief", task["brief"]) != task["brief"] else ""
    reopened = f" Reopened: {earlier['reopened']}" if earlier.get("reopened") else ""
    revoked = earlier.get("revoked")
    withdrawn = (f" Withdrawn by {revoked['by']} on {revoked['at'][:10]}: {revoked['reason'].rstrip('.')}."
                 if revoked else "")
    return (f"Round {len(task['rounds']) + 1}. Round {len(task['rounds'])}: {outcome} by {decision['by']} "
            f"on {decision['at'][:10]}: {decision['reason'].rstrip('.')}.{revised}{reopened}{withdrawn}")


def last_approval(state: Path) -> dict | None:
    """The project's most recent approval, earlier rounds included: its task, when, and the check commands it was
    given with. The decision brief compares the commands of the task to decide with these."""
    latest = None
    for path in sorted((state / "tasks").glob("*.json")) if (state / "tasks").is_dir() else []:
        try:
            task = read_task(state, path.stem)
        except ValueError:
            continue
        for entry in [*task["rounds"], task]:
            decision = entry.get("decision") or {}
            if decision.get("outcome") == "approved" and (latest is None or decision["at"] > latest["at"]):
                latest = {"task": task["id"], "at": decision["at"],
                          "checks": entry.get("consultation", {}).get("scope", {}).get("checks", [])}
    return latest


def _check_change(profile: dict, action: str, command: str) -> str:
    """Who changed a check command through the profile commands, when and why, from the profile's history."""
    for entry in reversed(profile.get("changes", [])):
        if entry["change"].startswith(f"{action} check ") and command in entry["change"]:
            return f"{action} check by {entry['by']} on {entry['on']}: {entry['reason']}"
    return "no profile command recorded it: the profile was edited by hand"


def check_command_lines(task: dict, profile: dict, previous: dict | None = None) -> list[str]:
    """The shell commands task verify will run for the task, and those added or removed since the previous approval
    of the project, each with who changed it: a command added after one approval runs after the next."""
    if is_decision_task(task):
        return []
    commands = task["consultation"]["scope"].get("checks", [])
    lines = [f"Check command command:{index}, which task verify runs as a shell command in the project root: "
             f"`{command}`" for index, command in enumerate(commands, start=1)]
    if not commands:
        lines.append("Check commands: none; task verify runs no test for this task.")
    if previous is None:
        return lines
    since = f"since the last approval of the project ({previous['task']} on {previous['at'][:10]})"
    lines += [f"Check command added {since}: `{command}` ({_check_change(profile, 'add', command)})."
              for command in commands if command not in previous["checks"]]
    lines += [f"Check command removed {since}: `{command}` ({_check_change(profile, 'remove', command)})."
              for command in previous["checks"] if command not in commands and command not in profile.get("checks", [])]
    return lines


def decision_text(task: dict, profile: dict, previous: dict | None = None, register: dict | None = None) -> list[str]:
    """What the person reads before deciding, built once for the approval prompt, task challenge and task
    decision-payload: the decision summary (verdicts, warnings, conditions of approval, removals, blockers), the check
    commands task verify will run with those changed since the project's last approval, and the task's confirmed
    critical alerts that an import resolved since its last decision."""
    lines = (requester.brief_line(task, profile) + light_lane.decision_lines(task) + decision_summary(task)) + check_command_lines(task, profile, previous)
    if register is not None:
        since = task["rounds"][-1]["decision"]["at"] if task["rounds"] else None
        lines += [resolution_line(alert) for alert in resolved_by_import(register, task, since)]
    return lines


def record_review(task: dict, review: dict, root: Path | None = None, kept: list[str] | None = None) -> dict:
    """Record the review; with the project root, the project files and tests it cites must exist.

    kept names the passes kept from an approved round (kept_passes), so the person reads which boards did not review
    again; a review file cannot claim it.
    """
    if task["status"] != "consulting":
        raise TaskStateError("A review is recorded while the task is being consulted.")
    review = validate_review(task["consultation"], {key: value for key, value in review.items() if key != "kept"}
                             if isinstance(review, dict) else review, root)
    if kept:
        review["kept"] = kept
    result = {**task, "status": "reviewed", "review": review}
    result.pop("passes", None)
    return result


def _passes(task: dict) -> dict:
    if task["status"] != "consulting":
        raise TaskStateError("Board passes can only run while the task is being consulted.")
    passes = task.get("passes")
    if not passes or passes.get("consultation_id") != task["consultation"]["id"]:
        return {"consultation_id": task["consultation"]["id"], "boards": {}}
    return {"consultation_id": passes["consultation_id"], "boards": dict(passes["boards"])}


def start_pass(task: dict, board_id: str, mode: str, again: bool = False) -> dict:
    """Mark a board's pass as started. A done pass is only printed, unless again asks to redo it; starting again
    after a failed or done pass counts a new attempt, printing a pass that is already started does not."""
    passes = _passes(task)
    if board_id not in task["consultation"]["boards"]:
        raise ValueError(f"Board {board_id!r} is not part of this consultation.")
    if mode not in ("subagent", "sequential"):
        raise ValueError("A pass runs as a subagent or in sequence.")
    previous = passes["boards"].get(board_id, {})
    if previous.get("status") == "done" and not again:
        return {**task, "passes": passes, "_submitted": True}
    if previous.get("status") == "started" and previous.get("mode") == mode:
        return {**task, "passes": passes}
    passes["boards"][board_id] = {"status": "started", "mode": mode, "started_at": timestamp(),
                                  "attempts": previous.get("attempts", 0) + (0 if previous.get("status") == "started" else 1)}
    return {**task, "passes": passes}


def earlier_sequential_pass(task: dict, board_id: str) -> str | None:
    """In passes run one after the other, another board whose pass of this consultation was already started: it
    printed the instructions every pass shares, which the one agent running the sequence keeps in mind."""
    boards = (task.get("passes") or {}).get("boards", {})
    if boards.get(board_id, {}).get("mode") != "sequential":
        return None
    return next((other for other in task["consultation"]["boards"] if other != board_id
                 and boards.get(other, {}).get("mode") == "sequential" and not boards[other].get("kept_from")), None)


def submit_pass(task: dict, entry: dict, mode: str | None = None, root: Path | None = None) -> dict:
    """Record one board's entry. An invalid entry is recorded as a failure; the corrected file can be sent again."""
    passes = _passes(task)
    raw_id = entry.get("id") if isinstance(entry, dict) else None
    # The entry is validated with its ID stripped: look its pass up the same way.
    board_id = raw_id.strip() if isinstance(raw_id, str) else None
    current = passes["boards"].get(board_id, {}) if isinstance(board_id, str) else {}
    if isinstance(board_id, str) and board_id in task["consultation"]["boards"] and not current:
        raise ValueError(
            f"The {board_id} pass was not started on the current consultation. Run openguildkit task pass "
            f"{task['id']} {board_id}, review through that brief, then submit the entry."
        )
    mode = mode or current.get("mode", "sequential")
    try:
        validated = validate_board_entry(task["consultation"], entry, root)
    except ValueError as error:
        if isinstance(board_id, str) and board_id in task["consultation"]["boards"]:
            passes["boards"][board_id] = {**current, "status": "failed", "mode": mode, "error": str(error),
                                          "at": timestamp(), "attempts": current.get("attempts", 1)}
            return {**task, "passes": passes, "_error": str(error)}
        raise
    others = [state["entry"] for other, state in passes["boards"].items()
              if other != validated["id"] and state.get("status") == "done"]
    passes["boards"][validated["id"]] = {"status": "done", "mode": mode, "entry": validated, "at": timestamp(),
                                         "attempts": current.get("attempts", 1)}
    # The signs of copied advice that concern this entry, against the passes already done: each submit says what
    # its own pass adds, not the warnings of the earlier passes again.
    copied = review_warnings([*others, validated], focus=validated["id"])
    return {**task, "passes": passes, **({"_warnings": copied} if copied else {})}


def pass_progress(task: dict) -> list[dict]:
    """Each selected board with its pass status: done, failed, started (or interrupted) or missing.

    Once the review is recorded, the passes are part of it: each of its boards is done, in the review.
    """
    if task["status"] != "consulting" and "review" in task:
        return [{"board": entry["id"], "status": "done", "in": "review"} for entry in task["review"]["boards"]]
    passes = task.get("passes") if task["status"] == "consulting" else None
    if passes and passes.get("consultation_id") != task["consultation"]["id"]:
        passes = None
    progress = []
    for board_id in task["consultation"]["boards"]:
        state = (passes or {}).get("boards", {}).get(board_id)
        item = {"board": board_id, "status": state["status"] if state else "missing"}
        if state:
            item.update({key: state[key] for key in ("mode", "attempts", "error") if key in state})
        progress.append(item)
    return progress


def assemble_review(task: dict, summary: str) -> dict:
    """Build the full review from completed passes once every board is done."""
    passes = _passes(task)
    progress = pass_progress({**task, "passes": passes})
    waiting = [item["board"] for item in progress if item["status"] != "done"]
    if waiting:
        raise TaskStateError(f"The review assembles every board's pass, and {', '.join(waiting)} "
                             f"{'is' if len(waiting) == 1 else 'are'} not done.")
    modes = {passes["boards"][board_id]["mode"] for board_id in task["consultation"]["boards"]}
    execution = "subagents" if modes == {"subagent"} else "sequential" if modes == {"sequential"} else "mixed"
    review = {
        "consultation_id": task["consultation"]["id"],
        "summary": summary,
        "boards": [passes["boards"][board_id]["entry"] for board_id in task["consultation"]["boards"]],
        "execution": execution,
    }
    kept = [board_id for board_id in task["consultation"]["boards"] if passes["boards"][board_id].get("kept_from")]
    return record_review(task, review, kept=kept)


_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def waiver_policy(profile: dict) -> dict | None:
    return profile.get("waivers")


def expired_on(resolution: object) -> str | None:
    """The end date of a waiver that has passed, by the real clock whatever SOURCE_DATE_EPOCH says; None for a waiver
    still running, a clearance or no resolution. A waiver holds through its until day."""
    if not isinstance(resolution, dict) or resolution.get("kind") != "waived":
        return None
    until = resolution.get("until")
    try:
        end = date.fromisoformat(until) if isinstance(until, str) and _DAY.fullmatch(until) else None
    except ValueError:
        return None
    return until if end is not None and end < clock.real_today() else None


def expired_waivers(blockers: list) -> list[dict]:
    """The blockers whose waiver expired: blocker_list of a task, or the blockers of an exported record."""
    return [item for item in blockers if isinstance(item, dict) and expired_on(item.get("resolution"))]


def expired_waiver_step(task: dict, item: dict) -> str:
    """What the person does about a waiver that expired on an approved task. A condition of approval is resolved
    again; a blocker the approval rested on is under its seal, so the approval is withdrawn."""
    task_id, blocker_id, until = task["id"], item["id"], item["resolution"]["until"]
    if item.get("phase") == "verification":
        return (f"The waiver of {blocker_id} expired on {until}, so the blocker is open again: the person clears it with "
                f"its evidence (openguildkit task clear {task_id} {blocker_id} --evidence PATH --supports TEXT --by "
                f"NAME), grants a new waiver (openguildkit task waive {task_id} {blocker_id} --by NAME --reason TEXT "
                f"--scope TEXT --until YYYY-MM-DD), or withdraws the approval: {revoke_command(task_id)}.")
    return (f"The waiver of {blocker_id} expired on {until}, and the approval rested on it: the person withdraws the "
            f"approval ({revoke_command(task_id)}), then the task is consulted again and the blocker cleared with its "
            "evidence or waived anew before the next decision.")


def expired_waiver_problem(record: dict, relative: str) -> str | None:
    """guard --ci: a record of a task not completed whose waiver expired is refused. A completed task's record is
    history: its waiver covered the work it delivered."""
    if record.get("completed") or record.get("status") in DONE_STATUSES:
        return None
    expired = expired_waivers(record.get("blockers") if isinstance(record.get("blockers"), list) else [])
    if not expired:
        return None
    named = ", ".join(f"{item.get('id')} on {item['resolution']['until']}" for item in expired)
    return (f"{relative}: the waiver of a blocker expired ({named}) and task {record['task']} is not completed, so the "
            "blocker is open again. The person clears it with its evidence, grants a new waiver or withdraws the "
            f"approval (openguildkit task list names the step), then export the record again.")


def _clearing_evidence(value: str, root: Path) -> str:
    """Evidence that clears a blocker is a file or folder of the project, or an https link someone can open."""
    if value.startswith("https://") and len(value) > len("https://") and not any(char.isspace() for char in value):
        return value
    project = root.resolve()
    path = (project / value).resolve()
    if path.exists() and (path == project or project in path.parents):
        return path.relative_to(project).as_posix() or "."
    raise ValueError(
        f"Clearing evidence must be an existing file or folder of the project, or an https link: {value}."
    )


def _clearance_payload(task: dict, blocker_id: str, entry: dict) -> dict:
    return {
        "kind": "blocker-clearance",
        "task": task["id"],
        "consultation_id": task["consultation"]["id"],
        "review_sha256": seal(task["review"]),
        "blocker": blocker_id,
        **{key: entry[key] for key in ("by", "evidence", "supports", "fingerprint") if key in entry},
    }


def _check_clearance_signature(task: dict, blocker_id: str, entry: dict, policy: dict, root: Path) -> None:
    """A signed clearance follows the rule of a signed approval: --by names the person, as it does for task decide, and
    the signature must verify for --signer, an approver of the project; both are recorded."""
    if not entry.get("signer") or not entry.get("signature"):
        raise ValueError("This project requires a signed clearance. Run task clear with --payload FILE, "
                         "sign the payload, then pass --signature FILE --signer PRINCIPAL.")
    verify_signature(root, policy, _clearance_payload(task, blocker_id, entry), entry["signature"], entry["signer"])


def require_blocker_status(task: dict) -> None:
    """Blockers come from the boards' review: a person resolves them once it is recorded, before the decision or,
    for a condition of approval, before completion."""
    if task["status"] not in ("reviewed", "approved"):
        raise TaskStateError("A blocker is resolved once the boards' review is recorded, before the decision, or "
                             "after the approval for a condition of approval.")


def resolve_blocker(task: dict, blocker_id: str, resolution: dict, profile: dict, root: Path,
                    *, signing_payload: bool = False) -> dict:
    """Clear a blocker with evidence, or cover it with a waiver the project's policy allows.

    The record says whether the command ran at a terminal, so the approver knows when an agent cleared it.
    """
    require_blocker_status(task)
    known = {item["id"]: item for item in blocker_list(task)}
    if blocker_id not in known:
        listed = ", ".join(known) or "none"
        raise ValueError(f"Unknown blocker {blocker_id}. Blockers: {listed}.")
    blocker = known[blocker_id]
    first = blocker["resolution"]
    expired = expired_on(first)
    if first and not expired:
        raise ValueError(f"Blocker {blocker_id} already has a resolution: {first['kind']} by {first['by']} on "
                         f"{first.get('at', '')[:10]}. It stays as recorded; see task blockers.")
    verification = blocker.get("phase") == "verification"
    if expired and not verification and task["status"] == "approved":
        raise ValueError(expired_waiver_step(task, blocker))
    if verification and task["status"] != "approved":
        raise ValueError("Resolve a verification blocker after approval and before completion.")
    if not verification and task["status"] != "reviewed":
        raise ValueError("Resolve approval blockers after the review is recorded and before the decision.")
    by = resolution.get("by", "").strip()
    if not by:
        raise ValueError("Name the person who resolves the blocker.")
    entry = {"kind": resolution["kind"], "by": by, "at": clock.real_timestamp(),
             "recorded_from": "terminal" if resolution.get("terminal") else "no terminal"}
    if resolution["kind"] == "cleared":
        for field in ("evidence", "supports"):
            if not resolution.get(field, "").strip():
                raise ValueError(f"Clearing a blocker needs --{field}.")
            entry[field] = resolution[field].strip()
        entry["evidence"] = _clearing_evidence(entry["evidence"], root)
        entry["fingerprint"] = evidence_fingerprint(root, entry["evidence"])
        policy = approval_policy(profile)
        if signing_payload:
            if policy["mode"] != "signed":
                raise ValueError("A clearance payload is signed: it belongs to a project with signed approvals.")
            return _clearance_payload(task, blocker_id, entry)
        if policy["mode"] == "signed":
            entry.update(signer=resolution.get("signer"), signature=resolution.get("signature"))
            _check_clearance_signature(task, blocker_id, entry, policy, root)
    else:
        policy = waiver_policy(profile)
        if not policy:
            clear = (f"Clear {blocker_id} with its evidence at the person's terminal (openguildkit task clear "
                     f"{task['id']} {blocker_id} --evidence PATH --supports TEXT --by NAME)")
            if verification:
                raise ValueError(f"The project's policy allows no waiver. {clear}; if it cannot be met, the person "
                                 f"withdraws the approval: {revoke_command(task['id'])}.")
            raise ValueError(f"The project's policy allows no waiver. {clear}, or the person requests changes: "
                             f"openguildkit task decide {task['id']} --request-changes --by NAME --reason TEXT.")
        if by not in policy["allowed_by"]:
            raise ValueError(f"{by} cannot grant waivers. Allowed: {', '.join(policy['allowed_by'])}.")
        until = resolution.get("until", "")
        if not _DAY.fullmatch(until):
            raise ValueError("Give the waiver's end date as YYYY-MM-DD.")
        days = (datetime.fromisoformat(until).date() - clock.real_now().date()).days
        if days < 1 or days > policy["max_days"]:
            raise ValueError(f"A waiver lasts between 1 and {policy['max_days']} days.")
        for field in ("reason", "scope"):
            if not resolution.get(field, "").strip():
                raise ValueError(f"A waiver needs --{field}.")
            entry[field] = resolution[field].strip()
        entry["until"] = until
    if expired:
        # The expired waiver stays in the record, under the resolution that replaces it.
        entry["replaces"] = first
    field = resolution_field(blocker.get("phase"))
    return {**task, field: {**task.get(field, {}), blocker_id: entry}}


def unresolved_blockers(task: dict) -> list[str]:
    return [item["id"] for item in blocker_list(task)
            if (not item["resolution"] or expired_on(item["resolution"])) and item.get("phase") != "verification"]


def verification_blocker_problems(task: dict, profile: dict, root: Path | None = None) -> list[str]:
    policy = approval_policy(profile)
    problems = []
    for item in blocker_list(task):
        if item.get("phase") != "verification":
            continue
        resolution = item["resolution"]
        if not resolution:
            problems.append(f"Verification blocker {item['id']} is open. Clear it when {item['clears_when']}")
        elif expired_on(resolution):
            problems.append(f"Verification blocker {item['id']}: {expired_waiver_step(task, item)}")
        elif root is not None and policy["mode"] == "signed" and resolution["kind"] == "cleared":
            try:
                _check_clearance_signature(task, item["id"], resolution, policy, root)
            except ValueError as error:
                problems.append(f"Verification blocker {item['id']}: {error}")
    return problems


CHANGED_EVIDENCE_GROUP = "Evidence changed since it was accepted"


def _accepted_evidence(task: dict) -> list[tuple[str, str, str | None]]:
    """Each evidence a clearance or a passed named evidence cites: the evidence, what it was accepted for and its
    fingerprint, None for one recorded before fingerprints."""
    cited = [(item["resolution"]["evidence"], f"blocker {item['id']}", item["resolution"].get("fingerprint"))
             for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "cleared"]
    return cited + [(item["evidence"], item["check"], item.get("fingerprint"))
                    for item in task.get("result", {}).get("checks", [])
                    if item["check"].startswith("evidence:") and item["status"] == "passed" and "evidence" in item]


def evidence_states(task: dict, root: Path) -> list[dict]:
    """Each evidence a clearance or a passed named evidence cites, with its state now, once one has a fingerprint:
    a task recorded before fingerprints lists none."""
    cited = _accepted_evidence(task)
    if not any(fingerprint for _, _, fingerprint in cited):
        return []
    return [{"evidence": value, "for": name, "state": evidence_state(root, value, fingerprint)}
            for value, name, fingerprint in cited]


def changed_evidence(task: dict, root: Path) -> list[str]:
    """The evidence changed or gone since it was accepted, with who accepted it and when: an open point of the
    closing and a line of task list. guard --ci does not read it (question Q2 of the plan is not decided)."""
    accepted = {f"blocker {item['id']}": f"cleared on {item['resolution'].get('at', '')[:10]} by {item['resolution']['by']}"
                for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "cleared"}
    accepted.update({item["check"]: f"confirmed by {item.get('owner', 'nobody named')}"
                     for item in task.get("result", {}).get("checks", []) if item["check"].startswith("evidence:")})
    points = []
    for item in evidence_states(task, root):
        if item["state"] in ("changed", "missing"):
            how = "was cleared" if item["for"].startswith("blocker ") else "was recorded"
            points.append(f"{item['evidence']} {'changed' if item['state'] == 'changed' else 'is missing'} since "
                          f"{item['for']} {how} ({accepted[item['for']]})")
    return points


def record_result(task: dict, profile: dict, payload: dict, source: str = "report", relevance: dict | None = None,
                  root: Path | None = None, *, changed: list[str] | None = None) -> dict:
    """Add a delivery report to an approved task; later reports update earlier checks.

    A named evidence that cannot be recorded is held back under "_held" (for the caller to print and
    drop) and the rest is recorded: the task then waits for that evidence from its owner.
    """
    if task["status"] != "approved":
        raise TaskStateError("Results belong to an approved task that is not done yet.")
    validated = validate_result(task, profile, payload, source, relevance, root, changed=changed)
    held = validated.pop("_held", [])
    result = merge_results(task.get("result"), validated, source)
    if source == "report" and task.get("answers", {}).get("outcome") and not result["criteria"]:
        raise ValueError(
            "The task has an expected outcome: report at least one acceptance criterion. Run task result ID --template."
        )
    updated = {**task, "result": result}
    for key, value in (("waiting_for", waiting_evidence(updated, profile, relevance)),
                       ("warnings", result_warnings(updated, profile, relevance))):
        result.pop(key, None)
        if value:
            result[key] = value
    return {**_with_wait(updated), "_held": held}


def _with_wait(task: dict) -> dict:
    """Next to the status, the evidence an approved task waits for, so task show and the export say it too."""
    task = {key: value for key, value in task.items() if key != "waiting_for"}
    waiting = task.get("result", {}).get("waiting_for", [])
    if waiting:
        task["waiting_for"] = [f"{item['title']} ({item['check']}) from {item['owner']}" for item in waiting]
    return task


def defer_evidence(task: dict, profile: dict, deferrals: list[tuple[str, dict]], by: str,
                   relevance: dict | None = None) -> dict:
    """Hand named evidence that is still awaited to a follow-up task, recorded on behalf of its owner."""
    waiting = {item["check"]: item for item in waiting_evidence(task, profile, relevance)}
    entries = []
    for check_id, follow_up in deferrals:
        if check_id not in waiting:
            listed = ", ".join(waiting) or "none"
            raise ValueError(f"{check_id} is not a named evidence this task waits for. Awaited: {listed}.")
        if follow_up.get("follows", {}).get("task") != task["id"]:
            raise ValueError(f"Task {follow_up['id']} does not follow {task['id']}: open it with "
                             f'openguildkit task new "BRIEF" --follows {task["id"]}.')
        entries.append({"check": check_id, "task": follow_up["id"], "owner": waiting[check_id]["owner"],
                        "by": by, "at": timestamp()})
    result = {**task["result"], "deferred": [*task["result"].get("deferred", []), *entries]}
    result.pop("waiting_for", None)
    return _with_wait({**task, "result": result})


def complete_task(task: dict, profile: dict, root: Path | None = None, relevance: dict | None = None,
                  by: str | None = None, *, changed: list[str] | None = None) -> dict:
    """Close the task: done when nothing is left open, done-with-reservations otherwise.

    Closing over a skipped or failed data protection, security or AI rule that concerns the task
    needs the person's name (the command line also asks for a terminal).
    """
    problems = (verification_blocker_problems(task, profile, root)
                + [f"Blocker {item['id']}: {expired_waiver_step(task, item)}" for item in expired_waivers(blocker_list(task))
                   if item.get("phase") != "verification"]
                + completion_problems(task, profile, relevance, changed=changed, root=root))
    if problems:
        raise ValueError("The task cannot be declared done:\n- " + "\n- ".join(problems))
    groups = points_left_open(task, profile, relevance, root)
    sensitive = next((group for group in groups if group["group"] == SENSITIVE_GROUP), None)
    if sensitive and not (by or "").strip():
        raise ValueError(
            f"{len(sensitive['points'])} data protection, security or AI point(s) are skipped, failed or declared not "
            "applicable as a pack. A person "
            f"confirms closing over them: openguildkit task complete {task['id']} --by NAME, at a terminal."
        )
    result = {**task.get("result", {}),
              "closing": {"open_points": groups, "not_concerned": not_concerned(task, profile, relevance)}}
    if by and by.strip():
        result["closing"]["by"] = by.strip()
    if not task["consultation"]["scope"].get("checks") and not is_decision_task(task):
        result["closing"]["verification"] = NO_COMMAND
    status = "done-with-reservations" if groups else "done"
    return _with_wait({**task, "status": status, "completed_at": timestamp(), "result": result})


SENSITIVE_GROUP = "Data protection, security or AI rules skipped, failed or declared not applicable as a pack"
# The other titles of the closing that other readers (the retrospective) tell apart.
NOT_RUN_GROUP = "Project checks that could not run in this environment"
OTHER_RULES_GROUP = "Other rules skipped or failed"
VERDICTS_GROUP = "Board verdicts at approval that asked for changes"
NO_COMMAND = ("No project check command ran for this task: the profile lists none (checks in "
              ".openguildkit/project.json), so nothing was run to verify the change.")


def _open_disagreements(task: dict) -> list[str]:
    """Each disagreement left open with its point and its two boards, then the decision the person takes."""
    deliberation = task.get("deliberation", {})
    objections = {item["id"]: item for item in deliberation.get("objections", [])}
    points = []
    for item_id in deliberation.get("open", []):
        objection = objections.get(item_id)
        points.append(f"{objection['from']} objects to {objection['to']}: {objection['point']}" if objection
                      else f"disagreement {item_id} was left open")
    if points and deliberation.get("decision_needed"):
        points.append(f"Decision needed: {deliberation['decision_needed']}")
    return points


def _blocks_not_lifted(task: dict) -> list[str]:
    """A board that said block, approved over blockers that were waived or left open rather than cleared."""
    points = []
    for entry in task.get("review", {}).get("boards", []):
        if entry.get("challenge", {}).get("verdict") != "block":
            continue
        open_ones = [item for item in blocker_list(task) if item["board"] == entry["id"]
                     and not (item["resolution"] and item["resolution"]["kind"] == "cleared")]
        details = "; ".join(
            f"blocker {item['id']} is waived until {item['resolution']['until']}, not cleared"
            if item["resolution"] else f"blocker {item['id']} is not cleared" for item in open_ones)
        if open_ones:
            points.append(f"{entry['id']} said block; {details}")
    return points


def points_left_open(task: dict, profile: dict, relevance: dict | None = None, root: Path | None = None) -> list[dict]:
    """What a closed task leaves open, grouped by nature, most serious first; empty groups are left out. With the
    project root, evidence changed since it was accepted too."""
    checks = {check["id"]: check for check in asked_checks(task, profile, relevance)}
    reported = outcomes(task, profile, relevance)
    sensitive, other = [], []
    for item in reported.values():
        check = checks.get(item["check"])
        if check is None or check["kind"] == "command" or item["status"] not in ("skipped", "failed"):
            continue
        detail = f": {item['reason']} ({item['owner']})" if item.get("reason") else ""
        line = f"{item['check']} is {item['status']}{detail}"
        area = sensitive_area(check.get("pack", ""))
        (sensitive if area else other).append(f"{line} [{area}]" if area else line)
    result = task.get("result", {})
    sweeping = {item.get("via_pack") for item in reported.values()}
    for item in result.get("packs", []):
        area = sensitive_area(item["pack"])
        if area and item["pack"] in sweeping:
            sensitive.append(f"pack {item['pack']} is declared not applicable as a whole: {item['reason']} "
                             f"({item['owner']}) [{area}]")
    groups = [
        (SENSITIVE_GROUP, sensitive),
        ("Board blocks not lifted", _blocks_not_lifted(task)),
        (delivered_review.FINDINGS_GROUP, delivered_review.open_points(task)),
        (CHANGED_EVIDENCE_GROUP, changed_evidence(task, root) if root is not None else []),
        (NOT_RUN_GROUP, [
            f"{item['check']} could not run: {item['reason']} (recorded by {item['owner']})"
            for item in result.get("checks", []) if item.get("cannot_run")]),
        ("Blockers waived rather than cleared", [
            f"blocker {item['id']} is waived until {item['resolution']['until']}"
            for item in blocker_list(task) if item["resolution"] and item["resolution"]["kind"] == "waived"]),
        ("Disagreements between boards left open", _open_disagreements(task)),
        ("Named evidence handed to a follow-up task", [
            f"{item['check']} is handed to task {item['task']}, provided by {item['owner']} (recorded by {item['by']})"
            for item in result.get("deferred", [])]),
        (OTHER_RULES_GROUP, other),
        ("Warnings on the result", list(result.get("warnings", []))),
    ]
    found = [{"group": title, "points": points} for title, points in groups if points]
    verdicts = [f"{entry['id']} said {entry['challenge']['verdict']}" for entry in task.get("review", {}).get("boards", [])
                if entry.get("challenge", {}).get("verdict") == "revise"]
    if found and verdicts:
        found.append({"group": VERDICTS_GROUP, "points": verdicts})
    return found


def record_deliberation(task: dict, payload: dict) -> dict:
    return {**task, "deliberation": validate_deliberation(task, payload)}


def decided_message(task: dict, problem: dict | None = None) -> str | None:
    """For a task a person already decided: its status, who decided and when, and the one command that fits next.

    problem is the task's approval_problem: an approval that no longer holds leads to a new consultation, not to the
    handoff, which would refuse it.
    """
    decision, task_id, status = task.get("decision"), task["id"], task["status"]
    if not decision:
        return None
    who = f"by {decision['by']} on {decision['at'][:10]}"
    if status == "approved" and problem and problem["severity"] == "error":
        return f"Task {task_id} was approved {who}, but the approval no longer holds. {problem['message']}"
    if status == "approved":
        return (f"Task {task_id} is already approved {who}. Next: openguildkit task handoff {task_id}. To change the "
                f"work, the person withdraws the approval at their terminal ({revoke_command(task_id)}), then you "
                "consult again.")
    if status in DONE_STATUSES:
        return (f"Task {task_id} is already decided and {status}: approved {who}. To change the work, open a follow-up: "
                f"openguildkit task new \"BRIEF\" --follows {task_id}")
    if status == "changes-requested":
        return (f"Task {task_id} already has changes requested {who}. Next: {reconsult_command(task_id)}, then "
                "record the new review before deciding.")
    return None


def record_decision(
    task: dict, approve: bool, by: str, reason: str, base_revision: dict | None = None, signature: dict | None = None,
    confirmed_removals: list[str] | None = None, separate: bool = False,
) -> dict:
    """Record the person's decision. Approving needs their confirmation of each protected board removed. separate
    says that the profile separated the requester from the approver: the approval and its seal record it."""
    if task["status"] != "reviewed":
        decided = decided_message(task)
        if decided:
            raise ValueError(decided)
        raise TaskStateError("Record the boards' review before deciding.")
    unconfirmed = [board for board in pending_removals(task) if board not in (confirmed_removals or [])]
    if approve and unconfirmed:
        raise ValueError(
            f"Approval cancelled: the removal of the {', '.join(unconfirmed)} board was not confirmed. Type its name "
            "at the approval prompt, or request changes and consult again with it."
        )
    open_blockers = unresolved_blockers(task)
    if approve and open_blockers:
        raise ValueError(
            f"Resolve each blocker before approving: {', '.join(open_blockers)}. Clear it with evidence "
            "(task clear), waive it if the project allows (task waive), or request changes."
        )
    if not by.strip() or not reason.strip():
        raise ValueError("Supply the decision owner and a reason.")
    status = "approved" if approve else "changes-requested"
    # A person's decision is dated by the real clock, which its age is measured with (clock.py).
    decision = {"outcome": status, "by": by.strip(), "reason": reason.strip(), "at": clock.real_timestamp()}
    if approve:
        payload = decision_payload(task, by, reason, base_revision, separate=separate)
        decision.update(base_revision=base_revision, seal=seal(payload))
        if separate:
            decision["separate_requester"] = True
        if signature is not None:
            decision.update(signer=signature["signer"], signature=signature["text"])
        if pending_removals(task):
            decision["confirmed_removals"] = pending_removals(task)
    return {**task, "status": status, "decision": decision}


def revoke_approval(task: dict, by: str, reason: str) -> dict:
    """Withdraw an approval: the task goes back to changes requested, and the approval goes to the rounds with who
    withdrew it, when and why. The person does it at their terminal, as they approved; the guard stops counting the
    task at once."""
    task_id, status = task["id"], task["status"]
    if status in DONE_STATUSES:
        raise ValueError(decided_message(task))
    if status != "approved":
        raise TaskStateError("Only an approved task has an approval to withdraw.")
    if not by.strip() or not reason.strip():
        raise ValueError("Name the person who withdraws the approval with --by and say why with --reason.")
    at = clock.real_timestamp()
    archived = {**archived_round(task), "revoked": {"by": by.strip(), "reason": reason.strip(), "at": at}}
    decision = {"outcome": "changes-requested", "by": by.strip(), "reason": f"Approval withdrawn: {reason.strip()}",
                "at": at, "withdraws": task["decision"]["at"]}
    result = {**task, "status": "changes-requested", "decision": decision, "rounds": [*task["rounds"], archived]}
    for key in (resolution_field("verification"), "result", "waiting_for", "completed_at"):
        result.pop(key, None)
    return result


ACTIONS = ("public-research", "external-api", "send-message", "publish", "install-dependency", "other")
_TARGET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}")


def record_authorization(task: dict, action: str, target: str, allow: bool, by: str, reason: str) -> dict:
    """Record a person's decision on an external action outside the authorized scope."""
    if action not in ACTIONS:
        raise ValueError(f"Choose the action from {', '.join(ACTIONS)}.")
    if not _TARGET.fullmatch(target) or "?" in target or "@" in target:
        raise ValueError("Name the target as a host or tool name, without a query, an address or private details.")
    if not by.strip() or not reason.strip():
        raise ValueError("Supply the decision owner and a reason.")
    entry = {
        "action": action, "target": target, "decision": "allow" if allow else "deny",
        "by": by.strip(), "reason": reason.strip(), "at": clock.real_timestamp(),
    }
    return {**task, "authorizations": [*task.get("authorizations", []), entry]}


def stale_review_message(task_id: str) -> str:
    """What a review given under other rules, checks or boards than the profile's waits for: task decide, task list
    and task consult say it in the same words (a project upgraded from 0.16.1 has its reviewed tasks in this state)."""
    return (f"The rules, checks or boards of the project changed since {task_id} was consulted. The person requests "
            f"changes (openguildkit task decide {task_id} --request-changes --by NAME --reason TEXT), then you consult "
            "again.")


def require_current_scope(task: dict, profile: dict, catalog: dict) -> None:
    """Refuse to decide over a review given under other rules, checks or boards than the profile's."""
    if not fingerprint_holds(task.get("profile_fingerprint"), profile, catalog):
        if task["status"] in ("approved", *DONE_STATUSES):
            raise ValueError(stale_approval_message(task["id"], rule_changes(task, profile, catalog)))
        raise ValueError(stale_review_message(task["id"]))
