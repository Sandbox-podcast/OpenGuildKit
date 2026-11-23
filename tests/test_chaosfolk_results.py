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

from tests.support import CapturedCli, run_cli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


def summary(*results):
    return {"schema_version": 1, "results": [
        {"name": name, "scenario": f"/ci/qa/scenarios/{name}", "status": status, "seconds": 1.5, "message": message}
        for name, status, message in results
    ]}


class ChaosFolkResultTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"personal_data": False, "name": "Portal", "stack": ["Python", "ChaosFolk"], "packs": [], "checks": [command]})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK))
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        self.run_cli("task", "verify", TASK)
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json"))
        rules = [{"check": c["id"], "status": "passed", "evidence": "qa/replays.md"} for c in checks if c["kind"] == "rule"]
        write_json(self.root / "rules.json", {"revision": "abc1234", "criteria": [], "checks": rules})
        self.run_cli("task", "result", TASK, "--file", self.root / "rules.json")

    def replay(self, *results):
        path = self.root / "qa-results" / "summary.json"
        write_json(path, summary(*results))
        return self.run_cli("task", "verify", TASK, "--chaosfolk", path, "--tool-version", "b406600")

    def test_a_regression_or_an_unusable_run_blocks_completion_and_a_passing_replay_clears_it(self):
        self.replay(("h02-save.json", "failed", "Draft not saved"), ("h03-login.json", "error", "Browser did not start"))
        _, error = io.StringIO(), None
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--project", str(self.root), "task", "complete", TASK]), 1)
        self.assertIn("chaosfolk:h02-save.json failed", stderr.getvalue())
        self.assertIn("chaosfolk:h03-login.json gave no verdict", stderr.getvalue())

        self.replay(("h02-save.json", "passed", ""), ("h03-login.json", "passed", ""))
        comparison = json.loads(self.run_cli("task", "runs", TASK, "--json"))
        self.assertEqual(comparison["changed"]["h02-save.json"], ["failed", "passed"])
        self.assertEqual(self.run_cli("task", "complete", TASK).strip(), "done")
        record = json.loads(self.run_cli("task", "show", TASK))
        run = record["result"]["runs"][-1]
        self.assertEqual(run["version"], "b406600")
        self.assertEqual(run["summary"], "qa-results/summary.json")

    def test_a_file_that_is_not_a_summary_is_refused(self):
        bad = self.root / "bad.json"
        write_json(bad, {"results": []})
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--project", str(self.root), "task", "verify", TASK, "--chaosfolk", str(bad)]), 1)
        self.assertIn("not a ChaosFolk regression summary", stderr.getvalue())


    def complete_error(self):
        return run_cli(self.root, "task", "complete", TASK, expect=1).stderr

    def test_a_scenario_listed_twice_keeps_its_failure(self):
        output = self.replay(("login", "failed", "500 on submit"), ("login", "passed", ""), ("checkout", "passed", ""))
        self.assertIn("chaosfolk:login: failed", output)
        self.assertNotIn("Ready", output)
        record = json.loads(self.run_cli("task", "show", TASK))
        self.assertEqual(record["result"]["runs"][-1]["outcomes"]["login"], "failed")
        self.assertEqual([c["check"] for c in record["result"]["checks"]].count("chaosfolk:login"), 1)
        self.assertIn("chaosfolk:login failed", self.complete_error())

    def test_a_scenario_missing_from_the_last_replay_is_not_counted_as_passed(self):
        self.replay(("a.json", "passed", ""), ("b.json", "passed", ""))
        output = self.replay(("b.json", "passed", ""))
        self.assertIn("chaosfolk:a.json: missing", output)
        record = json.loads(self.run_cli("task", "show", TASK))
        self.assertNotIn("chaosfolk:a.json", [c["check"] for c in record["result"]["checks"]])
        self.assertIn("chaosfolk:a.json ran in the previous replay and is missing from the last one", self.complete_error())


if __name__ == "__main__":
    unittest.main()
