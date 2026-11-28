import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json
from tests.support import CapturedCli, run_cli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"


class TaskListTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text()))
        self.run_cli("init", "--answers", self.root / "profile.json")

    def approved(self, task_id):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
        self.run_cli("task", "consult", task_id, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id))
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=task_id):
            self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille Martin", "--reason", "Agreed")

    def test_tasks_are_listed_by_status_owner_and_period_with_their_next_step(self):
        self.approved("request-status")
        self.run_cli("task", "new", "Show the request history.", "--id", "history")
        rows = {row["id"]: row for row in json.loads(self.run_cli("task", "list", "--json"))}
        self.assertEqual(rows["history"]["status"], "draft")
        self.assertIn("questionnaire", rows["history"]["next"])
        self.assertEqual(rows["request-status"]["owner"], "Camille Martin")
        self.assertIn("record the results", rows["request-status"]["next"])
        approved = json.loads(self.run_cli("task", "list", "--status", "approved", "--json"))
        self.assertEqual([row["id"] for row in approved], ["request-status"])
        self.assertEqual(json.loads(self.run_cli("task", "list", "--owner", "camille martin", "--json"))[0]["id"], "request-status")
        self.assertEqual(json.loads(self.run_cli("task", "list", "--since", "2999-01-01", "--json")), [])

    def test_a_period_that_is_not_a_date_is_refused_for_each_option(self):
        """Issue 380: any text was accepted, so --until listed everything and --since listed nothing."""
        self.run_cli("task", "new", "Show the request history.", "--id", "history")
        for option in ("--since", "--until"):
            for value in ("garbage", "2026-13-45", "2026-02-30", "20261125", ""):
                with self.subTest(option=option, value=value):
                    result = run_cli(self.root, "task", "list", option, value, expect=1)
                    self.assertEqual(result.stdout, "")
                    self.assertTrue(result.stderr.startswith(f"OpenGuildKit: {option}: "), result.stderr)
                    self.assertIn("YYYY-MM-DD", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_the_period_bounds_are_inclusive_days(self):
        self.run_cli("task", "new", "Show the request history.", "--id", "history")
        created = json.loads(self.run_cli("task", "show", "history"))["created_at"][:10]
        day = date.fromisoformat(created)

        def listed(*period):
            return [row["id"] for row in json.loads(self.run_cli("task", "list", *period, "--json"))]

        self.assertEqual(listed("--since", created), ["history"])
        self.assertEqual(listed("--until", created), ["history"])
        self.assertEqual(listed("--since", created, "--until", created), ["history"])
        self.assertEqual(listed("--since", (day - timedelta(days=1)).isoformat()), ["history"])
        self.assertEqual(listed("--until", (day + timedelta(days=1)).isoformat()), ["history"])
        self.assertEqual(listed("--since", (day + timedelta(days=1)).isoformat()), [])
        self.assertEqual(listed("--until", (day - timedelta(days=1)).isoformat()), [])

    def test_a_follow_up_task_carries_the_previous_decision(self):
        self.approved("request-status")
        self.run_cli("task", "new", "Add request history to the portal.", "--id", "history", "--follows", "request-status")
        self.run_cli("task", "consult", "history", "--answers", EXAMPLE / "answers.json")
        record = json.loads(self.run_cli("task", "show", "history"))
        self.assertEqual(record["consultation"]["scope"]["follows"]["decision"]["by"], "Camille Martin")
        self.assertEqual(json.loads(self.run_cli("task", "list", "--json"))[0]["follows"], "request-status")
        self.run_cli("task", "new", "x", "--id", "orphan", "--follows", "history", code=1)

    def test_a_selected_record_is_shared_without_internal_reviews(self):
        self.approved("request-status")
        target = self.root / "shared" / "request-status.json"
        self.run_cli("task", "export", "request-status", "--output", target)
        shared = json.loads(target.read_text())
        self.assertEqual(shared["decision"]["by"], "Camille Martin")
        self.assertNotIn("review", shared)
        self.assertNotIn("open_questions", json.dumps(shared))


if __name__ == "__main__":
    unittest.main()
