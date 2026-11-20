"""Read versioned evidence from Git and evaluate the supported catalog check."""

import os
import re
import subprocess
from pathlib import Path

from .catalog import EXPORT_EXPIRY_ID, is_positive_integer
from .project import profile_fingerprint, resolved_profile, rule_text
from .storage import parse_json


POLICY_PATH = f"packs/{EXPORT_EXPIRY_ID}.json"
EXPORT_PATH = "export.json"
FULL_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-replace-objects", "-c", "protocol.allow=never", "-C", str(repo.resolve()), *args],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Git could not read {args[-1]} in {repo}. Fetch the required commit first.")
    return result.stdout


def _committed_json(repo: Path, commit: str, path: str) -> dict:
    if not FULL_COMMIT.fullmatch(commit):
        raise ValueError("Use a full lowercase Git commit SHA.")
    if _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").strip() != commit.encode("ascii"):
        raise ValueError("The supplied SHA must identify a commit directly.")
    return parse_json(_git(repo, "show", f"{commit}:{path}"), f"{commit}:{path}")


def read_policy_pack(repo: Path, commit: str) -> dict:
    return _committed_json(repo, commit, POLICY_PATH)


def check_export(profile: dict, catalog: dict, target: Path, commit: str) -> dict:
    if EXPORT_EXPIRY_ID not in resolved_profile(profile, catalog)["packs"]:
        raise ValueError(f"Select the {EXPORT_EXPIRY_ID} pack in the trusted project profile.")
    pack = catalog["packs"][EXPORT_EXPIRY_ID]
    if "policy_commit" not in pack:
        raise ValueError("Supply the central policy repository and its commit.")
    rule = pack["rules"][0]
    threshold = int(rule["check"]["max_minutes"])
    instruction, _ = rule_text(rule)
    config = _committed_json(target, commit, EXPORT_PATH)
    minutes = config.get("downloadLinkMinutes")
    valid_minutes = is_positive_integer(minutes)
    return {
        "schema_version": 1,
        "rule": rule["id"],
        "rule_version": pack["version"],
        "policy_commit": pack["policy_commit"],
        "profile_fingerprint": profile_fingerprint(profile, catalog),
        "commit": commit,
        "instruction": instruction,
        "max_minutes": threshold,
        "actual_minutes": int(minutes) if valid_minutes else None,
        "status": "success" if valid_minutes and minutes <= threshold else "failure",
    }
