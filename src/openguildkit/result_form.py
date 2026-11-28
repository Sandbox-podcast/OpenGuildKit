"""The result template a person fills for an approved task, and the check of the result they return."""

from pathlib import Path
from urllib.parse import urlsplit

from .approval_check import DONE_STATUSES
from .board_entries import required_text
from .catalog_queries import recorded_value
from .relevance import sensitive_area
from .results import asked_checks, decision_revision_message, evidence_fingerprint, expected_checks, not_concerned
from .rule_checks import validate_path
from .sensitive import redact_data
from .workflow import is_decision_task

RESULT_STATUSES = ("passed", "failed", "skipped", "not-applicable")
CRITERION_STATUSES = ("met", "not-met")


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


# Fields of the result template that only explain it: a filled template is accepted as it is.
TEMPLATE_NOTES = {"instructions", "recorded_by_verify", "not_concerned"}


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
        return {key: required_text(payload[key], key) for key in ("revision", "pull_request") if payload.get(key)}
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
        entry = {key: required_text(item[key], f"criterion {key}") for key in ("criterion", "status", "evidence")}
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
                **{field: required_text(item.get(field), f"{item['pack']} {field}") for field in fields}}
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
        entry.update({field: required_text(item.get(field), f"{item['check']} {field}") for field in fields})
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
