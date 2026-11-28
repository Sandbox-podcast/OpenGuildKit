"""Reference check for an ordinary shared GitHub workflow using the same central export rule."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MAX_SAFE_INTEGER = (1 << 53) - 1


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("Duplicate key in JSON.")
        data[key] = value
    return data


def safe_integer(value: object) -> int | None:
    integer = type(value) is int or (type(value) is float and value.is_integer())
    return int(value) if integer and abs(value) <= MAX_SAFE_INTEGER else None


def committed_json(repo: Path, revision: str, name: str) -> dict:
    if not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", revision):
        raise ValueError("Use a full Git commit ID.")
    options = {"cwd": repo, "capture_output": True, "check": True}
    if subprocess.run(["git", "cat-file", "-t", revision], **options).stdout.strip() != b"commit":
        raise ValueError("The Git object must be a commit.")
    content = subprocess.run(["git", "show", f"{revision}:{name}"], **options).stdout
    data = json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique_object)
    if not isinstance(data, dict):
        raise ValueError(f"{name} must contain a JSON object.")
    return data


def evaluate(policy_repo: Path, policy_commit: str, target_repo: Path, head: str) -> tuple[str, dict]:
    pack = committed_json(policy_repo, policy_commit, "packs/export-link-expiry.json")
    version = pack.get("version")
    if pack.get("id") != "export-link-expiry" or not isinstance(version, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version
    ):
        raise ValueError("Expected a versioned export-link-expiry policy pack.")
    rules = pack.get("rules")
    if not isinstance(rules, list) or len(rules) != 1 or not isinstance(rules[0], dict):
        raise ValueError("Expected one export-link-expiry rule.")
    check = rules[0].get("check")
    required = {"kind": "field", "path": "export.json", "field": "downloadLinkMinutes"}
    if not isinstance(check, dict) or any(check.get(key) != value for key, value in required.items()):
        raise ValueError("Expected the shared integer check for export.json.")
    if check.get("integer") is not True or safe_integer(check.get("min")) != 1:
        raise ValueError("Expected a minimum integer value of 1.")
    maximum = safe_integer(check.get("max"))
    if maximum is None or maximum < 1:
        raise ValueError("The policy needs a positive integer maximum.")
    actual = safe_integer(committed_json(target_repo, head, "export.json").get("downloadLinkMinutes"))
    passed = actual is not None and 1 <= actual <= maximum
    guidance = f"Keep downloadLinkMinutes in export.json between 1 and {maximum} minutes."
    return guidance, {
        "commit": head, "policy_commit": policy_commit, "rule": pack["id"], "version": version,
        "max_minutes": maximum, "actual_minutes": actual, "status": "success" if passed else "failure",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-repo", required=True, type=Path)
    parser.add_argument("--policy-commit", required=True)
    parser.add_argument("--target-repo", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        guidance, evidence = evaluate(args.policy_repo, args.policy_commit, args.target_repo, args.commit)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "AGENTS.md").write_text(
            f"# Export link policy\n\n{guidance}\n\nPolicy commit: {args.policy_commit}\n", encoding="utf-8",
        )
        (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, RecursionError, subprocess.CalledProcessError) as error:
        print(f"Shared workflow: {error}", file=sys.stderr)
        return 2
    # The pilot runs in observation mode. Keep the raw verdict in the evidence.
    return 0


if __name__ == "__main__":
    sys.exit(main())
