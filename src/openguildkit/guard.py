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
from .decisions import approval_policy, check_decision, decision_payload, seal, verify_signature
from .lock import LOCK_FILE, read_lock
from .project import STATE_DIR, load_profile, profile_fingerprint
from .storage import read_json, write_json
from .task_index import tasks_with_status
from .tasks import STATUSES, read_task

MODES = ("off", "observe", "enforce")
DECISIONS_DIR = "decisions"
STALE_DAYS = 14
_PATCH_FILE = re.compile(r"^\*\*\* (?:(?:Update|Add|Delete) File|Move to): (.+)$", re.MULTILINE)
# Files the CLI writes through its own commands and the host settings the guard relies on.
PROTECTED = (
    f"{STATE_DIR}/tasks/", f"{STATE_DIR}/{DECISIONS_DIR}/", f"{STATE_DIR}/project.json", f"{STATE_DIR}/{LOCK_FILE}",
    ".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json", ".codex/config.toml", ".codex/rules/",
)


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


def _protected(relative: str) -> bool:
    folded = relative.casefold()
    return any(folded == item.casefold() or (item.endswith("/") and folded.startswith(item.casefold())) for item in PROTECTED)


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


def guard_hook(event: str, root: Path, state: Path, profile: dict, catalog: dict, hook_input: object) -> tuple[int, str, str]:
    """Return the exit code, stdout and stderr for a host hook."""
    mode = guard_mode(profile)
    if mode == "off":
        return 0, "", ""
    approvals = covering_approvals(root, state, profile, catalog)
    if event == "prompt":
        context = (
            f"OpenGuildKit: approved task(s) in progress: {_describe(approvals)}. Keep changes within their scope."
            if approvals else NO_TASK
        )
        return 0, _context(event, context), ""
    inside = [relative for relative in (_project_relative(root, path) for path in edited_paths(hook_input)) if relative]
    protected = [relative for relative in inside if _protected(relative)]
    work = [relative for relative in inside if not _protected(relative) and PurePosixPath(relative).parts[:1] != (STATE_DIR,)]
    if protected:
        message = (
            f"OpenGuildKit: {', '.join(protected)} is written by the openguildkit commands and the guard relies on it. "
            "Edit refused: ask the person to run the openguildkit command that changes it."
        )
    elif work and not approvals:
        message = f"{NO_TASK} Edit refused for: {', '.join(work)}."
    elif work:
        return 0, _context(event, f"OpenGuildKit: this edit falls under approved task(s) {_describe(approvals)}. "
                                  "Keep it within that scope."), ""
    else:
        return 0, "", ""
    if mode == "enforce":
        return 2, "", message
    return 0, _context(event, message), ""


def _declared_mode(project: Path | None) -> str:
    """The guard mode written in the profile, read without validation; enforce when it cannot be read."""
    try:
        start = project.resolve() if project is not None else Path.cwd().resolve()
        roots = [start] if project is not None else [start, *start.parents]
        state = next((root / STATE_DIR for root in roots if (root / STATE_DIR).is_dir()), None)
        if state is None:
            return "off"
        mode = read_json(state / "project.json").get("guard", "off")
    except Exception:
        return "enforce"
    return mode if mode in MODES else "enforce"


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
        mode = mode or _declared_mode(project)
        if mode == "off":
            return 0, "", ""
        reason = _one_line(error)
        if event == "prompt":
            return 0, _context(event, f"OpenGuildKit: the guard could not run ({reason}). Tell the person; "
                                      "file edits are refused until it is fixed."), ""
        message = f"OpenGuildKit: the guard could not check this edit ({reason}). Edit refused: fix the cause or ask the person."
        if mode == "enforce":
            return 2, "", message
        return 0, _context(event, message), ""


def export_decision(root: Path, state: Path, task: dict, profile: dict, output: Path | None = None) -> Path:
    """Write a shareable record of an approved decision: no evidence details, no internal notes.

    The record carries the approval payload, and its signature when there is one, so CI can recompute the seal.
    """
    if task["status"] not in ("approved", "done"):
        raise ValueError("Only an approved or completed task can be exported.")
    check_decision(task, root, profile)
    decision = task["decision"]
    record = {
        "schema_version": 1,
        "task": task["id"],
        "brief": task["brief"],
        "status": task["status"],
        "profile_fingerprint": task["profile_fingerprint"],
        "boards": [
            {"id": entry["id"], "verdict": entry.get("challenge", {}).get("verdict")}
            for entry in task["review"]["boards"]
        ],
        "decision": {key: decision[key] for key in ("by", "reason", "at", "seal", "base_revision") if key in decision},
    }
    record["decision"]["payload"] = decision_payload(task, decision["by"], decision["reason"], decision.get("base_revision"))
    for key in ("signer", "signature"):
        if key in decision:
            record["decision"][key] = decision[key]
    if task.get("result"):
        record["result"] = {
            key: task["result"][key] for key in ("revision", "pull_request") if key in task["result"]
        }
        record["result"]["checks"] = {item["check"]: item["status"] for item in task["result"]["checks"]}
    if task.get("follows"):
        record["follows"] = task["follows"]["task"]
    path = output if output is not None else state / DECISIONS_DIR / f"{task['id']}.json"
    write_json(path, record)
    return path


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


def _record_problem(record: dict, relative: str, fingerprint: str, policy: dict, base_root: Path, earlier: set) -> str | None:
    """Why a decision record cannot cover the changes, or None when it can."""
    decision = record["decision"]
    payload = decision.get("payload")
    if record["task"] in earlier:
        return f"{relative}: task {record['task']} already had a decision on the base revision; open a new task for new work."
    if payload is None:
        return f"{relative} carries no approval payload. Export it again with openguildkit task export {record['task']}."
    expected = {"task": record["task"], "outcome": "approved", "profile_fingerprint": record["profile_fingerprint"],
                "by": decision["by"], "reason": decision["reason"]}
    if any(payload.get(key) != value for key, value in expected.items()) or seal(payload) != decision["seal"]:
        return f"{relative}: the seal does not match the approval it records. Export the decision again from the task."
    if record["profile_fingerprint"] != fingerprint:
        return f"{relative} was approved under other rules than those of the base revision."
    if policy["mode"] == "signed":
        if not isinstance(decision.get("signature"), str) or not isinstance(decision.get("signer"), str):
            return f"{relative}: the project requires signed approvals and this decision is not signed."
        try:
            verify_signature(base_root, policy, payload, decision["signature"], decision["signer"])
        except ValueError as error:
            return f"{relative}: {error}"
    return None


def _earlier_tasks(directory: Path) -> set:
    """Tasks that already had an exported decision on the base revision."""
    tasks = set()
    for path in sorted(directory.glob("*.json")):
        try:
            tasks.add(read_json(path).get("task"))
        except ValueError:
            continue
    return tasks


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
            return {"mode": "off", "changed": len(work), "decisions": [], "problems": [
                "The base revision has no OpenGuildKit profile: nothing to enforce yet."], "ok": True}
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
            problem = _record_problem(record, relative, fingerprint, policy, base_root, earlier)
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
