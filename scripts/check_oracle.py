"""List the assertions a branch removes from the tests while it changes src/.

    PR_BODY=... python scripts/check_oracle.py [--base REF]

REF defaults to origin/main. The diff is the tracked one since the common ancestor of REF and HEAD, working tree
included. A test made green by weakening it is the costliest silent failure: the fix and the weaker test sit in one
diff. When that diff changes a file under src/ and removes a line of a test file (a path with a tests/ folder) that
holds `self.assert` or `expect(`, each such line must appear under `## Assertions changed` in the body of the pull
request, read from PR_BODY. A line removed in one place and added in another (a move) does not count. Exit 1 names
the lines not listed.
"""

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSERTION = re.compile(r"self\.assert|\bexpect\(")
SECTION = re.compile(r"^##[ \t]+Assertions changed[ \t]*$(.*?)(?=^##[ \t]|\Z)", re.MULTILINE | re.DOTALL | re.IGNORECASE)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "git failed")
    return result.stdout


def _squash(text: str) -> str:
    return " ".join(text.split())


def assertions_removed(root: Path, base: str) -> tuple[bool, list[tuple[str, str]]]:
    """Whether src/ changed since base, and the (path, line) of each assertion removed from the tests."""
    mine = subprocess.run(["git", "-C", str(root), "merge-base", base, "HEAD"], capture_output=True, text=True)
    since = mine.stdout.strip() if mine.returncode == 0 and mine.stdout.strip() else base
    touches_src = bool(_git(root, "ls-files", "--others", "--exclude-standard", "src").split())
    removed, added = [], Counter()
    path, header = "", False
    for line in _git(root, "diff", "-U0", "--no-color", "--no-renames", since).splitlines():
        if line.startswith("diff --git"):
            header = True
        elif header and line.startswith("--- "):
            path = line[6:] if line.startswith("--- a/") else path
        elif header and line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else path
        elif line.startswith("@@"):
            header = False
            touches_src = touches_src or path.startswith("src/")
        elif not header and line[:1] in "+-" and "/tests/" in f"/{path}" and ASSERTION.search(line):
            if line[0] == "-":
                removed.append((path, line[1:].strip()))
            else:
                added[_squash(line[1:])] += 1
    kept = []
    for path, text in removed:
        if added[_squash(text)] > 0:
            added[_squash(text)] -= 1
        else:
            kept.append((path, text))
    return touches_src, kept


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Require the assertions a branch removes to be listed in its pull request.")
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    touches_src, removed = assertions_removed(root, args.base)
    if not touches_src or not removed:
        print("check_oracle: no assertion removed next to a change of src/.")
        return 0
    found = SECTION.search(os.environ.get("PR_BODY", ""))
    listed = _squash(found.group(1)) if found else ""
    missing = [(path, text) for path, text in removed if _squash(text) not in listed]
    if not missing:
        print(f"check_oracle: {len(removed)} removed assertion(s), all listed under Assertions changed.")
        return 0
    print("check_oracle: these assertions are removed next to a change of src/ and not listed under "
          "`## Assertions changed` in the pull request:")
    for path, text in missing:
        print(f"{path}: {text}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
