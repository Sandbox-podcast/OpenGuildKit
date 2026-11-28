"""Bind an approval to the consultation, the review, the rules in force and the project revision.

Every approval carries a seal: a SHA-256 over what was approved. The handoff refuses a
decision whose seal no longer matches the task record. A project can also require a
signed approval: the approver signs the decision with an SSH key listed in an
allowed-signers file kept in the repository, and the CLI verifies it locally. The key may be a
certificate of an authority (a `cert-authority` line); an approver who adds signed_at to the
payload has the approval, once recorded, verified at that time, so that an expiry later on voids none.
"""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import clock, git
from .storage import read_json

NAMESPACE = "openguildkit-decision"


def _sha256(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def git_revision(root: Path) -> dict | None:
    """The commit the project is at, and whether files differ from it. None outside a Git repository."""
    head = git.text(root, "rev-parse", "--verify", "HEAD")
    if head is None:
        return None
    status = git.text(root, "status", "--porcelain", "--untracked-files=no")
    return {"commit": head.strip(), "dirty": bool(status and status.strip())}


def changed_paths_since(root: Path, commit: str) -> list[str]:
    """Changes to tracked and staged files between an approved commit and the working tree."""
    change = git.names(root, "diff", "--name-only", "--no-renames", commit, "--")
    if change is None:
        raise ValueError("Could not compare the project files with the approved Git revision.")
    return change


def exported_boards(review: dict) -> list[dict]:
    """Each board's verdict and recommendation, as an exported record shows them."""
    return [
        {"id": entry["id"], "verdict": entry.get("challenge", {}).get("verdict"),
         "recommendation": entry["recommendation"]}
        for entry in review.get("boards", [])
    ]


def exported_rounds(task: dict) -> list[dict]:
    """The earlier rounds as an exported record shows them: who decided what and why, and a revised brief."""
    return [
        {"consultation_id": previous.get("consultation", {}).get("id"),
         "summary": previous.get("review", {}).get("summary"),
         "boards": exported_boards(previous.get("review", {})),
         "decision": {key: value for key, value in previous.get("decision", {}).items()
                      if key in ("outcome", "by", "reason", "at")},
         # The brief of that round when it was revised since, and why an approval was reopened.
         **{key: previous[key] for key in ("brief", "reopened")
            if key in previous and (key != "brief" or previous["brief"] != task["brief"])}}
        for previous in task["rounds"]
    ]


def shared_digest(brief: str, summary: str, boards: list[dict], rounds: list[dict]) -> str:
    """The digest of what an exported record shows of the approval; the approval's seal covers it."""
    return _sha256({"brief": brief, "summary": summary, "boards": boards, "rounds": rounds})


def task_shared_digest(task: dict) -> str:
    return shared_digest(task["brief"], task["review"]["summary"], exported_boards(task["review"]), exported_rounds(task))


def record_digest(record: dict) -> str:
    """The digest of an exported record, without the field that holds it."""
    return _sha256({key: value for key, value in record.items() if key != "record_sha256"})


# Approvals sealed from version 2 on also cover what their exported record shows; from version 3 on, the payload a
# signer reads carries the brief and the review summary in clear. Earlier ones verify as before.
PAYLOAD_VERSION = 3
PAYLOAD_VERSIONS = (3, 2, 1)


SIGNED_AT_FORMAT = "YYYY-MM-DDTHH:MM:SSZ"
_SIGNED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
# The clocks of two machines differ by seconds: a signature this far ahead of the clock still counts as made.
CLOCK_SKEW = timedelta(minutes=5)


def signing_time(value: str | None, *, now_ok: bool = False) -> str | None:
    """The time an approver states they signed at, checked: UTC written YYYY-MM-DDTHH:MM:SSZ and not in the future.
    "now" is this instant when now_ok. None when none is given."""
    if value is None:
        return None
    current = clock.real_now()
    if now_ok and value == "now":
        return current.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not _SIGNED_AT.fullmatch(value):
        raise ValueError(f"--signed-at is a UTC time written {SIGNED_AT_FORMAT}, such as 2026-11-27T10:15:30Z. "
                         "Nothing was written.")
    if datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=current.tzinfo) > current + CLOCK_SKEW:
        raise ValueError(f"--signed-at {value} is in the future: the signature cannot have been made yet.")
    return value


def signing_time_of(timestamp: str | None) -> str | None:
    """The date of a decision, as clock.real_timestamp writes it, written as signed_at; None when it cannot be read."""
    if not isinstance(timestamp, str):
        return None
    try:
        moment = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment.tzinfo else None


def date_moved(decision: dict, payload: dict) -> bool:
    """Whether a local approval shows a decision date other than the one its seal covers. With the audit log on, a local
    approval carries signed_at, the time of its decision (#454): `at` is then that time to the second. A signed approval
    carries the time its signer gave, which `at` may follow by days."""
    return bool(payload.get("signed_at")) and "signature" not in decision \
        and signing_time_of(decision.get("at")) != payload["signed_at"]


def verify_time(payload: dict) -> str | None:
    """The time a payload says it was signed at, as `ssh-keygen -O verify-time=` writes it; None when it says none."""
    moment = payload.get("signed_at")
    if moment is None:
        return None
    if not isinstance(moment, str) or not _SIGNED_AT.fullmatch(moment):
        raise ValueError(f"signed_at must be a UTC time written {SIGNED_AT_FORMAT}.")
    return re.sub(r"[-:T]", "", moment)


def decision_payload(task: dict, by: str, reason: str, base_revision: dict | None, version: int = PAYLOAD_VERSION,
                     separate: bool = False, signed_at: str | None = None) -> dict:
    """What an approval covers. The approver signs exactly this object in signed mode. separate says that the profile
    separated the requester from the approver when it was given (requester.py). signed_at, when the approver gives
    it, is the time they sign at: the recorded approval is then verified at that time (verify_recorded_signature)."""
    payload = {
        "task": task["id"],
        "outcome": "approved",
        "consultation_id": task["consultation"]["id"],
        "scope_sha256": _sha256(task["consultation"]["scope"]),
        "review_sha256": _sha256(task["review"]),
        "profile_fingerprint": task["profile_fingerprint"],
        "blocker_resolutions_sha256": _sha256(task.get("blocker_resolutions", {})),
        "by": by.strip(),
        "reason": reason.strip(),
        "base_revision": base_revision,
    }
    # Boards added or removed at consultation are part of what the person approves: the
    # approval names each protected board whose removal they confirmed.
    adjustments = task["consultation"].get("adjustments")
    if adjustments:
        payload["adjustments_sha256"] = _sha256(adjustments)
        confirmed = sorted(item["board"] for item in adjustments if item.get("confirmation") == "pending")
        if confirmed:
            payload["confirmed_removals"] = confirmed
    # The short lane and its paths are part of what the person approves, and the signer reads them in clear.
    if task.get("lane"):
        payload.update(lane=task["lane"], paths=task["paths"])
    # Who asked for the work, and whether the requester was kept from approving: only when named or on, so that an
    # approval without them covers exactly what it covered before.
    if isinstance(task.get("requested_by"), str):
        payload["requested_by"] = task["requested_by"]
    if separate:
        payload["separate_requester"] = True
    if signed_at:
        payload["signed_at"] = signed_at
    if version >= 2:
        payload["shared_sha256"] = task_shared_digest(task)
    if version >= 3:
        payload.update(brief=task["brief"], summary=task["review"]["summary"])
    return payload


def payload_text(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def seal(payload: dict) -> str:
    return _sha256(payload)


def approval_policy(profile: dict) -> dict:
    return profile.get("approval") or {"mode": "local"}


def committed_signers(root: Path, relative: str) -> str:
    """The allowed signers file as Git holds it at HEAD, so that a key added to the working copy signs nothing.

    Refused, naming the file, outside a Git repository, when Git does not track the file, or when the working copy
    differs from HEAD: who may approve changes through a commit a person reviews.
    """
    shown = f"The allowed signers file {relative}"
    retry = "Have the person review and commit it, then sign again."
    inside = git.text(root, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.strip() != "true":
        raise ValueError(f"{shown} is verified as Git holds it at HEAD, and the project is not in a Git repository. "
                         "Signed approvals need the project and this file in Git.")
    tracked = git.text(root, "ls-files", "--error-unmatch", "--", relative)
    committed = git.text(root, "show", f"HEAD:./{relative}")
    if tracked is None or committed is None:
        raise ValueError(f"{shown} is not committed: a signature is verified against its version at HEAD. {retry}")
    if git.text(root, "diff", "--quiet", "HEAD", "--", relative) is None:
        raise ValueError(f"{shown} differs from its version at HEAD (git diff HEAD -- {relative}): a signature is "
                         f"verified against the committed file, never against a working copy. {retry}")
    return committed


class SignerNotCurrent(ValueError):
    """The signer is not among the current approvers, or the current signers file does not verify their signature."""


def verify_signature(root: Path, policy: dict, payload: dict, signature: str, signer: str, *,
                     committed: bool = True, at_signing: bool = False) -> None:
    """Check an SSH signature of the decision against the project's allowed signers.

    The signers come from HEAD (committed_signers). committed=False reads the file as it is in root, for a copy
    already extracted from a Git revision, such as the base revision CI reads. The key or certificate is judged at
    the current time, or with at_signing at the signed_at of the payload when it has one.
    """
    if signer not in policy["approvers"]:
        raise SignerNotCurrent(f"{signer} is not an approver for this project. "
                               f"Approvers: {', '.join(policy['approvers'])}.")
    allowed = (root / policy["allowed_signers"]).resolve()
    if not allowed.is_file() or root.resolve() not in allowed.parents:
        raise ValueError(f"The allowed signers file {policy['allowed_signers']} is missing from the project.")
    signers = committed_signers(root, Path(policy["allowed_signers"]).as_posix()) if committed else None
    _ssh_verify(allowed.read_text(encoding="utf-8") if signers is None else signers, payload, signature, signer,
                verify_time(payload) if at_signing else None)


def _ssh_verify(signers: str, payload: dict, signature: str, signer: str, at: str | None = None) -> None:
    """Verify the signature of the payload for signer, against the text of an allowed signers file, at the time `at`
    (ssh-keygen's YYYYMMDDHHMMSSZ) instead of now when it is given."""
    if shutil.which("ssh-keygen") is None:
        raise ValueError("Verifying a signed approval needs ssh-keygen (OpenSSH 8.1 or later).")
    with tempfile.TemporaryDirectory() as directory:
        signature_path = Path(directory) / "decision.sig"
        signature_path.write_text(signature, encoding="utf-8")
        allowed = Path(directory) / "allowed_signers"
        allowed.write_text(signers, encoding="utf-8")
        result = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", signer, "-n", NAMESPACE, "-s", str(signature_path),
             *(["-O", f"verify-time={at}"] if at else [])],
            input=payload_text(payload).encode("utf-8"), capture_output=True, check=False,
        )
    if result.returncode:
        raise SignerNotCurrent(f"The signature does not verify for {signer}: "
                               f"{result.stderr.decode(errors='replace').strip()}")


PROJECT_FILE = ".openguildkit/project.json"


def merged_reference(root: Path) -> str | None:
    """The branch that holds reviewed, merged work: the remote's default branch (origin/HEAD, which git clone sets), or
    else the upstream branch the current branch tracks. None when the repository has neither."""
    for reference in ("refs/remotes/origin/HEAD", "@{upstream}"):
        found = git.text(root, "rev-parse", "--verify", "--quiet", "--symbolic-full-name", reference)
        if found and found.strip():
            name = found.strip()
            return name.removeprefix("refs/remotes/")
    return None


def signers_at_approval(history: Path, payload: dict, *, merged_only: bool = False) -> tuple[list[str], str] | None:
    """The approvers and the allowed signers file as Git held them at the revision an approval was signed at.

    task decide verifies against the signers file at HEAD and records HEAD in the signed payload, so that revision
    holds the file the signature was verified against. None when the revision is not in the history of HEAD, or
    does not hold a signed project.json and its signers file. merged_only also asks that the revision be on the merged
    branch (merged_reference): a commit only this copy holds, which an agent can write and revert, does not count.
    """
    base = payload.get("base_revision")
    commit = base.get("commit") if isinstance(base, dict) else None
    if not isinstance(commit, str) or not commit or commit.startswith("-"):
        return None
    if git.text(history, "merge-base", "--is-ancestor", commit, "HEAD") is None:
        return None
    if merged_only:
        merged = merged_reference(history)
        if merged is None or git.text(history, "merge-base", "--is-ancestor", commit, merged) is None:
            return None
    try:
        profile = json.loads(git.text(history, "show", f"{commit}:./{PROJECT_FILE}") or "")
        policy = profile["approval"]
        approvers, relative = policy["approvers"], Path(policy["allowed_signers"]).as_posix()
    except (ValueError, TypeError, KeyError):
        return None
    signers = git.text(history, "show", f"{commit}:./{relative}")
    if policy.get("mode") != "signed" or not isinstance(approvers, list) or signers is None:
        return None
    return approvers, signers


def _not_merged(history: Path, payload: dict) -> str:
    """Why the signers of the approval's revision were not read: that revision is not on the merged branch."""
    commit = str((payload.get("base_revision") or {}).get("commit", ""))[:12]
    merged = merged_reference(history)
    where = (f"which {merged} does not contain" if merged else
             "and this repository has no merged branch to read it from (no origin/HEAD and no upstream branch)")
    return (f" The approval was signed at revision {commit}, {where}: the approvers and signers of an earlier "
            "revision count only once it is merged. Merge it, or have a current approver sign again.")


def verify_recorded_signature(root: Path, policy: dict, payload: dict, signature: str, signer: str, *,
                              committed: bool = True, history: Path | None = None) -> str | None:
    """Verify the signature of an approval already recorded, which a departed approver may have given.

    Against the current approvers and signers file first: None when they verify it. When the signer has left them
    since, the approval holds if it verifies against those of the revision it was signed at (signers_at_approval), read
    from the Git repository history (root by default); that revision is returned. Read from root, in a local copy,
    the revision must also be on the merged branch, so that a key an agent committed and then reverted approves
    nothing; CI passes history and judges the record against its base revision instead. A new approval goes through
    verify_signature, which refuses them. A payload with signed_at is verified at that time, so that the expiry of a
    key or of a certificate since voids no approval the signer gave while it was valid.
    """
    try:
        verify_signature(root, policy, payload, signature, signer, committed=committed, at_signing=True)
        return None
    except SignerNotCurrent as current:
        if not (history or committed):
            raise
        source = history or root
        recorded = signers_at_approval(source, payload, merged_only=history is None)
        if recorded is None or signer not in recorded[0]:
            unmerged = history is None and signers_at_approval(source, payload)
            if unmerged and signer in unmerged[0]:
                raise SignerNotCurrent(f"{current}{_not_merged(source, payload)}") from None
            raise
        try:
            _ssh_verify(recorded[1], payload, signature, signer, verify_time(payload))
        except ValueError:
            raise current from None
        return payload["base_revision"]["commit"]


DECISIONS_DIR = "decisions"


def exported_records(state: Path) -> list[tuple[Path, dict | None]]:
    """Every exported decision record of the repository, teammates' included; None for a file that is not one."""
    records = []
    for path in sorted((state / DECISIONS_DIR).glob("*.json")):
        try:
            record = read_json(path)
        except (OSError, ValueError):
            record = None
        if not isinstance(record, dict) or not isinstance(record.get("task"), str):
            record = None
        records.append((path, record))
    return records


def ignored_by_git(root: Path, paths: list[str]) -> set[str]:
    """The project paths that git ignores, so a teammate who pulls the repository will not have them."""
    if not paths:
        return set()
    # check-ignore fails with 1 when it ignores none of the paths.
    return {name.replace("\\", "/") for name in git.names(root, "check-ignore", "--no-index", "--", *paths) or []}


def reconsult_command(task_id: str) -> str:
    """The command that consults a task again with its recorded answers: it runs without a terminal."""
    return f"openguildkit task consult {task_id} --reuse-answers"


def reconsult_hint(task_id: str) -> str:
    """The next command for an approval that no longer holds, the same in every message."""
    return (f"Consult it again with {reconsult_command(task_id)} (--answers FILE to change the answers), "
            f'or open a linked task with openguildkit task new "BRIEF" --follows {task_id}.')


def stale_approval_message(task_id: str, changes: list[str] | None = None) -> str:
    """One wording for an approval given under other rules, naming what changed when it is known."""
    detail = f" ({'; '.join(changes)})" if changes else ""
    return f"The approval for {task_id} was recorded under earlier rules{detail}. {reconsult_hint(task_id)}"


def history_message(task_id: str, changes: list[str] | None = None, sealed: bool = True) -> str:
    """A completed task whose approval predates the current rules or sealed decisions: history, nothing to do."""
    if not sealed:
        return f"Task {task_id} was completed before approvals were sealed; its record stays as history."
    detail = f" ({'; '.join(changes)})" if changes else ""
    return f"Task {task_id} was completed under earlier rules{detail}; its record stays as history."


def check_decision_seal(task: dict) -> dict:
    """Check the seal without launching Git or verifying an SSH signature."""
    decision = task["decision"]
    if "seal" not in decision:
        raise ValueError(f"The approval for {task['id']} has no seal: it was edited by hand or written by a release "
                         f"older than sealed decisions. {reconsult_hint(task['id'])}")
    for version in PAYLOAD_VERSIONS:
        payload = decision_payload(task, decision["by"], decision["reason"], decision.get("base_revision"), version,
                                   separate=decision.get("separate_requester") is True,
                                   signed_at=decision.get("signed_at"))
        if seal(payload) == decision["seal"]:
            if date_moved(decision, payload):
                raise ValueError(f"The date of the approval of {task['id']} was changed after it was sealed. "
                                 f"{reconsult_hint(task['id'])}")
            return payload
    raise ValueError(f"The record of {task['id']} no longer matches what was approved. {reconsult_hint(task['id'])}")


def base_commit(task: dict) -> str | None:
    """The commit an approval was given at, when the project was a Git repository then."""
    base = (task.get("decision") or {}).get("base_revision")
    return base.get("commit") if isinstance(base, dict) and isinstance(base.get("commit"), str) else None


def revisions_outside_history(root: Path, commits: list[str]) -> set[str]:
    """The commits among these that HEAD no longer contains, found with one git call whatever their number.

    `git rev-list C... --not HEAD` lists what the commits reach and HEAD does not: a commit HEAD contains is not
    listed, one a rebase, a squash or an amendment replaced is. Outside a Git repository, or for a commit git no
    longer has, nothing is reported, so the approval is judged on the rest.
    """
    wanted = sorted({commit for commit in commits if commit})
    if not wanted:
        return set()
    listed = git.text(root, "rev-list", "--ignore-missing", *wanted, "--not", "HEAD")
    return set((listed or "").split()) & set(wanted)


def outside_history_message(task_id: str, commit: str) -> str:
    return (f"The approved revision {commit[:12]} of {task_id} is no longer in the project history: a rebase, a "
            f"squash or an amended commit replaced it. {reconsult_hint(task_id)}")


def decision_problem(task: dict, root: Path | None, profile: dict, outside: set[str] | None = None) -> tuple | None:
    """What breaks an approval besides its rules: the seal, the signature, the approved revision. (kind, message).

    Without the project root, only the seal is checked. outside holds the revisions already known to be out of the
    history (revisions_outside_history), so a reader of many approvals asks git once.
    """
    decision = task["decision"]
    try:
        payload = check_decision_seal(task)
    except ValueError as error:
        return ("invalid-seal" if "seal" in decision else "no-seal"), str(error)
    return None if root is None else signature_or_history_problem(task, root, profile, payload, outside)


# The one kind signature_or_history_problem returns that does not break the approval: a reader shows it as a note.
EARLIER_SIGNERS = "earlier-signers"


def signature_or_history_problem(task: dict, root: Path, profile: dict, payload: dict,
                                 outside: set[str] | None = None) -> tuple | None:
    """The signature a signed project requires, then the approved revision, for an approval whose seal holds.

    An approval verified by the approvers and signers of the revision it was signed at holds, and comes back as
    (EARLIER_SIGNERS, a note naming the signer and the revision), for the readers to say so.
    """
    decision = task["decision"]
    policy = approval_policy(profile)
    earlier = None
    if policy["mode"] == "signed":
        if "signature" not in decision:
            return "unsigned", (f"The project requires a signed approval and the approval of {task['id']} is not "
                                f"signed. {reconsult_hint(task['id'])}")
        try:
            earlier = verify_recorded_signature(root, policy, payload, decision["signature"], decision["signer"])
        except ValueError as error:
            return "invalid-signature", f"{error} {reconsult_hint(task['id'])}"
    commit = base_commit(task)
    if commit and commit in (outside if outside is not None else revisions_outside_history(root, [commit])):
        return "outside-history", outside_history_message(task["id"], commit)
    if earlier:
        return EARLIER_SIGNERS, (f"The approval of {task['id']} was signed by {decision['signer']}, who is no longer a "
                                 f"current approver: it holds through the approvers and signers file of revision "
                                 f"{earlier[:12]}, where it was signed.")
    return None


def check_decision(task: dict, root: Path, profile: dict) -> None:
    """Refuse an approval that no longer matches the record, its signature or the project history."""
    problem = decision_problem(task, root, profile)
    if problem and problem[0] != EARLIER_SIGNERS:
        raise ValueError(problem[1])
