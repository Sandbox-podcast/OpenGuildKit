"""docs/exit-codes.md: each row of its table is a command that departs from the general rule, replayed here."""

import json
import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.storage import write_json

from tests import test_results

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "exit-codes.md"
ROW = re.compile(r"^\| `([^`]+)` \| (\d+) \| ([A-Za-z ]+):", re.MULTILINE)
HOOK = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app/main.py"}}


def page_rows() -> list[str]:
    """Each row of the table of the commands that depart from the rule, as `command|code|label`."""
    table = PAGE.read_text(encoding="utf-8").split("## The commands that depart from it", 1)[1].split("\n## ", 1)[0]
    return [f"{command}|{code}|{label}" for command, code, label in ROW.findall(table)]


class ExitCodeTests(test_results.ResultCase):
    def fresh(self, **profile) -> Path:
        """A new empty folder as the project, with a profile when one is given."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        if profile:
            write_json(self.root.parent / f"{self.root.name}.json", {"personal_data": "no", **profile})
            self.run_cli("init", "--answers", self.root.parent / f"{self.root.name}.json")
        return self.root

    def test_every_row_of_the_page_is_replayed_and_gives_the_code_it_names(self):
        """Issue #495: the exit codes table said 2 was a usage error, and three commands gave 2 for another reason."""
        cases = {
            "guard --hook|2|Refused": self.hook_refused,
            "guard --ci|1|Problem": self.guard_ci_problem,
            "guard --ci|1|Not evaluated": self.guard_ci_not_evaluated,
            "check|1|Problem": self.check_problem,
            "check|1|Not evaluated": self.check_not_evaluated,
            "ci-check|2|Not evaluated": self.ci_check_not_evaluated,
            "tools apply|2|Partial": self.tools_apply_partial,
            "host scan --strict|1|Finding": self.host_scan_strict,
            "task verify|1|Failed": self.task_verify_failed,
            "docs share check|1|Expired": self.share_check_expired,
        }
        self.assertEqual(sorted(page_rows()), sorted(cases))
        for row, replay in cases.items():
            with self.subTest(row=row):
                replay()

    def test_the_table_of_the_workflow_page_no_longer_calls_every_2_a_usage_error(self):
        """Issue #495: docs/workflow.md said 2 is a command-line usage error; guard --hook, tools apply and ci-check give it too."""
        table = (REPO / "docs" / "workflow.md").read_text(encoding="utf-8").split("## Exit codes", 1)[1]
        self.assertNotIn("| 2 | Command-line usage error |", table)
        self.assertIn("(exit-codes.md)", table)
        for command in ("guard --hook", "tools apply", "ci-check"):
            self.assertIn(command, table)

    def hook_refused(self):
        self.fresh(guard="enforce")
        self.run_cli("guard", "--hook", "pre-edit", stdin=json.dumps(HOOK), code=2)
        write_json(self.root / ".openguildkit" / "project.json",
                   {**json.loads((self.root / ".openguildkit" / "project.json").read_text()), "guard": "observe"})
        self.run_cli("guard", "--hook", "pre-edit", stdin=json.dumps(HOOK), code=0)

    def guard_ci_problem(self):
        self.fresh()
        self.git("init", "-q", "-b", "main")
        self.run_cli("init", "--answers", self.write_answers(guard="enforce"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "change")
        self.run_cli("guard", "--ci", "--base", "main", code=1)

    def guard_ci_not_evaluated(self):
        self.fresh(guard="enforce")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        _, error = self.run_cli("guard", "--ci", "--base", "nope", code=1)
        self.assertIn("nope", error)

    def check_problem(self):
        self.fresh(host="claude-code", guard="enforce")
        _, error = self.run_cli("check", code=1)
        self.assertIn("The host settings do not enforce", error)

    def check_not_evaluated(self):
        self.fresh()
        _, error = self.run_cli("check", code=1)
        self.assertIn("No OpenGuildKit project found", error)

    def ci_check_not_evaluated(self):
        self.fresh(host="claude-code")
        _, error = self.run_cli("ci-check", "--target-repo", self.root, "--commit", "HEAD", code=2)
        self.assertIn("export-link-expiry", error)

    def tools_apply_partial(self):
        self.fresh(host="claude-code")
        self.run_cli("tools", "apply", "jira", "gryzzly", "--mock", "--host", "claude-code", code=2)
        self.run_cli("tools", "apply", "jira", "--mock", "--host", "claude-code", code=0)
        self.fresh(host="claude-code")
        self.run_cli("tools", "apply", "gryzzly", "--mock", "--host", "claude-code", code=1)

    def host_scan_strict(self):
        self.fresh(host="claude-code")
        write_json(self.root / ".mcp.json", {"mcpServers": {"docs": {"command": "npx", "args": ["-y", "some-docs-server"]}}})
        self.assertIn("warning mcp-unpinned", self.run_cli("host", "scan")[0])
        self.run_cli("host", "scan", "--strict", code=1)

    def task_verify_failed(self):
        self.fresh()
        self.approved(exit_code=1)
        self.run_cli("task", "verify", test_results.TASK, code=1)

    def share_check_expired(self):
        self.fresh(host="claude-code")
        page = self.root / "docs-site" / "page.md"
        page.parent.mkdir(parents=True)
        page.write_text("# Shared page\n", encoding="utf-8")
        today = clock.real_today()
        self.run_cli("docs", "share", "add", "--deliverable", "docs-site/page.md", "--portal",
                     "https://docs.example.org/p/portal", "--recipient", "client@example.org",
                     "--until", (today + timedelta(days=14)).isoformat(), "--by", "Camille")
        with patch("openguildkit.clock.real_today", return_value=today + timedelta(days=15)):
            output, error = self.run_cli("docs", "share", "check", code=1)
        self.assertIn("client@example.org", output + error)

    def write_answers(self, **profile) -> Path:
        path = self.root.parent / f"{self.root.name}.json"
        write_json(path, {"personal_data": "no", **profile})
        return path


if __name__ == "__main__":
    unittest.main()
