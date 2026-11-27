"""Check the text of a pull request against docs/agents/conventions.md.

    PR_TITLE=... PR_BODY=... python scripts/check_pr_text.py [--base REF]

CI passes the title and the body of the pull request in PR_TITLE and PR_BODY, and the base in --base. Exit 1 prints
each problem: a title or a commit subject since the common ancestor of REF and HEAD that names a range or a list of
issues (`#377 to #407`, `#12, #13`), so that `git log --grep '#N'` finds each issue; a `Closes #N` in the body with
no line `#N what it fixed (file:function)`, which the squash commit keeps; no `## Not verified` section in the body,
or an empty one (write what was not run, or "nothing").
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
RANGE = re.compile(r"#\d+ to #\d+|#\d+, #\d+")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?[ \t]+#(\d+)", re.IGNORECASE)


def section(body: str, heading: str) -> str | None:
    """The text under `## HEADING` up to the next `## ` heading, comments left out; None when the heading is absent."""
    found = re.search(rf"^##[ \t]+{re.escape(heading)}[ \t]*$(.*?)(?=^##[ \t]|\Z)", body, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return HTML_COMMENT.sub("", found.group(1)).strip() if found else None


def problems(title: str, body: str, subjects: tuple[str, ...] | list[str] = ()) -> list[str]:
    """What the pull request breaks, one sentence each; an empty list when it follows the conventions."""
    found = [f"The {kind} names a range or a list of issues: {text!r}. One issue per subject, so that `git log --grep` finds it."
             for kind, text in [("title", title), *[("commit subject", subject) for subject in subjects]]
             if RANGE.search(text)]
    body = HTML_COMMENT.sub("", body)
    for number in dict.fromkeys(CLOSING.findall(body)):
        if not re.search(rf"^[ \t]*(?:[-*][ \t]+)?#{number}[ \t]+\S", body, re.MULTILINE):
            found.append(f"The body closes #{number} and has no line `#{number} what it fixed (file:function)`.")
    if not section(body, "Not verified"):
        found.append("The body needs a `## Not verified` section that says what was not run, or `nothing`.")
    return found


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Check the title, the body and the commit subjects of a pull request.")
    parser.add_argument("--base", help="check the commit subjects since the common ancestor of this revision and HEAD")
    args = parser.parse_args(argv)
    subjects = []
    if args.base:
        mine = subprocess.run(["git", "-C", str(root), "merge-base", args.base, "HEAD"], capture_output=True, text=True, check=False)
        since = mine.stdout.strip() if mine.returncode == 0 and mine.stdout.strip() else args.base
        log = subprocess.run(["git", "-C", str(root), "log", "--format=%s", f"{since}..HEAD"], capture_output=True, text=True, check=False)
        subjects = log.stdout.splitlines()
    found = problems(os.environ.get("PR_TITLE", ""), os.environ.get("PR_BODY", ""), subjects)
    for line in found:
        print(f"check_pr_text: {line}")
    if not found:
        print("check_pr_text: the pull request follows the conventions.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
