"""Run one pass per board, resume a failed pass and assemble the review."""

import copy
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
        self.assertNotIn("## Project scope and active rules", brief)
        self.assertIn("## Task", brief)
        self.assertIn(f"openguildkit task brief {TASK_ID} --scope", brief)
        self.assertLess(len(brief), 16_000)
        scope = self.run_cli("task", "brief", TASK_ID, "--scope").stdout
        self.assertTrue(scope.startswith("## Project scope and active rules"))
        self.assertNotIn("### product", scope)
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

    def test_one_submission_reports_every_problem_and_the_corrected_file_goes_through(self):
        self.consult_example()
        entry = copy.deepcopy(self.entries()["security"])
        path = self.write_json("security.json", entry)
        refused = self.run_cli("task", "submit", TASK_ID, "--file", path, expect=1)
        self.assertIn("pass was not started", refused.stderr)

        self.run_cli("task", "pass", TASK_ID, "security", "--mode", "subagent")
        entry["challenge"]["confidence"] = "top"
        entry["challenge"]["specialists"][0]["basis"] = "seen"
        entry["challenge"]["specialists"][1]["evidence_refs"] = [0]
        failed = self.run_cli("task", "submit", TASK_ID, "--file", self.write_json("bad.json", entry), expect=1).stderr
        for expected in ("challenge.confidence: must be one of low, medium, high (got 'top')",
                         "challenge.specialists[1].basis: must be one of observed, assumption, missing (got 'seen')",
                         "challenge.specialists[2].evidence_refs: [0] is not a valid position",
                         "counted from 1", "Correct the file and send it again", "no new pass is needed"):
            self.assertIn(expected, failed)

        def attempts():
            progress = json.loads(self.run_cli("task", "progress", TASK_ID, "--json").stdout)
            return next(item for item in progress if item["board"] == "security")["attempts"]

        self.assertEqual(attempts(), 1)
        shown = self.run_cli("task", "pass", TASK_ID, "security", "--show").stdout
        self.assertIn("# Board pass: security", shown)
        self.assertIn("the valid positions are 1 and 2; 0 is never valid", shown)
        self.assertEqual(attempts(), 1)

        self.run_cli("task", "submit", TASK_ID, "--file", self.write_json("security.json", self.entries()["security"]))
        self.assertEqual(attempts(), 1)
