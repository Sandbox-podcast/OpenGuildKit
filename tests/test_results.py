import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.results import validate_result
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

    def approved(self, exit_code=0, answers=None, **extra):
        command = f'"{sys.executable}" -c "import sys; print(\'checked\'); sys.exit({exit_code})"'
        profile = {"name": "Portal", "stack": ["Python"], "packs": ["python"], "checks": [command], **extra}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        if answers:
            write_json(self.root / "answers.json", {**json.loads((EXAMPLE / "answers.json").read_text()), **answers})
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json" if answers else EXAMPLE / "answers.json")
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
        output, _ = self.run_cli("task", "verify", TASK)
        self.assertIn("checked", output)
        self.assertIn(".openguildkit/tasks/", output)
        self.assertIn("command:1 is mandatory and failed", output)
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": self.rule_outcomes()})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("command:1 is mandatory and failed", error)
        self.assertIn("rule:python/", error)
        self.assertIn("checked", error)

    def test_a_person_can_record_an_environment_reservation_for_a_project_command(self):
        self.approved(exit_code=1)
        options = ("--unavailable", "command:1=Dependencies unavailable offline", "--by", "Camille")
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("task", "verify", TASK, *options, code=1)
        self.assertIn("interactive terminal", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            _, error = self.run_cli("task", "verify", TASK, *options, "--chaosfolk", "unused.json", code=1)
            self.assertIn("without --chaosfolk", error)
            output, _ = self.run_cli("task", "verify", TASK, *options)
        self.assertIn("command:1: skipped", output)
        self.assertIn("Dependencies unavailable offline", output)
        self.report(*self.rule_outcomes())
        output, _ = self.run_cli("task", "complete", TASK)
        self.assertIn("done", output)
        self.assertIn("Dependencies unavailable offline", output)

    def test_task_verify_explains_how_to_add_project_commands(self):
        self.approved(checks=[])
        output, _ = self.run_cli("task", "verify", TASK)
        self.assertIn("No project check command is configured", output)
        self.assertIn(".openguildkit/project.json (checks)", output)

    def test_skipped_checks_need_a_reason_and_an_owner(self):
        self.approved()
        rule = self.rule_outcomes()[0]["check"]
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [],
                                               "checks": [{"check": rule, "status": "skipped"}]})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("reason", error)
        write_json(self.root / "result.json", {"criteria": [], "checks": []})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("revision or pull request", error)


    def record(self):
        return json.loads(self.run_cli("task", "show", TASK)[0])

    def report(self, *checks, criteria=(), code=0):
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": list(criteria), "checks": list(checks)})
        return self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=code)

    def test_only_task_verify_records_a_command_check(self):
        self.approved(exit_code=1)
        self.assertIn("command:1: failed", self.run_cli("task", "verify", TASK)[0])
        _, error = self.report({"check": "command:1", "status": "passed", "evidence": "trust me"}, code=1)
        self.assertIn("task verify", error)
        checks = {item["check"]: item for item in self.record()["result"]["checks"]}
        self.assertEqual(checks["command:1"]["status"], "failed")

    def test_a_check_with_a_non_zero_exit_code_cannot_pass(self):
        self.approved()
        rule = self.rule_outcomes()[0]["check"]
        _, error = self.report({"check": rule, "status": "passed", "evidence": "ci.log", "exit_code": 1}, code=1)
        self.assertIn("exit_code", error)
        task, profile = self.record(), json.loads((self.root / ".openguildkit" / "project.json").read_text())
        with self.assertRaisesRegex(ValueError, "exit_code"):
            validate_result(task, profile, {"revision": "abc1234", "checks": [
                {"check": "command:1", "status": "passed", "evidence": "log", "exit_code": 2}]}, source="verify")

    def test_chaosfolk_checks_come_only_from_a_replay(self):
        self.approved()
        _, error = self.report({"check": "chaosfolk:anything", "status": "passed", "evidence": "trust me"}, code=1)
        self.assertIn("task verify --chaosfolk", error)
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": [],
                                               "run": {"tool": "chaosfolk", "outcomes": {}}})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)

    def test_a_task_with_an_expected_outcome_needs_a_criterion(self):
        self.approved(answers={"outcome": "Customers see the status of their own requests."})
        self.run_cli("task", "verify", TASK)
        _, error = self.report(*self.rule_outcomes(), code=1)
        self.assertIn("criterion", error)
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("acceptance criterion", error)
        self.report(*self.rule_outcomes(), criteria=[
            {"criterion": "Customers see the status of their own requests.", "status": "met", "evidence": "tests/test_status.py"}])
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")

    def test_results_refuse_a_record_that_no_longer_matches_its_approval(self):
        self.approved(exit_code=1)
        path = self.root / ".openguildkit" / "tasks" / f"{TASK}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["consultation"]["scope"]["checks"] = ["true"]
        record["consultation"]["scope"]["packs"] = []
        write_json(path, record)
        for action in (("verify",), ("complete",)):
            _, error = self.run_cli("task", *action, TASK, code=1)
            self.assertIn("no longer matches what was approved", error)
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": []})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("no longer matches what was approved", error)

    def test_results_refuse_a_task_whose_rules_changed(self):
        self.approved()
        path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile["packs"].append("web-accessibility")
        write_json(path, profile)
        self.run_cli("sync")
        _, error = self.run_cli("task", "verify", TASK, code=1)
        self.assertIn("changed", error)

    def test_the_result_template_lists_the_criteria_and_every_expected_check(self):
        outcome = "Customers see the status of their own requests."
        self.approved(answers={"outcome": outcome})
        output, notes = self.run_cli("task", "result", TASK, "--template")
        template = json.loads(output)
        self.assertEqual(template["criteria"][0]["criterion"], outcome)
        expected = [item["check"] for item in self.rule_outcomes()]
        self.assertEqual([item["check"] for item in template["checks"]], expected)
        self.assertIn("command:1", notes)
        self.assertIn("task verify", notes)
        self.run_cli("task", "verify", TASK)
        template["revision"] = "abc1234"
        template["criteria"][0].update(status="met", evidence="tests/test_status.py")
        for item in template["checks"]:
            item.update(status="not-applicable", reason="No change in this area.", owner="Camille")
        write_json(self.root / "filled.json", template)
        self.run_cli("task", "result", TASK, "--file", self.root / "filled.json")
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")


if __name__ == "__main__":
    unittest.main()
