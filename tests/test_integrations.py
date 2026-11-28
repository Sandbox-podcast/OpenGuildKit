import contextlib
import io
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.integrations import HOST_FILES, packaged_file
from tests.support import CapturedCli, run_cli

REPO = Path(__file__).resolve().parents[1]
PACKAGED = REPO / "src" / "openguildkit" / "agent_files"


class IntegrationTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_repository_copies_match_the_packaged_files(self):
        self.assertEqual(packaged_file("skills/openguildkit/SKILL.md"),
                         (REPO / "integrations/skills/openguildkit/SKILL.md").read_text(encoding="utf-8"))
        # The reference files of the skill too, and no copy without its packaged file.
        packaged = {path.relative_to(PACKAGED / "skills").as_posix() for path in (PACKAGED / "skills").rglob("*.md")}
        copies = {path.relative_to(REPO / "integrations/skills").as_posix()
                  for path in (REPO / "integrations/skills").rglob("*.md")}
        self.assertEqual(copies, packaged)
        self.assertGreater(len(packaged), 6)
        for name in sorted(packaged):
            with self.subTest(file=name):
                self.assertEqual(packaged_file(f"skills/{name}"),
                                 (REPO / "integrations/skills" / name).read_text(encoding="utf-8"))
        for name in ("guild-board", "market-analyst", "dependency-watch"):
            self.assertEqual(packaged_file(f"agents/{name}.md"),
                             (REPO / f"integrations/claude-code/agents/{name}.md").read_text(encoding="utf-8"))

    def test_the_market_and_dependency_agents_are_installed_with_the_board(self):
        self.run_cli("integrations", "--host", "claude-code")
        agents = self.root / ".claude" / "agents"
        self.assertEqual(sorted(path.name for path in agents.glob("*.md")),
                         ["dependency-watch.md", "guild-board.md", "market-analyst.md"])
        analyst = (agents / "market-analyst.md").read_text(encoding="utf-8")
        self.assertIn("name: market-analyst", analyst)
        for words in ("`local-only`", "`public-sources`", "openguildkit market new", "openguildkit market change",
                      "never edit the JSON", "no personal data", "Obscura and Playwright"):
            self.assertIn(words, analyst)
        watch = (agents / "dependency-watch.md").read_text(encoding="utf-8")
        for words in ("name: dependency-watch", "openguildkit alerts import", "--without-task", "task alerts SLUG --link",
                      "Never run `openguildkit alerts accept`", "only after the task is approved"):
            self.assertIn(words, watch)

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

    def test_every_packaged_file_is_installed_and_the_references_come_with_the_skill(self):
        packaged = {path.relative_to(PACKAGED).as_posix() for path in PACKAGED.rglob("*.md")}
        for host, folder in (("claude-code", ".claude"), ("codex", ".agents"), ("other", ".agents")):
            with self.subTest(host=host):
                self.assertLessEqual({name for name in packaged if name.startswith("skills/")}, set(HOST_FILES[host]))
                if host == "claude-code":
                    self.assertEqual(set(HOST_FILES[host]), packaged)
                root = self.root / host
                root.mkdir()
                run_cli(root, "integrations", "--host", host)
                installed = root / folder / "skills" / "openguildkit"
                names = sorted(path.name for path in (PACKAGED / "skills/openguildkit/references").glob("*.md"))
                self.assertEqual(sorted(path.name for path in (installed / "references").glob("*.md")), names)
                for name in names:
                    self.assertEqual((installed / "references" / name).read_text(encoding="utf-8"),
                                     packaged_file(f"skills/openguildkit/references/{name}"))
                # One version note for the skill, next to SKILL.md, and none among the reference files.
                self.assertTrue((installed / "openguildkit-version.txt").is_file())
                self.assertFalse((installed / "references" / "openguildkit-version.txt").exists())

    def test_a_kept_reference_file_is_named_in_the_version_note_and_replaced_with_force(self):
        self.run_cli("integrations", "--host", "claude-code")
        installed = self.root / ".claude" / "skills" / "openguildkit"
        reference = installed / "references" / "setup.md"
        reference.write_text("# Team setup\n", encoding="utf-8")
        self.assertIn("references/setup.md: kept", self.run_cli("integrations", "--host", "claude-code"))
        self.assertEqual(reference.read_text(encoding="utf-8"), "# Team setup\n")
        self.assertIn("references/setup.md kept", (installed / "openguildkit-version.txt").read_text(encoding="utf-8"))
        self.assertIn("replaced", self.run_cli("integrations", "--host", "claude-code", "--force"))
        self.assertEqual((installed / "references" / "setup.md.previous").read_text(encoding="utf-8"), "# Team setup\n")

    def test_the_wheel_carries_every_packaged_file(self):
        """The package data patterns reach each file of agent_files, the reference files of the skill included."""
        package = REPO / "src" / "openguildkit"
        patterns = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"][
            "package-data"]["openguildkit"]
        shipped = {path for pattern in patterns for path in package.glob(pattern)}
        missing = sorted(path.relative_to(package).as_posix() for path in (package / "agent_files").rglob("*")
                         if path.is_file() and path not in shipped)
        self.assertEqual(missing, [], "add these files to package-data in pyproject.toml")

    def test_integrations_prints_only_the_files_it_handled(self):
        lines = self.run_cli("integrations", "--host", "claude-code").splitlines()
        self.assertEqual(len(lines), len(HOST_FILES["claude-code"]))
        for line in lines:
            self.assertRegex(line, r"^\.claude/\S+\.md: (installed|unchanged|kept|replaced)")

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
