"""Record what was delivered for an approved task and the checks that prove it.

The expected checks come from the approved scope: every project check command is
mandatory, and every rule of the active packs must be reported. A rule with a machine
check is evaluated and recorded by task verify instead of being reported. A named piece of
evidence that a rule requires is mandatory: task result supplies it as a project path or
an https link. A project can make some rules mandatory with `required_rules`. A task is
done only when every mandatory check passed with evidence.
"""

import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from .catalog import rule_check
from .decisions import git_revision
from .project import rule_text
from .rule_checks import evaluate_check, validate_path
from .storage import write_text

RESULT_STATUSES = ("passed", "failed", "skipped", "not-applicable")
CRITERION_STATUSES = ("met", "not-met")
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
            name = f"{pack['id']}/{rule['id']}"
            _, verification = rule_text(rule)
            check = {"id": f"rule:{name}", "kind": "rule", "verification": verification,
                     "mandatory": pack["id"] in required or name in required}
            machine = rule_check(rule)
            if machine is not None:
                check.update(kind="machine", check=machine)
            checks.append(check)
            # A named evidence of an active pack is always due: the pack was accepted for the project.
            checks.extend(
                {"id": f"evidence:{name}/{item['id']}", "kind": "evidence", "title": item["title"],
                 "verification": f"Supply {item['title']} as a project path or an https link.", "mandatory": True}
                for item in rule.get("evidence", [])
            )
    return checks


def _run_command(root: Path, state: Path, task: dict, check: dict, command: str, timeout: int) -> dict:
    """Run one command in the project root and keep its log as evidence."""
    started = time.monotonic()
    try:
        # The commands come from the project profile or the project's own catalog, which it controls.
        completed = subprocess.run(
            command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        code, output = completed.returncode, completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as error:
        code, output = None, f"Timed out after {timeout} seconds.\n{error.stdout or ''}{error.stderr or ''}"
    log = state / "tasks" / f"{task['id']}-checks" / f"{check['id'].replace(':', '-').replace('/', '-')}.log"
    write_text(log, f"$ {command}\n{output[-LOG_TAIL:]}")
    return {
        "check": check["id"],
        "status": "passed" if code == 0 else "failed",
        "evidence": log.relative_to(root).as_posix(),
        "exit_code": code,
        "seconds": round(time.monotonic() - started, 1),
    }


def run_command_checks(root: Path, state: Path, task: dict, profile: dict, timeout: int = 1800) -> list[dict]:
    """Run the project's check commands and evaluate the rules' machine checks, with their evidence."""
    revision = git_revision(root)
    results = []
    for check in expected_checks(task, profile):
        if check["kind"] == "command":
            outcome = _run_command(root, state, task, check, check["command"], timeout)
        elif check["kind"] == "machine" and check["check"]["kind"] == "command":
            outcome = _run_command(root, state, task, check, check["check"]["command"], timeout)
        elif check["kind"] == "machine":
            outcome = {"check": check["id"], **evaluate_check(root, check["check"])}
        else:
            continue
        results.append({**outcome, **({"revision": revision["commit"]} if revision else {})})
    return results


def _evidence_reference(value: str, check_id: str) -> str:
    """A named evidence is an https link or a path inside the project."""
    if value.startswith("https://"):
        if not urlsplit(value).hostname or any(character.isspace() for character in value):
            raise ValueError(f"{check_id} evidence must be a valid https link.")
        return value
    try:
        validate_path(value, f"{check_id} evidence", pattern=False)
    except ValueError:
        raise ValueError(
            f"{check_id} evidence must be a project path such as docs/privacy/record.md or an https link."
        ) from None
    return value


def evidence_files_missing(root: Path, payload: dict, task: dict, profile: dict) -> list[str]:
    """Named evidences given as project paths that do not exist."""
    named = {check["id"] for check in expected_checks(task, profile) if check["kind"] == "evidence"}
    checks = payload.get("checks") if isinstance(payload, dict) else None
    missing = []
    # A malformed result is left to validate_result, which says what to fix.
    for item in checks if isinstance(checks, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("check"), str) or item["check"] not in named:
            continue
        if item.get("status") != "passed":
            continue
        value = _evidence_reference(_text(item.get("evidence"), f"{item['check']} evidence"), item["check"])
        if not value.startswith("https://") and not (root / value).exists():
            missing.append(f"{item['check']}: {value} does not exist in the project.")
    return missing


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain text.")
    return value.strip()


def _refusal(task: dict, message: str) -> ValueError:
    """A refused result names what is accepted and the template that shows it."""
    return ValueError(f"{message} Run openguildkit task result {task['id']} --template for the shape.")


def validate_result(task: dict, profile: dict, payload: dict, source: str = "report") -> dict:
    """A result names the delivered revision or PR, the acceptance criteria and each check's outcome.

    A report written by the agent (`source` "report") covers rules and criteria only: command
    checks and ChaosFolk replays are recorded by `task verify` ("verify"), which runs or reads them.
    """
    if task.get("status") not in ("approved", "done"):
        raise ValueError("Record results for an approved task.")
    fields = {"revision", "pull_request", "criteria", "checks"} | ({"run"} if source == "verify" else set())
    if not isinstance(payload, dict) or not payload.keys() <= fields:
        raise _refusal(task, "A result has revision or pull_request, criteria and checks.")
    if not payload.get("revision") and not payload.get("pull_request"):
        raise _refusal(task, "Name the delivered revision or pull request: revision (a commit SHA) or pull_request.")
    known = {check["id"]: check for check in expected_checks(task, profile)}
    try:
        result = {key: _text(payload[key], key) for key in ("revision", "pull_request") if payload.get(key)}
    except ValueError as error:
        raise _refusal(task, str(error)) from None
    if "run" in payload:
        result["runs"] = [payload["run"]]
    criteria = payload.get("criteria", [])
    if not isinstance(criteria, list):
        raise _refusal(task, "criteria must be a list of objects with criterion, status and evidence.")
    result["criteria"] = []
    for item in criteria:
        if not isinstance(item, dict) or item.keys() != {"criterion", "status", "evidence"}:
            raise _refusal(task, "Each criterion has criterion, status (met or not-met) and evidence.")
        if item["status"] not in CRITERION_STATUSES:
            raise _refusal(task, f"A criterion status is met or not-met, not {item['status']!r}.")
        try:
            result["criteria"].append({key: _text(item[key], f"criterion {key}") for key in item})
        except ValueError as error:
            raise _refusal(task, str(error)) from None
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        raise _refusal(task, "checks must be a list of objects with check and status.")
    result["checks"] = []
    for item in checks:
        if not isinstance(item, dict) or "check" not in item or "status" not in item:
            raise _refusal(task, f"Each check has check and status ({', '.join(RESULT_STATUSES)}).")
        try:
            _check_source(item["check"], known, source)
        except ValueError as error:
            raise _refusal(task, str(error)) from None
        if not isinstance(item["status"], str) or item["status"] not in RESULT_STATUSES:
            raise _refusal(task, f"A check status is one of {', '.join(RESULT_STATUSES)}, not {item['status']!r}.")
        if item["status"] == "passed" and item.get("exit_code", 0) != 0:
            raise ValueError(f"{item['check']} has exit_code {item['exit_code']}: a check that exits non-zero cannot pass.")
        entry = {"check": item["check"], "status": item["status"]}
        fields = ("evidence",) if item["status"] in ("passed", "failed") else ("reason", "owner")
        try:
            entry.update({field: _text(item.get(field), f"{item['check']} {field}") for field in fields})
        except ValueError as error:
            needed = " and ".join(fields)
            raise _refusal(task, f"{error} A {item['status']} check needs {needed}.") from None
        if known.get(item["check"], {}).get("kind") == "evidence" and "evidence" in entry:
            entry["evidence"] = _evidence_reference(entry["evidence"], item["check"])
        for key in ("exit_code", "seconds", "revision", "chaosfolk_status", "message"):
            if key in item:
                entry[key] = item[key]
        result["checks"].append(entry)
    return result


def _check_source(check_id: object, known: dict, source: str) -> None:
    """Command checks and ChaosFolk scenarios are recorded by task verify only, never from a report."""
    if not isinstance(check_id, str):
        raise ValueError("Each check names its ID as text. Run task checks for the expected IDs.")
    if check_id.startswith("chaosfolk:"):
        if source != "verify":
            raise ValueError(f"{check_id} comes from a replay: run task verify --chaosfolk SUMMARY.")
        return
    if check_id not in known:
        raise ValueError(f"Unknown check {check_id}. Run task checks for the expected IDs.")
    if known[check_id]["kind"] == "command" and source != "verify":
        raise ValueError(f"{check_id} is recorded by task verify, which runs the command. Run task verify.")
    if known[check_id]["kind"] == "machine" and source != "verify":
        raise ValueError(f"{check_id} is recorded by task verify, which evaluates its check. Run task verify.")


def merge_results(previous: dict | None, new: dict) -> dict:
    """Later reports replace earlier outcomes check by check; a new replay replaces every earlier scenario."""
    if not previous:
        return new
    replayed = any(run.get("tool") == "chaosfolk" for run in new.get("runs", []))
    checks = {item["check"]: item for item in previous.get("checks", [])
              if not (replayed and item["check"].startswith("chaosfolk:"))}
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
        if check["kind"] == "evidence" and (outcome is None or outcome["status"] != "passed"):
            problems.append(
                f"{check['id']} needs {check['title']}: supply a project path or an https link with task result."
            )
        elif check["mandatory"]:
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
    for name in missing_scenarios(task):
        problems.append(
            f"chaosfolk:{name} ran in the previous replay and is missing from the last one. "
            "Replay it, or replay again if it was removed on purpose."
        )
    if task.get("answers", {}).get("outcome") and not result.get("criteria"):
        problems.append("The task has an expected outcome: report at least one acceptance criterion with task result.")
    for criterion in result.get("criteria", []):
        if criterion["status"] != "met":
            problems.append(f"Criterion not met: {criterion['criterion']}")
    return problems


CHAOSFOLK_STATUSES = {"passed": "passed", "failed": "failed", "error": "failed"}
CHAOSFOLK_SEVERITY = {"passed": 0, "error": 1, "failed": 2}


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
    worst = {}
    for item in results:
        if not isinstance(item, dict) or item.get("status") not in CHAOSFOLK_STATUSES or not isinstance(item.get("name"), str):
            raise ValueError(f"{summary_path} has a result without a name or a known status.")
        # A scenario listed several times keeps its worst outcome: a failure is never hidden by a later pass.
        previous = worst.get(item["name"])
        if previous is None or CHAOSFOLK_SEVERITY[item["status"]] > CHAOSFOLK_SEVERITY[previous["status"]]:
            worst[item["name"]] = item
    checks, outcomes = [], {}
    for name, item in worst.items():
        outcomes[name] = item["status"]
        entry = {"check": f"chaosfolk:{name}", "status": CHAOSFOLK_STATUSES[item["status"]],
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


def missing_scenarios(task: dict) -> list[str]:
    """Scenarios of the previous ChaosFolk replay that the last replay no longer ran."""
    runs = [run for run in task.get("result", {}).get("runs", []) if run.get("tool") == "chaosfolk"]
    if len(runs) < 2:
        return []
    return sorted(runs[-2]["outcomes"].keys() - runs[-1]["outcomes"].keys())


def result_template(task: dict, profile: dict) -> dict:
    """A result file to fill: the acceptance criteria, every check a report covers and each named evidence."""
    outcome = task.get("answers", {}).get("outcome", "")
    checks = []
    for check in expected_checks(task, profile):
        if check["kind"] == "rule":
            checks.append({"check": check["id"], "mandatory": check["mandatory"], "verification": check["verification"],
                           "status": "", "evidence": "", "reason": "", "owner": ""})
        elif check["kind"] == "evidence":
            checks.append({"check": check["id"], "mandatory": True, "evidence_name": check["title"],
                           "verification": check["verification"], "status": "", "evidence": ""})
    return {
        "revision": "",
        "pull_request": "",
        "criteria": [{"criterion": outcome, "status": "", "evidence": ""}],
        "checks": checks,
    }
