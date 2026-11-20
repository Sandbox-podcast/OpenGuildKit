"""Record what was delivered for an approved task and the checks that prove it.

The expected checks come from the approved scope: every project check command is
mandatory, and every rule of the active packs must be reported. A project can make some
rules mandatory with `required_rules`. A task is done only when every mandatory check
passed with evidence.
"""

import subprocess
import time
from pathlib import Path

from .decisions import git_revision
from .project import rule_text
from .storage import write_text

RESULT_STATUSES = ("passed", "failed", "skipped", "not-applicable")
LOG_TAIL = 4000


def expected_checks(task: dict, profile: dict) -> list[dict]:
    """The checks the handoff asks for, with an ID per check."""
    scope = task["consultation"]["scope"]
    required = set(profile.get("required_rules", []))
    checks = [
        {"id": f"command:{index}", "kind": "command", "command": command, "mandatory": True}
        for index, command in enumerate(scope.get("checks", []), start=1)
    ]
    for pack in scope.get("packs", []):
        for rule in pack["rules"]:
            rule_id = f"rule:{pack['id']}/{rule['id']}"
            _, verification = rule_text(rule)
            checks.append({
                "id": rule_id, "kind": "rule", "verification": verification,
                "mandatory": pack["id"] in required or f"{pack['id']}/{rule['id']}" in required,
            })
    return checks


def run_command_checks(root: Path, state: Path, task: dict, profile: dict, timeout: int = 1800) -> list[dict]:
    """Run the project's own check commands in the project root and keep each log as evidence."""
    revision = git_revision(root)
    logs = state / "tasks" / f"{task['id']}-checks"
    results = []
    for check in expected_checks(task, profile):
        if check["kind"] != "command":
            continue
        started = time.monotonic()
        try:
            # The commands come from the committed project profile, the source of what the project authorizes.
            completed = subprocess.run(
                check["command"], shell=True, cwd=root, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
            code, output = completed.returncode, completed.stdout + completed.stderr
        except subprocess.TimeoutExpired as error:
            code, output = None, f"Timed out after {timeout} seconds.\n{error.stdout or ''}{error.stderr or ''}"
        log = logs / f"{check['id'].replace(':', '-')}.log"
        write_text(log, f"$ {check['command']}\n{output[-LOG_TAIL:]}")
        results.append({
            "check": check["id"],
            "status": "passed" if code == 0 else "failed",
            "evidence": log.relative_to(root).as_posix(),
            "exit_code": code,
            "seconds": round(time.monotonic() - started, 1),
            **({"revision": revision["commit"]} if revision else {}),
        })
    return results


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain text.")
    return value.strip()


def validate_result(task: dict, profile: dict, payload: dict) -> dict:
    """A result names the delivered revision or PR, the acceptance criteria and each check's outcome."""
    if task.get("status") not in ("approved", "done"):
        raise ValueError("Record results for an approved task.")
    if not isinstance(payload, dict) or not payload.keys() <= {"revision", "pull_request", "criteria", "checks", "run"}:
        raise ValueError("A result has revision or pull_request, criteria and checks.")
    if not payload.get("revision") and not payload.get("pull_request"):
        raise ValueError("Name the delivered revision or pull request.")
    known = {check["id"]: check for check in expected_checks(task, profile)}
    result = {key: _text(payload[key], key) for key in ("revision", "pull_request") if payload.get(key)}
    if "run" in payload:
        result["runs"] = [payload["run"]]
    criteria = payload.get("criteria", [])
    if not isinstance(criteria, list):
        raise ValueError("criteria must be a list.")
    result["criteria"] = []
    for item in criteria:
        if not isinstance(item, dict) or item.keys() != {"criterion", "status", "evidence"}:
            raise ValueError("Each criterion has criterion, status (met or not-met) and evidence.")
        if item["status"] not in ("met", "not-met"):
            raise ValueError("A criterion is met or not-met.")
        result["criteria"].append({key: _text(item[key], f"criterion {key}") for key in item})
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        raise ValueError("checks must be a list.")
    result["checks"] = []
    for item in checks:
        if not isinstance(item, dict) or "check" not in item or "status" not in item:
            raise ValueError("Each check has check and status.")
        if item["check"] not in known and not item["check"].startswith("chaosfolk:"):
            raise ValueError(f"Unknown check {item['check']}. Run task checks for the expected IDs.")
        if item["status"] not in RESULT_STATUSES:
            raise ValueError(f"A check status is one of {', '.join(RESULT_STATUSES)}.")
        entry = {"check": item["check"], "status": item["status"]}
        if item["status"] in ("passed", "failed"):
            entry["evidence"] = _text(item.get("evidence"), f"{item['check']} evidence")
        else:
            entry["reason"] = _text(item.get("reason"), f"{item['check']} reason")
            entry["owner"] = _text(item.get("owner"), f"{item['check']} owner")
        for key in ("exit_code", "seconds", "revision", "chaosfolk_status", "message"):
            if key in item:
                entry[key] = item[key]
        result["checks"].append(entry)
    return result


def merge_results(previous: dict | None, new: dict) -> dict:
    """Later reports replace earlier outcomes check by check."""
    if not previous:
        return new
    checks = {item["check"]: item for item in previous.get("checks", [])}
    checks.update({item["check"]: item for item in new.get("checks", [])})
    merged = {**previous, **{key: new[key] for key in ("revision", "pull_request") if key in new}}
    merged["criteria"] = new["criteria"] or previous.get("criteria", [])
    merged["checks"] = list(checks.values())
    merged["runs"] = [*previous.get("runs", []), *new.get("runs", [])]
    if not merged["runs"]:
        merged.pop("runs")
    return merged


def completion_problems(task: dict, profile: dict) -> list[str]:
    """Why the task cannot be declared done yet."""
    result = task.get("result")
    if not result:
        return ["No result is recorded. Run task verify or task result."]
    problems = []
    reported = {item["check"]: item for item in result.get("checks", [])}
    for check in expected_checks(task, profile):
        outcome = reported.get(check["id"])
        if check["mandatory"]:
            if outcome is None:
                problems.append(f"{check['id']} is mandatory and has no result.")
            elif outcome["status"] != "passed":
                problems.append(f"{check['id']} is mandatory and {outcome['status']}.")
        elif outcome is None:
            problems.append(f"{check['id']} is not reported: pass, fail, skip or mark it not applicable.")
    for name, outcome in reported.items():
        if name.startswith("chaosfolk:") and outcome["status"] != "passed":
            reason = "gave no verdict" if outcome.get("chaosfolk_status") == "error" else "failed"
            problems.append(f"{name} {reason} in the last replay.")
    for criterion in result.get("criteria", []):
        if criterion["status"] != "met":
            problems.append(f"Criterion not met: {criterion['criterion']}")
    return problems


CHAOSFOLK_STATUSES = {"passed": "passed", "failed": "failed", "error": "failed"}


def chaosfolk_checks(root: Path, summary_path: Path, tool_version: str | None = None) -> dict:
    """Turn a ChaosFolk regression summary into check outcomes and a run record.

    ChaosFolk reports passed, failed (a product regression) or error (a run that gives no
    verdict). An error is recorded as a failed check, with its reason, never as a pass.
    """
    from .storage import read_json

    summary = read_json(summary_path)
    results = summary.get("results")
    if summary.get("schema_version") != 1 or not isinstance(results, list) or not results:
        raise ValueError(f"{summary_path} is not a ChaosFolk regression summary with results.")
    try:
        evidence = summary_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        evidence = str(summary_path)
    checks, outcomes = [], {}
    for item in results:
        if not isinstance(item, dict) or item.get("status") not in CHAOSFOLK_STATUSES or not isinstance(item.get("name"), str):
            raise ValueError(f"{summary_path} has a result without a name or a known status.")
        outcomes[item["name"]] = item["status"]
        entry = {"check": f"chaosfolk:{item['name']}", "status": CHAOSFOLK_STATUSES[item["status"]],
                 "evidence": evidence, "chaosfolk_status": item["status"]}
        if item.get("message"):
            entry["message"] = str(item["message"])[:500]
        checks.append(entry)
    run = {"tool": "chaosfolk", "summary": evidence, "outcomes": outcomes}
    if tool_version:
        run["version"] = tool_version
    return {"checks": checks, "run": run}


def compare_runs(task: dict, tool: str = "chaosfolk") -> dict | None:
    """Scenarios whose outcome changed between the last two runs of a tool."""
    runs = [run for run in task.get("result", {}).get("runs", []) if run["tool"] == tool]
    if len(runs) < 2:
        return None
    before, after = runs[-2]["outcomes"], runs[-1]["outcomes"]
    return {
        "before": runs[-2].get("at"),
        "after": runs[-1].get("at"),
        "changed": {name: [before.get(name), after.get(name)] for name in sorted(before.keys() | after.keys())
                    if before.get(name) != after.get(name)},
        "unchanged": sorted(name for name in before.keys() & after.keys() if before[name] == after[name]),
    }
