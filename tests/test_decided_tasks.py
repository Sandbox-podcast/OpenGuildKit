"""Messages on a task a person already decided, and output read by a closed pipe (issue #170)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json
from tests.support import CapturedCli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"


class DecidedTaskTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Support portal", "stack": ["Python"], "packs": [], "checks": [command]})
        self.run_cli("init", "--answers", self.root / "profile.json")

    def reviewed(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each request's status."}
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")

    def approved(self):
        self.reviewed()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

    def done(self):
        self.approved()
        self.run_cli("task", "verify", TASK)
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        rules = [{"check": c["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"}
                 for c in checks if c["kind"] == "rule"]
        write_json(self.root / "result.json", {"pull_request": "https://github.com/example/portal/pull/7", "checks": rules,
                                               "criteria": [{"criterion": "Users only see their own requests.",
                                                             "status": "met", "evidence": "tests/test_access.py"}]})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.run_cli("task", "complete", TASK)

    def decide_again(self):
        return self.run_cli("task", "decide", TASK, "--approve", "--by", "Agent", "--reason", "again", code=1)[1]

    def test_deciding_an_approved_task_says_it_is_already_approved_and_by_whom(self):
        self.approved()
        error = self.decide_again()
        self.assertIn(f"Task {TASK} is already approved by Camille on ", error)
        self.assertIn(f"Next: openguildkit task handoff {TASK}", error)
        self.assertNotIn("Record the boards' review", error)

    def test_deciding_a_completed_task_says_it_is_already_decided_with_its_status(self):
        self.done()
        status = json.loads(self.run_cli("task", "show", TASK, "--json")[0])["status"]
        error = self.decide_again()
        self.assertIn(f"Task {TASK} is already decided and {status}: approved by Camille on ", error)
        self.assertIn(f"--follows {TASK}", error)

    def test_deciding_a_task_with_changes_requested_names_the_next_command(self):
        self.reviewed()
        self.run_cli("task", "decide", TASK, "--request-changes", "--by", "Camille", "--reason", "Narrow it")
        error = self.decide_again()
        self.assertIn("already has changes requested by Camille", error)
        self.assertIn(f"Next: openguildkit task consult {TASK}", error)
        error = self.run_cli("task", "handoff", TASK, code=1)[1]
        self.assertIn("changes requested by Camille: there is nothing to implement", error)

    def test_a_draft_still_asks_for_the_review(self):
        self.run_cli("task", "new", "Show statuses.", "--id", "draft")
        self.assertIn("Record the boards' review before deciding.",
                      self.run_cli("task", "decide", "draft", "--approve", "--by", "A", "--reason", "r", code=1)[1])

    def test_the_handoff_of_a_completed_task_says_so_and_shows_the_handoff_again(self):
        self.done()
        output, _ = self.run_cli("task", "handoff", TASK)
        self.assertIn("(task done", output.splitlines()[0])
        self.assertIn("nothing is left to implement", output)
        self.assertIn("## Approved project scope", output)

    def test_the_progress_of_a_completed_task_shows_the_recorded_passes(self):
        self.done()
        output, _ = self.run_cli("task", "progress", TASK)
        boards = json.loads(self.run_cli("task", "show", TASK, "--json")[0])["consultation"]["boards"]
        self.assertEqual(output.splitlines(), [f"{board}: done (in review)" for board in boards])
        self.assertNotIn("missing", output)

    def test_a_damaged_record_names_its_file_and_the_command_to_replace_it(self):
        self.approved()
        path = self.root / ".openguildkit" / "tasks" / f"{TASK}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("answers")
        write_json(path, record)
        error = self.run_cli("task", "show", TASK, code=1)[1]
        self.assertIn("an approved task needs answers", error)
        self.assertIn(f"Restore .openguildkit/tasks/{TASK}.json from a backup, or delete that file and open a new task "
                      "with openguildkit task new.", error)
        listed = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertIn("delete that file", listed[0]["next"])

    @unittest.skipIf(os.name == "nt", "Windows has no /dev/null; its NUL device is not a path the export can test.")
    def test_the_decision_record_can_be_written_to_a_special_file(self):
        self.approved()
        self.run_cli("task", "export", TASK, "--output", os.devnull)

    @unittest.skipIf(os.name == "nt", "A closed pipe raises another error on Windows, and the test relies on POSIX pipes.")
    def test_output_read_by_head_ends_quietly(self):
        lines = "\n".join(f"Line {index} of a long brief." for index in range(20000))
        (self.root / "big.md").write_text(lines, encoding="utf-8")
        self.run_cli("task", "new", "--file", self.root / "big.md", "--id", "big")
        command = [sys.executable, "-m", "openguildkit", "--project", str(self.root), "task", "show", "big"]
        environment = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        process.stdout.readline()
        process.stdout.close()
        stderr = process.stderr.read()
        process.stderr.close()
        self.assertEqual(process.wait(timeout=60), 0, stderr)
        self.assertEqual(stderr, b"")


if __name__ == "__main__":
    unittest.main()
