import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import main
from openguildkit.integrations import HOST_FILES, packaged_file

REPO = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--project", str(self.root), *arguments]), 0)
        return stdout.getvalue()

    def test_repository_copies_match_the_packaged_files(self):
        self.assertEqual(packaged_file("skills/openguildkit/SKILL.md"),
                         (REPO / "integrations/skills/openguildkit/SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(packaged_file("agents/guild-board.md"),
                         (REPO / "integrations/claude-code/agents/guild-board.md").read_text(encoding="utf-8"))

    def test_install_keeps_modified_files_unless_forced(self):
        output = self.run_cli("integrations", "--host", "claude-code")
        self.assertIn("installed", output)
        skill = self.root / HOST_FILES["claude-code"]["skills/openguildkit/SKILL.md"]
        self.assertTrue((skill.parent / "openguildkit-version.txt").is_file())
        self.assertIn("unchanged", self.run_cli("integrations", "--host", "claude-code"))
        skill.write_text("# Team version\n", encoding="utf-8")
        self.assertIn("kept", self.run_cli("integrations", "--host", "claude-code"))
        self.assertEqual(skill.read_text(encoding="utf-8"), "# Team version\n")
        self.assertIn("replaced", self.run_cli("integrations", "--host", "claude-code", "--force"))
        self.assertEqual(skill.with_name("SKILL.md.previous").read_text(encoding="utf-8"), "# Team version\n")
        self.run_cli("integrations", "--host", "codex")
        self.assertTrue((self.root / ".agents/skills/openguildkit/SKILL.md").is_file())

    def test_version_is_printed(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit):
            main(["--version"])
        self.assertTrue(stdout.getvalue().startswith("openguildkit "))


if __name__ == "__main__":
    unittest.main()
