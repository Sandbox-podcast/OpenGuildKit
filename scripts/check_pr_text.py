"""Check the text of a pull request against docs/agents/conventions.md.

    PR_TITLE=... PR_BODY=... python scripts/check_pr_text.py

CI passes the title and the body of the pull request in PR_TITLE and PR_BODY. Exit 1 prints each problem:
the body has no `## Not verified` section, or the section is empty (write what was not run, or "nothing").
"""

import os
import re
import sys

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def section(body: str, heading: str) -> str | None:
    """The text under `## HEADING` up to the next `## ` heading, comments left out; None when the heading is absent."""
    found = re.search(rf"^##[ \t]+{re.escape(heading)}[ \t]*$(.*?)(?=^##[ \t]|\Z)", body, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return HTML_COMMENT.sub("", found.group(1)).strip() if found else None


def problems(title: str, body: str) -> list[str]:
    """What the pull request breaks, one sentence each; an empty list when it follows the conventions."""
    found = []
    if not section(body, "Not verified"):
        found.append("The body needs a `## Not verified` section that says what was not run, or `nothing`.")
    return found


def main() -> int:
    found = problems(os.environ.get("PR_TITLE", ""), os.environ.get("PR_BODY", ""))
    for line in found:
        print(f"check_pr_text: {line}")
    if not found:
        print("check_pr_text: the pull request follows the conventions.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
