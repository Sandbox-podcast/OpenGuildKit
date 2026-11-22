"""Bind an approval to the consultation, the review, the rules in force and the project revision.

Every approval carries a seal: a SHA-256 over what was approved. The handoff refuses a
decision whose seal no longer matches the task record. A project can also require a
signed approval: the approver signs the decision with an SSH key listed in an
allowed-signers file kept in the repository, and the CLI verifies it locally.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .storage import read_json

NAMESPACE = "openguildkit-decision"


def _sha256(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    if shutil.which("git") is None:
        return None
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )


def git_revision(root: Path) -> dict | None:
    """The commit the project is at, and whether files differ from it. None outside a Git repository."""
    head = _git(root, "rev-parse", "--verify", "HEAD")
    if head is None or head.returncode:
        return None
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    dirty = bool(status and status.returncode == 0 and status.stdout.strip())
    return {"commit": head.stdout.strip(), "dirty": dirty}


def changed_paths_since(root: Path, commit: str) -> list[str]:
    """Changes to tracked and staged files between an approved commit and the working tree."""
    change = _git(root, "diff", "--name-only", "--no-renames", commit, "--")
    if change is None or change.returncode:
        raise ValueError("Could not compare the project files with the approved Git revision.")
    return change.stdout.splitlines()


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


def decision_payload(task: dict, by: str, reason: str, base_revision: dict | None, version: int = PAYLOAD_VERSION) -> dict:
    """What an approval covers. The approver signs exactly this object in signed mode."""
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
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode or inside.stdout.strip() != "true":
        raise ValueError(f"{shown} is verified as Git holds it at HEAD, and the project is not in a Git repository. "
                         "Signed approvals need the project and this file in Git.")
    tracked = _git(root, "ls-files", "--error-unmatch", "--", relative)
    committed = _git(root, "show", f"HEAD:./{relative}")
    if tracked.returncode or committed.returncode:
        raise ValueError(f"{shown} is not committed: a signature is verified against its version at HEAD. {retry}")
    changed = _git(root, "diff", "--quiet", "HEAD", "--", relative)
    if changed.returncode:
        raise ValueError(f"{shown} differs from its version at HEAD (git diff HEAD -- {relative}): a signature is "
                         f"verified against the committed file, never against a working copy. {retry}")
    return committed.stdout


def verify_signature(root: Path, policy: dict, payload: dict, signature: str, signer: str, *,
                     committed: bool = True) -> None:
    """Check an SSH signature of the decision against the project's allowed signers.

    The signers come from HEAD (committed_signers). committed=False reads the file as it is in root, for a copy
    already extracted from a Git revision, such as the base revision CI reads.
    """
    if signer not in policy["approvers"]:
        raise ValueError(f"{signer} is not an approver for this project. Approvers: {', '.join(policy['approvers'])}.")
    allowed = (root / policy["allowed_signers"]).resolve()
    if not allowed.is_file() or root.resolve() not in allowed.parents:
        raise ValueError(f"The allowed signers file {policy['allowed_signers']} is missing from the project.")
    signers = committed_signers(root, Path(policy["allowed_signers"]).as_posix()) if committed else None
    if shutil.which("ssh-keygen") is None:
        raise ValueError("Verifying a signed approval needs ssh-keygen (OpenSSH 8.1 or later).")
    with tempfile.TemporaryDirectory() as directory:
        signature_path = Path(directory) / "decision.sig"
        signature_path.write_text(signature, encoding="utf-8")
        if signers is not None:
            allowed = Path(directory) / "allowed_signers"
            allowed.write_text(signers, encoding="utf-8")
        result = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", signer, "-n", NAMESPACE, "-s", str(signature_path)],
            input=payload_text(payload).encode("utf-8"), capture_output=True, check=False,
        )
    if result.returncode:
        raise ValueError(f"The signature does not verify for {signer}: {result.stderr.decode(errors='replace').strip()}")


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
    result = _git(root, "check-ignore", "--no-index", "--", *paths)
    if result is None or result.returncode not in (0, 1):
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def reconsult_hint(task_id: str) -> str:
    """The next command for an approval that no longer holds, the same in every message."""
    return (f"Consult it again with openguildkit task consult {task_id}, "
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
        payload = decision_payload(task, decision["by"], decision["reason"], decision.get("base_revision"), version)
        if seal(payload) == decision["seal"]:
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
    listed = _git(root, "rev-list", "--ignore-missing", *wanted, "--not", "HEAD")
    if listed is None or listed.returncode:
        return set()
    return set(listed.stdout.split()) & set(wanted)


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


def signature_or_history_problem(task: dict, root: Path, profile: dict, payload: dict,
                                 outside: set[str] | None = None) -> tuple | None:
    """The signature a signed project requires, then the approved revision, for an approval whose seal holds."""
    decision = task["decision"]
    policy = approval_policy(profile)
    if policy["mode"] == "signed":
        if "signature" not in decision:
            return "unsigned", (f"The project requires a signed approval and the approval of {task['id']} is not "
                                f"signed. {reconsult_hint(task['id'])}")
        try:
            verify_signature(root, policy, payload, decision["signature"], decision["signer"])
        except ValueError as error:
            return "invalid-signature", f"{error} {reconsult_hint(task['id'])}"
    commit = base_commit(task)
    if commit and commit in (outside if outside is not None else revisions_outside_history(root, [commit])):
        return "outside-history", outside_history_message(task["id"], commit)
    return None


def check_decision(task: dict, root: Path, profile: dict) -> None:
    """Refuse an approval that no longer matches the record, its signature or the project history."""
    problem = decision_problem(task, root, profile)
    if problem:
        raise ValueError(problem[1])
