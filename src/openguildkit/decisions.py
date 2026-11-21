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


def decision_payload(task: dict, by: str, reason: str, base_revision: dict | None) -> dict:
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
    return payload


def payload_text(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def seal(payload: dict) -> str:
    return _sha256(payload)


def approval_policy(profile: dict) -> dict:
    return profile.get("approval") or {"mode": "local"}


def verify_signature(root: Path, policy: dict, payload: dict, signature: str, signer: str) -> None:
    """Check an SSH signature of the decision against the project's allowed signers."""
    if signer not in policy["approvers"]:
        raise ValueError(f"{signer} is not an approver for this project. Approvers: {', '.join(policy['approvers'])}.")
    allowed = (root / policy["allowed_signers"]).resolve()
    if not allowed.is_file() or root.resolve() not in allowed.parents:
        raise ValueError(f"The allowed signers file {policy['allowed_signers']} is missing from the project.")
    if shutil.which("ssh-keygen") is None:
        raise ValueError("Verifying a signed approval needs ssh-keygen (OpenSSH 8.1 or later).")
    with tempfile.TemporaryDirectory() as directory:
        signature_path = Path(directory) / "decision.sig"
        signature_path.write_text(signature, encoding="utf-8")
        result = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", signer, "-n", NAMESPACE, "-s", str(signature_path)],
            input=payload_text(payload).encode("utf-8"), capture_output=True, check=False,
        )
    if result.returncode:
        raise ValueError(f"The signature does not verify for {signer}: {result.stderr.decode(errors='replace').strip()}")


def stale_approval_message(task_id: str) -> str:
    return (f"The approval for {task_id} was recorded under earlier rules. "
            f'Open a new task with openguildkit task new "BRIEF" --follows {task_id}.')


def check_decision_seal(task: dict) -> dict:
    """Check the seal without launching Git or verifying an SSH signature."""
    decision = task["decision"]
    if "seal" not in decision:
        raise ValueError("This approval has no seal. It was edited outside the CLI or predates sealed decisions: open a new task.")
    payload = decision_payload(task, decision["by"], decision["reason"], decision.get("base_revision"))
    if seal(payload) != decision["seal"]:
        raise ValueError("The task record no longer matches what was approved. Open a new task for this work.")
    return payload


def check_decision(task: dict, root: Path, profile: dict) -> None:
    """Refuse an approval that no longer matches the record, its signature or the project history."""
    payload = check_decision_seal(task)
    decision = task["decision"]
    policy = approval_policy(profile)
    if policy["mode"] == "signed":
        if "signature" not in decision:
            raise ValueError("The project requires a signed approval and this one is not signed.")
        verify_signature(root, policy, payload, decision["signature"], decision["signer"])
    base = decision.get("base_revision")
    if base:
        ancestor = _git(root, "merge-base", "--is-ancestor", base["commit"], "HEAD")
        if ancestor is not None and ancestor.returncode == 1:
            raise ValueError(
                f"The approved revision {base['commit'][:12]} is no longer in the project history. "
                "Review the decision again in a new task."
            )
