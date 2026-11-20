"""Put the board in front of every change: in the agent, before file edits, and in CI.

`openguildkit guard` says whether an approved task covers the work in progress. Host
hooks run it when a request arrives and before a file edit. In CI, it checks that a
pull request carries an exported decision that matches the project's current rules.
"""

import json
import re
import subprocess
from pathlib import Path

from .decisions import check_decision
from .project import STATE_DIR, profile_fingerprint
from .storage import read_json, write_json
from .tasks import read_task

MODES = ("off", "observe", "enforce")
DECISIONS_DIR = "decisions"
_PATCH_FILE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.MULTILINE)


def guard_mode(profile: dict) -> str:
    return profile.get("guard", "off")


def covering_tasks(root: Path, state: Path, profile: dict, catalog: dict) -> list[str]:
    """Approved tasks, not yet done, whose approval still matches the record and the rules."""
    directory = state / "tasks"
    if not directory.is_dir():
        return []
    fingerprint = profile_fingerprint(profile, catalog)
    covered = []
    for path in sorted(directory.glob("*.json")):
        try:
            task = read_task(state, path.stem)
        except ValueError:
            continue
        if task["status"] != "approved" or task.get("profile_fingerprint") != fingerprint:
            continue
        if task.get("answers", {}).get("kind") == "decision":
            continue
        try:
            check_decision(task, root, profile)
        except ValueError:
            continue
        covered.append(task["id"])
    return covered


def edited_paths(hook_input: dict) -> list[str]:
    """File paths a host wants to edit: Claude Code passes file_path, Codex passes a patch."""
    tool_input = hook_input.get("tool_input") or {}
    paths = []
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(tool_input.get(key), str):
            paths.append(tool_input[key])
    for key in ("patch", "input", "command"):
        value = tool_input.get(key)
        if isinstance(value, str):
            paths.extend(match.strip() for match in _PATCH_FILE.findall(value))
    return paths


def _outside_work(root: Path, path: str) -> bool:
    """Edits outside the project, or to OpenGuildKit's own state, do not change the work."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return True
    return relative.parts[:1] == (STATE_DIR,)


NO_TASK = (
    "OpenGuildKit: no approved task covers new work in this project. If this request changes the project, "
    "open a task first (openguildkit task new BRIEF), consult the boards and wait for the person's approval "
    "before editing files."
)


def guard_hook(event: str, root: Path, state: Path, profile: dict, catalog: dict, hook_input: dict) -> tuple[int, str, str]:
    """Return the exit code, stdout and stderr for a host hook."""
    mode = guard_mode(profile)
    if mode == "off":
        return 0, "", ""
    covered = covering_tasks(root, state, profile, catalog)
    if event == "prompt":
        context = (
            f"OpenGuildKit: approved task(s) in progress: {', '.join(covered)}. Keep changes within their scope."
            if covered else NO_TASK
        )
        return 0, json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}), ""
    paths = [path for path in edited_paths(hook_input) if not _outside_work(root, path)]
    if covered or not paths:
        return 0, "", ""
    message = f"{NO_TASK} Edit refused for: {', '.join(paths)}."
    if mode == "enforce":
        return 2, "", message
    return 0, json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}), ""


def export_decision(root: Path, state: Path, task: dict, profile: dict, output: Path | None = None) -> Path:
    """Write a shareable record of an approved decision: no evidence details, no internal notes."""
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
    if "signer" in decision:
        record["decision"]["signer"] = decision["signer"]
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


def _git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def ci_guard(root: Path, state: Path, profile: dict, catalog: dict, base: str) -> dict:
    """Check that the changes since base come with an exported decision under the current rules."""
    changed = _git_lines(root, "diff", "--name-only", f"{base}...HEAD")
    prefix = f"{STATE_DIR}/{DECISIONS_DIR}/"
    records = [path for path in changed if path.startswith(prefix) and path.endswith(".json")]
    work = [path for path in changed if not path.startswith(f"{STATE_DIR}/")]
    fingerprint = profile_fingerprint(profile, catalog)
    valid, problems = [], []
    for relative in records:
        path = root / relative
        if not path.is_file():
            continue
        record = read_json(path)
        if record.get("profile_fingerprint") != fingerprint:
            problems.append(f"{relative} was approved under other rules.")
        elif not record.get("decision", {}).get("seal"):
            problems.append(f"{relative} has no sealed decision.")
        else:
            valid.append(record["task"])
    ok = not work or bool(valid)
    if work and not records:
        problems.append("The changes come with no exported decision (openguildkit task export ID).")
    return {"mode": guard_mode(profile), "changed": len(work), "decisions": valid, "problems": problems, "ok": ok}
