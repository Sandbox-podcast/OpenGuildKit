"""The boards review the diff a task delivered (issue #431): each board's brief, its findings, and what the closing and
the shared record keep of them. A task whose diff no board reviewed closes as before."""

import json
import shutil
import unittest

from openguildkit import delivered_review
from openguildkit.storage import read_json, write_json
from tests.test_approval_lifecycle import ApprovalCase


@unittest.skipIf(shutil.which("git") is None, "needs git")
class DeliveredReviewCase(ApprovalCase):
    """An approved task in Git whose change adds lines to status.py, delivered as a commit."""

    def setUp(self):
        super().setUp()
        self.git("init", "-q", "-b", "main")
        self.init()
        (self.root / "status.py").write_text("STATUS = 1\n", encoding="utf-8")
        (self.root / "notes.md").write_text("Notes.\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.approve("sx")
        (self.root / "status.py").write_text("STATUS = 1\n\n\ndef status(user):\n    return user.requests\n",
                                             encoding="utf-8")
        self.git("add", "status.py")
        self.git("commit", "-q", "-m", "Show the status")

    def deliver(self):
        self.run_cli("task", "verify", "sx")
        checks = [{"check": check["id"], "status": "not-applicable", "reason": "No change in this area.",
                   "owner": "Camille"}
                  for check in json.loads(self.run_cli("task", "checks", "sx", "--json")[0]) if check["kind"] == "rule"]
        write_json(self.root / "result.json", {"checks": checks, "criteria": [
            {"criterion": "Users only see their own requests.", "status": "met", "evidence": "status.py"}]})
        self.run_cli("task", "result", "sx", "--file", self.root / "result.json")

    def submit(self, payload, code=0):
        write_json(self.root / "findings.json", payload)
        return self.run_cli("task", "diff-review", "sx", "--submit", self.root / "findings.json", code=code)

    def boards(self):
        return [entry["id"] for entry in self.task("sx")["review"]["boards"]]


class BriefTests(DeliveredReviewCase):
    def test_the_diff_is_reviewed_once_the_delivered_revision_is_recorded(self):
        _, error = self.run_cli("task", "diff-review", "sx", code=1)
        self.assertIn("Record the delivered revision first: openguildkit task verify sx", error)

    def test_the_overview_names_the_files_and_one_command_per_board(self):
        self.deliver()
        output, _ = self.run_cli("task", "diff-review", "sx")
        self.assertIn("1 file: status.py (+4 -0)", output)
        for board in self.boards():
            self.assertIn(f"openguildkit task diff-review sx --board {board}   [not reviewed]", output)
        self.assertIn(f"0 boards of {len(self.boards())} reviewed the delivered diff", output)
        status = json.loads(self.run_cli("task", "diff-review", "sx", "--json")[0])
        self.assertEqual(status["files"], ["status.py"])
        self.assertEqual([row["board"] for row in status["boards"]], self.boards())

    def test_a_board_brief_holds_the_diff_what_the_decision_asked_and_the_lens(self):
        self.deliver()
        output, _ = self.run_cli("task", "diff-review", "sx", "--board", "security")
        self.assertIn("# Delivered diff review: security (Security and privacy)", output)
        self.assertIn("+def status(user):", output)
        self.assertIn("Decision: approved by Camille: Agreed", output)
        self.assertIn("Your recommendation at approval:", output)
        self.assertIn("Application security reviewer:", output)
        self.assertIn("openguildkit task diff-review sx --submit FILE", output)
        self.assertNotIn("notes.md", output)
        self.assertLess(len(output.encode("utf-8")), 10_000)
        brief = json.loads(self.run_cli("task", "diff-review", "sx", "--board", "security", "--json")[0])
        self.assertEqual(brief["files"], ["status.py"])
        self.assertEqual(brief["format"]["board"], "security")
        self.assertFalse(brief["diff_truncated"])

    def test_a_long_diff_is_cut_with_the_command_that_prints_the_rest(self):
        (self.root / "status.py").write_text("".join(f"LINE_{index} = {index}\n" for index in range(800)),
                                             encoding="utf-8")
        self.git("commit", "-qam", "Long")
        self.deliver()
        output, _ = self.run_cli("task", "diff-review", "sx", "--board", "security")
        self.assertIn(f"The diff is cut at {delivered_review.DIFF_LIMIT} characters: read the rest with git diff", output)
        self.assertLess(len(output.encode("utf-8")), 10_000)

    def test_an_unknown_board_is_refused_with_the_task_boards(self):
        self.deliver()
        _, error = self.run_cli("task", "diff-review", "sx", "--board", "finance", code=1)
        self.assertIn("Board finance did not review this task. Its boards: " + ", ".join(self.boards()), error)

    def test_new_files_left_out_of_git_are_named_when_the_working_tree_is_delivered(self):
        (self.root / "extra.py").write_text("X = 1\n", encoding="utf-8")
        self.deliver()
        task = self.task("sx")
        task["result"]["revision"] = "working tree"
        write_json(self.state / "tasks" / "sx.json", task)
        output, _ = self.run_cli("task", "diff-review", "sx", "--board", "security")
        line = next(line for line in output.splitlines() if line.startswith("New files Git does not track yet"))
        self.assertIn("not in the diff: read them in full:", line)
        self.assertIn("extra.py", line)


class FindingTests(DeliveredReviewCase):
    def setUp(self):
        super().setUp()
        self.deliver()

    def test_a_malformed_file_is_refused_with_every_problem_and_nothing_is_recorded(self):
        # OGK-TASK-048
        _, error = self.submit({"board": "security", "findings": [
            {"file": "notes.md", "line": 0, "severity": "critical", "action": "fix", "finding": ""},
            {"file": "status.py", "line": 4, "severity": "important", "action": "defer", "finding": "Later."}]},
            code=1)
        for problem in ("findings[0].file: got 'notes.md'; name a file of the change: status.py",
                        "findings[0].line: got 0", "findings[0].severity: got 'critical'; write blocking, important, minor",
                        "findings[0].finding: say what is wrong",
                        "findings[1]: status.py:4 is a line this change added: a problem the change causes is not "
                        "deferred"):
            self.assertIn(problem, error)
        self.assertIn("findings.json: The findings cannot be recorded", error)
        self.assertNotIn("delivered_review", self.task("sx"))

    def test_a_deferred_finding_on_a_line_the_change_kept_is_accepted(self):
        self.submit({"board": "engineering", "findings": [
            {"file": "status.py", "line": 1, "severity": "minor", "action": "defer", "finding": "Name the constant."}]})
        self.assertEqual(self.task("sx")["delivered_review"]["boards"]["engineering"]["findings"][0]["action"], "defer")

    def test_a_blocking_finding_is_counted_and_stays_open_at_the_closing(self):
        output, _ = self.submit({"board": "security", "findings": [
            {"file": "status.py", "line": 5, "severity": "blocking", "action": "fix",
             "finding": "Any user's requests are returned."}]})
        self.assertIn("security: 1 finding recorded.", output)
        self.assertIn(f"1 board of {len(self.boards())} reviewed the delivered diff; 1 blocking finding "
                      "(security, status.py:5).", output)
        for board in self.boards():
            if board != "security":
                self.submit({"board": board, "findings": []})
        output, _ = self.submit({"board": "security", "findings": [
            {"file": "status.py", "line": 5, "severity": "blocking", "action": "fix",
             "finding": "Any user's requests are returned."}]})
        self.assertIn("Next: fix it, record the new revision with openguildkit task result sx", output)
        output, _ = self.run_cli("task", "complete", "sx", "--by", "Camille", typed="sx")
        self.assertTrue(output.startswith("done-with-reservations"))
        closing = json.loads(self.run_cli("task", "show", "sx", "--closing")[0])
        group = next(group for group in closing["open_points"] if group["group"] == delivered_review.FINDINGS_GROUP)
        self.assertEqual(group["points"], ["security: blocking finding at status.py:5 (fix): Any user's requests are "
                                           "returned."])
        self.run_cli("task", "export", "sx")
        record = read_json(self.state / "decisions" / "sx.json")
        self.assertEqual(record["delivered_review"]["security"]["findings"][0]["line"], 5)
        self.assertIn(delivered_review.FINDINGS_GROUP, json.dumps(record["result"]["closing"]))

    def test_a_review_of_an_earlier_revision_is_an_open_point_once_a_new_one_is_delivered(self):
        self.submit({"board": "security", "findings": []})
        (self.root / "status.py").write_text("STATUS = 2\n", encoding="utf-8")
        self.git("commit", "-qam", "Again")
        self.run_cli("task", "verify", "sx")
        output, _ = self.run_cli("task", "diff-review", "sx")
        self.assertIn("[reviewed an earlier revision]", output)
        self.run_cli("task", "complete", "sx", "--by", "Camille", typed="sx")
        points = [point for group in self.task("sx")["result"]["closing"]["open_points"] for point in group["points"]]
        self.assertTrue(any(point.startswith("security reviewed revision") and "out of date" in point
                            for point in points), points)

    def test_findings_without_blocking_ones_leave_the_closing_as_it_was(self):
        for board in self.boards():
            self.submit({"board": board, "findings": [] if board != "qa" else [
                {"file": "status.py", "line": 1, "severity": "minor", "action": "fix", "finding": "Typo."}]})
        output, _ = self.run_cli("task", "diff-review", "sx")
        self.assertIn("no blocking finding.\nNext: openguildkit task complete sx.", output)
        output, _ = self.run_cli("task", "complete", "sx")
        self.assertEqual(output.splitlines()[0], "done")

    def test_the_review_is_refused_after_the_closing(self):
        self.run_cli("task", "complete", "sx")
        _, error = self.run_cli("task", "diff-review", "sx", code=1)
        self.assertIn("after task result and before task complete", error)

    def test_a_task_closed_without_a_review_exports_no_findings(self):
        self.run_cli("task", "complete", "sx")
        self.run_cli("task", "export", "sx")
        self.assertNotIn("delivered_review", read_json(self.state / "decisions" / "sx.json"))


if __name__ == "__main__":
    unittest.main()
