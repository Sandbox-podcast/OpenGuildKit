import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.storage import write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


class ResultTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def approved(self, exit_code=0, **extra):
        command = f'"{sys.executable}" -c "import sys; print(\'checked\'); sys.exit({exit_code})"'
        profile = {"name": "Portal", "stack": ["Python"], "packs": ["python"], "checks": [command], **extra}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

    def rule_outcomes(self):
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        return [
            {"check": check["id"], "status": "not-applicable", "reason": "No change in this area.", "owner": "Camille"}
            for check in checks if check["kind"] == "rule"
        ]

    def test_a_passing_mandatory_check_with_evidence_lets_the_task_finish(self):
        self.approved()
        output, _ = self.run_cli("task", "verify", TASK)
        self.assertIn("command:1: passed", output)
        record = json.loads(self.run_cli("task", "show", TASK)[0])
        log = self.root / record["result"]["checks"][0]["evidence"]
        self.assertIn("checked", log.read_text(encoding="utf-8"))
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("is not reported", error)
        write_json(self.root / "result.json", {
            "pull_request": "https://github.com/example/portal/pull/7",
            "criteria": [{"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/test_access.py"}],
            "checks": self.rule_outcomes(),
        })
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")
        record = json.loads(self.run_cli("task", "show", TASK)[0])
        self.assertEqual(record["status"], "done")
        self.assertEqual(record["result"]["pull_request"], "https://github.com/example/portal/pull/7")

    def test_a_failed_or_unproven_mandatory_check_blocks_completion(self):
        self.approved(exit_code=1, required_rules=["python"])
        self.run_cli("task", "verify", TASK)
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": self.rule_outcomes()})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("command:1 is mandatory and failed", error)
        self.assertIn("rule:python/", error)

    def test_skipped_checks_need_a_reason_and_an_owner(self):
        self.approved()
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [],
                                               "checks": [{"check": "command:1", "status": "skipped"}]})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("reason", error)
        write_json(self.root / "result.json", {"criteria": [], "checks": []})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("revision or pull request", error)


if __name__ == "__main__":
    unittest.main()
