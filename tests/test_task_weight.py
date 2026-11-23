"""What the agent reads along a task, without the parts it already holds (issue 41)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from openguildkit.storage import write_json
from tests.test_results import GDPR_DPIA, GDPR_RECORD, TASK, ResultCase

from tests.support import CapturedCli

SMALL_BUG = {"kind": "bug", "surface": "service", "data": "internal", "research": "local", "concerns": ["none"],
             "context": "The CSV export of request statuses leaves the status column empty."}
# The instructions every pass shares: how to fill an entry, and the shapes of an evidence item and a blocker.
SHARED = ("## How to fill the entry", "Write each evidence item in this shape:", "and each blocker in this shape:")


class TaskWeightTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        write_json(self.root / "setup.json", {"name": "Portal", "stack": ["Python"]})
        self.cli("init", "--answers", self.root / "setup.json")
        write_json(self.root / "answers.json", SMALL_BUG)
        self.cli("task", "new", "Fix the CSV export of request statuses", "--id", "small1")

    def test_the_follow_ups_of_the_smallest_bug_fit_in_a_kilobyte(self):
        whole = self.cli("task", "questions", "small1", "--answers", self.root / "answers.json")
        short = self.cli("task", "questions", "small1", "--answers", self.root / "answers.json", "--follow-ups")
        self.assertEqual(set(json.loads(short)), {"follow_ups", "open_points"})
        self.assertEqual({key: json.loads(whole)[key] for key in ("follow_ups", "open_points")}, json.loads(short))
        self.assertEqual([item["id"] for item in json.loads(short)["follow_ups"]], ["outcome"])
        self.assertLess(len(short.encode("utf-8")), 1024)
        self.assertGreater(len(whole.encode("utf-8")), 4 * len(short.encode("utf-8")))

    def test_passes_after_the_first_of_a_sequence_leave_out_the_instructions_they_share(self):
        self.cli("task", "consult", "small1", "--answers", self.root / "answers.json")
        boards = json.loads(self.cli("task", "show", "small1"))["consultation"]["boards"]
        self.assertGreaterEqual(len(boards), 3)
        alone = {board: self.cli("task", "brief", "small1", "--board", board) for board in boards}
        passes = {board: self.cli("task", "pass", "small1", board, "--mode", "sequential") for board in boards}
        first, *others = boards
        self.assertEqual(passes[first], alone[first])
        for board in others:
            with self.subTest(board=board):
                for text in SHARED:
                    self.assertIn(text, alone[board])
                    self.assertNotIn(text, passes[board])
                self.assertIn(f"as in the {first} pass of this sequence, printed again by openguildkit task brief "
                              f"small1 --board {first}.", passes[board])
                # The same rules, about 1.5 KB less to read.
                rules = alone[board][alone[board].index("## Rules of this board's packs"):]
                self.assertTrue(passes[board].endswith(rules))
                self.assertLess(len(passes[board].encode("utf-8")), len(alone[board].encode("utf-8")) - 1_400)

    def test_passes_run_as_subagents_each_print_the_shared_instructions(self):
        self.cli("task", "consult", "small1", "--answers", self.root / "answers.json")
        for board in json.loads(self.cli("task", "show", "small1"))["consultation"]["boards"]:
            printed = self.cli("task", "pass", "small1", board, "--mode", "subagent")
            for text in SHARED:
                self.assertIn(text, printed)


class RevisionAndClosingTests(ResultCase):
    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_the_result_takes_the_revision_task_verify_read(self):
        self.approved(git_project=True)
        head = self.git("rev-parse", "HEAD")
        self.run_cli("task", "verify", TASK)
        template = json.loads(self.run_cli("task", "result", TASK, "--template")[0])
        self.assertEqual((template["revision"], template["pull_request"]), (head, ""))
        write_json(self.root / "result.json", {"criteria": [], "checks": self.rule_outcomes()})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.assertEqual(self.record()["result"]["revision"], head)

    def test_a_result_without_a_revision_is_still_refused_before_any_is_recorded(self):
        self.approved()
        write_json(self.root / "result.json", {"criteria": [], "checks": self.rule_outcomes()})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("Name the delivered revision or pull request", error)
        self.assertEqual(json.loads(self.run_cli("task", "result", TASK, "--template")[0])["revision"], "")

    def test_the_list_points_to_a_command_that_prints_only_the_open_points(self):
        self.approved(patterns=["gdpr-personal-data"])
        self.run_cli("task", "verify", TASK)
        (self.root / "docs").mkdir()
        for name in ("record.md", "dpia.md"):
            (self.root / "docs" / name).write_text("Kept by the data protection officer.", encoding="utf-8")
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        answers = [{"check": c["id"], "status": "skipped" if c["id"] == "rule:python/follow-python-style"
                    else "not-applicable", "reason": f"Nothing here touches {c['id']}.", "owner": "Camille"}
                   for c in checks if c["kind"] == "rule" and c["concerned"]]
        answers += [{"check": GDPR_RECORD, "status": "passed", "evidence": "docs/record.md", "owner": "Dana (DPO)"},
                    {"check": GDPR_DPIA, "status": "passed", "evidence": "docs/dpia.md", "owner": "Dana (DPO)"}]
        write_json(self.root / "result.json", {"criteria": [{"criterion": "Users only see their own requests.",
                                                             "status": "met", "evidence": "tests/test_access.py"}],
                                               "checks": answers})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.assertEqual(self.run_cli("task", "complete", TASK, "--by", "CM", typed=TASK)[0].splitlines()[0],
                         "done-with-reservations")
        listed = json.loads(self.run_cli("task", "list", "--json")[0])[0]["next"]
        self.assertEqual(listed, f"Done with reservations: see the open points with openguildkit task show {TASK} "
                                 "--closing.")
        closing = self.run_cli("task", "show", TASK, "--closing")[0]
        whole = self.run_cli("task", "show", TASK)[0]
        self.assertEqual(json.loads(closing), {"id": TASK, "status": "done-with-reservations", "by": "CM",
                                               "open_points": self.record()["result"]["closing"]["open_points"]})
        self.assertIn("rule:python/follow-python-style is skipped", closing)
        self.assertLess(len(closing.encode("utf-8")), 2_000)
        self.assertGreater(len(whole.encode("utf-8")), 20 * len(closing.encode("utf-8")))
        # A teammate who has only the exported record reads the same open points.
        self.run_cli("task", "export", TASK)
        (self.root / ".openguildkit" / "tasks" / f"{TASK}.json").unlink()
        self.assertEqual(self.run_cli("task", "show", TASK, "--closing")[0], closing)

    def test_an_open_task_has_no_closing_to_show(self):
        self.approved()
        _, error = self.run_cli("task", "show", TASK, "--closing", code=1)
        self.assertIn("Only a completed task has a closing with its open points.", error)
        self.assertIn(f"Next: openguildkit task handoff {TASK}", error)


if __name__ == "__main__":
    unittest.main()
