"""The surface of the CLI: help pages, where the global options go, the conventions of the options, the words of
the outputs. Each test reads the parser or runs a command through the CLI.
"""

import argparse
import contextlib
import io
import json
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

    def test_task_alerts_says_it_is_a_shortcut_of_the_alerts_commands(self):
        """Issue #526: task alerts and alerts import, set and link write the same register, and nothing said so."""
        shortcut = _subcommands(_subcommands(command_parser())["task"])["alerts"].description
        self.assertIn("Shortcut of the alerts commands", shortcut)

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


class ByOptionTests(unittest.TestCase):
    def by_options(self):
        return [(" ".join(path), action) for path, parser in walk(command_parser())
                for action in options(parser) if "--by" in action.option_strings]

    def test_by_reads_the_same_on_every_command(self):
        """Issue #493: --by had 14 help texts, asked for a name, and showed BY as its placeholder."""
        found = self.by_options()
        self.assertGreaterEqual(len(found), 24)
        self.assertEqual({(action.help, action.metavar) for _, action in found},
                         {("Your initials or team handle, not your full name: it is committed.", "INITIALS")})

    def test_no_command_proposed_by_the_tool_asks_for_a_name(self):
        """Issue #493: 49 strings of src proposed `--by NAME`, against the rule of the initials."""
        # The managed block of AGENTS.md: a block changed without INSTRUCTIONS_LAYOUT raised reads as edited by hand.
        kept = {"agent_workflow.py"}
        sources = [path for path in (REPO / "src" / "openguildkit").rglob("*")
                   if path.is_file() and path.suffix in (".py", ".md") and path.name not in kept]
        found = [path.relative_to(REPO).as_posix() for path in sources
                 if "--by NAME" in (text := path.read_text(encoding="utf-8")) or '"--by", "NAME"' in text]
        self.assertEqual(found, [])

    def test_a_name_with_an_address_is_accepted_with_a_warning_that_cites_the_rule(self):
        """Issue #493: a full name and an address went into the committed profile without a word."""
        with tempfile.TemporaryDirectory(prefix="ogk-by-") as folder:
            root = Path(folder)
            run_cli(root, "init", "--answers", PROFILE)
            for value in ("Camille Martin <camille.martin@example.com>", "camille@example.com", "Camille Martin"):
                with self.subTest(value=value):
                    done = run_cli(root, "profile", "add", "convention", f"Use British spelling ({value})", "--by", value,
                                   "--reason", "Team style")
                    self.assertIn("initials", done.stderr)
                    self.assertIn("docs/personal-data.md", done.stderr)
            quiet = run_cli(root, "profile", "add", "convention", "Use Oxford commas", "--by", "CM", "--reason", "Team style")
            self.assertEqual(quiet.stderr, "")


# The names an output destination must not take: it is --output, whatever the command writes.
OTHER_OUTPUT_NAMES = {"--out", "--outfile", "--dest", "--destination", "--to"}


class OptionConventionTests(unittest.TestCase):
    def test_every_option_that_takes_a_value_names_it(self):
        """Issue #498: 152 options of 208 showed their own name in capitals as placeholder (--reason REASON)."""
        bare = [f"{' '.join(path)} {action.option_strings[0]}" for path, parser in walk(command_parser())
                for action in options(parser) if action.nargs != 0 and action.metavar is None and not action.choices]
        self.assertEqual(bare, [])

    def test_a_destination_of_output_is_always_called_output(self):
        """Issue #498: `storybook generate` took --out when five commands took --output."""
        names = {option for _, parser in walk(command_parser()) for action in options(parser)
                 for option in action.option_strings}
        self.assertEqual(sorted(names & OTHER_OUTPUT_NAMES), [])

    def test_storybook_generate_takes_output_and_still_accepts_out(self):
        """Issue #498: --out of storybook generate stays accepted, and only --output is documented."""
        parse = command_parser().parse_args
        self.assertEqual(parse(["storybook", "generate", "--output", "design"]).out, Path("design"))
        self.assertEqual(parse(["storybook", "generate", "--out", "design"]).out, Path("design"))
        page = _subcommands(_subcommands(command_parser())["storybook"])["generate"].format_help()
        self.assertIn("--output", page)
        self.assertNotIn("--out ", page)

    def test_the_only_hidden_option_is_the_old_name_of_output(self):
        hidden = [action.option_strings for _, parser in walk(command_parser()) for action in parser._actions
                  if action.option_strings and action.help is argparse.SUPPRESS]
        self.assertEqual(hidden, [["--out"]])


class TaskShowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="ogk-show-")
        cls.addClassCleanup(cls.folder.cleanup)
        cls.root = Path(cls.folder.name)
        run_cli(cls.root, "init", "--answers", PROFILE)
        run_cli(cls.root, "task", "new", "Show customers their request status", "--id", "status")

    def test_summary_prints_a_screen_and_json_prints_the_record(self):
        """Issue #498: `task show` printed the whole record, 3,763 lines of JSON in a task done."""
        summary = run_cli(self.root, "task", "show", "status", "--summary").stdout
        self.assertLess(len(summary.encode("utf-8")), 5_000)
        self.assertIn("status [draft] Show customers their request status", summary)
        self.assertIn("next: Answer the questionnaire and consult the boards.", summary)
        record = json.loads(run_cli(self.root, "task", "show", "status", "--json").stdout)
        self.assertEqual((record["id"], record["status"]), ("status", "draft"))

    def test_the_default_of_show_is_still_the_record(self):
        """The default of `task show` is a person's choice to change: scripts parse it today."""
        shown = json.loads(run_cli(self.root, "task", "show", "status").stdout)
        self.assertEqual(shown, json.loads(run_cli(self.root, "task", "show", "status", "--json").stdout))

    def test_the_summary_and_the_closing_points_do_not_go_together(self):
        refused = run_cli(self.root, "task", "show", "status", "--summary", "--closing", expect=2)
        self.assertIn("not allowed with", refused.stderr)


if __name__ == "__main__":
    unittest.main()
