import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.storage import write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


class PublishingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"name": "Support portal", "stack": ["Python"], "packs": [], "checks": [command]})
        self.run_cli("init", "--answers", self.root / "profile.json")

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def done_task(self, task_id=TASK, brief_file=EXAMPLE / "brief.md"):
        self.run_cli("task", "new", "--file", brief_file, "--id", task_id)
        answers = {**json.loads((EXAMPLE / "answers.json").read_text()), "outcome": "Customers see each request's status and next step."}
        write_json(self.root / "answers.json", answers)
        self.run_cli("task", "consult", task_id, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=task_id):
            self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Agreed")
        self.run_cli("task", "verify", task_id)
        checks = json.loads(self.run_cli("task", "checks", task_id, "--json")[0])
        rules = [{"check": c["id"], "status": "not-applicable", "reason": "Out of scope.", "owner": "Camille"} for c in checks if c["kind"] == "rule"]
        write_json(self.root / "result.json", {"pull_request": "https://github.com/example/portal/pull/7", "checks": rules,
                                               "criteria": [{"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/test_access.py"}]})
        self.run_cli("task", "result", task_id, "--file", self.root / "result.json")
        self.run_cli("task", "complete", task_id)

    def test_completed_tasks_become_reference_learn_and_dated_blog_pages(self):
        self.done_task()
        self.run_cli("task", "new", "Not finished yet.", "--id", "draft")
        self.run_cli("docs", "export", "--tasks", "draft", "--output", "docs-site", "--version", "1.4.0", code=1)
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.4.0")
        site = self.root / "docs-site"
        reference = (site / "reference" / f"{TASK}.md").read_text(encoding="utf-8")
        self.assertIn('project_version: "1.4.0"', reference)
        self.assertIn("Users only see their own requests.", reference)
        self.assertNotIn("tests/test_access.py", reference)
        self.assertNotIn("recommendation", reference)
        blog = next((site / "blog").glob(f"*-{TASK}.md"))
        self.assertRegex(blog.read_text(encoding="utf-8"), r'date: "\d{4}-\d{2}-\d{2}"')
        self.assertIn(f"(reference/{TASK}.md)", (site / "SUMMARY.md").read_text(encoding="utf-8"))

        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.5.0", "--sections", "reference,blog")
        self.assertIn('project_version: "1.5.0"', (site / "reference" / f"{TASK}.md").read_text(encoding="utf-8"))
        self.assertFalse((site / "learn" / f"{TASK}.md").exists())
        self.assertEqual(len(list((site / "reference").glob("*.md"))), 1)

    def test_export_refuses_a_folder_it_did_not_create(self):
        self.done_task()
        (self.root / "notes").mkdir()
        (self.root / "notes" / "team.md").write_text("# Team\n", encoding="utf-8")
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "notes", "--version", "1.0.0", code=1)

    def test_shares_record_recipients_end_date_and_revocation(self):
        until = (date.today() + timedelta(days=14)).isoformat()
        common = ["docs", "share", "add", "--deliverable", "docs-site/reference/request-status.md", "--portal", "https://docs.example.org/p/portal"]
        self.run_cli(*common, "--recipient", "not-an-email", "--until", until, "--by", "Camille", code=1)
        output, _ = self.run_cli(*common, "--recipient", "client@example.org", "--until", until, "--by", "Camille")
        self.assertIn("remove their access on", output)
        shares = json.loads(self.run_cli("docs", "share", "list", "--json")[0])
        self.assertEqual(shares[0]["state"], "active")
        self.run_cli("docs", "share", "check")
        state = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(state.read_text())
        data["shares"][0]["until"] = (date.today() - timedelta(days=1)).isoformat()
        state.write_text(json.dumps(data), encoding="utf-8")
        self.run_cli("docs", "share", "check", code=1)
        self.run_cli("docs", "share", "revoke", "--id", data["shares"][0]["id"], "--by", "Camille")
        self.run_cli("docs", "share", "check")
        self.assertIn("shares/", (self.root / ".openguildkit" / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
