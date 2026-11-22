"""The host `other`: every command that writes nothing for it says so and gives the way forward."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import main
from openguildkit.lock import package_version
from openguildkit.storage import write_json


class OtherHostTests(unittest.TestCase):
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
        write_json(self.root / "answers.json", {"name": "svc", "host": "other", **answers})
        return self.run_cli("init", "--answers", self.root / "answers.json")

    def test_init_says_which_instruction_files_it_writes(self):
        output, _ = self.init()
        self.assertEqual(json.loads((self.root / ".openguildkit" / "project.json").read_text())["host"], "other")
        self.assertIn("Wrote AGENTS.md", output)
        self.assertIn("CLAUDE.md, one line that imports AGENTS.md for Claude Code", output)
        self.assertTrue((self.root / "CLAUDE.md").is_file())

    def test_integrations_install_the_skill_for_another_agent(self):
        output, _ = self.run_cli("integrations", "--host", "other")
        skill = self.root / ".agents" / "skills" / "openguildkit" / "SKILL.md"
        self.assertTrue(skill.is_file())
        self.assertIn("Other agents: the skill is in .agents/skills/openguildkit/", output)
        lines = output.strip().splitlines()
        self.assertTrue(lines[0].endswith(f"(openguildkit {package_version()})"), lines[0])
        self.assertNotIn(f"openguildkit {package_version()}", [line.strip() for line in lines])

    def test_host_apply_says_it_writes_nothing_and_host_check_passes(self):
        self.init()
        # Writing nothing is not a success: the command says so and exits 1.
        output, error = self.run_cli("host", "apply", code=1)
        self.assertIn("the project's host is other, so host apply wrote nothing", error)
        self.assertIn("openguildkit profile set host claude-code (or codex)", error)
        self.assertFalse((self.root / ".claude" / "settings.json").exists())
        output, _ = self.run_cli("host", "check")
        self.assertIn("[by instruction]", output)
        self.assertIn("Nothing missing.", output)
        self.run_cli("check")

    def test_tools_commands_name_the_host_to_pass(self):
        self.init()
        _, error = self.run_cli("tools", "apply", "jira", "--mock", code=1)
        self.assertIn("the project's host is other", error)
        self.assertIn("--host claude-code or --host codex", error)
        self.assertIn("openguildkit tools plan ID --host codex", error)
        output, _ = self.run_cli("tools", "plan", "jira", "--mock", "--host", "codex")
        self.assertIn("jira", output)
        _, error = self.run_cli("tools", "remove", "jira", code=1)
        self.assertIn("--host claude-code or --host codex", error)
        self.run_cli("tools", "apply", "jira", "--mock", "--host", "codex")
        self.assertTrue((self.root / ".codex" / "config.toml").is_file())

    def test_host_check_fails_while_a_setting_is_missing(self):
        self.init()
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text())
        write_json(self.root / ".openguildkit" / "project.json", {**profile, "host": "codex", "guard": "off"})
        self.run_cli("sync")
        output, _ = self.run_cli("host", "check", code=1)
        self.assertIn("[missing]", output)
        self.assertIn("setting(s) missing. Run openguildkit host apply", output)
        self.run_cli("host", "apply")
        output, _ = self.run_cli("host", "check")
        self.assertIn("Nothing missing.", output)


if __name__ == "__main__":
    unittest.main()
