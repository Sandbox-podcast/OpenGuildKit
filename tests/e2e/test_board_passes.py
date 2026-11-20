"""Run one pass per board, resume a failed pass and assemble the review."""

import json

from tests.e2e.test_cli_flow import EXAMPLE, TASK_ID, CliTestCase


class BoardPassTests(CliTestCase):
    def entries(self):
        review = json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))
        return {entry["id"]: entry for entry in review["boards"]}

    def test_each_board_gets_its_brief_and_a_failed_pass_is_retried_alone(self):
        self.consult_example()
        entries = self.entries()
        boards = list(entries)
        brief = self.run_cli("task", "pass", TASK_ID, "security", "--mode", "subagent").stdout
        self.assertIn("# Board pass: security", brief)
        self.assertIn("## Project scope and active rules", brief)
        self.assertIn('"id": "application-security"', brief)
        self.assertNotIn("### product", brief)

        self.run_cli("task", "submit", TASK_ID, "--file", self.write_json("security.json", entries["security"]))
        broken = {**entries["design"], "recommendation": " "}
        self.run_cli("task", "pass", TASK_ID, "design", "--mode", "subagent")
        failed = self.run_cli("task", "submit", TASK_ID, "--file", self.write_json("design.json", broken), expect=1)
        self.assertIn("recorded as failed", failed.stderr)

        progress = {item["board"]: item for item in json.loads(self.run_cli("task", "progress", TASK_ID, "--json").stdout)}
        self.assertEqual(progress["security"]["status"], "done")
        self.assertEqual(progress["design"]["status"], "failed")
        self.assertEqual(progress["product"]["status"], "missing")
        self.run_cli("task", "review", TASK_ID, "--summary", "Too early.", expect=1)

        self.run_cli("task", "pass", TASK_ID, "design", "--mode", "subagent")
        self.assertEqual(json.loads(self.run_cli("task", "progress", TASK_ID, "--json").stdout)[3]["status"], "started")
        self.run_cli("task", "submit", TASK_ID, "--file", self.write_json("design.json", entries["design"]))
        for board in boards:
            if board not in ("security", "design"):
                self.run_cli("task", "pass", TASK_ID, board)
                self.run_cli("task", "submit", TASK_ID, "--file", self.write_json(f"{board}.json", entries[board]))
        progress = json.loads(self.run_cli("task", "progress", TASK_ID, "--json").stdout)
        self.assertTrue(all(item["status"] == "done" for item in progress))
        self.assertEqual(next(item for item in progress if item["board"] == "design")["attempts"], 2)

        self.assertEqual(self.run_cli("task", "review", TASK_ID, "--summary", "Read-only scope first.").stdout.strip(), "reviewed")
        record = self.task_record()
        self.assertEqual(record["review"]["execution"], "mixed")
        self.assertNotIn("passes", record)
        self.assertIn("# Decision brief", self.run_cli("task", "challenge", TASK_ID).stdout)

    def test_a_new_consultation_starts_the_passes_again(self):
        self.consult_example()
        self.run_cli("task", "pass", TASK_ID, "security")
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")
        progress = json.loads(self.run_cli("task", "progress", TASK_ID, "--json").stdout)
        self.assertTrue(all(item["status"] == "missing" for item in progress))
