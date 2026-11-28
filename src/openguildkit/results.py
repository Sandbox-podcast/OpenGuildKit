"""Record what was delivered for an approved task and the checks that prove it.

The expected checks come from the approved scope: every project check command is mandatory,
and every rule of the packs that concern the task (see relevance.py) must be reported; the
others are listed as not concerned, with the reason. A rule with a machine check is evaluated
and recorded by task verify instead of being reported. A named piece of evidence is a
document its owner provides, as a project path or an https link: the tool checks that a path
exists, never what it says. A project can make some rules mandatory with `required_rules`.
"""

import hashlib
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .catalog import recorded_value, rule_check
from .decisions import changed_paths_since, git_revision
from .project import STATE_DIR, rule_text
from .project_checks import failure_message
from .relevance import DECISION_REASON, evidence_owner, judge_rules, sensitive_area
from .rule_checks import evaluate_check, validate_path
from .sensitive import redact_data
from .storage import write_text
from .wording import plural
from .workflow import is_decision_task

RESULT_STATUSES = ("passed", "failed", "skipped", "not-applicable")
CRITERION_STATUSES = ("met", "not-met")
LOG_TAIL = 4000
# Seconds a check command may run before task verify records it as failed.
COMMAND_TIMEOUT = 1800


def _evidence_concerned(item: dict, answers: dict) -> tuple[bool, str]:
    """A named evidence with a condition on the task's data is asked only when the data meets it."""
    when = item.get("when", {}).get("data")
    data = answers.get("data")
    if not when or not data or data == "unsure" or data in when:
        return True, ""
    return False, f"it applies when the task's data is {'/'.join(when)}, and the task's data is {data}"


def expected_checks(task: dict, profile: dict, relevance: dict | None = None) -> list[dict]:
    """Every check of the approved scope, with an ID, and whether it concerns the task (and why not).

    Without a relevance judgement every check concerns the task. The project's check commands always do,
    except for a decision task: the approval records its process, and it delivers no implementation.
    """
    scope = task["consultation"]["scope"]
    every = bool((relevance or {}).get("every") or profile.get("ask_every_rule"))
    checks = [
        {"id": f"command:{index}", "kind": "command", "command": command, "mandatory": True,
         "concerned": True, "reason": ""}
        for index, command in enumerate(scope.get("checks", []), start=1)
    ]
    answers = scope.get("answers", {})
    # The same judgement as the board passes and the handoff (relevance.judge_rules), rule by rule.
    rules = judge_rules(task, profile, relevance)
    for pack in scope.get("packs", []):
        for rule in pack["rules"]:
            name = f"{pack['id']}/{rule['id']}"
            _, verification = rule_text(rule)
            judged = rules[name]
            mandatory, concerned, reason = judged["mandatory"], judged["concerned"], judged["reason"]
            check = {"id": f"rule:{name}", "kind": "rule", "pack": pack["id"], "verification": verification,
                     "mandatory": mandatory, "selected": judged["selected"],
                     "concerned": concerned, "reason": reason}
            machine = rule_check(rule)
            if machine is not None:
                check.update(kind="machine", check=machine)
            checks.append(check)
            for item in rule.get("evidence", []):
                applies, why = (True, "") if every else _evidence_concerned(item, answers)
                must = _must_supply(item, mandatory, scope)
                checks.append({
                    "id": f"evidence:{name}/{item['id']}", "kind": "evidence", "pack": pack["id"], "title": item["title"],
                    "verification": f"{item['title']}: passed with a project path or an https link.",
                    "must_supply": must, "owner_role": evidence_owner(pack["id"]),
                    "selected": bool(must) or judged["selected"],
                    "concerned": concerned and (applies or bool(must)),
                    "reason": (reason or why) if not (concerned and (applies or must)) else "",
                })
    if is_decision_task(task):
        for check in checks:
            if check["concerned"]:
                check.update(concerned=False, reason=DECISION_REASON)
    return checks


def asked_checks(task: dict, profile: dict, relevance: dict | None = None) -> list[dict]:
    """The checks that concern the task: the ones a result answers."""
    return [check for check in expected_checks(task, profile, relevance) if check["concerned"]]


def not_concerned(task: dict, profile: dict, relevance: dict | None = None) -> list[dict]:
    """What the task is not asked, one entry per pack (or per evidence), with the reason."""
    entries = {}
    for check in expected_checks(task, profile, relevance):
        if check["concerned"]:
            continue
        pack_wide = check["kind"] != "evidence" or check["reason"] == (relevance or {}).get("packs", {}).get(
            check.get("pack"), {}).get("reason")
        key = check.get("pack") if pack_wide and check.get("pack") else check["id"]
        entry = entries.setdefault(key, {("pack" if key == check.get("pack") else "check"): key,
                                         "reason": check["reason"], "checks": 0})
        entry["checks"] += 1
    return list(entries.values())


def _must_supply(item: dict, required: bool, scope: dict) -> str | None:
    """Why a named evidence must be supplied rather than declared not applicable, or None.

    It must be supplied when the project requires its rule, or when the evidence applies to
    the task's data answer.
    """
    if required:
        return "its rule or pack is listed in the profile's required_rules"
    data = scope.get("answers", {}).get("data")
    if data in item.get("when", {}).get("data", []):
        return f"the task's data is {data}"
    return None


def _run_command(root: Path, state: Path, task: dict, check: dict, command: str) -> dict:
    """Run one command in the project root and keep its log as evidence."""
    started = time.monotonic()
    try:
        # The commands come from the project profile or the project's own catalog, which it controls.
        completed = subprocess.run(
            command, shell=True, cwd=root, capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
        code, output = completed.returncode, completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as error:
        code, output = None, f"Timed out after {COMMAND_TIMEOUT} seconds.\n{error.stdout or ''}{error.stderr or ''}"
    log = state / "tasks" / f"{task['id']}-checks" / f"{check['id'].replace(':', '-').replace('/', '-')}.log"
    write_text(log, f"$ {command}\n{output[-LOG_TAIL:]}")
    evidence = log.relative_to(root).as_posix()
    outcome = {
        "check": check["id"],
        "status": "passed" if code == 0 else "failed",
        "evidence": evidence,
        "exit_code": code,
        "seconds": round(time.monotonic() - started, 1),
    }
    if code != 0:
        outcome["message"] = failure_message(code, output, evidence)
    return outcome


def _stamp(outcome: dict, revision: dict | None, *, journal: bytes | None = None) -> dict:
    """The fingerprint of what this check recorded, and the commit it ran against.

    journal is the log file task verify just wrote. A machine check has no log: its fingerprint is the evidence
    sentence, and a later reader does not look for a file.
    """
    stamped = dict(outcome)
    if journal is not None:
        stamped["sha256"] = hashlib.sha256(journal).hexdigest()
        stamped["journal"] = True
    elif isinstance(stamped.get("evidence"), str):
        stamped["sha256"] = hashlib.sha256(stamped["evidence"].encode("utf-8")).hexdigest()
    if revision:
        stamped["revision"] = {"commit": revision["commit"], "clean": not revision["dirty"]}
    return stamped


def run_command_checks(root: Path, state: Path, task: dict, profile: dict, relevance: dict | None = None,
                       only: set[str] | None = None) -> list[dict]:
    """Run the project's check commands and evaluate the machine checks of the rules that concern the task.

    only limits the run to these check IDs.
    """
    revision = git_revision(root)
    results = []
    for check in asked_checks(task, profile, relevance):
        if only is not None and check["id"] not in only:
            continue
        journal = None
        if check["kind"] == "command":
            outcome = _run_command(root, state, task, check, check["command"])
            journal = (root / outcome["evidence"]).read_bytes()
        elif check["kind"] == "machine" and check["check"]["kind"] == "command":
            outcome = _run_command(root, state, task, check, check["check"]["command"])
            journal = (root / outcome["evidence"]).read_bytes()
        elif check["kind"] == "machine":
            outcome = {"check": check["id"], **evaluate_check(root, check["check"])}
        else:
            continue
        results.append(_stamp(outcome, revision, journal=journal))
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


# Folders a folder's fingerprint leaves out: Git's own and the tool's records, which change with every command.
_UNLISTED = {".git", STATE_DIR}


def evidence_fingerprint(root: Path, value: str) -> str:
    """What task clear and task result record of an evidence: the SHA-256 of a file's bytes, of the list of a
    folder's files (their names, not their content), or "external" for an https link no one here can check."""
    if value.startswith("https://"):
        return "external"
    path = root / value
    if path.is_dir():
        names = sorted(item.relative_to(path).as_posix() for item in path.rglob("*")
                       if item.is_file() and not _UNLISTED & set(item.relative_to(path).parts))
        return "sha256:" + hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_state(root: Path, value: str, fingerprint: str | None) -> str:
    """unchanged, changed or missing since the fingerprint was recorded; external for a link; no fingerprint for an
    evidence recorded before fingerprints were."""
    if fingerprint is None:
        return "no fingerprint"
    if fingerprint == "external":
        return "external"
    if not (root / value).exists():
        return "missing"
    return "unchanged" if evidence_fingerprint(root, value) == fingerprint else "changed"


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain text.")
    return value.strip()


def _shape(task: dict) -> str:
    return f"Run openguildkit task result {task['id']} --template for the shape."


def _refusal(task: dict, message: str) -> ValueError:
    """A refused result names what is accepted and the template that shows it."""
    return ValueError(f"{message} {_shape(task)}")


class _Problems:
    """The defects of one result, each with the entry that holds it: one refusal lists them all (issue #490)."""

    def __init__(self, task: dict):
        self.task = task
        self.found: list[tuple[str, ValueError]] = []

    def add(self, path: str, error: ValueError) -> None:
        self.found.append((path, error))

    def run(self, path: str, function, *args, default=None):
        """The value of function(*args), or default with its refusal kept under the entry's path."""
        try:
            return function(*args)
        except ValueError as error:
            self.add(path, error)
            return default

    def raise_any(self) -> None:
        """A single defect keeps its own message; several are listed, then the template is named once."""
        if len(self.found) == 1:
            raise self.found[0][1]
        if self.found:
            lines = [f"{path}: {str(error).removesuffix(' ' + _shape(self.task))}" for path, error in self.found]
            raise ValueError(f"The result has {len(lines)} problems:\n- " + "\n- ".join(lines) + f"\n{_shape(self.task)}")


def decision_changes(root: Path, task: dict) -> list[str]:
    """Project changes since the decision's approved revision, excluding its exported records."""
    base = task.get("decision", {}).get("base_revision")
    if not is_decision_task(task) or not base:
        return []
    commit = base["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", commit):
        raise ValueError("The decision has no valid approved Git revision to compare.")
    return [path for path in changed_paths_since(root, commit)
            if not (path.startswith(f"{STATE_DIR}/decisions/") and path.endswith(".json"))]


def decision_revision_message(changed: list[str]) -> str:
    shown = ", ".join(changed[:3])
    if len(changed) > 3:
        shown += f" and {len(changed) - 3} more"
    return f"Project files changed since the approved revision ({shown}). Name the delivered revision or pull request."


# Fields of the result template that only explain it: a filled template is accepted as it is.
TEMPLATE_NOTES = {"instructions", "recorded_by_verify", "not_concerned"}
DONE_STATUSES = ("done", "done-with-reservations")


def _revision(task: dict, payload: dict, changed: list[str] | None) -> dict:
    """The delivered revision or pull request; a decision task that changed no project file needs neither, and one
    already recorded (the revision task verify reads from Git) stands when the report leaves it out."""
    if not payload.get("revision") and not payload.get("pull_request"):
        recorded = task.get("result") or {}
        if recorded.get("revision") or recorded.get("pull_request"):
            return {}
        if changed:
            raise _refusal(task, decision_revision_message(changed))
        if is_decision_task(task):
            return {}
        raise _refusal(task, "Name the delivered revision or pull request: revision (a commit SHA) or pull_request.")
    try:
        return {key: _text(payload[key], key) for key in ("revision", "pull_request") if payload.get(key)}
    except ValueError as error:
        raise _refusal(task, str(error)) from None


def _criterion(task: dict, item: object, known: dict, root: Path | None) -> dict:
    """A criterion is met or not, with its evidence; verified_by ties it to a verify command or a test file."""
    if not isinstance(item, dict) or not {"criterion", "status", "evidence"} <= item.keys() <= {
            "criterion", "status", "evidence", "verified_by"}:
        raise _refusal(task, "Each criterion has criterion, status (met or not-met), evidence and, optionally, "
                             "verified_by.")
    if item["status"] not in CRITERION_STATUSES:
        raise _refusal(task, f"A criterion status is met or not-met, not {item['status']!r}.")
    try:
        entry = {key: _text(item[key], f"criterion {key}") for key in ("criterion", "status", "evidence")}
    except ValueError as error:
        raise _refusal(task, str(error)) from None
    verified = item.get("verified_by")
    if verified:
        verified = verified.strip() if isinstance(verified, str) else ""
        if verified.startswith("command:"):
            if known.get(verified, {}).get("kind") != "command":
                raise _refusal(task, f"verified_by {verified} is not a check command of the task (see task checks).")
        else:
            try:
                validate_path(verified, "verified_by", pattern=False)
            except ValueError:
                raise _refusal(task, "verified_by names a check command such as command:1 or a test file of "
                                     "the project such as tests/test_access.py.") from None
            if root is not None and not (root / verified).is_file():
                raise _refusal(task, f"verified_by {verified} does not exist in the project.")
        entry["verified_by"] = verified
    return entry


def _pack_answer(task: dict, item: object, scope: set) -> dict | None:
    """One answer can cover every rule of a pack: passed or failed with evidence, skipped or not-applicable
    with a reason and the person who owns it. A pack entry left with an empty status is not answered yet."""
    if not isinstance(item, dict) or not {"pack", "status"} <= item.keys() <= {
            "pack", "status", "evidence", "reason", "owner", "rules"}:
        raise _refusal(task, "Each pack answer has pack, status, and evidence or reason and owner.")
    if item["status"] == "":
        return None
    if item["pack"] not in scope:
        raise _refusal(task, f"Pack {item['pack']!r} is not in the task's approved scope.")
    if item["status"] not in RESULT_STATUSES:
        raise _refusal(task, f"Pack {item['pack']} status is one of {', '.join(RESULT_STATUSES)}, "
                             f"not {item['status']!r}.")
    fields = ("evidence",) if item["status"] in ("passed", "failed") else ("reason", "owner")
    try:
        return {"pack": item["pack"], "status": item["status"],
                **{field: _text(item.get(field), f"{item['pack']} {field}") for field in fields}}
    except ValueError as error:
        raise _refusal(task, f"{error} A {item['status']} pack needs {' and '.join(fields)}.") from None


def validate_result(task: dict, profile: dict, payload: dict, source: str = "report", relevance: dict | None = None,
                    root: Path | None = None, *, changed: list[str] | None = None) -> dict:
    """A result names the delivered revision or PR, the acceptance criteria and each check's outcome.

    A report written by the agent (`source` "report") covers rules and criteria only: command
    checks and ChaosFolk replays are recorded by `task verify` ("verify"), which runs or reads them.
    A credential in a report is replaced with a placeholder, as in a brief. A blank status is a question left unanswered. A named evidence that cannot be recorded (a
    missing file, or not-applicable where it must be supplied) is held back with the reason, under
    "_held" (each with its check and message), and the rest is recorded: the task waits for that evidence.
    """
    if task.get("status") not in ("approved", *DONE_STATUSES):
        raise ValueError("Record results for an approved task.")
    if source == "report":
        payload = redact_data(payload)
    fields = {"revision", "pull_request", "criteria", "checks", "packs"} | TEMPLATE_NOTES
    if source == "verify":
        fields.add("run")
    if not isinstance(payload, dict) or not payload.keys() <= fields:
        raise _refusal(task, "A result has revision or pull_request, criteria, checks and, optionally, packs.")
    known = {check["id"]: check for check in expected_checks(task, profile, relevance)}
    problems = _Problems(task)
    result = problems.run("revision", _revision, task, payload, changed, default={})
    if "run" in payload:
        result["runs"] = [payload["run"]]
    lists = {}
    for name, shape in (("criteria", "criterion, status and evidence"), ("checks", "check and status"),
                        ("packs", "pack, status and its evidence or reason and owner")):
        lists[name] = payload.get(name, [])
        if not isinstance(lists[name], list):
            problems.add(name, _refusal(task, f"{name} must be a list of objects with {shape}."))
            lists[name] = []
    result["criteria"] = [
        entry for number, item in enumerate(lists["criteria"], 1)
        if not (isinstance(item, dict) and not item.get("status") and not item.get("evidence"))
        and (entry := problems.run(f"criteria[{number}]", _criterion, task, item, known, root)) is not None]
    scope = {pack["id"] for pack in task["consultation"]["scope"].get("packs", [])}
    result["packs"] = [
        entry for number, item in enumerate(lists["packs"], 1)
        if (entry := problems.run(f"packs[{number}]", _pack_answer, task, item, scope)) is not None]
    result["checks"], result["_held"] = [], []
    for number, item in enumerate(lists["checks"], 1):
        if isinstance(item, dict) and item.get("status") == "":
            continue
        found = problems.run(f"checks[{number}]", _check_entry, task, item, known, source, root)
        if found is None:
            continue
        entry, held = found
        if held:
            result["_held"].append({"check": entry["check"], "message": held})
        else:
            result["checks"].append(entry)
    problems.raise_any()
    if not result["packs"] and "packs" not in payload:
        result.pop("packs")
    return result


def _check_entry(task: dict, item: object, known: dict, source: str, root: Path | None) -> tuple[dict, str]:
    """One check outcome, or the reason a named evidence is held back."""
    if not isinstance(item, dict) or "check" not in item or "status" not in item:
        raise _refusal(task, f"Each check has check and status ({', '.join(RESULT_STATUSES)}).")
    try:
        _check_source(item["check"], known, source)
    except ValueError as error:
        raise _refusal(task, str(error)) from None
    check = known.get(item["check"], {})
    if not isinstance(item["status"], str) or item["status"] not in RESULT_STATUSES:
        accepted = ", ".join(RESULT_STATUSES)
        if check.get("kind") == "evidence":
            accepted = SUPPLY if check.get("must_supply") else "passed or not-applicable"
        raise _refusal(task, f"{item['check']} status is {accepted}, not {item['status']!r}.")
    if item["status"] == "passed" and item.get("exit_code", 0) != 0:
        raise ValueError(f"{item['check']} has exit_code {item['exit_code']}: a check that exits non-zero cannot pass.")
    entry = {"check": item["check"], "status": item["status"]}
    if item["status"] not in ("passed", "failed") and check.get("must_supply"):
        return entry, (f"{item['check']} must be supplied because {check['must_supply']}: ask "
                       f"{check['owner_role']} for {check['title']} (a project path or an https link). The agent "
                       "does not write it.")
    fields = ("evidence",) if item["status"] in ("passed", "failed") else ("reason", "owner")
    if check.get("kind") == "evidence" and item["status"] == "passed":
        fields = ("evidence", "owner")
    try:
        entry.update({field: _text(item.get(field), f"{item['check']} {field}") for field in fields})
    except ValueError as error:
        needed = " and ".join(fields)
        if check.get("kind") == "evidence" and item["status"] == "passed":
            needed += " (the person who provided or confirmed the document)"
        raise _refusal(task, f"{error} A {item['status']} {check.get('kind', 'check')} needs {needed}.") from None
    entry.update(recorded_value(task, item["check"], item))
    if check.get("kind") == "evidence" and "evidence" in entry:
        entry["evidence"] = _evidence_reference(entry["evidence"], item["check"])
        value = entry["evidence"]
        if root is not None and item["status"] == "passed" and not value.startswith("https://") and not (
                root / value).exists():
            return entry, f"{item['check']}: {value} does not exist in the project."
        if root is not None and item["status"] == "passed":
            entry["fingerprint"] = evidence_fingerprint(root, value)
    if item.get("cannot_run") is True and source == "verify" and check.get("kind") == "command":
        entry["cannot_run"] = True
    for key in ("exit_code", "seconds", "revision", "chaosfolk_status", "message", "sha256", "journal"):
        if key in item:
            entry[key] = item[key]
    return entry, ""


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


def merge_results(previous: dict | None, new: dict, source: str = "report") -> dict:
    """Later reports replace earlier outcomes check by check; a new replay replaces every earlier scenario."""
    new = {key: value for key, value in new.items() if key != "_held"}
    if not previous:
        return new
    replayed = any(run.get("tool") == "chaosfolk" for run in new.get("runs", []))
    checks = {item["check"]: item for item in previous.get("checks", [])
              if not (replayed and item["check"].startswith("chaosfolk:"))}
    checks.update({item["check"]: item for item in new.get("checks", [])})
    merged = {**previous, **{key: new[key] for key in ("revision", "pull_request") if key in new}}
    merged["criteria"] = new["criteria"] or previous.get("criteria", [])
    merged["checks"] = list(checks.values())
    # The pack answers are those of the latest report that gives any; a pack whose rules a later
    # report answers one by one loses its answer, so the result reads as it stands. What task verify
    # records is no such answer.
    answered = {item["check"].split(":", 1)[1].split("/", 1)[0] for item in new.get("checks", [])
                if source == "report" and item["check"].startswith("rule:")}
    packs = new["packs"] if "packs" in new else [item for item in previous.get("packs", []) if item["pack"] not in answered]
    merged.pop("packs", None)
    if packs:
        merged["packs"] = packs
    merged["runs"] = [*previous.get("runs", []), *new.get("runs", [])]
    if not merged["runs"]:
        merged.pop("runs")
    return merged


def declared_cannot_run(task: dict) -> dict:
    """The check commands a person declared unable to run in this environment, by check ID."""
    return {item["check"]: item for item in (task.get("result") or {}).get("checks", []) if item.get("cannot_run")}


def keep_declarations(task: dict, ran: list[dict]) -> tuple[list[dict], list[str]]:
    """A person's declaration that a command cannot run stays until the command passes or they withdraw it."""
    declared = declared_cannot_run(task)
    kept, notes = [], []
    for outcome in ran:
        declaration = declared.get(outcome["check"])
        if declaration and outcome["status"] != "passed":
            notes.append(f"{outcome['check']} still cannot run here: {declaration['owner']} declared it "
                         f"({declaration['reason']}). The declaration stays until the command passes or "
                         f"{declaration['owner']} withdraws it with task verify {task['id']} --withdraw "
                         f"{outcome['check']} --by INITIALS.")
            continue
        if declaration:
            notes.append(f"{outcome['check']} passes now: the declaration by {declaration['owner']} is replaced.")
        kept.append(outcome)
    return kept, notes


def _swept(check: dict, result: dict) -> dict | None:
    """The pack answer that covers this check, when one does: never a required rule or evidence, nor a
    check that task verify records."""
    if check.get("mandatory") or check.get("must_supply") or check["kind"] in ("command", "machine"):
        return None
    return next((item for item in result.get("packs", []) if item["pack"] == check.get("pack")), None)


def outcomes(task: dict, profile: dict, relevance: dict | None = None) -> dict:
    """Each asked check's outcome: reported one by one, or covered by a pack answer."""
    result = task.get("result") or {}
    reported = {item["check"]: item for item in result.get("checks", [])}
    for check in asked_checks(task, profile, relevance):
        if check["id"] not in reported:
            pack = _swept(check, result)
            if pack:
                reported[check["id"]] = {**{key: value for key, value in pack.items() if key != "pack"},
                                         "check": check["id"], "via_pack": pack["pack"]}
    return reported


def deferred_evidence(task: dict) -> dict:
    return {item["check"]: item for item in (task.get("result") or {}).get("deferred", [])}


def waiting_evidence(task: dict, profile: dict, relevance: dict | None = None) -> list[dict]:
    """Named evidence that must be supplied and is not yet, with who provides it; deferred ones excluded."""
    reported, deferred = outcomes(task, profile, relevance), deferred_evidence(task)
    return [
        {"check": check["id"], "title": check["title"], "owner": check["owner_role"], "why": check["must_supply"]}
        for check in asked_checks(task, profile, relevance)
        if check["kind"] == "evidence" and check["must_supply"] and check["id"] not in deferred
        and reported.get(check["id"], {}).get("status") != "passed"
    ]


def _evidence_problems(check: dict, outcome: dict | None) -> list[str]:
    """A named evidence blocks completion until it is answered, or supplied when it must be."""
    supply = f"supply {check['title']} as a project path or an https link"
    if outcome is None:
        if check["must_supply"]:
            return [f"{check['id']} waits for {check['owner_role']}: {supply} (it must be supplied because "
                    f"{check['must_supply']}), or hand it to a follow-up task with task complete --defer."]
        return [f"{check['id']} has no answer: {supply}, or declare it not-applicable with a reason and an owner."]
    if outcome["status"] == "passed" or (outcome["status"] == "not-applicable" and not check["must_supply"]):
        return []
    return [f"{check['id']} is {outcome['status']}: {supply}."]


def answers_to_report(task: dict, profile: dict, relevance: dict | None = None) -> list[str]:
    """The rules and named evidence a result file answers, when no report has answered any of them yet.

    task verify counts them instead of listing them: the result template lists them with the answers each accepts.
    A mandatory rule stays listed by its own line. Empty once a report answered a rule, a pack or a named evidence.
    """
    result = task.get("result") or {}
    asked = asked_checks(task, profile, relevance)
    kinds = {check["id"]: check["kind"] for check in asked}
    answered = any(kinds.get(item["check"]) in ("rule", "evidence") for item in result.get("checks", []))
    if answered or result.get("packs"):
        return []
    deferred = deferred_evidence(task)
    return [check["id"] for check in asked
            if (check["kind"] == "rule" and not check["mandatory"])
            or (check["kind"] == "evidence" and check["id"] not in deferred)]


def set_aside_rules(task: dict, profile: dict, relevance: dict | None = None) -> list[str]:
    """The data protection, security or AI rules and evidence that the task's answers select (GDPR for personal data,
    for example) and that were declared not applicable one by one: the person who closes the task confirms each at a
    terminal. A pack declared not applicable as a whole is an open point already."""
    checks = {check["id"]: check for check in asked_checks(task, profile, relevance)}
    lines = []
    for item in outcomes(task, profile, relevance).values():
        check = checks.get(item["check"])
        area = sensitive_area(check.get("pack", "")) if check else None
        if area and check.get("selected") and item["status"] == "not-applicable" and not item.get("via_pack"):
            lines.append(f"{item['check']} is not-applicable: {item.get('reason', '')} ({item.get('owner', '')}) [{area}]")
    return lines


def _journal_problems(task: dict, root: Path | None) -> list[str]:
    """A command journal whose bytes no longer match the hash task verify recorded.

    A check recorded before journals were hashed has no sha256: it stays readable and is not failed.
    """
    if root is None:
        return []
    problems = []
    for item in (task.get("result") or {}).get("checks", []):
        if item.get("journal") is not True or not isinstance(item.get("sha256"), str):
            continue
        evidence = item.get("evidence")
        name = item.get("check", "a check")
        if not isinstance(evidence, str):
            continue
        path = root / evidence
        if not path.is_file():
            problems.append(f"{name}: the journal {evidence} is missing, so its sha256 cannot be confirmed.")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            problems.append(f"{name}: the journal {evidence} no longer matches the recorded sha256.")
    return problems


def completion_problems(task: dict, profile: dict, relevance: dict | None = None, *,
                        changed: list[str] | None = None, root: Path | None = None) -> list[str]:
    """Why the task cannot be declared done yet: only the checks that concern it count.

    A decision task needs no result unless its answers name an outcome; when it changed project
    files, it names the delivered revision or pull request.
    """
    decision = is_decision_task(task)
    result = task.get("result") or {}
    if not decision and not result:
        return ["No result is recorded. Run task verify or task result."]
    problems = _journal_problems(task, root)
    if changed and not (result.get("revision") or result.get("pull_request")):
        problems.append(decision_revision_message(changed))
    reported, deferred = outcomes(task, profile, relevance), deferred_evidence(task)
    for check in asked_checks(task, profile, relevance):
        outcome = reported.get(check["id"])
        if check["kind"] == "evidence":
            if check["id"] not in deferred:
                problems.extend(_evidence_problems(check, outcome))
        elif check["mandatory"]:
            if outcome is None:
                problems.append(f"{check['id']} is mandatory and has no result.")
            elif outcome["status"] != "passed" and not outcome.get("cannot_run"):
                cause = f": {outcome['message']}" if outcome.get("message") else "."
                problems.append(f"{check['id']} is mandatory and {outcome['status']}{cause}")
        elif outcome is None:
            problems.append(f"{check['id']} is not reported: pass, fail, skip or mark it not applicable.")
    for name, outcome in reported.items():
        if name.startswith("chaosfolk:") and outcome["status"] != "passed":
            reason = "gave no verdict" if outcome.get("chaosfolk_status") == "error" else "failed"
            problems.append(f"{name} {reason} in the last replay.")
    for name in (() if decision else missing_scenarios(task)):
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


# File names and suffixes that cannot be a register, a decision or a policy: configuration, code, images.
OTHER_TYPE_NAMES = {"dockerfile", "makefile", "package.json", "package-lock.json", "pyproject.toml", "requirements.txt",
                    "docker-compose.yml", "compose.yaml", ".env", "readme.md", "agents.md", "claude.md"}
OTHER_TYPE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".php", ".cs", ".sh", ".sql",
                       ".css", ".html", ".toml", ".yml", ".yaml", ".ini", ".cfg", ".lock", ".png", ".jpg", ".jpeg",
                       ".gif", ".svg", ".webp", ".log"}
NOT_RUN = re.compile(r"\b(not|never|non|pas|without)\s+(been\s+)?(executed|run|ran|exécutée?s?|lancée?s?)\b"
                     r"|read from (the )?code|lu dans le code", re.IGNORECASE)


def _evidence_warnings(passed: list[dict]) -> list[str]:
    """Cheap signals that a named evidence is not the document it claims to be. Its content is never read."""
    warnings = []
    by_file: dict[str, list[str]] = {}
    for item in passed:
        by_file.setdefault(item["evidence"].casefold(), []).append(item["check"])
        name = PurePosixPath(item["evidence"]).name.casefold()
        if not item["evidence"].startswith("https://") and (
                name in OTHER_TYPE_NAMES or PurePosixPath(name).suffix in OTHER_TYPE_SUFFIXES):
            warnings.append(f"{item['check']} cites {item['evidence']}, which looks like configuration, code or an "
                            "image rather than the named document.")
    for value, checks in by_file.items():
        if len(checks) > 1:
            warnings.append(f"The same file is cited for {len(checks)} different named evidences: {', '.join(checks)}.")
    return warnings


# One evidence item cited for passed rules of this many packs or more is named, as one evidence item behind every
# finding of a board is in the review: a unit test rarely proves accessibility, payments and consumer law at once.
SHARED_EVIDENCE_PACKS = 3


def _shared_rule_evidence(checks: dict, reported: dict) -> list[str]:
    """Evidence items cited for passed rules of several packs, each named once with its rules and packs."""
    cited: dict[str, dict] = {}
    for item in reported.values():
        check = checks.get(item["check"], {})
        if check.get("kind") != "rule" or item["status"] != "passed" or not item.get("evidence"):
            continue
        entry = cited.setdefault(item["evidence"].casefold(),
                                  {"evidence": item["evidence"], "rules": [], "packs": set()})
        entry["rules"].append(item["check"])
        entry["packs"].add(check.get("pack") or item.get("via_pack") or "")
    warnings = []
    for entry in cited.values():
        packs = sorted(pack for pack in entry["packs"] if pack)
        if len(packs) >= SHARED_EVIDENCE_PACKS:
            shown = ", ".join(packs[:6]) + (f" and {len(packs) - 6} more" if len(packs) > 6 else "")
            warnings.append(f"The same evidence {entry['evidence']} is cited for {len(entry['rules'])} passed rules "
                            f"of {len(packs)} packs ({shown}). Cite what shows each rule holds.")
    return warnings


def result_warnings(task: dict, profile: dict, relevance: dict | None = None) -> list[str]:
    """What a reviewer should look at twice: answers that sweep rules the task's answers select, and weak evidence."""
    result = task.get("result") or {}
    checks = {check["id"]: check for check in asked_checks(task, profile, relevance)}
    reported = outcomes(task, profile, relevance)
    warnings = []
    selected_packs = {check["pack"] for check in checks.values() if check.get("selected")}
    sweeping = {item.get("via_pack") for item in reported.values()}
    for item in result.get("packs", []):
        if item["status"] == "not-applicable" and item["pack"] in selected_packs and item["pack"] in sweeping:
            warnings.append(f"Pack {item['pack']} was declared not applicable as a whole by {item['owner']}, although "
                            "the task's answers select it. Check each of its rules.")
    not_applicable = [item for item in reported.values() if item["status"] == "not-applicable" and "via_pack" not in item]
    reasons: dict[str, list[str]] = {}
    for item in not_applicable:
        reasons.setdefault(" ".join(item.get("reason", "").casefold().split()), []).append(item["check"])
    for reason, names in reasons.items():
        selected = [name for name in names if checks.get(name, {}).get("selected")]
        if selected and len(names) > 1:
            shown = ", ".join(selected[:5]) + (f" and {len(selected) - 5} more" if len(selected) > 5 else "")
            warnings.append(f"{shown} {'is' if len(selected) == 1 else 'are'} selected by the task's "
                            f"answers yet declared not applicable with the same reason as {plural(len(names) - 1, 'other answer')}. "
                            "Give the reason that applies to each.")
    passed = [item for item in result.get("checks", []) if checks.get(item["check"], {}).get("kind") == "evidence"
              and item["status"] == "passed"]
    warnings += _evidence_warnings(passed)
    warnings += _shared_rule_evidence(checks, reported)
    statuses = {item["check"]: item["status"] for item in result.get("checks", [])}
    for criterion in result.get("criteria", []):
        if criterion["status"] == "met" and NOT_RUN.search(criterion["evidence"]):
            warnings.append(f"Criterion \"{criterion['criterion']}\" is met on evidence that says it was not run.")
        verified = criterion.get("verified_by", "")
        if criterion["status"] == "met" and verified.startswith("command:") and statuses.get(verified) != "passed":
            warnings.append(f"Criterion \"{criterion['criterion']}\" is met, but {verified} has not passed in task verify.")
    return warnings


def verification_of(criterion: dict, result: dict) -> str:
    """What a met criterion rests on: its check or test, a check that has not passed, or a declaration only."""
    verified = criterion.get("verified_by")
    if not verified:
        return "declared only"
    statuses = {item["check"]: item["status"] for item in result.get("checks", [])}
    if verified.startswith("command:") and statuses.get(verified) != "passed":
        return f"{verified}, which has not passed"
    return verified


def criteria_summary(result: dict) -> str | None:
    """How many met criteria are tied to a check or a test that holds, to one that has not passed, or only declared."""
    met = [item for item in result.get("criteria", []) if item["status"] == "met"]
    if not met:
        return None
    kinds = [verification_of(item, result) for item in met]
    unproven = sum(kind.endswith("which has not passed") for kind in kinds)
    declared = [item["criterion"] for item, kind in zip(met, kinds) if kind == "declared only"]
    verified = len(met) - unproven - len(declared)
    text = f"Criteria met: {verified} tied to a check or a test"
    if unproven:
        text += f", {unproven} tied to a check that has not passed"
    text += f", {len(declared)} declared only"
    return text + (f" ({'; '.join(declared)})." if declared else ".")


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


def compare_runs(task: dict) -> dict | None:
    """Scenarios whose outcome changed between the last two ChaosFolk replays."""
    runs = [run for run in task.get("result", {}).get("runs", []) if run["tool"] == "chaosfolk"]
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


# The requirement of a named evidence, written with the statuses the result file accepts.
SUPPLY = "passed"
SUPPLY_OR_NOT_APPLICABLE = "passed-or-not-applicable"
TEMPLATE_INSTRUCTIONS = (
    "Fill status for each entry; leave an entry's status empty to answer it later. A criterion is met or not-met, "
    "with evidence. A rule is passed, failed, skipped or not-applicable. Each entry of packs answers every rule it "
    "lists at once (passed or failed with evidence, skipped or not-applicable with a reason and an owner); to answer "
    "one of its rules apart, add that rule to checks. Any other pack that does not apply can be answered once in packs too: "
    '{"pack": ID, "status": "not-applicable", "reason": ..., "owner": ...}. The owner of a not-applicable or skipped '
    "answer is the person who decides it, and the reason is theirs: the agent proposes, the person confirms, and the "
    "agent never writes a name the person did not give. A named evidence with requirement passed is a document its "
    "owner provides (owner_role): ask them for it, never write it to pass the check. OpenGuildKit checks that a "
    "project path exists; it does not read the document. A criterion can name verified_by: a check command such as "
    "command:1 or a test file."
)


def _evidence_answer(check: dict) -> str:
    """How to answer a named evidence in the result file, with the statuses it accepts."""
    supplied = (f'Status "passed" once the document exists: evidence its project path or https link, and owner '
                f"the person who provided or confirmed it ({check['owner_role']}).")
    if check["must_supply"]:
        return f"{supplied} Only passed is accepted, because {check['must_supply']}."
    return f'{supplied} Or status "not-applicable", with a reason and an owner, when it does not apply to this task.'


def _pack_form(task: dict, asked: list[dict]) -> set[str]:
    """Packs the template answers once: none of their rules is required, records a value or is selected by the
    task's data or concerns, and none is a data protection, security or AI rule."""
    packs: dict[str, bool] = {}
    for check in asked:
        if check["kind"] != "rule" or not check.get("pack"):
            continue
        whole = not (check["mandatory"] or check["selected"] or sensitive_area(check["pack"])
                     or recorded_value(task, check["id"]))
        packs[check["pack"]] = packs.get(check["pack"], True) and whole
    return {pack for pack, whole in packs.items() if whole}


def result_template(task: dict, profile: dict, relevance: dict | None = None, *,
                    changed: list[str] | None = None) -> dict:
    """A result file to fill: the criteria, every check that concerns the task and a report covers, and what is not asked.

    The checks that task verify records and the packs that do not concern the task are listed in
    the file itself, so standard output carries only JSON.
    """
    outcome = task.get("answers", {}).get("outcome", "")
    # The revision task verify read from Git, or an earlier report's, is filled in: the report need not name it again.
    delivered = {key: (task.get("result") or {}).get(key, "") for key in ("revision", "pull_request")}
    if is_decision_task(task):
        template = {"criteria": [{"criterion": outcome, "status": "", "evidence": ""}] if outcome else [],
                    "not_concerned": not_concerned(task, profile, relevance)}
        return {**delivered, **template} if changed else template
    asked = asked_checks(task, profile, relevance)
    by_pack = _pack_form(task, asked)
    checks, verify, packs = [], [], {}
    for check in asked:
        if check.get("pack") in by_pack and check["kind"] == "rule":
            packs.setdefault(check["pack"], {"pack": check["pack"], "status": "", "evidence": "", "reason": "",
                                             "owner": "", "rules": {}})["rules"][check["id"]] = check["verification"]
        elif check["kind"] == "rule":
            entry = {"check": check["id"], "verification": check["verification"],
                     "status": "", "evidence": "", "reason": "", "owner": "", **recorded_value(task, check["id"])}
            if check["mandatory"]:
                entry["required"] = "passed with evidence (the profile's required_rules)"
            checks.append(entry)
        elif check["kind"] == "evidence":
            checks.append({
                "check": check["id"], "evidence_name": check["title"], "owner_role": check["owner_role"],
                "requirement": SUPPLY if check["must_supply"] else SUPPLY_OR_NOT_APPLICABLE,
                "answer": _evidence_answer(check), "status": "", "evidence": "", "reason": "", "owner": "",
            })
        else:
            verify.append({"check": check["id"], "what": check.get("command") or check["verification"]})
    return {
        "instructions": TEMPLATE_INSTRUCTIONS,
        **delivered,
        "criteria": [{"criterion": outcome, "status": "", "evidence": "", "verified_by": ""}],
        "checks": checks,
        "packs": list(packs.values()),
        "recorded_by_verify": verify,
        "not_concerned": not_concerned(task, profile, relevance),
    }
