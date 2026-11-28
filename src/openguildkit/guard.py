"""Put the board in front of every change: in the agent, before file edits, and in CI.

`openguildkit guard` says whether an approved task covers the work in progress. Host
hooks run it when a request arrives and before a file edit. In CI, it checks that a
pull request carries an exported decision that matches the rules of its base revision.

Entry: guard_mode, covering_approvals, edited_paths, signers_file, hook_answer, guard_hook
Tests: tests/test_audit_log.py, tests/test_before_delivered_review.py, tests/test_delivered_review.py,
tests/test_evidence_fingerprints.py, tests/test_exit_codes.py, tests/test_gemini_host.py,
tests/test_managed_settings.py, tests/test_org_catalog.py, tests/test_record_lifecycle.py, tests/test_requester.py,
tests/test_sarif_commands.py, tests/test_short_lane.py
"""

import json
import re
import sys
from pathlib import Path, PurePosixPath

from . import incident, lazy_re, short_lane
from .catalog import load_catalog
from .decisions import DECISIONS_DIR, base_commit, revisions_outside_history
from .lock import LOCK_FILE, apply_lock, read_lock
from .org_catalog import organization_in
from .project import STATE_DIR, load_profile, project_root, restricted_paths, state_path
from .startup import MODES as MODES  # The modes, named here for the callers of the guard.
from .startup import UNKNOWN_MODE, declared_mode
from .task_index import tasks_with_status
from .terminal import interactive

# The hook runs before every edit an agent makes: it imports the task records, the rule plan, the export, CI, git,
# doc_links and wording modules only in the functions that use them (#539).
FLAGGED = "Edit flagged, not blocked"  # the words of an edit observe lets through; the audit log reads them
_PATCH_FILE = lazy_re.compile(r"^\*\*\* (?:(?:Update|Add|Delete) File|Move to): (.+)$", re.MULTILINE)
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
    from .approval_check import days_since

    return days_since(moment)


def read_task_lazily(state: Path, task_id: str) -> dict:
    """task_files.read_task, imported on the first call: the hook reads records only when one may be approved."""
    from .task_files import read_task as read

    return read(state, task_id)


# The statuses of tasks.STATUSES that cannot cover an edit, named here so that the hook reads the status index without
# importing tasks (tests/test_performance.py compares the two).
NOT_COVERING = ("draft", "consulting", "reviewed", "changes-requested", "done", "done-with-reservations")


def covering_approvals(root: Path, state: Path, profile: dict, catalog: dict) -> list[dict]:
    """Approved tasks, not yet done, whose approval still holds (approval_check.approval_problem).

    The status index skips the records that are not approved without parsing them; every other record is read
    and checked in full, so the index never decides what is covered. One git call checks the approved revisions of
    them all, whatever their number. There is no age limit: the person withdraws an approval with task revoke.
    """
    directory = state / "tasks"
    if not directory.is_dir():
        return []
    approved = []
    for task_id in tasks_with_status(state, set(NOT_COVERING)):
        try:
            task = read_task_lazily(state, task_id)
        except Exception:  # A broken record covers nothing; it must not stop the guard.
            continue
        if task["status"] == "approved" and task.get("answers", {}).get("kind") != "decision":
            approved.append(task)
    if not approved:
        return []
    from .approval_check import STALE_DAYS, approval_problem
    from .project_rules import Fingerprints

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
            if short_lane.is_light(task):
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
            from .approval_check import STALE_DAYS

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
HOOK_OUTCOMES = ("covered", "uncovered", "lane", "protected", "signers", "restricted", "unchecked", "outside")
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
    return (f"The guard holds each edit to the paths of the short-lane {'task' if len(approvals) == 1 else 'tasks'} ({short_lane.covered_summary(approvals)}), "
            "not to the brief: keep this work within the approved brief and bring anything else back to the person.")


def approval_text(item: dict) -> str:
    """One covering task in a line of guard: its ID and brief, its lane, and a warning on an old approval."""
    from .approval_check import STALE_DAYS

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
    verdict = "Edit refused" if refuse else f"{FLAGGED} (guard: observe)"
    if mode == UNKNOWN_MODE:
        detail += "; the profile cannot be read, so the guard cannot know its mode and refuses edits as in enforce"
    if outcome == "covered":
        if dialect == "gemini" and event != "prompt":
            return 0, "", ""  # Before a tool, Gemini CLI has no documented way to tell the agent: the request hook did.
        return 0, _context(event, f"OpenGuildKit: approved work in progress: {detail}. {note}", dialect), ""
    if event == "prompt":
        if outcome != "unchecked":
            return 0, _context(event, NO_TASK, dialect), ""
        edits = "refused" if refuse else "flagged, not blocked,"
        return 0, _context(event, f"OpenGuildKit: the guard could not run ({detail}). Tell the person; "
                                  f"file edits are {edits} until it is fixed.", dialect), ""
    if outcome == "protected":
        message = (f"OpenGuildKit: {detail} is written by the openguildkit commands and the guard relies on it. "
                   f"{verdict}: ask the person to run the openguildkit command that changes it.")
    elif outcome == "restricted":
        message = (f"OpenGuildKit: {detail} is a restricted path of the project (restricted_paths in "
                   f".openguildkit/project.json): agents neither read nor edit it, even under an approved task. "
                   f"{verdict}: ask the person.")
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
    freeze = incident.frozen(profile)
    if freeze and event == "prompt":
        return 0, _context(event, f"OpenGuildKit: {incident.frozen_text(freeze)}. File edits are refused. {incident.LIFT}",
                           dialect), ""
    approvals = covering_approvals(root, state, profile, catalog)
    if event == "prompt":
        return hook_answer(event, mode, "covered" if approvals else "uncovered", _describe(approvals), dialect,
                           scope_note(approvals))
    inside = [relative for relative in (_project_relative(root, path) for path in edited_paths(hook_input)) if relative]
    if freeze and inside:  # Whatever the mode and the approvals: the person lifts the freeze.
        return 2, "", f"OpenGuildKit: Edit refused: {incident.frozen_text(freeze)}. {incident.LIFT}"
    closed = [pattern.casefold() for pattern in restricted_paths(profile)]
    restricted = [relative for relative in inside if any(short_lane.matches(pattern, relative.casefold()) for pattern in closed)]
    if restricted:  # Even under an approved task: the person edits a restricted path, or changes the setting.
        return hook_answer(event, mode, "restricted", ", ".join(restricted), dialect)
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
            not item.get("lane") or short_lane.covers(relative, item["paths"], light) for item in approvals)]
        if left:
            return hook_answer(event, mode, "lane", f"{', '.join(left)} (approved short-lane {'task' if len(approvals) == 1 else 'tasks'}: "
                                                    f"{short_lane.covered_summary(approvals)})", dialect)
        return hook_answer(event, mode, "covered", _describe(approvals), dialect, scope_note(approvals))
    return hook_answer(event, mode, "outside")


def _one_line(error: BaseException) -> str:
    text = str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"
    return " ".join(text.split()) or type(error).__name__


def run_hook(event: str, raw: str | None, project: Path | None, load) -> tuple[int, str, str]:
    """The answer of _decide_hook; a refusal, or an edit flagged in observe, is also written in the audit log, when a
    person turned it on."""
    answer = _decide_hook(event, raw, project, load)
    flagged = answer[0] == 0 and event == "pre-edit" and FLAGGED in answer[1]
    if answer[0] == 2 or flagged:
        from . import audit_log

        audit_log.refused(raw, project, "guard.flagged" if flagged else "guard.refused")
    return answer


def _decide_hook(event: str, raw: str | None, project: Path | None, load) -> tuple[int, str, str]:
    """Run a host hook so that, in enforce mode, any failure to decide refuses the edit.

    load() returns the project root, state, profile and catalog; it may raise. A profile that declares the guard
    off ends the hook before load(): whatever the catalog and the profile say, the answer is to let the edit through.
    """
    if declared_mode(project) == "off":
        from .workstation import no_profile_answer

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
        return hook_answer(event, mode or declared_mode(project), "unchecked", _one_line(error), dialect)


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


