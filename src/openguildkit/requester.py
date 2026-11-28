"""The requester of a task (`task new --requested-by`) and the profile option, off by default, that keeps the requester
from approving it, at `task decide` and in `guard --ci` (RFC #445).

`task new --requested-by NAME` records the requester. A person turns `separate-requester` on in the profile at a
terminal (profile_cli); then every new task names its requester, task decide refuses an approval by that person,
and guard --ci refuses a record whose approver is its requester when the base revision has the option on. Names are
compared without case or spaces. A signed approval compares the requester to the signer's principal too; in a project
with signed approvals, task new takes as requester only a principal of the allowed signers file, so that comparison is
exact (#475).

Entry: active, same_person, declared, approval_problem, brief_line, record_problem
Tests: tests/test_requester.py
"""

import fnmatch
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .doc_links import doc_link
from .errors import OgkError
from .records import Profile, Task

FIELD = "separate_requester"
# The scheduled watch opens a task for each confirmed alert: no person asked for it.
ALERT_REQUESTER = "openguildkit alerts"


def section() -> str:
    return doc_link("docs/workflow.md", "requester-and-approver")


def active(profile: Mapping[str, Any]) -> bool:
    return profile.get(FIELD) is True


def same_person(first: object, second: object) -> bool:
    """Whether two names are the same once case and spaces are set aside."""
    if not isinstance(first, str) or not isinstance(second, str):
        return False
    return "".join(first.split()).casefold() == "".join(second.split()).casefold() != ""


def principals(root: Path, relative: str) -> list[str]:
    """The principals of an allowed signers file (ssh-keygen ALLOWED SIGNERS: the first field of each line, comma
    separated, possibly patterns). Refused, naming the file, when it cannot be read."""
    try:
        text = (root / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise OgkError("OGK-TASK-109", f"The allowed signers file {relative} cannot be read ({getattr(error, 'strerror', None) or error}), "
                         "so the requester cannot be checked against its principals. Nothing was written.") from None
    found = []
    for line in text.splitlines():
        words = line.split()
        if words and not words[0].startswith("#"):
            found += [item for item in words[0].strip('"').split(",") if item and not item.startswith("!")]
    return list(dict.fromkeys(found))


def declared(name: str | None, profile: Profile, root: Path | None = None) -> str | None:
    """The requester task new records: the name given, on one line, and required when the option is on. With the
    option on in a project with signed approvals, it is a principal of the allowed signers file."""
    if name is None:
        if active(profile):
            raise OgkError("OGK-TASK-016", "This project separates who requests a task from who approves it (profile "
                             "separate-requester on): name the person who asked for the work with --requested-by NAME. "
                             "Nothing was written.")
        return None
    if not name.strip() or "\n" in name or "\r" in name:
        raise OgkError("OGK-TASK-017", "--requested-by takes the name of the person who asked for the work, on one line. "
                         "Nothing was written.")
    approval = profile.get("approval") or {}
    if root is not None and active(profile) and approval.get("mode") == "signed":
        relative = approval.get("allowed_signers", "")
        known = principals(root, relative)
        if not any(fnmatch.fnmatchcase(name.strip(), item) for item in known):
            raise OgkError("OGK-TASK-018", f"{name.strip()} is not a principal of {relative}: in a project with signed approvals, the "
                             f"requester is named as their key signs ({', '.join(known[:10]) or 'no principal'}), so "
                             f"that they cannot approve their own request under another name ({section()}). Nothing "
                             "was written.")
    return name.strip()


def _ask_another(task_id: str) -> str:
    return (f"Ask another person to approve it at their terminal: openguildkit task decide {task_id} --approve --by INITIALS "
            f"--reason WHY, or request changes ({section()}).")


def approval_problem(task: Task, profile: Profile, by: str, signer: str | None = None) -> str | None:
    """Why this approval is refused when the option is on: the task names no requester, or its requester approves it
    under the name given or as the signer."""
    if not active(profile):
        return None
    name = task.get("requested_by")
    if not isinstance(name, str):
        return (f"Task {task['id']} records no requester: it was opened before this project separated the requester "
                f'from the approver. Open the work again with openguildkit task new "BRIEF" --requested-by NAME, '
                "and have another person approve it.")
    if same_person(name, by):
        return f"{name} requested task {task['id']} and cannot approve it too. {_ask_another(task['id'])}"
    if same_person(name, signer):
        return (f"{name} requested task {task['id']} and signs this approval as {signer}: the requester cannot "
                f"approve it too. {_ask_another(task['id'])}")
    return None


def brief_line(task: Task, profile: Profile) -> list[str]:
    """The line the person reads before deciding, when the task names its requester."""
    name = task.get("requested_by")
    if not isinstance(name, str):
        return []
    return [f"Requested by {name}: another person approves it." if active(profile) else f"Requested by {name}."]


def record_problem(record: dict, new: bool) -> tuple[str, str] | None:
    """What guard --ci refuses in an exported record when the base revision has the option on: a new approval that
    names no requester, or an approval by its requester (by name or as signer). (code, message), or None."""
    decision = record["decision"]
    name = decision.get("payload", {}).get("requested_by")
    task_id = record["task"]
    if not isinstance(name, str):
        if not new:
            return None
        return "decision-requester-missing", (
            f"Task {task_id} records no requester, and the base revision separates the requester from the approver "
            f'(separate-requester on). Open the work with openguildkit task new "BRIEF" --requested-by NAME and have '
            "another person approve it.")
    approver = decision.get("by") if same_person(name, decision.get("by")) else (
        decision.get("signer") if same_person(name, decision.get("signer")) else None)
    if approver is None:
        return None
    return "decision-requester-approved", (
        f"{name} requested task {task_id} and approved it as {approver}, and the base revision separates the requester "
        f"from the approver (separate-requester on). Have another person approve it, then export it again.")
