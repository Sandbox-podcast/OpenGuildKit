"""What the CLI says when a command ends on an error: the trace on request, and the option that named the file."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.__main__ import main as start
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
DEBUG = {"OPENGUILDKIT_DEBUG": "1"}


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="ogk-trace-")
        cls.addClassCleanup(cls.folder.cleanup)
        cls.root = Path(cls.folder.name)
        run_cli(cls.root, "init", "--answers", EXAMPLE / "profile.json")

    def test_the_trace_comes_before_the_message_when_the_variable_is_one(self):
        """Issue #504: an error turned into one line lost its Python trace, and no switch gave it back."""
        for mode in (False, True):
            with self.subTest(process=mode):
                plain = run_cli(self.root, "task", "show", "nope", expect=1, subprocess_mode=mode)
                traced = run_cli(self.root, "task", "show", "nope", expect=1, subprocess_mode=mode, env=DEBUG)
                self.assertEqual(traced.stdout, plain.stdout)
                self.assertEqual(traced.stderr.count("Traceback (most recent call last)"), 1)
                self.assertTrue(traced.stderr.startswith("Traceback"), traced.stderr)
                self.assertIn("tasks.py", traced.stderr)
                self.assertTrue(traced.stderr.endswith(plain.stderr), "the message is the one of the plain run")

    def test_without_the_variable_the_output_is_the_one_of_before(self):
        for value in (None, "", "0", "yes"):
            with self.subTest(value=value):
                shown = run_cli(self.root, "task", "show", "nope", expect=1, env={} if value is None else {"OPENGUILDKIT_DEBUG": value})
                self.assertNotIn("Traceback", shown.stderr)
                self.assertTrue(shown.stderr.startswith("OpenGuildKit: "))
                self.assertEqual(len(shown.stderr.splitlines()), 1)

    def test_a_command_without_an_error_prints_no_trace(self):
        self.assertEqual(run_cli(self.root, "task", "list", env=DEBUG).stderr, "")

    def test_the_edit_hook_prints_the_trace_before_its_message(self):
        with patch("openguildkit.guard.hook_command", side_effect=OSError("disk gone")), patch.dict(os.environ, DEBUG):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = start(["guard", "--hook", "prompt"])
        self.assertEqual(code, 1)
        self.assertTrue(err.getvalue().startswith("Traceback"), err.getvalue())
        self.assertTrue(err.getvalue().endswith("OpenGuildKit: disk gone\n"))
        with patch("openguildkit.guard.hook_command", side_effect=OSError("disk gone")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                start(["guard", "--hook", "prompt"])
        self.assertEqual(err.getvalue(), "OpenGuildKit: disk gone\n")

    def test_guard_without_git_names_guard_py_in_its_trace(self):
        """Issue #504: `OpenGuildKit: [Errno 2] No such file or directory: 'git'` named no function."""
        empty = tempfile.mkdtemp(prefix="ogk-nopath-")
        self.addCleanup(os.rmdir, empty)
        plain = run_cli(self.root, "guard", "--ci", "--base", "HEAD", expect=1, subprocess_mode=True, env={"PATH": empty})
        traced = run_cli(self.root, "guard", "--ci", "--base", "HEAD", expect=1, subprocess_mode=True,
                         env={"PATH": empty, **DEBUG})
        self.assertIn("guard.py", traced.stderr)
        self.assertTrue(traced.stderr.endswith(plain.stderr))

    def test_importing_the_cli_does_not_load_the_traceback_module(self):
        # -S: no site module, so no .pth file of a tool, such as the coverage of a child process, loads traceback first.
        done = subprocess.run([sys.executable, "-S", "-c", "import sys, openguildkit.cli; print('traceback' in sys.modules)"],
                              capture_output=True, text=True, check=False,
                              env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        self.assertEqual(done.stdout.strip(), "False", done.stderr)


class NamedFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="ogk-file-")
        cls.addClassCleanup(cls.folder.cleanup)
        cls.root = Path(cls.folder.name)
        run_cli(cls.root, "init", "--answers", EXAMPLE / "profile.json")
        run_cli(cls.root, "task", "new", "Show customers their request status", "--id", "status")

    def test_a_missing_file_given_to_an_option_is_named_with_its_option(self):
        """Issue #504: `task submit ID --file missing.json` said `[Errno 2] No such file or directory: 'missing.json'`."""
        for command in (["task", "submit", "status", "--file"], ["task", "new", "--file"],
                        ["storybook", "generate", "--proposals"]):
            with self.subTest(command=command):
                failed = run_cli(self.root, *command, "missing.json", expect=1)
                self.assertIn(f"{command[-1]} missing.json", failed.stderr)
                self.assertNotIn("[Errno 2]", failed.stderr)

    def test_a_file_the_command_reads_without_an_option_keeps_its_message(self):
        failed = run_cli(self.root, "alerts", "import", "missing.json", expect=1)
        self.assertIn("missing.json", failed.stderr)


if __name__ == "__main__":
    unittest.main()
