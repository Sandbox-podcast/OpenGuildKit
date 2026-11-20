import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.deliverables import load_deliverables
from openguildkit.storage import write_json

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"


class DeliverableTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "p.json", {"name": "Portal", "stack": ["Python"], "tools": ["Brevo"]})
        self.run_cli("init", "--answers", self.root / "p.json")

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def approved_task(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "launch")
        self.run_cli("task", "consult", "launch", "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", "launch")[0])
        write_json(self.root / "r.json", {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())})
        self.run_cli("task", "review", "launch", "--file", self.root / "r.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="launch"):
            self.run_cli("task", "decide", "launch", "--approve", "--by", "Camille Martin", "--reason", "Launch agreed")

    def test_bundled_templates_link_a_method_inputs_approvals_and_checks(self):
        templates = load_deliverables(load_catalog())
        brief = templates["campaign-brief"]
        self.assertEqual(brief["method"], "marketing-campaign-planning")
        self.assertTrue(any(item["data"] == "internal" for item in brief["inputs"]))
        self.assertTrue(brief["tool_actions"])

    def test_a_draft_starts_from_an_approved_task_with_an_approved_tool(self):
        output, _ = self.run_cli("deliverable", "show", "campaign-brief")
        self.assertIn("Needs your approval (task authorize --action send-message)", output)
        self.run_cli("task", "new", "Plan the spring campaign.", "--id", "draft-task")
        self.run_cli("deliverable", "new", "campaign-brief", "--task", "draft-task", "--tool", "Brevo", "--output", "brief.md", code=1)
        self.approved_task()
        _, error = self.run_cli("deliverable", "new", "campaign-brief", "--task", "launch", "--tool", "Mailchimp", "--output", "brief.md", code=1)
        self.assertIn("not an approved tool", error)
        output, _ = self.run_cli("deliverable", "new", "campaign-brief", "--task", "launch", "--tool", "Brevo", "--output", "brief.md")
        self.assertIn("Audience segment, described without personal data (internal data)", output)
        draft = (self.root / "brief.md").read_text(encoding="utf-8")
        self.assertIn('approved_by: "Camille Martin"', draft)
        self.assertEqual(json.loads(self.run_cli("task", "show", "launch")[0])["deliverables"][0]["tool"], "Brevo")

        problems, _ = self.run_cli("deliverable", "check", "brief.md", code=1)
        self.assertIn("placeholder", problems)
        self.assertIn("claim-substantiated", problems)
        filled = draft.replace("TODO: each source with its date or link", "Customer interviews, 2026-11-02").replace("TODO", "Filled.")
        for check in ("claim-substantiated", "consent-confirmed", "measurement-ready"):
            filled = filled.replace(f"- [ ] {check}:", f"- [x] {check}:").replace(f"{check}: ", f"{check}: ", 1)
        filled = "\n".join(line + "docs/evidence.md" if line.startswith("- [x] ") else line for line in filled.splitlines()) + "\n"
        (self.root / "brief.md").write_text(filled, encoding="utf-8")
        output, _ = self.run_cli("deliverable", "check", "brief.md")
        self.assertIn("Ready for review by marketing, communication, legal", output)


if __name__ == "__main__":
    unittest.main()
