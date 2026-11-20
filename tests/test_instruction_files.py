import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.project import BEGIN, END, merged_instructions, validate_profile
from openguildkit.storage import write_json


class InstructionFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.answers = self.root / "answers.json"
        write_json(self.answers, {"name": "Portal", "stack": ["Python"]})

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def test_a_byte_order_mark_is_kept_and_does_not_block_the_project(self):
        agents, claude = self.root / "AGENTS.md", self.root / "CLAUDE.md"
        self.run_cli("init", "--answers", self.answers)
        for path in (agents, claude):
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.run_cli("check")
        self.run_cli("sync")
        self.assertTrue(agents.read_bytes().startswith(b"\xef\xbb\xbf# ") or agents.read_bytes().startswith(b"\xef\xbb\xbf<!--"))
        self.assertEqual(claude.read_bytes().count(b"@AGENTS.md"), 1)
        self.run_cli("task", "new", "Show the request status.", "--id", "status")

    def test_markers_quoted_in_a_code_block_are_left_alone(self):
        agents = self.root / "AGENTS.md"
        example = f"# Team notes\n\nOpenGuildKit manages this block:\n\n```markdown\n{BEGIN}\n(generated)\n{END}\n```\n\nRun make test.\n"
        agents.write_text(example, encoding="utf-8")
        self.run_cli("init", "--answers", self.answers)
        text = agents.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(example))
        self.assertEqual(text.count(BEGIN), 2)
        self.run_cli("check")
        with agents.open("a", encoding="utf-8") as handle:
            handle.write(f"\n~~~text\n{END}\n~~~\n")
        self.run_cli("check")

    def test_profile_text_refuses_every_kind_of_line_break(self):
        catalog = load_catalog()
        for value in ("line one\rline two", "Python\r" + END, "one two"):
            with self.assertRaisesRegex(ValueError, "single line"):
                validate_profile({"name": "x", "conventions": [value]}, catalog)
            with self.assertRaisesRegex(ValueError, "single line"):
                validate_profile({"name": "x", "stack": [value]}, catalog)

    @unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "symbolic links need POSIX here")
    def test_a_claude_file_linked_to_agents_is_recognised(self):
        (self.root / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        os.symlink("AGENTS.md", self.root / "CLAUDE.md")
        self.run_cli("init", "--answers", self.answers)
        self.assertTrue((self.root / "CLAUDE.md").is_symlink())
        self.assertNotIn("@AGENTS.md", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.run_cli("check")
        self.run_cli("sync")

    @unittest.skipUnless(hasattr(os, "symlink") and os.name == "posix", "symbolic links need POSIX here")
    def test_other_symbolic_links_are_still_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        target = Path(outside.name) / "CLAUDE.md"
        target.write_text("# Elsewhere\n", encoding="utf-8")
        os.symlink(target, self.root / "CLAUDE.md")
        _, error = self.run_cli("init", "--answers", self.answers, code=1)
        self.assertIn("symbolic link", error)

    def test_marker_errors_name_the_file_in_question(self):
        self.run_cli("init", "--answers", self.answers)
        (self.root / "CLAUDE.md").write_text(f"{END}\n@AGENTS.md\n", encoding="utf-8")
        _, error = self.run_cli("sync", code=1)
        self.assertIn("CLAUDE.md has malformed", error)
        with self.assertRaisesRegex(ValueError, "AGENTS.md has malformed"):
            merged_instructions(f"{BEGIN}\n", "rules")


if __name__ == "__main__":
    unittest.main()
