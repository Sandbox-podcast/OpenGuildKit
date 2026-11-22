"""Small setup defects from the field: the tools next step, a hand-edited managed block, a generic MCP plan."""

import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.storage import write_json

from tests.support import CapturedCli


class SetupMinorTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def init(self, **answers):
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", **answers})
        return self.run_cli("init", "--answers", self.root / "answers.json")[0]

    def test_each_task_question_has_a_one_line_help_and_says_what_unsure_does(self):
        self.init()
        self.run_cli("task", "new", "Let customers download their invoices as PDF.", "--id", "invoices")
        listing = json.loads(self.run_cli("task", "questions", "invoices")[0])
        answers = {"kind": "feature", "surface": ["customer"], "data": "personal", "research": "local"}
        write_json(self.root / "task-answers.json", answers)
        followed = json.loads(self.run_cli("task", "questions", "invoices", "--answers", self.root / "task-answers.json")[0])
        for question in listing["questions"] + followed["questions"]:
            with self.subTest(question=question["id"]):
                self.assertEqual(len(question["help"].splitlines()), 1)
                self.assertLessEqual(len(question["help"]), 120)
                self.assertTrue(question["unsure"])
        self.assertIn("outcome", {question["id"] for question in followed["questions"]})

    def test_init_prints_the_tools_plan_step_for_every_host(self):
        output = self.init(tools=["Jira", "Sentry"])
        self.assertIn("openguildkit tools plan jira sentry", output)

    def test_the_other_host_gets_a_generic_mcp_plan_that_writes_nothing(self):
        self.init(tools=["Jira"])
        for arguments in (("jira", "--mock"), ("jira",)):
            with self.subTest(arguments=arguments):
                output, error = self.run_cli("tools", "plan", *arguments)
                block = next(line.strip() for line in output.splitlines() if line.strip().startswith('{"mcpServers"'))
                servers = json.loads(block)["mcpServers"]
                self.assertEqual(len(servers), 1)
                self.assertTrue(all(isinstance(entry, dict) for entry in servers.values()))
                self.assertNotIn("Claude Code", output)
                self.assertNotIn("codex mcp login", output)
                self.assertIn("Nothing is written. The project's host is other", error)
        self.assertIn("with the agent's own MCP sign-in", output)
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
