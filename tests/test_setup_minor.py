"""Small setup defects from the field: the tools next step, a hand-edited managed block, a generic MCP plan."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import main
from openguildkit.storage import write_json


class SetupMinorTests(unittest.TestCase):
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

    def init(self, **answers):
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", **answers})
        return self.run_cli("init", "--answers", self.root / "answers.json")[0]

    def test_init_prints_the_tools_plan_step_for_every_host(self):
        output = self.init(tools=["Jira", "Sentry"])
        self.assertIn("openguildkit tools plan jira sentry", output)

    def test_the_other_host_gets_a_generic_mcp_plan_that_writes_nothing(self):
        self.init(tools=["Jira"])
        output, error = self.run_cli("tools", "plan", "jira", "--mock")
        self.assertIn("mcpServers: {", output)
        self.assertIn("Nothing is written. The project's host is other", error)
        self.assertFalse((self.root / ".mcp.json").exists())

    def test_check_names_a_hand_edit_and_sync_says_what_it_replaces(self):
        self.init()
        agents = self.root / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        edited = text.replace("Project: Ledger", "Project: Ledger\nAlways answer in French.", 1)
        agents.write_text(edited, encoding="utf-8")
        _, error = self.run_cli("check", code=1)
        self.assertIn("was edited by hand (1 line(s), first: Always answer in French.)", error)
        output, _ = self.run_cli("sync")
        self.assertIn("Replaced 1 line(s) edited by hand in the managed block of AGENTS.md", output)
        self.assertIn("  - Always answer in French.", output)
        self.assertEqual(agents.read_text(encoding="utf-8"), text)
        self.run_cli("check")

    def test_a_profile_change_is_not_reported_as_a_hand_edit(self):
        self.init()
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        write_json(self.root / ".openguildkit" / "project.json", {**profile, "conventions": ["Small commits"]})
        _, error = self.run_cli("check", code=1)
        self.assertIn("out of date", error)
        self.assertNotIn("by hand", error)
        output, _ = self.run_cli("sync")
        self.assertNotIn("Replaced", output)


if __name__ == "__main__":
    unittest.main()
