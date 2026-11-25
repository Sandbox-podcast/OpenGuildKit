"""A person at a terminal: standard input must be a console, not only a device whose isatty() is true (#357)."""

import io
import os
import re
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from openguildkit import terminal

from tests.test_results import TASK, ResultCase

SOURCE = Path(__file__).resolve().parents[1] / "src" / "openguildkit"


@contextmanager
def device_that_is_not_a_console():
    """Standard input as Windows gives NUL: a device whose isatty() is true, and which no person types in."""
    with open(os.devnull, encoding="utf-8") as stream, patch("sys.stdin", stream), \
            patch.object(stream, "isatty", return_value=True), \
            patch("openguildkit.terminal.console", return_value=False):
        yield


class InteractiveTests(unittest.TestCase):
    def test_a_device_is_a_terminal_only_when_it_is_a_console(self):
        with device_that_is_not_a_console():
            self.assertFalse(terminal.interactive())
        with open(os.devnull, encoding="utf-8") as stream, patch("sys.stdin", stream), \
                patch.object(stream, "isatty", return_value=True), \
                patch("openguildkit.terminal.console", return_value=True):
            self.assertTrue(terminal.interactive())

    def test_a_stand_in_stream_keeps_its_own_answer(self):
        """The suite types at a terminal with a stream that has no device: its isatty() stands."""
        with patch("sys.stdin", io.StringIO("")):
            self.assertFalse(terminal.interactive())
            with patch("sys.stdin.isatty", return_value=True):
                self.assertTrue(terminal.interactive())
        with patch("sys.stdin", None):
            self.assertFalse(terminal.interactive())

    @unittest.skipUnless(os.name == "nt", "the NUL device is a Windows device")
    def test_nul_is_not_a_console_on_windows(self):
        with open("NUL", encoding="utf-8") as stream:
            self.assertTrue(stream.isatty())
            self.assertFalse(terminal.windows_console(stream.fileno()))

    def test_no_module_asks_isatty_of_standard_input_but_the_terminal_module(self):
        callers = [path.name for path in SOURCE.rglob("*.py")
                   if path.name != "terminal.py" and re.search(r"stdin\.isatty\(", path.read_text(encoding="utf-8"))]
        self.assertEqual(callers, [])


class ActsOfAPersonTests(ResultCase):
    def test_an_approval_from_a_device_that_is_not_a_console_is_refused_with_its_reason(self):
        self.reviewed()
        with device_that_is_not_a_console():
            _, error = self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed",
                                    code=1)
        self.assertIn("Approval requires a person at an interactive terminal.", error)
        self.assertNotIn("EOF", error)
        self.assertEqual(self.record()["status"], "reviewed")


if __name__ == "__main__":
    unittest.main()
