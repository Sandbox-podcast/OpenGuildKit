"""Issue #483: git blame skips the bulk squashes, and GOVERNANCE.md says how a pull request of several issues merges."""

import importlib.util
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BlameIgnoreTests(unittest.TestCase):
    """commit-names-its-issues: git blame skips the bulk squashes, and GOVERNANCE.md says how main merges."""

    def revisions(self) -> list[str]:
        lines = (REPO / ".git-blame-ignore-revs").read_text(encoding="utf-8").splitlines()
        found = []
        for number, line in enumerate(lines):
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line, r"^[0-9a-f]{40}$", f"line {number + 1} is not a full SHA")
                self.assertTrue(number and lines[number - 1].startswith("# "), f"{line} has no comment above it")
                found.append(line)
        return found

    def test_issue_483_each_ignored_revision_is_a_full_sha_with_its_reason(self):
        """Issue #483: git blame led to a commit of 523 files for 41 to 77 % of the lines of the central modules."""
        self.assertIn("6ec06a59c240c34e2ccdd4b670da9b071d669971", self.revisions())
        self.assertIn("git config blame.ignoreRevsFile .git-blame-ignore-revs",
                      (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8"))

    def test_ignored_revisions_exist_when_the_history_is_here(self):
        for revision in self.revisions():
            probe = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{revision}^{{commit}}"],
                                   capture_output=True, check=False) if shutil.which("git") else None
            if probe is None or probe.returncode:
                self.skipTest(f"{revision} is not in this clone (shallow, or not a Git checkout)")

    def test_issue_483_governance_says_how_a_pull_request_of_several_issues_merges(self):
        """Issue #483: GOVERNANCE.md did not say which merge method applies to a pull request of several issues."""
        merging = (REPO / "GOVERNANCE.md").read_text(encoding="utf-8").split("## Merging", 1)[1].split("\n## ", 1)[0]
        self.assertIn("squash", merging)
        self.assertIn("several issues", merging)
        line = re.search(r"`(#N [^`]*\(file:function\))`", merging)
        self.assertTrue(line, "the section shows the line of each issue")
        body = "Closes #12\n" + line.group(1).replace("#N", "#12") + "\n\n## Not verified\n\nnothing"
        self.assertEqual(_load("check_pr_text").problems("Fix it (#12)", body), [])
