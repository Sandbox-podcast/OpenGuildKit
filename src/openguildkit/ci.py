"""Read versioned evidence from Git and evaluate the central policy's field check on it."""

import re
from pathlib import Path

from . import git
from .catalog import EXPORT_EXPIRY_ID, rule_check
from .project import profile_fingerprint, resolved_profile, rule_text
from .rule_checks import compare_field, parse_fields
from .storage import parse_json


POLICY_PATH = f"packs/{EXPORT_EXPIRY_ID}.json"
ORG_POLICY = "policy.json"  # org_policy.py
FULL_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _git(repo: Path, *args: str) -> bytes:
    result = git.run(repo.resolve(), *args, offline=True)
    if result is None:
        raise ValueError("Reading the evidence needs Git: it is not installed or not on the PATH.")
    if result.returncode:
        raise ValueError(f"Git could not read {args[-1]} in {repo}. Fetch the required commit first.")
    return result.stdout


def _committed_file(repo: Path, commit: str, path: str) -> bytes:
    if not FULL_COMMIT.fullmatch(commit):
        raise ValueError("Use a full lowercase Git commit SHA.")
    if _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").strip() != commit.encode("ascii"):
        raise ValueError("The supplied SHA must identify a commit directly.")
    return _git(repo, "show", f"{commit}:{path}")


def _committed_json(repo: Path, commit: str, path: str) -> dict:
    return parse_json(_committed_file(repo, commit, path), f"{commit}:{path}")


def _holds(repo: Path, commit: str, path: str) -> bool:
    try:
        return FULL_COMMIT.fullmatch(commit) is not None and _git(repo, "cat-file", "-e", f"{commit}:{path}") == b""
    except ValueError:
        return False


def read_policy_pack(repo: Path, commit: str) -> dict:
    """The central export rule; a commit that holds an organization policy instead names the command that reads it."""
    try:
        return _committed_json(repo, commit, POLICY_PATH)
    except ValueError:
        if not _holds(repo, commit, ORG_POLICY):
            raise
        raise ValueError(f"--policy-repo reads only the central export rule ({POLICY_PATH}), and commit {commit[:12]} "
                         f"holds an organization policy ({ORG_POLICY}). Pin it at a terminal: openguildkit org-catalog "
                         "set --repo PATH --commit SHA --by INITIALS --reason WHY; in CI: openguildkit guard --ci "
                         "--org-policy PATH --org-commit SHA.") from None


def check_export(profile: dict, catalog: dict, target: Path, commit: str) -> dict:
    """Judge the target commit with the central rule's field check, read from the exact commit."""
    if EXPORT_EXPIRY_ID not in resolved_profile(profile, catalog)["packs"]:
        raise ValueError(f"Select the {EXPORT_EXPIRY_ID} pack in the trusted project profile.")
    pack = catalog["packs"][EXPORT_EXPIRY_ID]
    if "policy_commit" not in pack:
        raise ValueError("Supply the central policy repository and its commit.")
    rule = pack["rules"][0]
    check = rule_check(rule)
    instruction, _ = rule_text(rule)
    data = parse_fields(_committed_file(target, commit, check["path"]), f"{commit}:{check['path']}")
    outcome = compare_field(check, data)
    return {
        "schema_version": 2,
        "rule": rule["id"],
        "rule_version": pack["version"],
        "policy_commit": pack["policy_commit"],
        "profile_fingerprint": profile_fingerprint(profile, catalog),
        "commit": commit,
        "instruction": instruction,
        "check": check,
        "actual": outcome["actual"],
        "evidence": outcome["evidence"],
        "status": "success" if outcome["passed"] else "failure",
    }
