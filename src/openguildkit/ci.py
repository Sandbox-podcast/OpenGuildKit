"""Reads versioned evidence from Git and evaluates the central policy's field check.

Entry: read_policy_pack, check_export
Tests: tests/e2e/test_export_ci.py
"""

import re
from pathlib import Path

from . import git
from .catalog import EXPORT_EXPIRY_ID, rule_check
from .errors import OgkError
from .project_instructions import rule_text
from .project_rules import profile_fingerprint, resolved_profile
from .records import Catalog, Profile
from .rule_checks import compare_field, parse_fields
from .storage import parse_json

POLICY_PATH = f"packs/{EXPORT_EXPIRY_ID}.json"
ORG_POLICY = "policy.json"  # org_policy.py
FULL_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _committed_bytes(repo: Path, *args: str) -> bytes:
    """What a Git command prints about a commit, which must be in the copy."""
    result = git.required(repo.resolve(), *args, needs="Reading the evidence", offline=True)
    if result.returncode:
        raise OgkError("OGK-CI-001", f"Git could not read {args[-1]} in {repo}. Fetch the required commit first.")
    return result.stdout


def _committed_file(repo: Path, commit: str, path: str) -> bytes:
    if not FULL_COMMIT.fullmatch(commit):
        raise OgkError("OGK-CI-002", "Use a full lowercase Git commit SHA.")
    if _committed_bytes(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").strip() != commit.encode("ascii"):
        raise OgkError("OGK-CI-003", "The supplied SHA must identify a commit directly.")
    return _committed_bytes(repo, "show", f"{commit}:{path}")


def _committed_json(repo: Path, commit: str, path: str) -> dict:
    return parse_json(_committed_file(repo, commit, path), f"{commit}:{path}")


def _holds(repo: Path, commit: str, path: str) -> bool:
    try:
        return FULL_COMMIT.fullmatch(commit) is not None and _committed_bytes(repo, "cat-file", "-e", f"{commit}:{path}") == b""
    except ValueError:
        return False


def read_policy_pack(repo: Path, commit: str) -> dict:
    """The central export rule; a commit that holds an organization policy instead names the command that reads it."""
    try:
        return _committed_json(repo, commit, POLICY_PATH)
    except ValueError:
        if not _holds(repo, commit, ORG_POLICY):
            raise
        raise OgkError("OGK-CI-004", f"--policy-repo reads only the central export rule ({POLICY_PATH}), and commit {commit[:12]} "
                         f"holds an organization policy ({ORG_POLICY}). Pin it at a terminal: openguildkit org-catalog "
                         "set --repo PATH --commit SHA --by INITIALS --reason WHY; in CI: openguildkit guard --ci "
                         "--org-policy PATH --org-commit SHA.") from None


def check_export(profile: Profile, catalog: Catalog, target: Path, commit: str) -> dict:
    """Judge the target commit with the central rule's field check, read from the exact commit."""
    if EXPORT_EXPIRY_ID not in resolved_profile(profile, catalog)["packs"]:
        raise OgkError("OGK-CI-005", f"Select the {EXPORT_EXPIRY_ID} pack in the trusted project profile.")
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
