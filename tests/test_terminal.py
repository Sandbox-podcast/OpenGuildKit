"""A person at a terminal: standard input must be a console, not only a device whose isatty() is true (#357)."""

import ast
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

    def test_typed_refuses_without_a_terminal_and_compares_what_the_person_types(self):
        """Issue #461: the act a person types is written once, and it reads nothing without a terminal."""
        with patch("sys.stdin", io.StringIO("")), patch("builtins.input") as asked:
            with self.assertRaisesRegex(ValueError, "^Run it at a terminal.$"):
                terminal.typed("t1", "Type t1: ", refusal="Run it at a terminal.", cancelled="Cancelled.")
            asked.assert_not_called()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=" t1 "), \
                patch("sys.stderr", io.StringIO()) as stderr:
            terminal.typed("t1", "Type t1: ", refusal="no", cancelled="Cancelled.")
            self.assertEqual(stderr.getvalue(), "Type t1: ")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="t2"), \
                patch("sys.stderr", io.StringIO()), self.assertRaisesRegex(ValueError, "^Cancelled.$"):
            terminal.typed("t1", "Type t1: ", refusal="no", cancelled="Cancelled.")

    def test_no_module_compares_what_a_person_types_but_the_terminal_module(self):
        """Issue #461: an ID typed at the prompt is compared in terminal.typed only (yes or no questions aside)."""
        def reads_input(node):
            return any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "input"
                       for call in ast.walk(node))

        comparisons = []
        for path in sorted(SOURCE.rglob("*.py")):
            if path.name == "terminal.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops) \
                        and reads_input(node):
                    comparisons.append(f"{path.name}:{node.lineno}")
        self.assertEqual(comparisons, [])


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
