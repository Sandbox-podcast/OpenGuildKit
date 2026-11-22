"""Every CLI command and task action is run by at least one test.

The test walks the argparse tree and looks in the test files for an invocation:
the group and action as consecutive arguments, such as "task", "pass", or a
top-level command as an argument of its own. A new command without a test fails here.

A command the web interface tests send to a running server is not an invocation of
its own: the calls of their HTTP helpers are left out of the search, and so are
subscripts such as results["ui"], so that ["ui"] in a request body or a key does not
count as a test of openguildkit ui.
"""

import argparse
import ast
import re
import unittest
from pathlib import Path

from openguildkit.cli import _parser

TESTS = Path(__file__).resolve().parent
# The helpers of tests/test_webui.py that send a command to the server over HTTP.
HTTP_HELPERS = {"run_in_page", "request", "refused_by_server"}


def _subcommands(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def command_paths() -> list[tuple[str, ...]]:
    """Each runnable command: a top-level command, or a group and its action."""
    paths = []
    for name, command in _subcommands(_parser()).items():
        actions = _subcommands(command)
        paths.extend([(name, action) for action in actions] if actions else [(name,)])
    return paths


def _pattern(path: tuple[str, ...]) -> re.Pattern:
    quoted = [f"[\"']{re.escape(part)}[\"']" for part in path]
    return re.compile(r"[(\[,]\s*" + r",\s*".join(quoted) + r"\s*[,)\]]")


def without_http_calls(source: str) -> str:
    """The source with every call of an HTTP helper blanked out, its arguments included, and every string
    subscript (results["ui"])."""
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    text = list(source)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _name(node.func) in HTTP_HELPERS:
            blank = node
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            blank = node.slice
        else:
            continue
        begin = starts[blank.lineno - 1] + _column(lines[blank.lineno - 1], blank.col_offset)
        end = starts[blank.end_lineno - 1] + _column(lines[blank.end_lineno - 1], blank.end_col_offset)
        text[begin:end] = " " * (end - begin)
    return "".join(text)


def _name(function: ast.expr) -> str | None:
    if isinstance(function, ast.Attribute):
        return function.attr
    return function.id if isinstance(function, ast.Name) else None


def _column(line: str, offset: int) -> int:
    """ast counts columns in UTF-8 bytes; the text is indexed in characters."""
    return len(line.encode("utf-8")[:offset].decode("utf-8", "ignore"))


def _test_sources() -> str:
    own = Path(__file__).resolve()
    return "\n".join(without_http_calls(path.read_text(encoding="utf-8"))
                     for path in sorted(TESTS.rglob("test_*.py")) if path != own)


class CliCoverageTests(unittest.TestCase):
    def test_the_walk_finds_the_known_commands(self):
        paths = command_paths()
        self.assertIn(("task", "pass"), paths)
        self.assertIn(("storybook", "compose"), paths)
        self.assertIn(("deliverable", "list"), paths)
        self.assertIn(("check",), paths)
        self.assertGreater(len(paths), 50)

    def test_every_command_and_task_action_is_invoked_by_a_test(self):
        sources = _test_sources()
        missing = [" ".join(path) for path in command_paths() if not _pattern(path).search(sources)]
        self.assertEqual(missing, [], "Add a test that runs each of these commands through the CLI.")

    def test_the_search_does_not_match_a_bare_mention(self):
        self.assertIsNone(_pattern(("task", "waive")).search('help = "task waive needs a terminal"'))
        self.assertIsNotNone(_pattern(("task", "waive")).search('run_cli("task", "waive", TASK_ID)'))
        self.assertIsNotNone(_pattern(("sync",)).search('main(["--project", str(root), "sync"])'))

    def test_a_command_sent_to_the_web_server_is_not_a_test_of_that_command(self):
        page = ('status = self.run_in_page("ui")\n'
                'answer = self.request("/api/run", {"batch": {"tasks": ["task", "list"], "ui": ["ui"]}})\n'
                'self.request(\n    "/api/run",\n    {"argv": ["ui"]},\n)\n'
                'self.assertEqual(answer["results"]["ui"]["code"], 1)\n')
        self.assertIsNotNone(_pattern(("ui",)).search(page))
        self.assertIsNone(_pattern(("ui",)).search(without_http_calls(page)))
        started = 'subprocess.Popen([sys.executable, "-m", "openguildkit", "--project", root, "ui", "--port", "0"])\n'
        self.assertIsNotNone(_pattern(("ui",)).search(without_http_calls(page + started)))
        self.assertIsNotNone(_pattern(("ui",)).search(without_http_calls('main(["--project", root, "ui"])')))


if __name__ == "__main__":
    unittest.main()
