"""Require, for each bug a branch closes, a test that names it and a line in the fix ledger.

    PR_BODY=... python scripts/check_fix_trace.py [--base REF] [--bugs N,M]

REF defaults to origin/main. The issues closed are the `Closes #N` (or `Fixes`, `Resolves`) of the commit messages
since the common ancestor of REF and HEAD, and of PR_BODY (its comments left out). An issue is a bug when it has the label `bug`, read with
`gh issue view` (GH_TOKEN and GH_REPO in CI; an issue whose label cannot be read is taken for a bug); --bugs names
the bugs instead, and asks nothing of GitHub. For each bug the script wants `Issue #N` in a file under tests/,
web/tests/ or integrations/ci/test/, and its line in docs/agents/fixes.jsonl. Exit 1 says what is missing.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#(\d+)", re.IGNORECASE)
TEST_FOLDERS = ("tests", "web/tests", "integrations/ci/test")
LEDGER = "docs/agents/fixes.jsonl"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "git failed")
    return result.stdout


def _is_bug(number: int) -> bool:
    """True unless GitHub says the issue lacks the label `bug`; an unreadable label counts as a bug."""
    try:
        result = subprocess.run(["gh", "issue", "view", str(number), "--json", "labels", "--jq", ".labels[].name"],
                                capture_output=True, text=True, check=False)
    except OSError:
        return True
    return result.returncode != 0 or "bug" in result.stdout.split()


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Require a named test and a ledger line for each bug a branch closes.")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--bugs", help="comma-separated issue numbers to treat as the bugs, without asking GitHub")
    args = parser.parse_args(argv)
    mine = subprocess.run(["git", "-C", str(root), "merge-base", args.base, "HEAD"], capture_output=True, text=True)
    since = mine.stdout.strip() if mine.returncode == 0 and mine.stdout.strip() else args.base
    body = re.sub(r"<!--.*?-->", "", os.environ.get("PR_BODY", ""), flags=re.DOTALL)
    messages = _git(root, "log", "--format=%B", f"{since}..HEAD") + "\n" + body
    closed = sorted({int(number) for number in CLOSING.findall(messages)})
    if args.bugs is not None:
        wanted = {int(number) for number in args.bugs.split(",") if number.strip()}
        bugs = [number for number in closed if number in wanted]
    else:
        bugs = [number for number in closed if _is_bug(number)]
    tests = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                      for folder in TEST_FOLDERS if (root / folder).is_dir()
                      for path in (root / folder).rglob("*") if path.is_file() and "node_modules" not in path.parts)
    ledger = root / LEDGER
    recorded = set()
    for line in ledger.read_text(encoding="utf-8").splitlines() if ledger.is_file() else []:
        try:
            recorded.add(json.loads(line).get("issue"))
        except (json.JSONDecodeError, AttributeError):
            continue
    problems = []
    for number in bugs:
        if not re.search(rf"Issue #{number}(?!\d)", tests):
            problems.append(f'#{number}: no test under tests/ names "Issue #{number}" (start its docstring with `Issue #{number}:`).')
        if number not in recorded:
            problems.append(f"#{number}: no line in {LEDGER} (issue, symptom, cause as file:function, test, commit).")
    for problem in problems:
        print(f"check_fix_trace: {problem}")
    if not problems:
        print(f"check_fix_trace: {len(bugs)} bug(s) closed, each with its test and its ledger line.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
