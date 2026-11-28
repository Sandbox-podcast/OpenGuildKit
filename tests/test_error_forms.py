"""Errors and warnings have one form: a file is named in words, an unknown identifier reads alike, a list can be empty
and still say so, and a warning goes to the error stream that a redirected result does not carry."""

import ast
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.errors import os_error_message, unknown
from openguildkit.storage import write_json
from tests.support import CapturedCli

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "src" / "openguildkit"
EXAMPLE = REPO / "examples" / "request-status"
# A warning text built here and printed by its caller to the error stream, or part of a document a person asked for.
WARNING_TEXTS = {"sensitive.py": "returned to task_cli, which prints each to stderr",
                 "workflow.py": "a line of the decision brief, the document `task challenge` prints"}


class ErrorFormTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.run_cli("init", "--answers", EXAMPLE / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "t1")

    def test_a_missing_file_is_named_in_words_by_every_command_that_reads_one(self):
        """Issue #528: ten commands printed "[Errno 2] No such file or directory" without saying what was missing."""
        commands = (("task", "submit", "t1", "--file", "nope.json"), ("task", "consult", "t1", "--answers", "nope.json"),
                    ("task", "respond", "t1", "--file", "nope.json"), ("task", "review", "t1", "--file", "nope.json"),
                    ("task", "new", "--file", "nope.md"), ("alerts", "import", "nope.json"),
                    ("deliverable", "check", "nope.md"), ("preview", "--answers", "nope.json"),
                    ("recommend", "--answers", "nope.json"), ("storybook", "propose", "--inventory", "nope.json"))
        for command in commands:
            with self.subTest(command=" ".join(command)):
                _, error = self.run_cli(*command, code=1)
                self.assertNotIn("[Errno", error)
                # A file an option names is named with it: `Cannot open --file nope.json: it does not exist.`
                option = rf"{command[-2]} " if command[-2].startswith("--") else r"\S*"
                self.assertRegex(error, rf"Cannot open {option}nope\.(json|md): it does not exist\.")

    def test_other_system_errors_do_not_show_the_python_text_either(self):
        self.assertEqual(os_error_message(IsADirectoryError(21, "Is a directory", "docs")),
                         "Cannot open docs: it is a folder, not a file.")
        self.assertEqual(os_error_message(PermissionError(13, "Permission denied", "a.json")),
                         "Cannot open a.json: permission denied.")
        self.assertEqual(os_error_message(OSError(28, "No space left on device")), "No space left on device.")
        self.assertEqual(os_error_message(OSError(5, "Input/output error", "a.json")),
                         "Cannot open a.json: input/output error.")

    def test_an_unknown_identifier_reads_the_same_in_every_command(self):
        """Issue #528: an unknown task, deliverable and pattern had three forms."""
        self.assertEqual(unknown("deliverable", "nope", "deliverable list"),
                         "Unknown deliverable: nope. Run openguildkit deliverable list.")
        for command, kind in ((("deliverable", "show", "nope"), "deliverable"), (("patterns", "--id", "nope"), "pattern"),
                              (("references", "--id", "nope"), "reference ID"), (("task", "show", "nope"), "task")):
            with self.subTest(command=" ".join(command)):
                _, error = self.run_cli(*command, code=1)
                self.assertRegex(error, rf"OpenGuildKit: Unknown {kind}: nope\. .*Run openguildkit [a-z ]+")

    def test_task_list_refuses_a_status_that_does_not_exist_and_names_the_statuses(self):
        """Issue #528: `task list --status Done` answered "No task matches." with exit 0."""
        _, error = self.run_cli("task", "list", "--status", "bogus", code=2)
        for status in ("draft", "consulting", "reviewed", "changes-requested", "approved", "done", "done-with-reservations"):
            self.assertIn(status, error)

    def test_an_empty_share_register_says_so(self):
        """Issue #528: `docs share list` printed nothing and exited 0."""
        output, _ = self.run_cli("docs", "share", "list")
        self.assertEqual(output, "No share recorded.\n")
        self.assertEqual(json.loads(self.run_cli("docs", "share", "list", "--json")[0]), [])

    def test_every_warning_goes_to_the_error_stream(self):
        """Issue #528: of 15 "Warning:" lines, 10 went to standard output, in the middle of the redirected result."""
        found = []
        for path in sorted(SOURCE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            printed = {id(argument): any(keyword.arg == "file" for keyword in call.keywords)
                       for call in ast.walk(tree) if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "print"
                       for argument in ast.walk(call)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"\bWarning: ", node.value) \
                        and not printed.get(id(node)) and path.name not in WARNING_TEXTS:
                    found.append(f"{path.name}:{node.lineno}")
        self.assertEqual(found, [])

    def test_host_apply_says_the_path_once_and_prints_what_it_wrote_as_its_result(self):
        """Issue #528: host apply wrote "Wrote .claude/settings.json" on stderr and the PATH warning twice."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        write_json(self.root / "answers.json", {"personal_data": "no", "host": "claude-code", "guard": "enforce"})
        self.run_cli("init", "--answers", self.root / "answers.json")
        with patch("openguildkit.hosts.shutil.which", return_value=None):
            output, error = self.run_cli("host", "apply", code=1)
        self.assertIn("Wrote .claude/settings.json", output)
        self.assertNotIn("Wrote", error)
        self.assertEqual(output.count("is not on this workstation's PATH"), 1)

    def test_guard_ci_without_its_base_names_the_option_that_sets_it(self):
        """Issue #528: guard --ci without origin/main printed Git's error and usage, without --base."""
        subprocess.run(["git", "-C", str(self.root), "init", "-q", "-b", "main"], check=True)
        _, error = self.run_cli("guard", "--ci", "--base", "origin/main", code=1)
        self.assertIn("base revision origin/main not found: pass --base REF", error)


if __name__ == "__main__":
    unittest.main()
