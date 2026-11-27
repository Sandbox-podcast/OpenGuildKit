"""The surface of the CLI: help pages, where the global options go, the conventions of the options, the words of
the outputs. Each test reads the parser or runs a command through the CLI.
"""

import argparse
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import command_parser, main
from openguildkit.cli_surface import COMMAND_ORDER, hoist_global_options
from tests.support import run_cli
from tests.test_cli_coverage import _subcommands


def walk(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()):
    """Every parser of the CLI with its command path, the root included."""
    yield path, parser
    for name, command in _subcommands(parser).items():
        yield from walk(command, (*path, name))


def options(parser: argparse.ArgumentParser):
    """The options of one parser that a person can type, the hidden aliases and --help left out."""
    return [action for action in parser._actions
            if action.option_strings and action.help is not argparse.SUPPRESS and not isinstance(action, argparse._HelpAction)]


REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "examples" / "request-status" / "profile.json"


def cli(*argv) -> tuple[int, str, str]:
    """Run main with exactly these arguments: the code, the standard output and the standard error."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class HelpPageTests(unittest.TestCase):
    def test_every_command_says_what_it_does(self):
        """Issue #492: 102 help pages of 104 never said what the command does."""
        bare = [" ".join(path) for path, parser in walk(command_parser()) if not parser.description]
        self.assertEqual(bare, [])

    def test_no_help_page_is_wider_than_80_columns(self):
        """Issue #492: the usage of the root and of task repeated the list of commands, 244 and 277 characters."""
        with patch.dict(os.environ, {"COLUMNS": "80", "NO_COLOR": "1"}):
            wide = {" ".join(path): max(len(line) for line in parser.format_help().splitlines())
                    for path, parser in walk(command_parser())}
        self.assertEqual({name: width for name, width in wide.items() if width > 80}, {})

    def test_the_usage_names_the_commands_once(self):
        """Issue #492: the choices of a group were written twice, in the usage and under it."""
        with patch.dict(os.environ, {"COLUMNS": "80", "NO_COLOR": "1"}):
            page = command_parser().format_help()
        self.assertIn("COMMAND", page.partition("\n\n")[0])
        self.assertEqual(page.count("\n    task "), 1)

    def test_check_help_gives_the_sentence_of_the_command(self):
        """Issue #492: `openguildkit check --help` held an usage and an option, no sentence."""
        with tempfile.TemporaryDirectory() as folder:
            result = run_cli(folder, "check", "--help")
        self.assertIn("Check that the instructions match the project profile.", result.stdout)

    def test_every_command_of_the_root_is_named_in_a_group_of_the_root_page(self):
        self.assertEqual(sorted(set(_subcommands(command_parser())) - set(COMMAND_ORDER)), [])

    def test_the_root_page_lists_the_commands_under_headings(self):
        with patch.dict(os.environ, {"COLUMNS": "100", "NO_COLOR": "1"}):
            page = command_parser().format_help()
        self.assertLess(page.index("Set up a project"), page.index("\n    init "))
        self.assertLess(page.index("\n    init "), page.index("Browse the catalog"))
        self.assertLess(page.index("\n    catalog "), page.index("\n    ui "))

    def test_no_argument_prints_the_help(self):
        """Issue #492: `openguildkit` alone ended on an error of usage instead of the help."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([])
        self.assertEqual((code, err.getvalue()), (0, ""))
        self.assertIn("usage: openguildkit", out.getvalue())
        self.assertIn("Project rules and specialist reviews", out.getvalue())


class ProjectOptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="ogk-surface-")
        cls.addClassCleanup(cls.folder.cleanup)
        cls.root = Path(cls.folder.name)
        run_cli(cls.root, "init", "--answers", PROFILE)

    def test_the_project_option_may_follow_the_command(self):
        """Issue #496: `openguildkit check --project DIR` was refused as an unrecognized argument."""
        for command in (["check"], ["task", "list"], ["catalog", "--json"]):
            with self.subTest(command=command):
                before = cli("--project", str(self.root), *command)
                self.assertEqual(before[0], 0, before)
                self.assertEqual(cli(*command, "--project", str(self.root)), before)
                self.assertEqual(cli(*command, f"--project={self.root}"), before)

    def test_the_other_global_options_may_follow_the_command_too(self):
        code, _, err = cli("ci-check", "--target-repo", str(self.root), "--commit", "0" * 40,
                           "--policy-repo", str(self.root), "--policy-commit", "0" * 40, "--project", str(self.root))
        self.assertNotIn("unrecognized arguments", err)
        self.assertNotEqual(code, 0)

    def test_a_project_that_is_not_a_folder_is_refused_where_it_stands(self):
        code, _, err = cli("check", "--project", str(self.root / "missing"))
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_the_web_page_cannot_retarget_the_project(self):
        from openguildkit import webui

        with self.assertRaises(webui.Refused):
            webui.CliRunner(self.root).parse(["check", "--project", str(self.root / "elsewhere")])

    def test_hoisting_moves_each_global_option_in_front_in_order(self):
        self.assertEqual(hoist_global_options(["check", "--project", "a"]), ["--project", "a", "check"])
        self.assertEqual(hoist_global_options(["--project", "a", "check", "--project=b", "--json"]),
                         ["--project", "a", "--project=b", "check", "--json"])
        self.assertEqual(hoist_global_options(["task", "new", "--", "--project", "a"]), ["task", "new", "--", "--project", "a"])
        self.assertEqual(hoist_global_options(["check", "--project"]), ["check", "--project"])
        self.assertEqual(hoist_global_options([]), [])


if __name__ == "__main__":
    unittest.main()
