import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        for name in ("guild-board", "market-analyst"):
            self.assertEqual(packaged_file(f"agents/{name}.md"),
                             (REPO / f"integrations/claude-code/agents/{name}.md").read_text(encoding="utf-8"))

    def test_the_market_analyst_is_installed_with_the_board(self):
        self.run_cli("integrations", "--host", "claude-code")
        agents = self.root / ".claude" / "agents"
        self.assertEqual(sorted(path.name for path in agents.glob("*.md")),
                         ["guild-board.md", "market-analyst.md"])
        analyst = (agents / "market-analyst.md").read_text(encoding="utf-8")
        self.assertIn("name: market-analyst", analyst)
        for words in ("`local-only`", "`public-sources`", "openguildkit market new", "openguildkit market change",
                      "never edit the JSON", "no personal data", "Obscura and Playwright"):
            self.assertIn(words, analyst)

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

    def test_the_version_file_names_a_file_kept_at_another_version(self):
        self.run_cli("integrations", "--host", "claude-code")
        skill = self.root / HOST_FILES["claude-code"]["skills/openguildkit/SKILL.md"]
        agent = self.root / HOST_FILES["claude-code"]["agents/guild-board.md"]
        skill.write_text("# Team version\n", encoding="utf-8")
        with patch("openguildkit.integrations.package_version", return_value="9.9.9"):
            self.assertIn("kept", self.run_cli("integrations", "--host", "claude-code"))
        kept = (skill.parent / "openguildkit-version.txt").read_text(encoding="utf-8")
        self.assertNotEqual(kept.strip(), "9.9.9")
        self.assertIn("SKILL.md", kept)
        self.assertEqual((agent.parent / "openguildkit-version.txt").read_text(encoding="utf-8"), "9.9.9\n")
        with patch("openguildkit.integrations.package_version", return_value="9.9.9"):
            self.run_cli("integrations", "--host", "claude-code", "--force")
        self.assertEqual((skill.parent / "openguildkit-version.txt").read_text(encoding="utf-8"), "9.9.9\n")

    def test_version_is_printed(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit):
            main(["--version"])
        self.assertTrue(stdout.getvalue().startswith("openguildkit "))


if __name__ == "__main__":
    unittest.main()
