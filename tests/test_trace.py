"""openguildkit trace FILE: from a file to the exported decisions that cover it, and whether it changed since (issue #434)."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json

from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"
RECORD = f".openguildkit/decisions/{TASK}.json"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
           # No background maintenance: it would hold a lock in .git while a test removes the folder.
           "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "maintenance.auto", "GIT_CONFIG_VALUE_0": "false",
           "GIT_CONFIG_KEY_1": "gc.auto", "GIT_CONFIG_VALUE_1": "0"}


def remove_tree(path: Path) -> None:
    """shutil.rmtree, which also removes the read-only object files Git writes on Windows."""
    def writable(function, name, _):
        os.chmod(name, 0o700)
        function(name)
    shutil.rmtree(path, **({"onexc": writable} if sys.version_info >= (3, 12) else {"onerror": writable}))


def snapshot(root: Path) -> dict:
    """Every file below the root, .git included, with its bytes and its modification time."""
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            files[path.relative_to(root).as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns)
    return files


@unittest.skipIf(shutil.which("git") is None, "needs git")
class TraceTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "portal"
        self.root.mkdir()
        self.work = Path(temporary.name)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True,
                              env=GIT_ENV).stdout

    def write(self, relative, text="x\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def main_branch(self):
        self.git("init", "-q", "-b", "main")
        self.write("README.md", "Suport portal\n")
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.work / "profile.json", {"name": "Support portal", "stack": ["Python"], "packs": [],
                                                "checks": [command], "guard": "enforce", "personal_data": "no"})
        self.run_cli("init", "--answers", self.work / "profile.json")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def approve(self, task=TASK):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each request's status."}
        write_json(self.work / "answers.json", answers)
        self.run_cli("task", "consult", task, "--answers", self.work / "answers.json")
        template = json.loads(self.run_cli("task", "template", task)[0])
        write_json(self.work / "review.json",
                   {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", task, "--file", self.work / "review.json")
        self.run_cli("task", "decide", task, "--approve", "--by", "Camille Martin", "--reason", "Agreed", typed=task)

    def complete(self):
        self.run_cli("task", "verify", TASK)
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        rules = [{"check": item["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"}
                 for item in checks if item["kind"] == "rule"]
        rules[0] = {"check": rules[0]["check"], "status": "failed", "evidence": "The style check reports errors."}
        write_json(self.work / "result.json", {
            "pull_request": "https://github.com/example/portal/pull/7", "checks": rules,
            "criteria": [{"criterion": "Users only see their own requests.", "status": "met",
                          "evidence": "tests/test_access.py"}]})
        self.run_cli("task", "result", TASK, "--file", self.work / "result.json")
        self.run_cli("task", "complete", TASK, "--by", "Camille Martin", typed=TASK)

    def delivered(self):
        """README.md fixed under an approved task, completed, its record exported and committed with the fix."""
        self.main_branch()
        self.approve()
        self.write("README.md", "Support portal\n")
        self.git("commit", "-q", "-am", "fix the typo")
        self.complete()
        self.run_cli("task", "export", TASK)
        self.git("add", "-f", RECORD)
        self.git("commit", "-q", "-m", "decision record")

    def trace(self, *arguments, code=0):
        return self.run_cli("trace", *arguments, code=code)

    def test_a_file_no_decision_covers_gets_one_line_and_the_command_that_opens_a_task(self):
        self.main_branch()
        out, err = self.trace("app.py")
        self.assertIn("No exported decision covers app.py.", out)
        self.assertIn("openguildkit task new", out)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertEqual(err, "")

    def test_a_covered_file_names_the_task_the_approver_the_revision_and_the_checks(self):
        self.delivered()
        revision = json.loads((self.root / RECORD).read_text())["result"]["revision"]
        out, _ = self.trace("README.md")
        first = out.splitlines()[0]
        self.assertIn(f"{TASK} [done-with-reservations, ", first)
        self.assertIn("by CM", first)
        self.assertNotIn("Camille", out)
        self.assertIn(revision[:7], first)
        self.assertIn("1 failed", out)
        self.assertIn("holds under the current rules", out)
        self.assertNotIn("Changed since", out)
        self.assertIn(f"Next: openguildkit task show {TASK}", out)

    def test_a_commit_on_the_file_after_the_decision_is_named_as_not_covered(self):
        self.delivered()
        self.write("README.md", "Support portal, now with statuses\n")
        self.git("commit", "-q", "-am", "unreviewed change")
        commit = self.git("rev-parse", "HEAD").strip()
        out, _ = self.trace("README.md")
        self.assertIn(f"Changed since the last decision (commit {commit[:7]}): no decision covers this change.", out)
        # Another file is not touched by that commit.
        self.write("other.md")
        self.assertNotIn("Changed since", self.trace(RECORD)[0])

    def test_a_file_with_an_accent_or_a_space_is_traced_to_the_task_that_delivered_it(self):
        """Issue #458: task export wrote docs/résumé.md in Git's quoted form, and trace said no decision covered it."""
        self.main_branch()
        self.approve()
        names = ["docs/a b.md", "docs/résumé.md"]
        for name in names:
            self.write(name)
        self.git("add", "docs")
        self.git("commit", "-q", "-m", "docs")
        self.complete()
        self.run_cli("task", "export", TASK)
        record = json.loads((self.root / RECORD).read_text())
        self.assertEqual(record["files"], names)
        for name in names:
            self.assertIn(f"{TASK} [", self.trace(name)[0].splitlines()[0])
        # A record exported before the fix still names the file.
        write_json(self.root / RECORD, {**record, "files": ["docs/a b.md", '"docs/r\\303\\251sum\\303\\251.md"']})
        self.assertIn(f"{TASK} [", self.trace("docs/résumé.md")[0].splitlines()[0])

    def test_two_decisions_of_the_same_day_are_ordered_by_their_time(self):
        """Issue #525: two approvals of one day were ordered by task ID, and the commit of the later one was named as a
        change no decision covers."""
        self.main_branch()
        for task, text, second in (("za", "Support portal\n", 1), ("ab", "Support portal, with statuses\n", 5)):
            with patch("openguildkit.clock.real_timestamp", return_value=f"2026-11-26T20:17:0{second}+00:00"):
                self.approve(task)
            self.write("README.md", text)
            self.git("commit", "-q", "-am", f"change of {task}")
            self.run_cli("task", "export", task)
            self.git("add", "-f", f".openguildkit/decisions/{task}.json")
            self.git("commit", "-q", "-m", f"record of {task}")
        out, _ = self.trace("README.md")
        self.assertTrue(out.startswith("ab ["), out)
        self.assertNotIn("Changed since", out)
        self.assertIn("Next: openguildkit task show ab", out)
        detail = json.loads(self.trace("README.md", "--json")[0])
        self.assertEqual([item["task"] for item in detail["decisions"]], ["ab", "za"])
        self.write("README.md", "Unreviewed\n")
        self.git("commit", "-q", "-am", "unreviewed change")
        self.assertIn("Changed since the last decision", self.trace("README.md")[0])

    def test_an_earlier_approval_exported_later_does_not_hide_the_latest_one(self):
        """Issue #525: changes were counted from the first decision of the list, not from the latest in the history."""
        self.main_branch()
        for task, text, second in (("ab", "Support portal\n", 5), ("za", "Support portal, with statuses\n", 1)):
            with patch("openguildkit.clock.real_timestamp", return_value=f"2026-11-26T20:17:0{second}+00:00"):
                self.approve(task)
            self.write("README.md", text)
            self.git("commit", "-q", "-am", f"change of {task}")
            self.run_cli("task", "export", task)
            self.git("add", "-f", f".openguildkit/decisions/{task}.json")
            self.git("commit", "-q", "-m", f"record of {task}")
        out, _ = self.trace("README.md")
        self.assertTrue(out.startswith("ab ["), out)
        self.assertNotIn("Changed since", out)

    def test_a_journal_changed_after_the_export_is_named(self):
        self.delivered()
        journal = json.loads((self.root / RECORD).read_text())["result"]["journals"][0]
        (self.root / journal["evidence"]).write_text("edited\n", encoding="utf-8")
        out, _ = self.trace("README.md")
        self.assertIn(f"evidence changed since the export: {journal['check']}", out)
        detail = json.loads(self.trace("README.md", "--json")[0])
        self.assertEqual(detail["decisions"][0]["evidence_changed"], [journal["check"]])

    def test_a_withdrawn_approval_is_shown_as_withdrawn(self):
        self.main_branch()
        self.approve()
        self.write("README.md", "Support portal\n")
        self.git("commit", "-q", "-am", "fix the typo")
        self.run_cli("task", "export", TASK)
        self.run_cli("task", "revoke", TASK, "--by", "Camille Martin", "--reason", "Wrong scope", typed=TASK)
        self.run_cli("task", "export", TASK)
        out, _ = self.trace("README.md")
        self.assertIn("withdrawn by CM", out)
        self.assertIn("covers nothing", out)
        detail = json.loads(self.trace("README.md", "--json")[0])
        self.assertFalse(detail["decisions"][0]["holds"])
        self.assertEqual(detail["decisions"][0]["withdrawn"]["reason"], "Wrong scope")

    def test_an_unreadable_record_is_reported_as_such_and_the_others_still_listed(self):
        self.delivered()
        self.write(".openguildkit/decisions/broken.json", "{not json")
        record = json.loads((self.root / RECORD).read_text())
        record["brief"] = "Changed by hand"
        write_json(self.root / ".openguildkit/decisions/edited.json", {**record, "task": "edited"})
        out, _ = self.trace("README.md")
        self.assertIn(".openguildkit/decisions/broken.json [unreadable]", out)
        self.assertIn("edited [", out)
        self.assertIn("does not hold", out)
        self.assertIn(f"{TASK} [done-with-reservations, ", out)
        detail = json.loads(self.trace("README.md", "--json")[0])
        self.assertEqual([item["record"] for item in detail["unreadable"]], [".openguildkit/decisions/broken.json"])

    def test_the_json_detail_lists_each_decision_most_recent_first(self):
        self.delivered()
        detail = json.loads(self.trace("README.md", "--json")[0])
        self.assertEqual(detail["path"], "README.md")
        decision = detail["decisions"][0]
        self.assertEqual((decision["task"], decision["status"], decision["by"], decision["initials"]),
                         (TASK, "done-with-reservations", "Camille Martin", "CM"))
        self.assertTrue(decision["holds"])
        self.assertEqual(len(decision["checks"]["failed"]), 1)
        self.assertIsNone(detail["changed_since"]["commit"])
        self.assertEqual(detail["next"], f"openguildkit task show {TASK}")

    def test_trace_reads_and_writes_nothing(self):
        self.delivered()
        self.write("README.md", "Changed\n")
        self.git("commit", "-q", "-am", "unreviewed change")
        self.write("README.md", "Changed again, not committed\n")
        before = snapshot(self.root)
        self.trace("README.md")
        self.trace("README.md", "--json")
        self.trace("app.py")
        self.assertEqual(snapshot(self.root), before)

    def test_a_path_outside_the_project_is_refused_with_what_to_do(self):
        self.main_branch()
        _, err = self.trace(self.work / "profile.json", code=1)
        self.assertIn("is outside the project", err)

    def test_outside_git_the_decisions_are_listed_without_the_change_check(self):
        self.delivered()
        remove_tree(self.root / ".git")
        out, _ = self.trace("README.md")
        self.assertIn(f"{TASK} [done-with-reservations, ", out)
        self.assertIn("not a Git repository", out)
        detail = json.loads(self.trace("README.md", "--json")[0])
        self.assertIsNone(detail["changed_since"])


if __name__ == "__main__":
    unittest.main()
