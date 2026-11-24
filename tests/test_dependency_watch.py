"""The scheduled dependency watch: how its register pull request passes the guard, and where its scanner runs."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json

from tests.support import CapturedCli
from tests.test_workflows import parse, run_text, steps

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
FIXTURES = Path(__file__).with_name("fixtures") / "alerts"
TEMPLATE = REPO / "integrations" / "github" / "openguildkit-dependency-watch.yml"
ALERT = "npm:semver:ghsa-c2qf-rxjj-qqgw"
BRANCH = "openguildkit/dependency-watch"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}


class RegisterPullRequestGuardTests(CapturedCli, unittest.TestCase):
    """A pull request that changes only .openguildkit/alerts.json, as the scheduled job opens it, under enforce."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, env=GIT_ENV)

    def approve_review_task(self, task_id):
        self.run_cli("task", "new", "Review the alerts the weekly dependency watch imported.", "--id", task_id)
        self.run_cli("task", "consult", task_id, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=task_id):
            self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Weekly review")

    def test_the_register_pull_request_passes_enforce_once_a_review_task_exports_its_decision(self):
        profile = {**json.loads((EXAMPLE / "profile.json").read_text()), "guard": "enforce"}
        write_json(self.root / "profile.json", profile)
        self.git("init", "-q", "-b", "main")
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        # What the scheduled job pushes: the imported register, alone, on its branch.
        self.git("checkout", "-q", "-b", BRANCH)
        self.run_cli("alerts", "import", FIXTURES / "npm-audit.json")
        self.git("add", ".openguildkit/alerts.json")
        self.git("commit", "-q", "-m", "Update the dependency alert register")
        output, _ = self.run_cli("guard", "--ci", "--base", "main", "--json", code=1)
        result = json.loads(output)
        self.assertEqual(result["mode"], "enforce")
        self.assertIn("no exported decision", result["problems"][0])

        # What docs/alerts.md says: the review task is approved on the base branch, then the reviewer reviews the
        # alerts on the job's branch, commits the register and exports the decision there.
        self.git("checkout", "-q", "main")
        self.approve_review_task("alert-review")
        self.git("checkout", "-q", BRANCH)
        self.run_cli("alerts", "set", ALERT, "--status", "dismissed", "--by", "Camille", "--reason", "Build tool only")
        self.git("commit", "-q", "-am", "Review the new alerts")
        exported = self.run_cli("task", "export", "alert-review")[0].strip().splitlines()[-1]
        self.assertEqual(json.loads((self.root / exported).read_text())["files"], [".openguildkit/alerts.json"])
        self.git("add", "-f", exported)
        self.git("commit", "-q", "-m", "Decision of the register review")
        result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json")[0])
        self.assertEqual((result["decisions"], result["problems"], result["ok"]), (["alert-review"], [], True))

    def test_the_template_and_the_docs_say_how_the_pull_request_passes_the_guard_and_why_its_checks_wait(self):
        alerts = (REPO / "docs" / "alerts.md").read_text(encoding="utf-8")
        integrations = (REPO / "integrations" / "README.md").read_text(encoding="utf-8")
        header = TEMPLATE.read_text(encoding="utf-8").split("\nname:", 1)[0]
        for text in (alerts, header):
            with self.subTest(text=text[:40]):
                self.assertIn("guard --ci", text)
                self.assertIn("GITHUB_TOKEN", text)
                self.assertIn("approv", text)
        self.assertIn("### The pull request and the guard", alerts)
        for command in ("openguildkit task new", "task decide", "git checkout openguildkit/dependency-watch",
                        "openguildkit task export"):
            self.assertIn(command, alerts)
        self.assertIn("docs/alerts.md#the-pull-request-and-the-guard", integrations)


class DependencyWatchTemplateTests(unittest.TestCase):
    def setUp(self):
        self.workflow = parse(TEMPLATE)
        self.jobs = self.workflow["jobs"]

    def test_the_scanner_runs_in_a_read_only_job_and_hands_its_report_as_an_artifact(self):
        self.assertEqual(self.workflow["permissions"], {})
        scan, watch = self.jobs["scan"], self.jobs["watch"]
        self.assertEqual(scan["permissions"], {"contents": "read"})
        self.assertIn("pip-audit", run_text(scan))
        upload = next(step for step in steps(scan) if str(step.get("uses", "")).startswith("actions/upload-artifact@"))
        self.assertEqual(upload["with"]["path"], "report.json")
        self.assertEqual(watch["needs"], "scan")
        self.assertEqual(watch["permissions"], {"contents": "write", "issues": "write", "pull-requests": "write"})
        download = next(step for step in steps(watch)
                        if str(step.get("uses", "")).startswith("actions/download-artifact@"))
        self.assertEqual(download["with"]["name"], upload["with"]["name"])
        script = run_text(watch)
        self.assertNotIn("pip-audit", script)
        self.assertNotIn("requirements", script)
        self.assertIn("openguildkit alerts import report.json", script)
        installs = [line for line in script.splitlines() if "pip install" in line]
        self.assertEqual(installs, ['python -m pip install "$RUNNER_TEMP/$OPENGUILDKIT_WHEEL"'])


if __name__ == "__main__":
    unittest.main()
