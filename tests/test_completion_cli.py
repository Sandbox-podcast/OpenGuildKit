"""Shell completion and the reference of the commands, both written from the parser (issue #499)."""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import command_parser
from openguildkit.completion_cli import reference, script
from tests.support import run_cli
from tests.test_cli_surface import options, walk

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cli_reference.py"
PAGE = ROOT / "docs" / "cli.md"


def completed(shell: str, text: str, body: str) -> list[str]:
    """What the completion function of `shell` offers after the words in `body`: the script is sourced by a shell
    that has no other configuration."""
    with tempfile.TemporaryDirectory(prefix="ogk-completion-") as folder:
        file = Path(folder) / "completion.sh"
        file.write_text(text, encoding="utf-8")
        flags = ["--noprofile", "--norc"] if shell == "bash" else ["-f"]
        done = subprocess.run([shutil.which(shell), *flags, "-c", f"{body.replace('FILE', str(file))}"],
                              capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr)
    return done.stdout.split()


class ScriptTests(unittest.TestCase):
    def test_the_command_prints_a_script_for_each_shell(self):
        """Issue #499: `openguildkit completion` was an invalid choice, 94 commands had no completion."""
        for shell, printed in (("bash", run_cli(ROOT, "completion", "bash").stdout),
                               ("zsh", run_cli(ROOT, "completion", "zsh").stdout)):
            with self.subTest(shell=shell):
                self.assertEqual(printed, script(shell, command_parser()))
                self.assertIn("openguildkit", printed)

    def test_the_shell_reads_the_scripts_without_error(self):
        for shell in ("bash", "zsh"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell), tempfile.TemporaryDirectory(prefix="ogk-completion-") as folder:
                file = Path(folder) / "completion.sh"
                file.write_text(script(shell, command_parser()), encoding="utf-8")
                checked = subprocess.run([shutil.which(shell), "-n", str(file)], capture_output=True, text=True)
                self.assertEqual((checked.returncode, checked.stderr), (0, ""))

    def test_bash_offers_the_actions_options_and_values_of_the_command_typed(self):
        if not shutil.which("bash"):
            self.skipTest("no bash")
        text = script("bash", command_parser())

        def offered(*words: str, current: str = "") -> list[str]:
            typed = " ".join(["openguildkit", *words, current])
            return completed("bash", text, f"source FILE; COMP_WORDS=({typed}); COMP_CWORD={len(words) + 1}; _openguildkit; "
                                           'printf "%s\\n" "${COMPREPLY[@]}"')

        self.assertEqual(offered("task", current="pa"), ["pass"])
        self.assertIn("decision-payload", offered("task"))
        self.assertEqual(sorted(set(offered("host")) & {"check", "apply", "scan"}), ["apply", "check", "scan"])
        self.assertEqual(offered("check", current="--for"), ["--format"])
        self.assertEqual(offered("check", "--format"), ["text", "sarif"])
        # An option and its value before the command are not read as commands.
        self.assertEqual(offered("--project", "somewhere", "task", current="li"), ["list"])
        # The options that may follow any command.
        self.assertIn("--project", offered("task", "list"))

    def test_zsh_reads_the_same_words_as_bash(self):
        if not shutil.which("zsh"):
            self.skipTest("no zsh")
        text = script("zsh", command_parser())
        self.assertEqual(completed("zsh", text, "compdef() { :; }; source FILE; _openguildkit_candidates check --format"),
                         ["text", "sarif"])
        self.assertIn("pass", completed("zsh", text, "compdef() { :; }; source FILE; _openguildkit_candidates task"))
        # `path` is tied to PATH in zsh: a function that makes it local loses every command.
        self.assertIn("catalog", completed("zsh", text, "compdef() { :; }; source FILE; _openguildkit_candidates"))

    def test_every_command_of_the_parser_is_in_the_script(self):
        text = script("bash", command_parser())
        missing = [" ".join(path) for path, _ in walk(command_parser()) if path and f"'{' '.join(path)}')" not in text
                   and f"\n    {' '.join(path)})" not in text]
        self.assertEqual(missing, [])


class ReferenceTests(unittest.TestCase):
    def test_the_page_lists_every_command_and_every_option_with_its_help(self):
        """Issue #499: nothing listed the 94 commands and 361 options; 8 options were written in no page."""
        text = PAGE.read_text(encoding="utf-8")
        for path, parser in walk(command_parser()):
            if not path:
                continue
            with self.subTest(command=" ".join(path)):
                heading = f"{'#' * (len(path) + 1)} {' '.join(path)}\n"
                self.assertIn(heading, text)
                section = text.partition(heading)[2].split("\n#", 1)[0]
                self.assertIn(parser.description, section)
                for action in options(parser):
                    self.assertIn(f"`{action.option_strings[0]}", section)
                    self.assertIn((action.help or "").split(". ")[0][:40], section)

    def test_a_new_option_changes_the_reference(self):
        small = argparse.ArgumentParser(prog="openguildkit", description="Small.")
        commands = small.add_subparsers(dest="command", metavar="COMMAND")
        leaf = commands.add_parser("go", help="Go there.")
        before = reference(small)
        leaf.add_argument("--fast", help="Do not stop.")
        after = reference(small)
        self.assertNotIn("--fast", before)
        self.assertIn("`--fast FAST`: Do not stop.", after)

    def test_the_page_is_current_and_a_stale_one_fails(self):
        run = lambda page: subprocess.run([sys.executable, "-I", str(SCRIPT), "--check", "--page", str(page)],
                                          capture_output=True, text=True)
        self.assertEqual(run(PAGE).returncode, 0, run(PAGE).stderr)
        with tempfile.TemporaryDirectory(prefix="ogk-page-") as folder:
            stale = Path(folder) / "cli.md"
            stale.write_text(PAGE.read_text(encoding="utf-8").replace("`--json`", "`--jsn`", 1), encoding="utf-8")
            failed = run(stale)
            self.assertEqual(failed.returncode, 1)
            self.assertIn("out of date", failed.stderr)


if __name__ == "__main__":
    unittest.main()
