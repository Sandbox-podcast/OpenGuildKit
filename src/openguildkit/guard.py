"""Put the board in front of every change: in the agent, before file edits, and in CI.

`openguildkit guard` says whether an approved task covers the work in progress. Host
hooks run it when a request arrives and before a file edit. In CI, it checks that a
pull request carries an exported decision that matches the rules of its base revision.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from . import light_lane, requester
from .catalog import load_catalog
from .delivered_review import exported_review
from .decisions import (
    DECISIONS_DIR, approval_policy, base_commit, changed_paths_since, check_decision, check_decision_seal,
    exported_boards, exported_records, exported_rounds, history_message, outside_history_message, record_digest,
    revisions_outside_history, seal, shared_digest, stale_approval_message, verify_recorded_signature, verify_signature,
)
from .lock import LOCK_FILE, apply_lock, read_lock
from .org_catalog import organization_in
from .project import STATE_DIR, Fingerprints, load_profile, project_root, state_path
from .results import DONE_STATUSES, verification_of
from .storage import read_json, write_json
from .task_index import tasks_with_status
from .tasks import (
    STALE_DAYS, STATUSES, approval_problem, days_since, evidence_states, expired_waiver_problem, read_task, task_path,
)
from .terminal import interactive
from .workstation import no_profile_answer
from .workflow import TaskStateError, exported_blockers, mock_evidence

MODES = ("off", "observe", "enforce")
# The mode when the profile cannot be read: the hook refuses edits, as in enforce, and says why.
UNKNOWN_MODE = "unknown"
_PATCH_FILE = re.compile(r"^\*\*\* (?:(?:Update|Add|Delete) File|Move to): (.+)$", re.MULTILINE)
# Files the CLI writes through its own commands and the host settings the guard relies on.
PROTECTED = (
    f"{STATE_DIR}/tasks/", f"{STATE_DIR}/{DECISIONS_DIR}/", f"{STATE_DIR}/project.json", f"{STATE_DIR}/{LOCK_FILE}",
    ".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json", ".codex/config.toml", ".codex/rules/",
    f"{STATE_DIR}/audit/",
)
# The host settings the guard relies on when the profile names that host: a project of another host may edit the file.
HOST_PROTECTED = {"gemini-cli": (".gemini/settings.json",)}
# Files under .openguildkit/ that are work like any other: an approved task must cover an edit. The project
# catalog changes what the boards review, and the alert register what blocks an approval.
STATE_WORK = (f"{STATE_DIR}/alerts.json", f"{STATE_DIR}/catalog/")


def guard_mode(profile: dict) -> str:
    return profile.get("guard", "off")


def _age_days(moment: str) -> int | None:
    return days_since(moment)


def covering_approvals(root: Path, state: Path, profile: dict, catalog: dict) -> list[dict]:
    """Approved tasks, not yet done, whose approval still holds (tasks.approval_problem).

    The status index skips the records that are not approved without parsing them; every other record is read
    and checked in full, so the index never decides what is covered. One git call checks the approved revisions of
    them all, whatever their number. There is no age limit: the person withdraws an approval with task revoke.
    """
    directory = state / "tasks"
    if not directory.is_dir():
        return []
    approved = []
    for task_id in tasks_with_status(state, set(STATUSES) - {"approved"}):
        try:
            task = read_task(state, task_id)
        except Exception:  # A broken record covers nothing; it must not stop the guard.
            continue
        if task["status"] == "approved" and task.get("answers", {}).get("kind") != "decision":
            approved.append(task)
    if not approved:
        return []
    fingerprints = Fingerprints(profile, catalog)
    outside = revisions_outside_history(root, [base_commit(task) for task in approved])
    covered = []
    for task in approved:
        try:
            found = approval_problem(task, profile, catalog, root, fingerprints=fingerprints, outside=outside,
                                     explain=False)
            if found and found["severity"] == "error":
                continue
            age = _age_days(task["decision"].get("at"))
            brief = task["brief"].strip().splitlines()
            entry = {"task": task["id"], "brief": brief[0][:120] if brief else "",
                     "approved_at": task["decision"].get("at"), "stale": age is None or age > STALE_DAYS}
            if light_lane.is_light(task):
                entry.update(lane=task["lane"], paths=task["paths"])
            covered.append(entry)
        except Exception:  # A broken record covers nothing; it must not stop the guard.
            continue
    return covered


def edited_paths(hook_input: object) -> list[str]:
    """File paths a host wants to edit: Claude Code and Gemini CLI (write_file, replace) pass file_path, Codex a patch.

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


def _protected(relative: str, host: str | None = None) -> bool:
    return _listed(relative, PROTECTED + HOST_PROTECTED.get(host, ()))


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
    # Beside a task of the full path, which covers every edit, a short-lane task is named with its paths; alone, the note
    # of the message (scope_note) names them.
    mixed = any(not item.get("lane") for item in approvals)
    for item in approvals:
        text = f"{item['task']} ({item['brief']})"
        if item.get("lane") and mixed:
            text += f", short lane limited to {', '.join(item['paths'])}"
        if item["stale"]:
            text += f", approved more than {STALE_DAYS} days ago: ask the person whether it still applies"
        parts.append(text)
    return "; ".join(parts)


# Gemini CLI names its hook events BeforeAgent (a request) and BeforeTool (before a tool), where Claude Code and Codex
# say UserPromptSubmit and PreToolUse; the input carries the name, so the answer follows it.
GEMINI_EVENTS = ("BeforeAgent", "BeforeTool")


def hook_dialect(hook_input: object) -> str:
    """The host whose format the hook input has: "gemini" for Gemini CLI, "claude" for the others."""
    name = hook_input.get("hook_event_name") if isinstance(hook_input, dict) else None
    return "gemini" if name in GEMINI_EVENTS else "claude"


def _context(event: str, text: str, dialect: str = "claude") -> str:
    """The JSON a hook prints to tell the agent, or for Gemini CLI before a tool the person, what the guard found.

    Gemini CLI documents additionalContext for BeforeAgent only: before a tool, its documented text field is
    systemMessage, which it shows to the person (https://geminicli.com/docs/hooks/reference/).
    """
    if dialect == "gemini":
        if event == "prompt":
            return json.dumps({"hookSpecificOutput": {"hookEventName": "BeforeAgent", "additionalContext": text}})
        return json.dumps({"systemMessage": text})
    name = "UserPromptSubmit" if event == "prompt" else "PreToolUse"
    return json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}})


# What the guard found: an approved task covers the work, no task covers it, the edit touches a file the guard
# relies on or the allowed signers file, the guard could not check, or the edit stays outside the project's work.
HOOK_OUTCOMES = ("covered", "uncovered", "lane", "protected", "signers", "unchecked", "outside")
SCOPE_NOTE = (
    "The guard does not compare the edited files with a task's scope: keep this work within the approved brief "
    "and bring anything else back to the person."
)
LANE_REASON = ("Each short-lane task covers only its paths, and rules, dependencies, the profile and agent instructions "
               "are never in the lane.")
LANE_ADVICE = ("Open a task on the full path (openguildkit task new BRIEF, without --lane) and wait for the person's "
               "approval before editing these files, or bring this edit back to the person.")


def scope_note(approvals: list[dict]) -> str:
    """What the guard compares with the edits: nothing for a task of the full path, the paths for short-lane tasks that
    are the only ones approved."""
    if not approvals or any(not item.get("lane") for item in approvals):
        return SCOPE_NOTE
    return (f"The guard holds each edit to the paths of the short-lane task(s) ({light_lane.covered_summary(approvals)}), "
            "not to the brief: keep this work within the approved brief and bring anything else back to the person.")


def approval_text(item: dict) -> str:
    """One covering task in a line of guard: its ID and brief, its lane, and a warning on an old approval."""
    lane = f" (short lane: {', '.join(item['paths'])})" if item.get("lane") else ""
    stale = f" (approved more than {STALE_DAYS} days ago: confirm it still applies)" if item["stale"] else ""
    return f"{item['task']}: {item['brief']}{lane}{stale}"


def hook_answer(event: str, mode: str, outcome: str, detail: str = "", dialect: str = "claude",
                note: str = SCOPE_NOTE) -> tuple[int, str, str]:
    """The exit code, stdout and stderr for a hook, built from the mode and the outcome so words and code agree.

    Only enforce refuses an edit (exit code 2, reason on stderr: the refusal of Claude Code, Codex and Gemini CLI);
    observe lets it through and says it is flagged.
    """
    if outcome not in HOOK_OUTCOMES:
        raise ValueError(f"Unknown guard outcome {outcome!r}: one of {', '.join(HOOK_OUTCOMES)}.")
    if mode == "off" or outcome == "outside":
        return 0, "", ""
    refuse = mode in ("enforce", UNKNOWN_MODE)
    verdict = "Edit refused" if refuse else "Edit flagged, not blocked (guard: observe)"
    if mode == UNKNOWN_MODE:
        detail += "; the profile cannot be read, so the guard cannot know its mode and refuses edits as in enforce"
    if outcome == "covered":
        if dialect == "gemini" and event != "prompt":
            return 0, "", ""  # Before a tool, Gemini CLI has no documented way to tell the agent: the request hook did.
        return 0, _context(event, f"OpenGuildKit: approved task(s) in progress: {detail}. {note}", dialect), ""
    if event == "prompt":
        if outcome != "unchecked":
            return 0, _context(event, NO_TASK, dialect), ""
        edits = "refused" if refuse else "flagged, not blocked,"
        return 0, _context(event, f"OpenGuildKit: the guard could not run ({detail}). Tell the person; "
                                  f"file edits are {edits} until it is fixed.", dialect), ""
    if outcome == "protected":
        message = (f"OpenGuildKit: {detail} is written by the openguildkit commands and the guard relies on it. "
                   f"{verdict}: ask the person to run the openguildkit command that changes it.")
    elif outcome == "signers":
        message = (f"OpenGuildKit: {detail} lists the keys that may sign approvals: only the person changes it, in a "
                   f"commit they review, even under an approved task. {verdict}: ask the person.")
    elif outcome == "lane":
        message = (f"OpenGuildKit: {verdict} for: {detail}. {LANE_REASON} {LANE_ADVICE}" if refuse
                   else f"OpenGuildKit: {verdict}: {detail}. {LANE_REASON} {LANE_ADVICE}")
    elif outcome == "uncovered":
        # In observe, what happened comes first: the instruction must not read stronger than the flag.
        advice = NO_TASK.removeprefix("OpenGuildKit: ")
        message = (f"{NO_TASK} {verdict} for: {detail}." if refuse
                   else f"OpenGuildKit: {verdict}: {detail}. {advice[0].upper()}{advice[1:]}")
    else:
        message = f"OpenGuildKit: the guard could not check this edit ({detail}). {verdict}: fix the cause or ask the person."
    if refuse:
        return 2, "", message
    return 0, _context(event, message, dialect), ""


def guard_hook(event: str, root: Path, state: Path, profile: dict, catalog: dict, hook_input: object) -> tuple[int, str, str]:
    """Return the exit code, stdout and stderr for a host hook."""
    mode = guard_mode(profile)
    if mode == "off":
        return 0, "", ""
    dialect = hook_dialect(hook_input)
    approvals = covering_approvals(root, state, profile, catalog)
    if event == "prompt":
        return hook_answer(event, mode, "covered" if approvals else "uncovered", _describe(approvals), dialect,
                           scope_note(approvals))
    inside = [relative for relative in (_project_relative(root, path) for path in edited_paths(hook_input)) if relative]
    signers = signers_file(root, profile)
    keys = [relative for relative in inside if signers and relative.casefold() == signers.casefold()]
    host = profile.get("host")
    protected = [relative for relative in inside if _protected(relative, host)]
    work = [relative for relative in inside if relative not in keys and not _protected(relative, host) and _is_work(relative)]
    if keys:
        return hook_answer(event, mode, "signers", ", ".join(keys), dialect)
    if protected:
        return hook_answer(event, mode, "protected", ", ".join(protected), dialect)
    if work and not approvals:
        return hook_answer(event, mode, "uncovered", ", ".join(work), dialect)
    if work:
        # A task of the full path covers every edit; a short-lane task, only the files its paths and the profile name.
        light = profile.get("light_paths") or []
        left = [relative for relative in work if not any(
            not item.get("lane") or light_lane.covers(relative, item["paths"], light) for item in approvals)]
        if left:
            return hook_answer(event, mode, "lane", f"{', '.join(left)} (approved short-lane task(s): "
                                                    f"{light_lane.covered_summary(approvals)})", dialect)
        return hook_answer(event, mode, "covered", _describe(approvals), dialect, scope_note(approvals))
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
    """The answer of _decide_hook; a refusal is also written in the audit log, when a person turned it on."""
    answer = _decide_hook(event, raw, project, load)
    if answer[0] == 2:
        from . import audit_log

        audit_log.refused(raw, project)
    return answer


def _decide_hook(event: str, raw: str | None, project: Path | None, load) -> tuple[int, str, str]:
    """Run a host hook so that, in enforce mode, any failure to decide refuses the edit.

    load() returns the project root, state, profile and catalog; it may raise. A profile that declares the guard
    off ends the hook before load(): whatever the catalog and the profile say, the answer is to let the edit through.
    """
    if _declared_mode(project) == "off":
        return no_profile_answer(event, project) or hook_answer(event, "off", "outside")
    mode, dialect = None, "claude"
    try:
        root, state, profile, catalog = load()
        mode = guard_mode(profile)
        if raw is None:
            raise ValueError("the hook input could not be read")
        try:
            hook_input = json.loads(raw) if raw.strip() or event == "pre-edit" else {}
        except ValueError as error:
            raise ValueError("the hook input is not JSON") from error
        dialect = hook_dialect(hook_input)
        return guard_hook(event, root, state, profile, catalog, hook_input)
    except Exception as error:  # A guard that cannot decide must not let an edit through in enforce mode.
        return hook_answer(event, mode or _declared_mode(project), "unchecked", _one_line(error), dialect)


def project_loader(project: Path | None, catalog_in_force=None):
    """load() for run_hook: the project root, its state folder, the validated profile and the catalog in force.

    catalog_in_force(state) gives that catalog; by default, the installed catalog with the project's additions,
    where the records of the catalog lock take precedence, as every command reads it.
    """
    def load():
        root = project_root(project)
        state = state_path(root)
        if catalog_in_force is not None:
            catalog = catalog_in_force(state)
        else:
            lock = read_lock(state)
            catalog = apply_lock(load_catalog(state / "catalog", organization=organization_in(lock, state)), lock)
        return root, state, load_profile(state, catalog), catalog

    return load


def hook_command(event: str, project: Path | None, catalog_in_force=None) -> int:
    """openguildkit guard --hook EVENT: read the host's input on stdin, print the answer, return the exit code.

    Hosts run it before every edit, so it imports only what the guard needs: __main__ calls it without the rest
    of the CLI.
    """
    try:
        raw = "" if interactive() else sys.stdin.read()
    except (OSError, UnicodeError):
        raw = None
    code, out, err = run_hook(event, raw, project, project_loader(project, catalog_in_force))
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    return code


def export_decision(root: Path, state: Path, task: dict, profile: dict, output: Path | None = None) -> Path:
    """Write a shareable record of an approved decision: no evidence details, no internal notes.

    The record carries the approval payload, and its signature when there is one, so CI can recompute the seal.
    """
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
    record["record_sha256"] = record_digest(record)
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


def _record_check(record: dict, relative: str, fingerprint: str | Fingerprints, policy: dict, base_root: Path,
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


_COMMIT = re.compile(r"[0-9a-f]{7,64}")


def in_history(history: Path, commit: object) -> bool:
    """Whether HEAD of the repository contains the commit: a commit git does not have, or one HEAD does not reach,
    is outside its history."""
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        return False
    return _git(history, "merge-base", "--is-ancestor", commit, "HEAD").returncode == 0


def _earlier_withdrawal(earlier: dict, task_id: str) -> bool:
    before = earlier.get(task_id)
    return isinstance(before, dict) and isinstance(before.get("withdrawn"), dict) and all(
        isinstance(before["withdrawn"].get(key), str) for key in ("by", "reason", "at"))


def _rules_hold(fingerprint: str | Fingerprints, recorded: str) -> bool:
    """Whether a record was approved under the current rules; a Fingerprints also accepts the fingerprint that an
    earlier release recorded for the same rules, so that an upgrade does not turn every record into earlier rules."""
    return fingerprint.holds(recorded) if isinstance(fingerprint, Fingerprints) else recorded == fingerprint


def _record_fault(record: dict, relative: str, fingerprint: str | Fingerprints, policy: dict, base_root: Path, earlier: dict,
                  *, extracted: bool = False, history: Path | None = None) -> tuple[str, str] | None:
    """What is wrong with a record: the code of its rule (docs/sarif.md) and a message, which _record_check writes
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
    if payload is None:
        return "decision-record-invalid", f"{relative} carries no approval payload. {export_again}"
    expected = {"task": record["task"], "outcome": "approved", "profile_fingerprint": record["profile_fingerprint"],
                "by": decision["by"], "reason": decision["reason"]}
    if "at" in payload:  # Sealed from version 4: the date the record shows is the date that was sealed.
        expected["at"] = decision.get("at")
    if any(payload.get(key) != value for key, value in expected.items()) or seal(payload) != decision["seal"]:
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
    current = record.get("schema_version", 1) >= RECORD_VERSION or "shared_sha256" in payload or "record_sha256" in record
    if current and record.get("record_sha256") != record_digest(record):
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
        if not isinstance(decision.get("signature"), str) or not isinstance(decision.get("signer"), str):
            return "decision-unsigned", f"{relative}: the project requires signed approvals and this decision is not signed."
        try:
            # An approval the base revision already carries may come from an approver who has left since; a new one
            # must come from a current approver.
            if record["task"] in earlier or not extracted:
                verify_recorded_signature(base_root, policy, payload, decision["signature"], decision["signer"],
                                          committed=not extracted, history=history)
            else:
                verify_signature(base_root, policy, payload, decision["signature"], decision["signer"], committed=False)
        except ValueError as error:
            return "decision-signature-invalid", f"{relative}: {error}"
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


def exported_decisions(root: Path, state: Path, profile: dict, fingerprint: str | Fingerprints) -> list[dict]:
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
            found = _record_check(record, relative, fingerprint, policy, root, {})
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
        elif row["local"] and (withdrawn := _withdrawn_here(state, record)):
            row["problem"] = {"kind": "withdrawn-here", "severity": "error", "message": (
                f"{relative}: the approval of {record['task']} was withdrawn in this copy by {withdrawn['by']} on "
                f"{withdrawn['at'][:10]}, and the record still says it is approved, so guard --ci keeps accepting it. "
                f"Write the withdrawal into it with openguildkit task export {record['task']}, and commit it."),
                "code": "decision-withdrawn-here"}
        rows.append(row)
    return rows


def _withdrawn_here(state: Path, record: dict) -> dict | None:
    """The withdrawal the local task records for the approval an exported record carries, if any."""
    try:
        task = read_task(state, record["task"])
    except Exception:  # An unreadable task record is reported by task list and check.
        return None
    return withdrawal_of(task, record)


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
    path = output if output is not None else state / DECISIONS_DIR / f"{task['id']}.json"
    shown = path.resolve().relative_to(root.resolve()).as_posix() if root.resolve() in path.resolve().parents else str(path)
    if not any(isinstance(item.get("revoked"), dict) for item in task.get("rounds", [])):
        raise TaskStateError("Only an approved or completed task can be exported, or one whose approval was withdrawn.")
    if not path.is_file():
        raise ValueError(f"The approval of {task['id']} was withdrawn and {shown} does not exist: there is no exported "
                         "record to write the withdrawal into, and nothing for guard --ci to accept.")
    _refuse_foreign_record(root, path, task)
    record = read_json(path)
    _record_shape(record, shown)
    withdrawn = withdrawal_of(task, record)
    if withdrawn is None:
        raise ValueError(f"{shown} holds an approval of {task['id']} that was not withdrawn: it is left as it is.")
    record = {key: value for key, value in record.items() if key != "record_sha256"}
    record["withdrawn"] = withdrawn
    record["record_sha256"] = record_digest(record)
    write_json(path, record)
    return path


def untracked_files(root: Path) -> list[str]:
    """The new files Git does not track yet, ignored files and decision records left out: no record lists them."""
    result = _git(root, "ls-files", "-z", "--others", "--exclude-standard", "--full-name")
    if result.returncode:
        return []
    prefix = f"{STATE_DIR}/{DECISIONS_DIR}/"
    return sorted(path for path in result.stdout.decode("utf-8", errors="replace").split("\0")
                  if path and not path.startswith(prefix))


def _earlier_records(directory: Path) -> dict:
    """The exported decisions of the base revision, by task, at any depth below the decisions folder, as the change's
    own records are found: a record merged in a subfolder still binds its approval. The record in the folder itself
    comes first when a task has several."""
    records = {}
    for path in sorted(directory.rglob("*.json"), key=lambda item: (item.parent != directory, item.as_posix())):
        try:
            record = read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and isinstance(record.get("task"), str):
            records.setdefault(record["task"], record)
    return records


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


LOCAL_RECORDS = (
    "Approvals on the base revision are local: CI recomputes each record's seal, but whoever can write a record can "
    "recompute it too, so nothing here proves who approved. Require signed approvals (docs/workflow.md#signed-approvals)"
)
WORKFLOW_DIR = ".github/workflows/"
GUARD_STEP = "openguildkit guard --ci"


def _shown_files(paths: list[str], limit: int = 10) -> str:
    return ", ".join(paths[:limit]) + (f" and {len(paths) - limit} more" if len(paths) > limit else "")


def _uncovered(work: list[str], covers: dict) -> str | None:
    """The changed files that no valid record of the change covers, as one problem; None when each is covered.

    covers maps each valid record's task to the files it covers, None when it lists none.
    """
    listed = {path for files in covers.values() for path in files or []}
    missing = [path for path in work if path not in listed]
    if not missing:
        return None
    unlisted = [task for task, files in covers.items() if files is None]
    detail = (f" The record(s) of {', '.join(unlisted)} list no files: approved before the project had a Git revision, "
              "or exported by an earlier release." if unlisted else "")
    return (f"{len(missing)} changed file(s) are in no decision record of this change: {_shown_files(missing)}. A record "
            "covers the files Git tracks that changed since its approval when it is exported: export it again once the "
            "work is committed (openguildkit task export ID), or open a task for this change." + detail)


def _lane_fault(record: dict, files: list[str] | None, light: list[str], base: str) -> str | None:
    """Why a short-lane record cannot cover the change: the base revision has no light_paths (a change cannot turn on
    the lane it is judged by), or a file the record lists is outside its paths or the base revision's light_paths. The
    files a record covers are those of its base version when the base holds the same approval."""
    if record.get("lane") != light_lane.LANE:
        return None
    where = f"the base revision {base}"
    if not light:
        return light_lane.off_message(record["task"], where)
    outside = light_lane.files_outside(record["paths"], light, files or [])
    return light_lane.outside_message(record["task"], record["paths"], light, outside, where) if outside else None


def changes_since_approval(root: Path, task: dict) -> list[str] | None:
    """The files Git tracks that changed since the task's approval, committed or not, and the new files it does not
    track yet (the decision records left out); None when the approval named no Git revision."""
    files = changed_files(root, (task.get("decision") or {}).get("base_revision"))
    return None if files is None else sorted({*files, *untracked_files(root)})


def _workflow_ref() -> str | None:
    """The workflow file GitHub Actions is running, from GITHUB_WORKFLOW_REF (owner/repo/PATH@ref)."""
    reference = os.environ.get("GITHUB_WORKFLOW_REF", "").split("@", 1)[0]
    parts = reference.split("/", 2)
    return parts[2] if len(parts) == 3 and parts[2].startswith(WORKFLOW_DIR) else None


def _changed_guard_workflows(root: Path, base: str, changed: list[str]) -> list[str]:
    """The changed workflow files that run this check, on the base revision or in the change."""
    running = _workflow_ref()
    found = []
    for path in changed:
        if not path.startswith(WORKFLOW_DIR):
            continue
        versions = [_git(root, "show", f"{revision}:{path}") for revision in (base, "HEAD")]
        if path == running or any(not item.returncode and GUARD_STEP.encode() in item.stdout for item in versions):
            found.append(path)
    return found


def _workflow_note(paths: list[str]) -> str:
    return (f"This change edits {', '.join(paths)}, which runs this check: on pull_request, GitHub runs the pull "
            "request's own copy of a workflow, so this result may come from the edited file. Have a person review the "
            "change, and keep pull requests from editing the check (CODEOWNERS on .github/workflows/, a ruleset that "
            "requires the workflow; see integrations/README.md#protect-the-check).")


def _journal_mismatch(root: Path, record: dict) -> str | None:
    """The checks whose journal is in this tree and no longer matches the exported sha256.

    A record exported before journals were hashed has none. A journal that this checkout does not contain
    (the project gitignore leaves .openguildkit/tasks/ out) cannot be re-hashed here: task complete checks
    it on the machine that still has the file.
    """
    result = record.get("result")
    journals = result.get("journals") if isinstance(result, dict) else None
    if not isinstance(journals, list):
        return None
    mismatched = []
    for item in journals:
        if not isinstance(item, dict):
            continue
        evidence, digest, name = item.get("evidence"), item.get("sha256"), item.get("check")
        if not isinstance(evidence, str) or not isinstance(digest, str) or not isinstance(name, str):
            continue
        path = root / evidence
        try:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        except OSError:
            current = None
        if current is not None and current != digest:
            mismatched.append(name)
    if not mismatched:
        return None
    return f"{', '.join(mismatched)}: the journal no longer matches the recorded sha256."


def ci_guard(root: Path, base: str, catalog_for, *, require_signed: bool = False, findings: list | None = None) -> dict:
    """Check that the changes since base come with a decision valid under the base revision's rules.

    The mode, the profile, the catalog lock and the allowed signers come from base, so a pull request
    cannot weaken the rules it is judged by. Each changed file must be listed by a valid record the change brings;
    a record of an approval already on base covers only the files its base version listed, so re-exporting an
    old approval cannot stretch it over new work. catalog_for(state) loads the catalog of a state directory.
    require_signed makes local approvals a problem.

    A list given as findings receives each problem and note as a finding of docs/sarif.md (code, level, message, path,
    line): a problem is an error, a note stays a note, and the path is the file it concerns, None when none does.
    """
    if _git(root, "rev-parse", "--is-inside-work-tree").returncode:
        raise ValueError("guard --ci needs a Git repository: the project folder is not inside one.")
    report = findings if findings is not None else []

    def flag(code: str, message: str, path: str | None = None, level: str = "error") -> str:
        report.append({"code": code, "level": level, "message": message, "path": path, "line": None})
        return message

    changed = _git_lines(root, "diff", "--name-only", "--no-renames", f"{base}...HEAD")
    prefix = f"{STATE_DIR}/{DECISIONS_DIR}/"
    records = [path for path in changed if path.startswith(prefix) and path.endswith(".json")]
    work = [path for path in changed if path not in records]
    valid, problems, covers, where = [], [], {}, {}
    running = _changed_guard_workflows(root, base, work)
    notes = [_workflow_note(running)] if running else []
    for path in running:
        flag("guard-workflow-edited", notes[0], path, "note")
    with tempfile.TemporaryDirectory() as directory:
        base_root = Path(directory)
        names = _git_lines(root, "ls-tree", "-r", "--name-only", base, "--", STATE_DIR)
        if f"{STATE_DIR}/project.json" not in names:
            return {"mode": "off", "changed": len(work), "decisions": [], "records": {},
                    "problems": [flag("guard-no-base-profile", _no_base_profile(root), None, "note")], "notes": notes,
                    "ok": True}
        _extract_base(root, base, base_root, [name for name in names if not name.startswith(f"{STATE_DIR}/tasks/")])
        base_state = base_root / STATE_DIR
        catalog = catalog_for(base_state)
        profile = load_profile(base_state, catalog)
        policy = approval_policy(profile)
        if policy["mode"] == "signed":
            _extract_base(root, base, base_root, [PurePosixPath(policy["allowed_signers"]).as_posix()])
        fingerprint = Fingerprints(profile, catalog)
        earlier = _earlier_records(base_state / DECISIONS_DIR)
        for relative in records:
            path = root / relative
            if not path.is_file():
                continue
            if PurePosixPath(relative).parent != PurePosixPath(prefix):
                problems.append(flag("decision-record-invalid", f"{relative} is not directly under {prefix}: task export "
                                     f"writes each record there, named after its task, and no record elsewhere covers a "
                                     f"change. Move it to {prefix}TASK.json or remove it.", relative))
                continue
            try:
                record = read_json(path)
            except (OSError, ValueError):
                problems.append(flag("decision-record-invalid", conflict_message(path, relative) or (
                    f"{relative} is not a decision record written by openguildkit task export. "
                    "Export the decision again or remove the file."), relative))
                continue
            try:
                _record_shape(record, relative)
            except ValueError as error:
                problems.append(flag("decision-record-invalid", str(error), relative))
                continue
            checked = _record_check(record, relative, fingerprint, policy, base_root, earlier, extracted=True, history=root)
            fault = (checked[2], checked[1]) if checked else None
            # A waiver that expired opens its blocker again: the record no longer covers the change.
            expired = None if fault else expired_waiver_problem(record, relative)
            fault = fault or (("decision-waiver-expired", expired) if expired else None)
            journal = _journal_mismatch(root, record)
            outside = None if fault else _lane_fault(record, (earlier.get(record["task"]) or record).get("files"),
                                                     profile.get("light_paths") or [], base)
            if fault:
                problems.append(flag(fault[0], fault[1], relative))
            if journal:
                problems.append(flag("evidence-journal-changed", journal, relative))
            if outside:
                problems.append(flag("decision-lane-outside", f"{relative}: {outside}", relative))
            # The base revision's profile says whether the requester may approve: a change cannot turn that off for itself.
            same = None if fault or not requester.active(profile) else requester.record_problem(
                record, record["task"] not in earlier)
            if same:
                problems.append(flag(same[0], f"{relative}: {same[1]}", relative))
            if not fault and not journal and not outside and not same:
                valid.append(record["task"])
                where[record["task"]] = relative
                covers[record["task"]] = (earlier.get(record["task"]) or record).get("files")
    if work and not records:
        problems.append(flag("decision-missing", "The changes come with no exported decision "
                                                 "(openguildkit task export ID)."))
    elif work and not valid and not problems:
        problems.append(flag("decision-missing", "No exported decision in this change is valid."))
    elif work and valid and (uncovered := _uncovered(work, covers)):
        problems.append(flag("decision-files-uncovered", uncovered))
    if policy["mode"] != "signed" and guard_mode(profile) != "off":
        if require_signed:
            problems.append(flag("approvals-not-signed", f"{LOCAL_RECORDS}: --require-signed fails this check until they are."))
        else:
            notes.append(flag("approvals-not-signed", f"{LOCAL_RECORDS}, or pass --require-signed to fail this check until "
                                                      "they are.", None, "note"))
    ok = not problems and (not work or bool(valid))
    return {"mode": guard_mode(profile), "changed": len(work), "decisions": valid, "records": where,
            "problems": problems, "notes": notes, "ok": ok}
