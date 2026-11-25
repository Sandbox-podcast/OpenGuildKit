"""A character device that is not a console is not a terminal (issue #357)."""

import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from openguildkit.storage import write_json
from openguildkit.terminal import interactive_input
from tests.support import run_cli
from tests.test_approval_lifecycle import EXAMPLE, ApprovalCase

SOURCE = Path(__file__).resolve().parents[1] / "src" / "openguildkit"


@contextmanager
def tty_that_is_not_a_console():
    """isatty() is true, and the Windows console check fails. That is what NUL does."""
    with patch("sys.stdin.isatty", return_value=True), \
            patch("openguildkit.terminal._isatty_replaced", return_value=False), \
            patch("openguildkit.terminal._windows_console", return_value=False), \
            patch("sys.platform", "win32"):
        yield


class TerminalSourceTests(unittest.TestCase):
    def test_no_module_calls_stdin_isatty_directly(self):
        offenders = []
        for path in sorted(SOURCE.rglob("*.py")):
            if "sys.stdin.isatty" in path.read_text(encoding="utf-8"):
                offenders.append(path.relative_to(SOURCE).as_posix())
        self.assertEqual(offenders, [])

    @unittest.skipUnless(sys.platform == "win32", "NUL is a character device only on Windows")
    def test_nul_reports_a_terminal_but_is_not_a_console(self):
        saved = sys.stdin
        stream = open("NUL", encoding="utf-8")
        try:
            sys.stdin = stream
            self.assertTrue(stream.isatty())
            self.assertFalse(interactive_input())
        finally:
            sys.stdin = saved
            stream.close()


class NonConsoleInputTests(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "nc")
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", "nc", "--answers", self.root / "answers.json")

    def test_reuse_answers_without_a_console_consults_as_unsure(self):
        task = self.task("nc")
        task["answers"].pop("concerns")
        write_json(self.state / "tasks" / "nc.json", task)
        with tty_that_is_not_a_console():
            self.assertFalse(interactive_input())
            result = run_cli(self.root, "task", "consult", "nc", "--reuse-answers", expect=0)
        self.assertIn("consulted as unsure", result.stderr)
        self.assertEqual(self.task("nc")["answers"]["concerns"], ["unsure"])

    def test_approve_without_a_console_is_refused(self):
        template = json.loads(self.run_cli("task", "template", "nc")[0])
        review = {"consultation_id": template["consultation_id"],
                  **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {board["id"] for board in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", "nc", "--file", self.root / "review.json")
        with tty_that_is_not_a_console():
            result = run_cli(self.root, "task", "decide", "nc", "--approve", "--by", "Camille",
                             "--reason", "Agreed", expect=1)
        self.assertIn("interactive terminal", result.stderr)
        self.assertNotEqual(self.task("nc").get("status"), "approved")
