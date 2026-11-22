"""Put the board in front of every change: in the agent, before file edits, and in CI.

`openguildkit guard` says whether an approved task covers the work in progress. Host
hooks run it when a request arrives and before a file edit. In CI, it checks that a
pull request carries an exported decision that matches the rules of its base revision.
"""

import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import clock
from .decisions import (
    DECISIONS_DIR, approval_policy, check_decision, check_decision_seal, exported_boards, exported_records,
    exported_rounds, history_message, record_digest, seal, shared_digest, stale_approval_message, verify_signature,
)
from .lock import LOCK_FILE, read_lock
from .project import STATE_DIR, load_profile, profile_fingerprint
from .results import DONE_STATUSES, verification_of
from .storage import read_json, write_json
from .task_index import tasks_with_status
from .tasks import STATUSES, read_task, task_path
from .workflow import mock_evidence

MODES = ("off", "observe", "enforce")
# The mode when the profile cannot be read: the hook refuses edits, as in enforce, and says why.
UNKNOWN_MODE = "unknown"
STALE_DAYS = 14
_PATCH_FILE = re.compile(r"^\*\*\* (?:(?:Update|Add|Delete) File|Move to): (.+)$", re.MULTILINE)
# Files the CLI writes through its own commands and the host settings the guard relies on.
PROTECTED = (
    f"{STATE_DIR}/tasks/", f"{STATE_DIR}/{DECISIONS_DIR}/", f"{STATE_DIR}/project.json", f"{STATE_DIR}/{LOCK_FILE}",
    ".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json", ".codex/config.toml", ".codex/rules/",
)
# Files under .openguildkit/ that are work like any other: an approved task must cover an edit. The project
# catalog changes what the boards review, and the alert register what blocks an approval.
STATE_WORK = (f"{STATE_DIR}/alerts.json", f"{STATE_DIR}/catalog/")


def guard_mode(profile: dict) -> str:
    return profile.get("guard", "off")


def _age_days(moment: str) -> int | None:
    try:
        approved = datetime.fromisoformat(moment)
    except (TypeError, ValueError):
        return None
    if approved.tzinfo is None:
        approved = approved.replace(tzinfo=timezone.utc)
    return (clock.now() - approved).days


def covering_approvals(root: Path, state: Path, profile: dict, catalog: dict) -> list[dict]:
    """Approved tasks, not yet done, whose approval still matches the record and the rules.

    The status index skips the records that are not approved without parsing them; every other record is read
    and checked in full, so the index never decides what is covered.
    """
    directory = state / "tasks"
    if not directory.is_dir():
        return []
    fingerprint = profile_fingerprint(profile, catalog)
    covered = []
    for task_id in tasks_with_status(state, set(STATUSES) - {"approved"}):
        try:
            task = read_task(state, task_id)
            if task["status"] != "approved" or task.get("profile_fingerprint") != fingerprint:
                continue
            if task.get("answers", {}).get("kind") == "decision":
                continue
            check_decision(task, root, profile)
            age = _age_days(task["decision"].get("at"))
            brief = task["brief"].strip().splitlines()
            covered.append({"task": task["id"], "brief": brief[0][:120] if brief else "",
                            "approved_at": task["decision"].get("at"), "stale": age is None or age > STALE_DAYS})
        except Exception:  # A broken record covers nothing; it must not stop the guard.
            continue
    return covered


def covering_tasks(root: Path, state: Path, profile: dict, catalog: dict) -> list[str]:
    return [item["task"] for item in covering_approvals(root, state, profile, catalog)]


def edited_paths(hook_input: object) -> list[str]:
    """File paths a host wants to edit: Claude Code passes file_path, Codex passes a patch.

    Raise ValueError when the input does not say which files change, so the hook can refuse.
    """
    if not isinstance(hook_input, dict) or not isinstance(hook_input.get("tool_input"), dict):
        raise ValueError("the hook input names no tool input")
    tool_input = hook_input["tool_input"]
    paths = []
    for key in ("file_path", "notebook_path", "path"):
        if key in tool_input:
            if not isinstance(tool_input[key], str):
                raise ValueError(f"tool_input.{key} is not a file path")
            paths.append(tool_input[key])
    for key in ("patch", "input", "command"):
        value = tool_input.get(key)
        if isinstance(value, str):
            paths.extend(match.strip() for match in _PATCH_FILE.findall(value))
    if not paths:
        raise ValueError("the hook input names no file to edit")
    return paths


def _project_relative(root: Path, path: str) -> str | None:
    """The path inside the project, in POSIX form; None for a path outside it."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _listed(relative: str, items: tuple) -> bool:
    """Whether a project path is one of the items, a folder item covering what it holds; case is ignored."""
    folded = relative.casefold()
    return any(folded == item.casefold() or (item.endswith("/") and folded.startswith(item.casefold())) for item in items)


def _protected(relative: str) -> bool:
    return _listed(relative, PROTECTED)


def signers_file(root: Path, profile: dict) -> str | None:
    """The allowed signers file of a project with signed approvals, as a project path; None otherwise."""
    approval = profile.get("approval") or {}
    if approval.get("mode") != "signed" or not isinstance(approval.get("allowed_signers"), str):
        return None
    return _project_relative(root, approval["allowed_signers"])


def _is_work(relative: str) -> bool:
    """Work an approved task must cover: any project file, except the state the CLI keeps for itself."""
    return PurePosixPath(relative).parts[:1] != (STATE_DIR,) or _listed(relative, STATE_WORK)


NO_TASK = (
    "OpenGuildKit: no approved task covers new work in this project. If this request changes the project, "
    "open a task first (openguildkit task new BRIEF), consult the boards and wait for the person's approval "
    "before editing files."
)


def _describe(approvals: list[dict]) -> str:
    """Each covering task with its brief, and a warning on approvals older than the delay."""
    parts = []
    for item in approvals:
        text = f"{item['task']} ({item['brief']})"
        if item["stale"]:
            text += f", approved more than {STALE_DAYS} days ago: ask the person whether it still applies"
        parts.append(text)
    return "; ".join(parts)


def _context(event: str, text: str) -> str:
    name = "UserPromptSubmit" if event == "prompt" else "PreToolUse"
    return json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}})


# What the guard found: an approved task covers the work, no task covers it, the edit touches a file the guard
# relies on or the allowed signers file, the guard could not check, or the edit stays outside the project's work.
HOOK_OUTCOMES = ("covered", "uncovered", "protected", "signers", "unchecked", "outside")
SCOPE_NOTE = (
    "The guard does not compare the edited files with a task's scope: keep this work within the approved brief "
    "and bring anything else back to the person."
)


def hook_answer(event: str, mode: str, outcome: str, detail: str = "") -> tuple[int, str, str]:
    """The exit code, stdout and stderr for a hook, built from the mode and the outcome so words and code agree.

    Only enforce refuses an edit (exit code 2, reason on stderr); observe lets it through and says it is flagged.
    """
    if mode == "off" or outcome == "outside":
        return 0, "", ""
    refuse = mode in ("enforce", UNKNOWN_MODE)
    verdict = "Edit refused" if refuse else "Edit flagged, not blocked (guard: observe)"
    if mode == UNKNOWN_MODE:
        detail += "; the profile cannot be read, so the guard cannot know its mode and refuses edits as in enforce"
    if outcome == "covered":
        return 0, _context(event, f"OpenGuildKit: approved task(s) in progress: {detail}. {SCOPE_NOTE}"), ""
    if event == "prompt":
        if outcome != "unchecked":
            return 0, _context(event, NO_TASK), ""
        edits = "refused" if refuse else "flagged, not blocked,"
        return 0, _context(event, f"OpenGuildKit: the guard could not run ({detail}). Tell the person; "
                                  f"file edits are {edits} until it is fixed."), ""
    if outcome == "protected":
        message = (f"OpenGuildKit: {detail} is written by the openguildkit commands and the guard relies on it. "
                   f"{verdict}: ask the person to run the openguildkit command that changes it.")
    elif outcome == "signers":
        message = (f"OpenGuildKit: {detail} lists the keys that may sign approvals: only the person changes it, in a "
                   f"commit they review, even under an approved task. {verdict}: ask the person.")
    elif outcome == "uncovered":
        # In observe, what happened comes first: the instruction must not read stronger than the flag.
        advice = NO_TASK.removeprefix("OpenGuildKit: ")
        message = (f"{NO_TASK} {verdict} for: {detail}." if refuse
                   else f"OpenGuildKit: {verdict}: {detail}. {advice[0].upper()}{advice[1:]}")
    else:
        message = f"OpenGuildKit: the guard could not check this edit ({detail}). {verdict}: fix the cause or ask the person."
    if refuse:
        return 2, "", message
    return 0, _context(event, message), ""


def guard_hook(event: str, root: Path, state: Path, profile: dict, catalog: dict, hook_input: object) -> tuple[int, str, str]:
    """Return the exit code, stdout and stderr for a host hook."""
    mode = guard_mode(profile)
    if mode == "off":
        return 0, "", ""
    approvals = covering_approvals(root, state, profile, catalog)
    if event == "prompt":
        return hook_answer(event, mode, "covered" if approvals else "uncovered", _describe(approvals))
    inside = [relative for relative in (_project_relative(root, path) for path in edited_paths(hook_input)) if relative]
    signers = signers_file(root, profile)
    keys = [relative for relative in inside if signers and relative.casefold() == signers.casefold()]
    protected = [relative for relative in inside if _protected(relative)]
    work = [relative for relative in inside if relative not in keys and not _protected(relative) and _is_work(relative)]
    if keys:
        return hook_answer(event, mode, "signers", ", ".join(keys))
    if protected:
        return hook_answer(event, mode, "protected", ", ".join(protected))
    if work and not approvals:
        return hook_answer(event, mode, "uncovered", ", ".join(work))
    if work:
        return hook_answer(event, mode, "covered", _describe(approvals))
    return hook_answer(event, mode, "outside")


def _declared_mode(project: Path | None) -> str:
    """The guard mode written in the profile, read without validation; unknown when it cannot be read."""
    try:
        start = project.resolve() if project is not None else Path.cwd().resolve()
        roots = [start] if project is not None else [start, *start.parents]
        state = next((root / STATE_DIR for root in roots if (root / STATE_DIR).is_dir()), None)
        if state is None:
            return "off"
        mode = read_json(state / "project.json").get("guard", "off")
    except Exception:
        return UNKNOWN_MODE
    return mode if mode in MODES else UNKNOWN_MODE


def _one_line(error: BaseException) -> str:
    text = str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"
    return " ".join(text.split()) or type(error).__name__


def run_hook(event: str, raw: str | None, project: Path | None, load) -> tuple[int, str, str]:
    """Run a host hook so that, in enforce mode, any failure to decide refuses the edit.

    load() returns the project root, state, profile and catalog; it may raise.
    """
    mode = None
    try:
        root, state, profile, catalog = load()
        mode = guard_mode(profile)
        if raw is None:
            raise ValueError("the hook input could not be read")
        try:
            hook_input = json.loads(raw) if raw.strip() or event == "pre-edit" else {}
        except ValueError as error:
            raise ValueError("the hook input is not JSON") from error
        return guard_hook(event, root, state, profile, catalog, hook_input)
    except Exception as error:  # A guard that cannot decide must not let an edit through in enforce mode.
        return hook_answer(event, mode or _declared_mode(project), "unchecked", _one_line(error))


def export_decision(root: Path, state: Path, task: dict, profile: dict, output: Path | None = None) -> Path:
    """Write a shareable record of an approved decision: no evidence details, no internal notes.

    The record carries the approval payload, and its signature when there is one, so CI can recompute the seal.
    """
    if task["status"] not in ("approved", "done", "done-with-reservations"):
        raise ValueError("Only an approved or completed task can be exported.")
    check_decision(task, root, profile)
    path = output if output is not None else state / DECISIONS_DIR / f"{task['id']}.json"
    _refuse_foreign_record(root, path, task)
    decision = task["decision"]
    record = {
        "schema_version": RECORD_VERSION,
        "task": task["id"],
        "brief": task["brief"],
        "status": task["status"],
        **({"waiting_for": task["waiting_for"]} if task.get("waiting_for") else {}),
        "profile_fingerprint": task["profile_fingerprint"],
        "task_created_at": task["created_at"],
        "summary": task["review"]["summary"],
        "boards": exported_boards(task["review"]),
        # Evidence read from a mock is synthetic: the record says so to anyone who reads it later.
        **({"mock_evidence": mock_evidence(task)} if mock_evidence(task) else {}),
        "decision": {key: decision[key] for key in ("by", "reason", "at", "seal", "base_revision") if key in decision},
        # A record exported before completion says so; task complete asks for a new export.
        "completed": "completed_at" in task,
    }
    if "completed_at" in task:
        record["completed_at"] = task["completed_at"]
    record["decision"]["payload"] = check_decision_seal(task)
    for key in ("signer", "signature"):
        if key in decision:
            record["decision"][key] = decision[key]
    if task.get("rounds"):
        record["rounds"] = exported_rounds(task)
    if task.get("result"):
        record["result"] = {
            key: task["result"][key] for key in ("revision", "pull_request") if key in task["result"]
        }
        record["result"]["checks"] = {item["check"]: item["status"] for item in task["result"]["checks"]}
        record["result"]["check_exceptions"] = [
            {key: item[key] for key in ("check", "status", "reason", "owner") if key in item}
            for item in task["result"]["checks"] if item["status"] in ("skipped", "not-applicable")
        ]
        # A reviewer sees which named evidence was declared not applicable, by whom and why.
        record["result"]["evidence_not_applicable"] = [
            {key: item[key] for key in ("check", "reason", "owner")} for item in task["result"]["checks"]
            if item["check"].startswith("evidence:") and item["status"] == "not-applicable"
        ]
        # The tool checks that a named evidence exists, never what it says: the record names who confirmed it.
        supplied = [{"check": item["check"], "evidence": item["evidence"], "confirmed_by": item.get("owner")}
                    for item in task["result"]["checks"]
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
    if task.get("follows"):
        record["follows"] = task["follows"]["task"]
    # The regulations and patterns the profile declined when the task was consulted, with who, when and why.
    declined = task.get("consultation", {}).get("scope", {}).get("declined")
    if declined:
        record["declined"] = declined
    # What was added after the approval (completion, result) is covered by a digest of the whole record.
    record["record_sha256"] = record_digest(record)
    write_json(path, record)
    return path


RECORD_VERSION = 2


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
    return isinstance(payload, dict) and payload.get("consultation_id") in ids


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


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def _git_lines(root: Path, *args: str) -> list[str]:
    result = _git(root, *args)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return [line for line in result.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]


def _extract_base(root: Path, base: str, directory: Path, names: list[str]) -> None:
    """Copy files of the base revision into directory, at the same relative paths."""
    for name in names:
        if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
            continue
        result = _git(root, "show", f"{base}:{name}")
        if result.returncode:
            continue
        target = directory / PurePosixPath(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.stdout)


def _record_shape(record: dict, relative: str) -> None:
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
    if problem:
        raise ValueError(f"{relative} is not a decision record written by openguildkit task export: {problem}. "
                         "Export the decision again or remove the file.")


def _record_problem(record: dict, relative: str, fingerprint: str, policy: dict, base_root: Path, earlier: set,
                    *, extracted: bool = False) -> str | None:
    """Why a decision record cannot cover the changes, or None when it can."""
    found = _record_check(record, relative, fingerprint, policy, base_root, earlier, extracted=extracted)
    return found[1] if found else None


def _record_check(record: dict, relative: str, fingerprint: str, policy: dict, base_root: Path,
                  earlier: set, *, extracted: bool = False) -> tuple[str, str] | None:
    """The kind of problem a decision record has and its message, or None when it holds.

    extracted says that base_root holds files copied from a Git revision (CI) rather than a working copy.
    """
    found = _record_fault(record, relative, fingerprint, policy, base_root, earlier, extracted=extracted)
    if found is None:
        return None
    if found == "earlier-rules":
        return found, f"{relative}: {stale_approval_message(record['task'])}"
    if found == "earlier-record":
        return found, (f"{relative} was exported by an earlier release, before records carried a digest: its "
                       f"content is not verified. Export it again with openguildkit task export {record['task']}.")
    return "invalid-record", found


def _record_fault(record: dict, relative: str, fingerprint: str, policy: dict, base_root: Path, earlier: set,
                  *, extracted: bool = False) -> str | None:
    """What is wrong with a record: a message, or the kind "earlier-rules" or "earlier-record"; None when it holds.

    Records written from RECORD_VERSION on carry two digests: the approval's seal covers what the record shows of
    the approval, and record_sha256 the whole record. A record that has neither was exported by an earlier release.
    """
    decision = record["decision"]
    payload = decision.get("payload")
    export_again = f"Export it again with openguildkit task export {record['task']}, or restore the file from git."
    if record["task"] in earlier:
        return f"{relative}: task {record['task']} already had a decision on the base revision; open a new task for new work."
    if payload is None:
        return f"{relative} carries no approval payload. {export_again}"
    expected = {"task": record["task"], "outcome": "approved", "profile_fingerprint": record["profile_fingerprint"],
                "by": decision["by"], "reason": decision["reason"]}
    if any(payload.get(key) != value for key, value in expected.items()) or seal(payload) != decision["seal"]:
        return f"{relative}: the seal does not match the approval it records. {export_again}"
    if PurePosixPath(relative).parent.name == DECISIONS_DIR and PurePosixPath(relative).stem != record["task"]:
        return f"{relative} names task {record['task']}: each record belongs in the file of its own task. {export_again}"
    shown = shared_digest(record.get("brief"), record.get("summary"), record.get("boards"), record.get("rounds", []))
    if "shared_sha256" in payload and payload["shared_sha256"] != shown:
        return (f"{relative}: what the record shows (brief, summary, board verdicts and recommendations, earlier "
                f"rounds) does not match what was approved. {export_again}")
    current = record.get("schema_version", 1) >= RECORD_VERSION or "shared_sha256" in payload or "record_sha256" in record
    if current and record.get("record_sha256") != record_digest(record):
        return f"{relative} was changed after it was exported. {export_again}"
    inconsistent = _completion_problem(record) if current else None
    if inconsistent:
        return (f"{relative}: its completion is not consistent ({inconsistent}): a record that says completed carries "
                f"the closing that task complete writes, and a record that does not carries none. {export_again}")
    if record["profile_fingerprint"] != fingerprint:
        return "earlier-rules"
    if not current:
        return "earlier-record"
    if policy["mode"] == "signed":
        if not isinstance(decision.get("signature"), str) or not isinstance(decision.get("signer"), str):
            return f"{relative}: the project requires signed approvals and this decision is not signed."
        try:
            verify_signature(base_root, policy, payload, decision["signature"], decision["signer"], committed=not extracted)
        except ValueError as error:
            return f"{relative}: {error}"
    return None


_CONFLICT_START = re.compile(r"^<<<<<<< ?(.*)$", re.MULTILINE)
_CONFLICT_END = re.compile(r"^>>>>>>> ?(.*)$", re.MULTILINE)
_APPROVER = re.compile(r'"by"\s*:\s*"((?:[^"\\]|\\.)*)"')
CONFLICT_SECTION = 'docs/workflow.md, "When two copies use the same task ID"'


def conflict_message(path: Path, relative: str) -> str | None:
    """Name a decision record left with git conflict markers, and whose each side is when the text says it."""
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
            f"another ID, and export it again (see {CONFLICT_SECTION}).")


def _completion_problem(record: dict) -> str | None:
    """Whether a record's completion agrees with what task complete writes. No person seals a completion, so
    this is consistency, not proof: the record's own digest can be recomputed by whoever edits it."""
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
        return f"the status is {status} while the closing lists {len(closing['open_points'])} group(s) of open points"
    return None


def _has_local_task(state: Path, task_id: str) -> bool:
    try:
        return task_path(state, task_id).is_file()
    except ValueError:
        return False


def exported_decisions(root: Path, state: Path, profile: dict, fingerprint: str) -> list[dict]:
    """Every exported decision of the repository, teammates' included, and whether it still holds.

    The record's twin of tasks.approval_problem: the same wording, an error for an approval not yet completed
    and a note for a completed one, whose record is history.
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
            _record_shape(record, relative)
            found = _record_check(record, relative, fingerprint, policy, root, set())
        except (OSError, ValueError) as error:
            row["problem"] = {"kind": "invalid-record", "severity": "error", "message": str(error)}
            rows.append(row)
            continue
        brief = str(record.get("brief", "")).strip().splitlines()
        # Records exported before the completed field said it through their status.
        completed = bool(record.get("completed", record.get("status") == "done"))
        row.update(task=record["task"], status=record.get("status", "approved"), completed=completed,
                   by=record["decision"]["by"], brief=brief[0][:80] if brief else "",
                   local=_has_local_task(state, record["task"]))
        if found:
            kind, message = found
            if kind == "earlier-rules" and completed:
                message = f"{relative}: {history_message(record['task'])}"
            note = kind == "earlier-record" or (kind == "earlier-rules" and completed)
            row["problem"] = {"kind": kind, "severity": "note" if note else "error",
                              "message": message}
        rows.append(row)
    return rows


def _earlier_tasks(directory: Path) -> set:
    """Tasks that already had an exported decision on the base revision."""
    tasks = set()
    for path in sorted(directory.glob("*.json")):
        try:
            tasks.add(read_json(path).get("task"))
        except ValueError:
            continue
    return tasks


def _no_base_profile(root: Path) -> str:
    """Why nothing is enforced on a base without a profile, and the mode that applies once the profile is merged."""
    if not (root / STATE_DIR / "project.json").is_file():
        return ("The base revision has no OpenGuildKit profile and neither does this change: nothing to enforce. "
                "Run openguildkit init to add one.")
    expected = ("The base revision has no OpenGuildKit profile: nothing is enforced, which is expected for the pull "
                "request that adds it.")
    mode = _declared_mode(root)
    if mode == UNKNOWN_MODE:
        return f"{expected} The profile of this change cannot be read: fix it before it is merged."
    return (f"{expected} The guard reads its mode from the base revision, so once the profile is merged the next pull "
            f'requests are checked with the mode it sets ("guard": "{mode}" in this change).')


def ci_guard(root: Path, base: str, catalog_for) -> dict:
    """Check that the changes since base come with a decision valid under the base revision's rules.

    The mode, the profile, the catalog lock and the allowed signers come from base, so a pull request
    cannot weaken the rules it is judged by. catalog_for(state) loads the catalog of a state directory.
    """
    changed = _git_lines(root, "diff", "--name-only", f"{base}...HEAD")
    prefix = f"{STATE_DIR}/{DECISIONS_DIR}/"
    records = [path for path in changed if path.startswith(prefix) and path.endswith(".json")]
    work = [path for path in changed if path not in records]
    valid, problems = [], []
    with tempfile.TemporaryDirectory() as directory:
        base_root = Path(directory)
        names = _git_lines(root, "ls-tree", "-r", "--name-only", base, "--", STATE_DIR)
        if f"{STATE_DIR}/project.json" not in names:
            return {"mode": "off", "changed": len(work), "decisions": [], "problems": [_no_base_profile(root)], "ok": True}
        _extract_base(root, base, base_root, [name for name in names if not name.startswith(f"{STATE_DIR}/tasks/")])
        base_state = base_root / STATE_DIR
        catalog = catalog_for(base_state)
        profile = load_profile(base_state, catalog)
        policy = approval_policy(profile)
        if policy["mode"] == "signed":
            _extract_base(root, base, base_root, [PurePosixPath(policy["allowed_signers"]).as_posix()])
        fingerprint = profile_fingerprint(profile, catalog)
        earlier = _earlier_tasks(base_state / DECISIONS_DIR)
        for relative in records:
            path = root / relative
            if not path.is_file():
                continue
            record = read_json(path)
            _record_shape(record, relative)
            problem = _record_problem(record, relative, fingerprint, policy, base_root, earlier, extracted=True)
            if problem:
                problems.append(problem)
            else:
                valid.append(record["task"])
    if work and not records:
        problems.append("The changes come with no exported decision (openguildkit task export ID).")
    elif work and not valid and not problems:
        problems.append("No exported decision in this change is valid.")
    ok = not problems and (not work or bool(valid))
    return {"mode": guard_mode(profile), "changed": len(work), "decisions": valid, "problems": problems, "ok": ok}
